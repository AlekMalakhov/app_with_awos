"""Pydantic models for Barley enrichment data."""

from pydantic import BaseModel


class EnrichmentResult(BaseModel):
    """Result of a Barley enrichment operation.

    Attributes:
        barley_context: Context returned by Barley, or None if unavailable.
        topics_extracted: The extracted topics string sent to Barley.
    """

    barley_context: str | None = None
    topics_extracted: str = ""
