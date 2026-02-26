"""Jira API client for authentication and ticket operations."""

import base64
import logging

import httpx
from tenacity import (
    RetryError,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from src.jira.config import JiraSettings
from src.jira.exceptions import (
    JiraAuthenticationError,
    JiraConnectionError,
    JiraIssueTypeNotSupportedError,
    JiraTicketNotFoundError,
)
from src.jira.models import ParentContext, TicketData

logger = logging.getLogger(__name__)


class _RetryableHTTPError(Exception):
    """Internal exception to trigger retry on 5xx and 429 status codes."""

    pass


def _is_retryable_error(exception: BaseException) -> bool:
    """Determine if an exception should trigger a retry.

    Args:
        exception: The exception that was raised.

    Returns:
        True if the exception should trigger a retry, False otherwise.
    """
    # Retry on our custom retryable HTTP error (5xx and 429)
    if isinstance(exception, _RetryableHTTPError):
        return True
    # Retry on connection errors
    if isinstance(exception, httpx.RequestError):
        return True
    # Retry on timeout
    if isinstance(exception, httpx.TimeoutException):
        return True
    # Don't retry on other exceptions
    return False


class JiraClient:
    """Async client for Jira REST API operations.

    Uses Basic Auth with email and API token for authentication.
    Provides connection validation and ticket retrieval functionality.
    """

    def __init__(self, settings: JiraSettings) -> None:
        """Initialize the Jira client with configuration settings.

        Args:
            settings: JiraSettings instance containing connection configuration.
        """
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.base_url,
            headers=self._build_auth_headers(),
        )

    def _build_auth_headers(self) -> dict[str, str]:
        """Build HTTP headers with Basic Auth credentials.

        Returns:
            Dictionary containing Authorization header with base64-encoded credentials.
        """
        credentials = f"{self._settings.user_email}:{self._settings.api_token}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/json",
        }

    async def validate_connection(self) -> bool:
        """Validate the Jira connection by calling the /myself endpoint.

        Uses exponential backoff retry for transient errors (5xx, 429, network issues).

        Returns:
            True if connection and authentication are successful.

        Raises:
            JiraAuthenticationError: If credentials are invalid (401/403).
            JiraConnectionError: If Jira is unreachable or request times out after retries.
        """

        @retry(
            stop=stop_after_attempt(self._settings.max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=16),
            retry=retry_if_exception(_is_retryable_error),
            reraise=True,
        )
        async def _validate_with_retry() -> bool:
            response = await self._client.get("/rest/api/3/myself")

            if response.status_code == 200:
                return True

            if response.status_code in (401, 403):
                raise JiraAuthenticationError(
                    f"Authentication failed with status {response.status_code}: "
                    "Invalid credentials or insufficient permissions"
                )

            # Retry on 5xx server errors and 429 rate limiting
            if response.status_code >= 500 or response.status_code == 429:
                raise _RetryableHTTPError(
                    f"Retryable HTTP error: {response.status_code}"
                )

            # 4xx errors (except 429) should fail immediately without retry
            raise JiraConnectionError(
                f"Unexpected response from Jira: {response.status_code}"
            )

        try:
            return await _validate_with_retry()
        except RetryError as e:
            # Retries exhausted - convert to JiraConnectionError
            last_exception = e.last_attempt.exception()
            if last_exception:
                raise JiraConnectionError(
                    f"Failed to connect to Jira after {self._settings.max_retries} retries: "
                    f"{last_exception}"
                ) from e
            raise JiraConnectionError(
                f"Failed to connect to Jira after {self._settings.max_retries} retries"
            ) from e
        except _RetryableHTTPError as e:
            # With reraise=True, the last exception is re-raised directly
            # This catches retryable HTTP errors (5xx, 429) after retries exhausted
            raise JiraConnectionError(
                f"Failed to connect to Jira after {self._settings.max_retries} retries: "
                f"{e}"
            ) from e
        except httpx.TimeoutException as e:
            raise JiraConnectionError(f"Request to Jira timed out: {e}") from e
        except httpx.RequestError as e:
            raise JiraConnectionError(f"Failed to connect to Jira: {e}") from e

    async def close(self) -> None:
        """Close the underlying HTTP client connection."""
        await self._client.aclose()

    def _extract_text_from_adf(self, adf: dict | None) -> str:
        """Extract plain text from Atlassian Document Format (ADF).

        Recursively traverses the ADF structure to extract text content.

        Args:
            adf: The ADF document structure, or None.

        Returns:
            Plain text extracted from the ADF, or empty string if null/missing.
        """
        if adf is None:
            return ""

        if not isinstance(adf, dict):
            return ""

        texts: list[str] = []

        def extract_text(node: dict | list | str) -> None:
            if isinstance(node, str):
                texts.append(node)
            elif isinstance(node, dict):
                # If this node has a "text" field, extract it
                if "text" in node:
                    texts.append(node["text"])
                # Recursively process "content" if present
                if "content" in node and isinstance(node["content"], list):
                    for child in node["content"]:
                        extract_text(child)
            elif isinstance(node, list):
                for item in node:
                    extract_text(item)

        extract_text(adf)
        return " ".join(texts)

    def _extract_parent_key(self, fields: dict) -> str | None:
        """Extract the parent issue key from response fields.

        Checks the ``parent`` field first (next-gen projects and
        subtasks in classic projects), then falls back to the
        configurable epic link custom field (classic projects).

        Args:
            fields: The ``fields`` dict from the Jira API response.

        Returns:
            The parent issue key, or None if no parent is linked.
        """
        parent = fields.get("parent")
        if parent and isinstance(parent, dict):
            parent_key = parent.get("key")
            if parent_key:
                return parent_key

        epic_field = self._settings.epic_link_field
        if epic_field and epic_field != "parent":
            value = fields.get(epic_field)
            if value and isinstance(value, str):
                return value

        return None

    def _parent_fields(self) -> str:
        """Build the ``fields`` query param for parent chain fetches."""
        base = "summary,description,issuetype,parent"
        epic_field = self._settings.epic_link_field
        if epic_field and epic_field != "parent":
            base += f",{epic_field}"
        return base

    async def get_parent_chain(
        self,
        parent_key: str,
        max_depth: int = 3,
    ) -> list[ParentContext]:
        """Walk the issue hierarchy upward and collect context.

        Starting from *parent_key*, fetches each parent's summary,
        description, and issue type, then follows *its* parent link.
        Stops when there is no further parent or *max_depth* is
        reached.

        This is a best-effort operation — it never raises.  If any
        single fetch fails the chain is returned as-is (possibly
        partially populated).

        Args:
            parent_key: The Jira key of the first parent to fetch.
            max_depth: Maximum number of levels to walk (default 3).

        Returns:
            Ordered list of ``ParentContext`` objects from nearest
            parent to most distant ancestor.
        """
        chain: list[ParentContext] = []
        current_key: str | None = parent_key
        fields_param = self._parent_fields()

        for _ in range(max_depth):
            if not current_key:
                break
            try:
                response = await self._client.get(
                    f"/rest/api/3/issue/{current_key}",
                    params={"fields": fields_param},
                )
                if response.status_code != 200:
                    logger.warning(
                        "Failed to fetch parent %s: HTTP %d",
                        current_key,
                        response.status_code,
                    )
                    break

                data = response.json()
                fields = data.get("fields", {})
                summary = fields.get("summary", "")
                desc_adf = fields.get("description")
                description = self._extract_text_from_adf(desc_adf)
                issuetype = fields.get("issuetype", {})
                issue_type = (
                    issuetype.get("name", "")
                    if issuetype
                    else ""
                )

                chain.append(
                    ParentContext(
                        key=current_key,
                        summary=summary,
                        description=description,
                        issue_type=issue_type,
                    )
                )
                logger.info(
                    "Fetched parent context: %s (%s)",
                    current_key,
                    issue_type,
                )

                # Walk up to the next parent
                current_key = self._extract_parent_key(fields)

            except Exception as e:
                logger.warning(
                    "Failed to fetch parent %s: %s",
                    current_key,
                    e,
                )
                break

        return chain

    async def get_ticket(self, issue_key: str) -> TicketData:
        """Retrieve ticket data from Jira by issue key.

        Uses exponential backoff retry for transient errors (5xx, 429, network issues).

        Args:
            issue_key: The Jira issue key (e.g., "PROJ-123").

        Returns:
            TicketData containing the ticket's key, summary, description, and issue type.

        Raises:
            JiraTicketNotFoundError: If the ticket does not exist (404).
            JiraIssueTypeNotSupportedError: If the ticket's issue type is not in the
                configured list of supported types.
            JiraConnectionError: If Jira is unreachable or request times out after retries.
        """

        @retry(
            stop=stop_after_attempt(self._settings.max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=16),
            retry=retry_if_exception(_is_retryable_error),
            reraise=True,
        )
        async def _get_ticket_with_retry() -> dict:
            response = await self._client.get(
                f"/rest/api/3/issue/{issue_key}",
                params={"fields": "summary,description,issuetype,parent"},
            )

            if response.status_code == 200:
                return response.json()

            if response.status_code == 404:
                raise JiraTicketNotFoundError(f"Ticket {issue_key} not found")

            if response.status_code in (401, 403):
                raise JiraAuthenticationError(
                    f"Authentication failed with status {response.status_code}: "
                    "Invalid credentials or insufficient permissions"
                )

            # Retry on 5xx server errors and 429 rate limiting
            if response.status_code >= 500 or response.status_code == 429:
                raise _RetryableHTTPError(
                    f"Retryable HTTP error: {response.status_code}"
                )

            # 4xx errors (except 404 and 429) should fail immediately without retry
            raise JiraConnectionError(
                f"Unexpected response from Jira: {response.status_code}"
            )

        try:
            data = await _get_ticket_with_retry()
        except RetryError as e:
            # Retries exhausted - convert to JiraConnectionError
            last_exception = e.last_attempt.exception()
            if last_exception:
                raise JiraConnectionError(
                    f"Failed to connect to Jira after {self._settings.max_retries} retries: "
                    f"{last_exception}"
                ) from e
            raise JiraConnectionError(
                f"Failed to connect to Jira after {self._settings.max_retries} retries"
            ) from e
        except _RetryableHTTPError as e:
            raise JiraConnectionError(
                f"Failed to connect to Jira after {self._settings.max_retries} retries: "
                f"{e}"
            ) from e
        except httpx.TimeoutException as e:
            raise JiraConnectionError(f"Request to Jira timed out: {e}") from e
        except httpx.RequestError as e:
            raise JiraConnectionError(f"Failed to connect to Jira: {e}") from e

        # Extract fields from response
        key = data.get("key", "")
        fields = data.get("fields", {})
        summary = fields.get("summary", "")
        description_adf = fields.get("description")
        description = self._extract_text_from_adf(description_adf)
        issuetype = fields.get("issuetype", {})
        issue_type = issuetype.get("name", "") if issuetype else ""
        parent_key = self._extract_parent_key(fields)

        # Validate issue type
        if issue_type not in self._settings.issue_types_list:
            raise JiraIssueTypeNotSupportedError(
                f"Issue type '{issue_type}' is not supported. "
                f"Supported types: {self._settings.issue_types_list}"
            )

        return TicketData(
            key=key,
            summary=summary,
            description=description,
            description_adf=description_adf,
            issue_type=issue_type,
            parent_key=parent_key,
        )

    async def search_tickets(self, jql: str, max_results: int = 50) -> list[TicketData]:
        """Search for tickets using JQL query.

        Uses exponential backoff retry for transient errors (5xx, 429, network issues).

        Args:
            jql: The JQL query string.
            max_results: Maximum number of results to return (default: 50).

        Returns:
            List of TicketData objects matching the query.

        Raises:
            JiraAuthenticationError: If credentials are invalid (401/403).
            JiraConnectionError: If Jira is unreachable or request times out after retries.
        """

        @retry(
            stop=stop_after_attempt(self._settings.max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=16),
            retry=retry_if_exception(_is_retryable_error),
            reraise=True,
        )
        async def _search_with_retry() -> dict:
            response = await self._client.get(
                "/rest/api/3/search/jql",
                params={
                    "jql": jql,
                    "maxResults": max_results,
                    "fields": "summary,description,issuetype,parent",
                },
            )

            if response.status_code == 200:
                return response.json()

            if response.status_code in (401, 403):
                raise JiraAuthenticationError(
                    f"Authentication failed with status {response.status_code}: "
                    "Invalid credentials or insufficient permissions"
                )

            # Retry on 5xx server errors and 429 rate limiting
            if response.status_code >= 500 or response.status_code == 429:
                raise _RetryableHTTPError(
                    f"Retryable HTTP error: {response.status_code}"
                )

            # 4xx errors (except 429) should fail immediately without retry
            raise JiraConnectionError(
                f"Unexpected response from Jira: {response.status_code}"
            )

        try:
            data = await _search_with_retry()
        except RetryError as e:
            # Retries exhausted - convert to JiraConnectionError
            last_exception = e.last_attempt.exception()
            if last_exception:
                raise JiraConnectionError(
                    f"Failed to connect to Jira after {self._settings.max_retries} retries: "
                    f"{last_exception}"
                ) from e
            raise JiraConnectionError(
                f"Failed to connect to Jira after {self._settings.max_retries} retries"
            ) from e
        except _RetryableHTTPError as e:
            raise JiraConnectionError(
                f"Failed to connect to Jira after {self._settings.max_retries} retries: "
                f"{e}"
            ) from e
        except httpx.TimeoutException as e:
            raise JiraConnectionError(f"Request to Jira timed out: {e}") from e
        except httpx.RequestError as e:
            raise JiraConnectionError(f"Failed to connect to Jira: {e}") from e

        # Extract issues from response and convert to TicketData
        issues = data.get("issues", [])
        tickets: list[TicketData] = []

        for issue in issues:
            key = issue.get("key", "")
            fields = issue.get("fields", {})
            summary = fields.get("summary", "")
            description_adf = fields.get("description")
            description = self._extract_text_from_adf(description_adf)
            issuetype = fields.get("issuetype", {})
            issue_type = issuetype.get("name", "") if issuetype else ""
            parent_key = self._extract_parent_key(fields)

            tickets.append(
                TicketData(
                    key=key,
                    summary=summary,
                    description=description,
                    description_adf=description_adf,
                    issue_type=issue_type,
                    parent_key=parent_key,
                )
            )

        return tickets

    async def update_description(self, issue_key: str, description_adf: dict) -> bool:
        """Update the description field of a Jira ticket.

        Uses exponential backoff retry for transient errors (5xx, 429, network issues).

        Args:
            issue_key: The Jira issue key (e.g., "PROJ-123").
            description_adf: The new description in Atlassian Document Format (ADF).

        Returns:
            True if the update succeeded, False otherwise.
        """
        if not issue_key:
            logger.error("Cannot update description: empty issue key")
            return False

        if not description_adf:
            logger.error("Cannot update description for %s: empty ADF", issue_key)
            return False

        @retry(
            stop=stop_after_attempt(self._settings.max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=16),
            retry=retry_if_exception(_is_retryable_error),
            reraise=True,
        )
        async def _update_with_retry() -> bool:
            response = await self._client.put(
                f"/rest/api/3/issue/{issue_key}",
                json={"fields": {"description": description_adf}},
            )

            if 200 <= response.status_code < 300:
                return True

            if response.status_code == 404:
                logger.error("Ticket %s not found", issue_key)
                return False

            if response.status_code in (401, 403):
                logger.error(
                    "Authentication failed when updating %s: HTTP %d",
                    issue_key,
                    response.status_code,
                )
                return False

            # Retry on 5xx server errors and 429 rate limiting
            if response.status_code >= 500 or response.status_code == 429:
                raise _RetryableHTTPError(
                    f"Retryable HTTP error: {response.status_code}"
                )

            # 4xx errors (except 404 and 429) should fail immediately without retry
            logger.error(
                "Failed to update description for %s: HTTP %d - %s",
                issue_key,
                response.status_code,
                response.text,
            )
            return False

        try:
            return await _update_with_retry()
        except RetryError as e:
            last_exception = e.last_attempt.exception()
            logger.error(
                "Failed to update description for %s after %d retries: %s",
                issue_key,
                self._settings.max_retries,
                last_exception,
            )
            return False
        except _RetryableHTTPError as e:
            logger.error(
                "Failed to update description for %s after %d retries: %s",
                issue_key,
                self._settings.max_retries,
                e,
            )
            return False
        except httpx.TimeoutException as e:
            logger.error("Request to update %s timed out: %s", issue_key, e)
            return False
        except httpx.RequestError as e:
            logger.error("Failed to connect to Jira when updating %s: %s", issue_key, e)
            return False

    async def add_label(self, issue_key: str, label: str) -> bool:
        """Add a label to a Jira ticket.

        This method does not raise exceptions - it returns False on any failure
        and logs the error for debugging purposes.

        Args:
            issue_key: The ticket key (e.g., "IGAL-123").
            label: The label to add (e.g., "ac-generated").

        Returns:
            True if successful, False if label addition failed.
        """
        try:
            response = await self._client.put(
                f"/rest/api/3/issue/{issue_key}",
                json={"update": {"labels": [{"add": label}]}},
            )

            if 200 <= response.status_code < 300:
                return True

            logger.error(
                "Failed to add label '%s' to ticket %s: HTTP %d - %s",
                label,
                issue_key,
                response.status_code,
                response.text,
            )
            return False

        except Exception as e:
            logger.error(
                "Failed to add label '%s' to ticket %s: %s",
                label,
                issue_key,
                str(e),
            )
            return False

    async def remove_label(self, issue_key: str, label: str) -> bool:
        """Remove a label from a Jira ticket.

        This method does not raise exceptions - it returns False on any failure
        and logs a warning for debugging purposes. It is safe to call even if
        the label does not exist on the ticket.

        Args:
            issue_key: The ticket key (e.g., "IGAL-123").
            label: The label to remove (e.g., "regenerating").

        Returns:
            True if successful, False if label removal failed.
        """
        try:
            response = await self._client.put(
                f"/rest/api/3/issue/{issue_key}",
                json={"update": {"labels": [{"remove": label}]}},
            )

            if 200 <= response.status_code < 300:
                return True

            logger.warning(
                "Failed to remove label '%s' from ticket %s: HTTP %d - %s",
                label,
                issue_key,
                response.status_code,
                response.text,
            )
            return False

        except Exception as e:
            logger.warning(
                "Failed to remove label '%s' from ticket %s: %s",
                label,
                issue_key,
                str(e),
            )
            return False

    async def add_comment(self, issue_key: str, body: str) -> bool:
        """Post a comment to a Jira ticket with Barley AI context.

        Creates an ADF-formatted comment with a "Barley AI Context" heading
        followed by the provided body text. This is a non-critical operation
        and does not use retry logic.

        This method does not raise exceptions - it returns False on any failure
        and logs the error for debugging purposes.

        Args:
            issue_key: The ticket key (e.g., "IGAL-123").
            body: The comment text to post under the "Barley AI Context" heading.

        Returns:
            True if successful, False if comment posting failed.
        """
        try:
            payload = {
                "body": {
                    "version": 1,
                    "type": "doc",
                    "content": [
                        {
                            "type": "heading",
                            "attrs": {"level": 3},
                            "content": [
                                {"type": "text", "text": "Barley AI Context"}
                            ],
                        },
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": body}],
                        },
                    ],
                }
            }

            response = await self._client.post(
                f"/rest/api/3/issue/{issue_key}/comment",
                json=payload,
            )

            if 200 <= response.status_code < 300:
                logger.info(
                    "Successfully added Barley AI Context comment to %s", issue_key
                )
                return True

            logger.error(
                "Failed to add comment to ticket %s: HTTP %d - %s",
                issue_key,
                response.status_code,
                response.text,
            )
            return False

        except Exception as e:
            logger.error(
                "Failed to add comment to ticket %s: %s",
                issue_key,
                str(e),
            )
            return False
