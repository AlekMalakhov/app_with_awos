"""Barley API client for AI-powered chat completions."""

import logging

import httpx

from src.barley.config import BarleySettings
from src.barley.exceptions import (
    BarleyAuthenticationError,
    BarleyConnectionError,
    BarleyError,
)

logger = logging.getLogger(__name__)


class BarleyClient:
    """Async client for Barley's OpenAI-compatible chat completions API.

    Uses Bearer token authentication. On any failure (timeout, HTTP error,
    network error), logs the error and returns None instead of raising
    exceptions to the caller. This ensures Barley failures never block
    the pipeline.
    """

    def __init__(self, settings: BarleySettings) -> None:
        """Initialize the Barley client with configuration settings.

        Args:
            settings: BarleySettings instance containing connection configuration.
        """
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.api_url,
            headers=self._build_headers(),
            timeout=settings.timeout,
        )

    def _build_headers(self) -> dict[str, str]:
        """Build HTTP headers with Bearer token authentication.

        Returns:
            Dictionary containing Authorization and Content-Type headers.
        """
        return {
            "Authorization": f"Bearer {self._settings.api_token}",
            "Content-Type": "application/json",
        }

    async def query(self, prompt: str) -> str | None:
        """Send a prompt to Barley and return the generated response.

        Sends a chat completion request with the given prompt and extracts
        the response content. On any failure, logs the error and returns None.

        Args:
            prompt: The user prompt to send to the model.

        Returns:
            The generated text response, or None if the request failed.
        """
        try:
            response = await self._client.post(
                "/v1/chat/completions",
                json={
                    "model": "anth",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                    "max_tokens": 3000,
                },
            )

            if response.status_code in (401, 403):
                raise BarleyAuthenticationError(
                    f"Authentication failed with status {response.status_code}"
                )

            if response.status_code >= 500:
                raise BarleyConnectionError(
                    f"Server error from Barley: {response.status_code}"
                )

            if response.status_code != 200:
                raise BarleyError(
                    f"Unexpected response from Barley: {response.status_code} - "
                    f"{response.text}"
                )

            data = response.json()
            choices = data.get("choices", [])
            if not choices:
                logger.error("Barley response contains no choices")
                return None

            content = choices[0].get("message", {}).get("content")
            if content is None:
                logger.error("Barley response choice has no message content")
                return None

            return content

        except BarleyAuthenticationError as e:
            logger.error("Barley authentication error: %s", e)
            return None
        except BarleyConnectionError as e:
            logger.error("Barley connection error: %s", e)
            return None
        except BarleyError as e:
            logger.error("Barley API error: %s", e)
            return None
        except httpx.TimeoutException as e:
            logger.error("Request to Barley timed out: %s", e)
            return None
        except httpx.RequestError as e:
            logger.error("Failed to connect to Barley: %s", e)
            return None
        except Exception as e:
            logger.error("Unexpected error querying Barley: %s", e)
            return None

    async def close(self) -> None:
        """Close the underlying HTTP client connection."""
        await self._client.aclose()
