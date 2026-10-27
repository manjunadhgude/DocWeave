"""Optional local sentence-transformers adapter; loading may download model weights."""
class EmbeddingUnavailable(RuntimeError): pass
class SentenceTransformerEmbedder:
    def __init__(self,model_name='sentence-transformers/all-MiniLM-L6-v2'): self.model_name=model_name; self._model=None
    def encode(self,texts):
        try:
            import numpy as np
            from sentence_transformers import SentenceTransformer
        except ImportError as exc: raise EmbeddingUnavailable('Install requirements-rag-optional.txt to enable semantic retrieval.') from exc
        if self._model is None:
            try: self._model=SentenceTransformer(self.model_name)
            except Exception as exc: raise EmbeddingUnavailable(f'Could not load embedding model ({type(exc).__name__}); check network or model cache.') from exc
        vectors=self._model.encode(list(texts),normalize_embeddings=True,convert_to_numpy=True)
        if not np.isfinite(vectors).all(): raise EmbeddingUnavailable('Embedding model returned non-finite values.')
        return vectors
