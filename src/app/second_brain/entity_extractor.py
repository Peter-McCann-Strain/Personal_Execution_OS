"""Entity extraction — extracts people, projects, topics from text.

Uses LLM (Haiku) for extraction. No fallback.
"""

from __future__ import annotations

from typing import Literal

import structlog
from anthropic import APIError, AsyncAnthropic
from pydantic import BaseModel, Field

from src.app.config import get_settings
from src.app.core.exceptions import LLMError
from src.app.core.llm_helpers import call_llm, parse_json_response

logger = structlog.get_logger()


class ExtractedEntity(BaseModel):
    """A single entity extracted from text."""

    name: str
    entity_type: Literal["person", "project", "topic", "place", "org"]
    context: str = ""


class ExtractedRelationship(BaseModel):
    """A relationship between two extracted entities."""

    source: str
    target: str
    relationship_type: Literal["works_with", "interested_in", "located_in", "part_of", "mentions"]


class ExtractionResult(BaseModel):
    """Validated result of entity extraction."""

    entities: list[ExtractedEntity] = Field(default_factory=list)
    relationships: list[ExtractedRelationship] = Field(default_factory=list)


ENTITY_PROMPT = """Extract entities from the following text.

## Entity Types
- person: a named person
- project: a named project or initiative
- topic: a subject or theme being discussed
- place: a named location
- org: an organisation or company

## Rules
- Only extract explicitly mentioned entities, don't infer
- Use the exact name as mentioned in the text
- Include a brief context snippet showing where the entity appears

Respond with JSON only:
{
    "entities": [
        {
            "name": "entity name",
            "entity_type": "person|project|topic|place|org",
            "context": "brief surrounding text"
        }
    ],
    "relationships": [
        {
            "source": "entity name",
            "target": "entity name",
            "relationship_type": "works_with|interested_in|located_in|part_of|mentions"
        }
    ]
}"""


async def extract_entities(
    text: str,
    client: AsyncAnthropic,
    model: str | None = None,
    max_tokens: int | None = None,
) -> ExtractionResult:
    """Extract entities and relationships from text.

    Returns a validated ``ExtractionResult`` with typed entities and relationships.
    """
    settings = get_settings()
    model = model or settings.entity_model
    max_tokens = max_tokens or settings.entity_max_tokens

    try:
        response = await call_llm(
            client,
            model=model,
            max_tokens=max_tokens,
            system=ENTITY_PROMPT,
            messages=[{"role": "user", "content": text}],
        )
    except (APIError, LLMError) as e:
        logger.error("entity_extraction_failed", error=str(e), model=model)
        raise LLMError(f"Entity extraction failed: {e}") from e

    data = parse_json_response(response, "entity extraction")

    try:
        result = ExtractionResult(**data)
    except ValueError as e:
        logger.warning("entity_extraction_validation_partial", error=str(e))
        # Graceful: validate what we can, discard malformed entries
        entities: list[ExtractedEntity] = []
        for ent in data.get("entities", []):
            if isinstance(ent, dict) and "name" in ent and "entity_type" in ent:
                try:
                    entities.append(ExtractedEntity(**ent))
                except ValueError:
                    continue

        relationships: list[ExtractedRelationship] = []
        for rel in data.get("relationships", []):
            if isinstance(rel, dict) and "source" in rel and "target" in rel:
                try:
                    relationships.append(ExtractedRelationship(**rel))
                except ValueError:
                    continue

        result = ExtractionResult(entities=entities, relationships=relationships)

    logger.info(
        "entities_extracted",
        entity_count=len(result.entities),
        relationship_count=len(result.relationships),
    )
    return result
