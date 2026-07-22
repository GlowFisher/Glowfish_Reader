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
    ocr_meta: NotRequired[dict]


class OcrProgress(TypedDict):
    schema_version: Literal[1]
    phase: str
    completed: int
    total: int
    engine: str
    fallback: NotRequired[str | None]
    error: NotRequired[str | None]
    job_id: NotRequired[str]
    batch: NotRequired[str]
    attempt: NotRequired[int]
    resumed: NotRequired[bool]
    current_page: NotRequired[str | None]
    last_checkpoint_at: NotRequired[float | None]
    completed_by_engine: NotRequired[dict[str, int]]


class RecoverableOcrJob(TypedDict):
    job_id: str
    batch: str
    source: str
    completed: int
    total: int
    engine: str
    updated_at: float
    failed_pages: list[str]


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
