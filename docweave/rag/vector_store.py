"""In-memory cosine index for small corpora."""
class VectorStoreError(RuntimeError): pass
class InMemoryVectorStore:
    def __init__(self): self._chunks=[]; self._vectors=None
    def add(self,chunks,vectors):
        try: import numpy as np
        except ImportError as exc: raise VectorStoreError('NumPy is required for vector retrieval.') from exc
        m=np.asarray(vectors,dtype=float)
        if m.ndim!=2 or m.shape[0]!=len(chunks): raise ValueError('Vector rows must match chunks.')
        if not np.isfinite(m).all(): raise ValueError('Vectors must be finite.')
        norms=np.linalg.norm(m,axis=1)
        if np.any(norms==0): raise ValueError('Zero vectors are not supported.')
        m=m/norms[:,None]
        if self._vectors is not None and m.shape[1]!=self._vectors.shape[1]: raise ValueError('Embedding dimensions do not match.')
        self._chunks.extend(chunks); self._vectors=m if self._vectors is None else np.vstack((self._vectors,m))
    def search(self,query_vector,top_k=5):
        if top_k<1: raise ValueError('top_k must be >= 1')
        if not self._chunks: return []
        import numpy as np
        from docweave.rag.models import RetrievedChunk
        q=np.asarray(query_vector,dtype=float).reshape(-1)
        if q.size!=self._vectors.shape[1] or not np.isfinite(q).all(): raise ValueError('Invalid query vector.')
        norm=np.linalg.norm(q)
        if norm==0: raise ValueError('Zero query vector is not supported.')
        scores=self._vectors@(q/norm); order=sorted(range(len(scores)),key=lambda i:(-float(scores[i]),self._chunks[i].chunk_id))[:top_k]
        return [RetrievedChunk(self._chunks[i],float(scores[i]),'semantic') for i in order]
def semantic_search(query,chunks,embedder,top_k=5):
    if not chunks: return []
    vectors=embedder.encode([c.text for c in chunks]); q=embedder.encode([query])[0]
    store=InMemoryVectorStore(); store.add(chunks,vectors); return store.search(q,top_k)
