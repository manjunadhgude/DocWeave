"""Semantic, keyword and reciprocal-rank-fusion hybrid retrieval."""
from docweave.rag.keyword import bm25_search, bm25_search_expanded
from docweave.rag.models import RetrievedChunk
def reciprocal_rank_fusion(*ranked_lists,top_k=5,constant=60):
    if top_k<1 or constant<1: raise ValueError('top_k and constant must be >= 1')
    scores={}; items={}
    for ranked in ranked_lists:
        seen=set()
        for rank,item in enumerate(ranked,1):
            key=item.chunk.chunk_id
            if key in seen: continue
            seen.add(key); items[key]=item; scores[key]=scores.get(key,0)+1/(constant+rank)
    keys=sorted(scores,key=lambda k:(-scores[k],k))[:top_k]
    return [RetrievedChunk(items[k].chunk,scores[k],'hybrid_rrf') for k in keys]
def hybrid_search(query,chunks,semantic_results=(),top_k=5,*,query_expansion=False):
    search = bm25_search_expanded if query_expansion else bm25_search
    lexical = search(query,chunks,max(top_k*2,top_k))
    return reciprocal_rank_fusion(semantic_results,lexical,top_k=top_k)

def retrieve(query,chunks,*,mode='hybrid',embedder=None,top_k=5):
    if mode=='keyword': return bm25_search(query,chunks,top_k)
    if mode=='keyword_expanded': return bm25_search_expanded(query,chunks,top_k)
    if mode not in {'semantic','hybrid','hybrid_expanded'}:
        raise ValueError(f'Unsupported retrieval mode: {mode}')
    if embedder is None:
        raise ValueError('An embedding provider is required for semantic/hybrid retrieval.')
    from docweave.rag.vector_store import semantic_search
    semantic=semantic_search(query,chunks,embedder,max(top_k*2,top_k))
    if mode=='semantic': return semantic[:top_k]
    return hybrid_search(
        query,chunks,semantic,top_k,
        query_expansion=(mode=='hybrid_expanded'),
    )
