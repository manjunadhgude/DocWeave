"""Answer assembly, conservative abstention and provenance-backed citations."""
from docweave.rag.models import Answer,Citation
def answer_question(question,retrieved,provider,*,min_score=0.0,max_evidence=5):
    if max_evidence<1: raise ValueError('max_evidence must be >= 1')
    usable=[r.chunk for r in retrieved if r.score>min_score][:max_evidence]
    if not usable: return Answer('I could not find sufficient evidence in the supplied documents.',True)
    raw=provider.generate(question,usable).strip()
    if not raw or raw=='INSUFFICIENT_EVIDENCE': return Answer('I could not find sufficient evidence in the supplied documents.',True)
    citations=tuple(Citation(c.document_id,c.source_name,c.chunk_id,c.page_number,c.text[:240]) for c in usable)
    return Answer(raw,False,citations,tuple(c.chunk_id for c in usable))
