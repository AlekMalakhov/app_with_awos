"""Pydantic models for AI generation results."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ACGenerationResult(BaseModel):
    """Result of an AI-powered acceptance criteria generation.

    Attributes:
        acceptance_criteria: The generated acceptance criteria strings.
        confidence_score: AI's confidence in the completeness/accuracy
            of the ACs (0.0-1.0).
        confidence_gaps: Specific areas where the AI lacked information
            (empty when confidence is high).
        sufficient_information: Whether the ticket had enough info to
            generate ACs.
    """

    acceptance_criteria: list[str]
    confidence_score: float = Field(ge=0.0, le=1.0)
    confidence_gaps: list[str]
    sufficient_information: bool
