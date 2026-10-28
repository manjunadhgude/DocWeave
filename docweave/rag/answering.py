# Conservative RAG answer assembly with provenance-backed citations.
import re

from docweave.rag.models import Answer, Citation

_ABSTENTION = "I could not find sufficient evidence in the supplied documents."
_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "has", "have", "in", "is", "it", "of", "on", "or", "that", "the",
    "this", "to", "was", "were", "with", "what", "when", "where",
    "which", "who", "why", "how", "does", "do", "did", "can", "could",
    "would", "should", "please", "tell", "me", "about",
}


def _content_tokens(text):
    # Retain numbers because they often carry important business evidence.
    tokens = re.findall(r"[a-zA-Z]+|\d+(?:[.,]\d+)*", text.casefold())
    return {token for token in tokens if token not in _STOP_WORDS and len(token) > 1}


def _has_lexical_support(answer_text, evidence_chunks):
    # Lexical overlap is only a sanity check, not semantic entailment verification.
    answer_tokens = _content_tokens(answer_text)
    evidence_tokens = _content_tokens(" ".join(chunk.text for chunk in evidence_chunks))
    return bool(answer_tokens and answer_tokens.intersection(evidence_tokens))


def answer_question(question, retrieved, provider, *, min_score=0.0, max_evidence=5):
    if max_evidence < 1:
        raise ValueError("max_evidence must be >= 1")
    usable = [item.chunk for item in retrieved if item.score > min_score][:max_evidence]
    if not usable:
        return Answer(_ABSTENTION, True)
    raw = provider.generate(question, usable)
    if not isinstance(raw, str):
        return Answer(_ABSTENTION, True)
    raw = raw.strip()
    if not raw or raw == "INSUFFICIENT_EVIDENCE":
        return Answer(_ABSTENTION, True)
    if not _has_lexical_support(raw, usable):
        return Answer(_ABSTENTION, True)
    citations = tuple(
        Citation(chunk.document_id, chunk.source_name, chunk.chunk_id,
                 chunk.page_number, chunk.text[:240])
        for chunk in usable
    )
    return Answer(raw, False, citations, tuple(chunk.chunk_id for chunk in usable))
