"""Multimodal contracts for Samaktha Core.

Defines the data models used when processing image, audio, document, and video
inputs through the ProviderManager boundary.  No raw media decoding occurs
here — these are pure data-transfer objects.
"""
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MediaType(str, Enum):
    IMAGE = "image"
    AUDIO = "audio"
    DOCUMENT = "document"
    VIDEO = "video"


class MediaInput(BaseModel):
    """A single piece of media to be processed."""

    media_id: str
    media_type: MediaType
    # source may be a URL, a base64-encoded string, or a local file path.
    # Interpretation is delegated to the provider.
    source: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class MultimodalRequest(BaseModel):
    """Request to process one or more media inputs via a multimodal provider."""

    input: MediaInput
    # Optional natural-language instructions for the model.
    instructions: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class MultimodalResponse(BaseModel):
    """Normalized response from a multimodal provider."""

    content: str
    detected_items: list[str] = Field(default_factory=list)
    provider_id: str
    usage: dict[str, int] = Field(default_factory=dict)
