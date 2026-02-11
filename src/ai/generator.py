"""AI-powered acceptance criteria generator using Anthropic Claude API."""

import logging

from anthropic import Anthropic

from src.ai.config import AISettings
from src.ai.exceptions import AIInvalidResponseError

logger = logging.getLogger(__name__)

# Tool schema for structured output
AC_TOOL = {
    "name": "submit_acceptance_criteria",
    "description": "Submit the generated acceptance criteria for a Jira ticket",
    "input_schema": {
        "type": "object",
        "properties": {
            "sufficient_information": {
                "type": "boolean",
                "description": (
                    "True if the ticket has enough information to generate "
                    "meaningful acceptance criteria, False otherwise"
                ),
            },
            "acceptance_criteria": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "List of 3-7 clear, testable acceptance criteria. "
                    "Empty if insufficient information."
                ),
            },
            "skip_reason": {
                "type": "string",
                "description": (
                    "Brief explanation of why ACs cannot be generated "
                    "(only when sufficient_information is false)"
                ),
            },
        },
        "required": ["sufficient_information", "acceptance_criteria"],
    },
}

TOPICS_TOOL = {
    "name": "submit_extracted_topics",
    "description": (
        "Submit the extracted topics, entities, and domain concepts "
        "from a Jira ticket"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "topics": {
                "type": "string",
                "description": (
                    "A consolidated natural-language summary of the key topics, "
                    "entities, domain concepts, and business terms found in the "
                    "ticket. Should read as a coherent passage, not a keyword list."
                ),
            },
        },
        "required": ["topics"],
    },
}

TOPICS_SYSTEM_PROMPT = """\
You are an expert at analyzing software development tickets and extracting \
their core subject matter.

Your task is to read a Jira ticket's summary and description, then extract \
the key topics, entities, domain concepts, and business terms.

GUIDELINES:
- Identify the primary domain area (e.g., payments, authentication, reporting)
- Extract named entities such as systems, services, APIs, or integrations
- Capture business terms and domain-specific language
- Note any technical concepts, frameworks, or tools mentioned
- Return a consolidated natural-language summary that provides rich context \
about what this ticket is about — NOT a list of keywords

Use the submit_extracted_topics tool to provide your response."""

SYSTEM_PROMPT = """\
You are an expert Product Owner writing acceptance criteria for software \
development tickets.

Your task is to analyze Jira tickets and generate clear, testable acceptance \
criteria.

GUIDELINES:
- Generate 3-7 acceptance criteria per ticket
- Use the format that best fits each criterion:
  - Given-When-Then for behavior-driven criteria
  - Simple checkbox statements for state/condition criteria
- Be SPECIFIC to THIS ticket - avoid generic criteria like "Code is tested" \
or "Documentation is updated"
- Each criterion should be independently verifiable
- If the description lacks sufficient detail to write meaningful ACs, set \
sufficient_information to false and explain why in skip_reason

Use the submit_acceptance_criteria tool to provide your response."""


