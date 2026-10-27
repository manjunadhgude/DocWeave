"""Transparent lexical reranking baseline, not a neural cross-encoder."""
from docweave.rag.keyword import tokenize
from docweave.rag.models import RetrievedChunk
def rerank(query,candidates,top_k=5):
    if top_k<1: raise ValueError('top_k must be >= 1')
    terms=set(tokenize(query)); scored=[]
    for item in candidates:
        text=item.chunk.text.lower(); overlap=len(terms & set(tokenize(text)))/max(1,len(terms)); phrase=.15 if query.strip().lower() in text else 0.0
        scored.append((overlap+phrase,item))
    scored.sort(key=lambda pair:(-pair[0],pair[1].chunk.chunk_id))
    return [RetrievedChunk(item.chunk,float(score),'lexical_rerank') for score,item in scored[:top_k]]
