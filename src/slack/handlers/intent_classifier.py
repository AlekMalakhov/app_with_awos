"""Intent classifier for classifying user responses to AC approval requests."""

from __future__ import annotations

import logging
from enum import Enum

from anthropic import Anthropic
from pydantic import BaseModel

from src.ai.config import AISettings
from src.ai.exceptions import AIInvalidResponseError

logger = logging.getLogger(__name__)


class Intent(str, Enum):
    """User intent categories for AC approval responses."""

    APPROVE = "approve"
    REJECT = "reject"
    MODIFY = "modify"


class IntentResult(BaseModel):
    """Result of intent classification.

    Attributes:
        intent: The classified intent category
        modification_request: Details of requested changes (only if intent is MODIFY)
    """

    intent: Intent
    modification_request: str | None = None


# Tool schema for structured output
CLASSIFY_TOOL = {
    "name": "classify_response",
    "description": "Classify the user's response to acceptance criteria review",
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": ["approve", "reject", "modify"],
                "description": (
                    "The user's intent: 'approve' if they accept the ACs, "
                    "'reject' if they want to cancel/keep original, "
                    "'modify' if they want changes"
                ),
            },
            "modification_request": {
                "type": "string",
                "description": (
                    "If intent is 'modify', extract what changes the user wants. "
                    "Null if intent is not 'modify'."
                ),
            },
        },
        "required": ["intent"],
    },
}

SYSTEM_PROMPT = """\
You are classifying a user's response to acceptance criteria that were presented \
for review.

Classify the user's intent into one of three categories:
- APPROVE: User accepts the proposed acceptance criteria (e.g., "yes", "approve", \
"looks good", "go ahead", "ship it", "lgtm", "perfect")
- REJECT: User wants to cancel and keep the original (e.g., "no", "reject", \
"cancel", "keep original", "nevermind", "stop", "abort")
- MODIFY: User wants changes to the criteria (e.g., "add...", "change...", \
"remove...", specific feedback about what to change)

If the intent is MODIFY, extract a clear description of what changes the user wants.

Use the classify_response tool to provide your classification."""


class IntentClassifier:
    """Classifies user intent using Anthropic Claude API."""

    def __init__(self, settings: AISettings) -> None:
        """Initialize the intent classifier.

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
        """Check if the classifier is enabled.

        Returns:
            True if API key is configured and client is available,
            False otherwise.
        """
        return self._settings.is_enabled

    async def classify_intent(self, message: str) -> IntentResult:
        """Classify user's response intent using Claude.

        Args:
            message: The user's message to classify

        Returns:
            IntentResult with the classified intent and optional modification request

        Raises:
            AIInvalidResponseError: When response cannot be parsed
        """
        if not self.is_enabled:
            logger.warning("IntentClassifier is disabled (no API key configured)")
            # Default to REJECT when disabled to avoid unintended approvals
            return IntentResult(intent=Intent.REJECT)

        user_message = f"""The user's message: "{message}"

Classify the user's intent using the classify_response tool."""

        try:
            # Anthropic SDK is sync, but we wrap for async interface compat
            response = self._client.messages.create(
                model=self._settings.ai_model,
                max_tokens=self._settings.ai_max_tokens,
                system=SYSTEM_PROMPT,
                tools=[CLASSIFY_TOOL],
                tool_choice={"type": "tool", "name": "classify_response"},
                messages=[{"role": "user", "content": user_message}],
            )

            return self._parse_response(response)

        except AIInvalidResponseError:
            # Re-raise our own exceptions
            raise
        except Exception as e:
            logger.error("Failed to classify intent: %s", e)
            raise AIInvalidResponseError(f"Failed to classify intent: {e}") from e

    def _parse_response(self, response) -> IntentResult:
        """Parse the tool_use response and extract intent classification.

        Args:
            response: Anthropic API response object

        Returns:
            IntentResult with classified intent

        Raises:
            AIInvalidResponseError: When response does not contain expected
                tool_use block
        """
        for block in response.content:
            if block.type == "tool_use" and block.name == "classify_response":
                tool_input = block.input

                intent_str = tool_input.get("intent")
                if intent_str is None:
                    logger.error("No intent field in tool response")
                    raise AIInvalidResponseError(
                        "Response did not contain intent field"
                    )

                try:
                    intent = Intent(intent_str)
                except ValueError as e:
                    logger.error("Invalid intent value: %s", intent_str)
                    raise AIInvalidResponseError(
                        f"Invalid intent value: {intent_str}"
                    ) from e

                modification_request = None
                if intent == Intent.MODIFY:
                    modification_request = tool_input.get("modification_request")
                    if not modification_request:
                        # If MODIFY but no modification_request, try to use the
                        # original message as the modification request
                        logger.warning(
                            "MODIFY intent but no modification_request provided"
                        )

                logger.info("Classified intent: %s", intent.value)
                return IntentResult(
                    intent=intent,
                    modification_request=modification_request,
                )

        logger.error("No tool_use block found in AI response")
        raise AIInvalidResponseError(
            "Response did not contain expected tool_use block"
        )
