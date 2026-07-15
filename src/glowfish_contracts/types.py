"""Dependency-free type declarations shared by component repositories."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict


class OcrLine(TypedDict):
    text: str
    box: list[float]
    score: float


class OcrPage(TypedDict):
    image: str
    width: int
    height: int
    lines: list[OcrLine]


class OcrProgress(TypedDict):
    schema_version: Literal[1]
    phase: str
    completed: int
    total: int
    engine: str
    fallback: NotRequired[str | None]
    error: NotRequired[str | None]


class ProofLine(TypedDict):
    id: str
    text_ocr: str
    text_draft: str
    text: str
    box: list[float]
    score: float
    para_break: bool
    deleted: bool


class ProofPage(TypedDict):
    page_id: str
    image: str
    width: int
    height: int
    lines: list[ProofLine]
    noise_lines: NotRequired[list[ProofLine]]
    order: list[str]


class ProofDocument(TypedDict):
    batch: str
    pages: list[ProofPage]
