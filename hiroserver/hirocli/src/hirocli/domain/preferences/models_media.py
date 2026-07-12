"""Media policy / capabilities (``prefs.media``). Split out of ``models.py`` for readability."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ModalityFlags(BaseModel):
    voice: bool = Field(default=False, title="Voice")
    image: bool = Field(default=False, title="Image")
    video: bool = Field(default=False, title="Video")
    file: bool = Field(default=False, title="File")


def default_input_modalities() -> ModalityFlags:
    return ModalityFlags(voice=True)


def default_output_modalities() -> ModalityFlags:
    # Voice output on by default so a fresh workspace can speak replies without extra setup.
    return ModalityFlags(voice=True)


class MediaPreferences(BaseModel):
    input: ModalityFlags = Field(default_factory=default_input_modalities)
    output: ModalityFlags = Field(default_factory=default_output_modalities)