class ACGenerator:
    """Generates acceptance criteria using Anthropic Claude API."""

    def __init__(self, settings: AISettings) -> None:
        """Initialize the AC generator.

        Args:
            settings: AI configuration settings including API key and model
                parameters.
        """
        self._settings = settings
        self._client = (
            Anthropic(api_key=settings.anthropic_api_key)
            if settings.is_enabled
            else None
        )

    @property
    def is_enabled(self) -> bool:
        """Check if the generator is enabled.

        Returns:
            True if API key is configured and client is available,
            False otherwise.
        """
        return self._settings.is_enabled

    async def generate(self, summary: str, description: str) -> list[str]:
        """Generate acceptance criteria for a Jira ticket.

        Args:
            summary: Ticket summary/title
            description: Ticket description text

        Returns:
            List of AC strings, or empty list if description insufficient
            or generator is disabled.
        """
        if not self.is_enabled:
            logger.warning("ACGenerator is disabled (no API key configured)")
            return []

        user_message = f"""TICKET SUMMARY: {summary}

TICKET DESCRIPTION:
{description or "(No description provided)"}

Analyze this ticket and generate acceptance criteria using the \
submit_acceptance_criteria tool."""

        try:
            # Anthropic SDK is sync, but we wrap for async interface compat
            response = self._client.messages.create(
                model=self._settings.ai_model,
                max_tokens=self._settings.ai_max_tokens,
                system=SYSTEM_PROMPT,
                tools=[AC_TOOL],
                tool_choice={"type": "tool", "name": "submit_acceptance_criteria"},
                messages=[{"role": "user", "content": user_message}],
            )

            return self._parse_response(response)

        except AIInvalidResponseError:
            # Re-raise our own exceptions
            raise
        except Exception as e:
            logger.error("Failed to generate ACs: %s", e)
            return []

    def _parse_response(self, response) -> list[str]:
        """Parse the tool_use response and extract acceptance criteria.

        Args:
            response: Anthropic API response object

        Returns:
            List of acceptance criteria strings

        Raises:
            AIInvalidResponseError: When response does not contain expected
                tool_use block
        """
        for block in response.content:
            if block.type == "tool_use" and block.name == "submit_acceptance_criteria":
                tool_input = block.input

                sufficient = tool_input.get("sufficient_information", False)
                if not sufficient:
                    skip_reason = tool_input.get(
                        "skip_reason", "Insufficient information"
                    )
                    logger.info(
                        "AI determined insufficient information: %s", skip_reason
                    )
                    return []

                acs = tool_input.get("acceptance_criteria", [])
                if not acs:
                    logger.warning("AI returned empty acceptance criteria list")
                    return []

                logger.info("AI generated %d acceptance criteria", len(acs))
                return acs

        logger.error("No tool_use block found in AI response")
        raise AIInvalidResponseError(
            "Response did not contain expected tool_use block"
        )

    async def extract_topics(self, summary: str, description: str) -> str:
        """Extract key topics and domain concepts from a Jira ticket.

        Uses Claude to analyze the ticket summary and description, extracting
        core topics, entities, and business terms as a consolidated
        natural-language string suitable for downstream processing.

        Args:
            summary: Ticket summary/title
            description: Ticket description text

        Returns:
            Consolidated string of extracted topics on success,
            raw description as fallback on any failure,
            or empty string if description is empty.
        """
        if not description:
            return ""

        if not self.is_enabled:
            logger.warning(
                "ACGenerator is disabled (no API key configured), "
                "returning raw description as fallback"
            )
            return description

        user_message = f"""TICKET SUMMARY: {summary}

TICKET DESCRIPTION:
{description}

Analyze this ticket and extract the key topics using the \
submit_extracted_topics tool."""

        try:
            response = self._client.messages.create(
                model=self._settings.ai_model,
                max_tokens=self._settings.ai_max_tokens,
                system=TOPICS_SYSTEM_PROMPT,
                tools=[TOPICS_TOOL],
                tool_choice={"type": "tool", "name": "submit_extracted_topics"},
                messages=[{"role": "user", "content": user_message}],
            )

            return self._parse_topics_response(response)

        except Exception as e:
            logger.warning(
                "Failed to extract topics, returning raw description: %s", e
            )
            return description

    def _parse_topics_response(self, response) -> str:
        """Parse the tool_use response and extract topics string.

        Args:
            response: Anthropic API response object

        Returns:
            Extracted topics string

        Raises:
            AIInvalidResponseError: When response does not contain expected
                tool_use block
        """
        for block in response.content:
            if block.type == "tool_use" and block.name == "submit_extracted_topics":
                tool_input = block.input
                topics = tool_input.get("topics", "")

                if not topics:
                    logger.warning("AI returned empty topics string")
                    raise AIInvalidResponseError(
                        "AI returned empty topics string"
                    )

                logger.info("AI extracted topics successfully")
                return topics

        logger.error("No tool_use block found in AI response for topic extraction")
        raise AIInvalidResponseError(
            "Response did not contain expected tool_use block"
        )
