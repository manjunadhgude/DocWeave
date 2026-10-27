from dataclasses import dataclass, field
from typing import Any
@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    document_id: str
    text: str
    source_name: str
    page_number: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
@dataclass(frozen=True)
class RetrievedChunk:
    chunk: Chunk
    score: float
    method: str
@dataclass(frozen=True)
class Citation:
    document_id: str
    source_name: str
    chunk_id: str
    page_number: int | None
    quote: str
@dataclass(frozen=True)
class Answer:
    answer: str
    abstained: bool
    citations: tuple[Citation, ...] = ()
    evidence_chunk_ids: tuple[str, ...] = ()
