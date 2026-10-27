"""Dependency-free BM25 keyword retrieval baseline."""
import math,re
from collections import Counter
from docweave.rag.models import RetrievedChunk
def tokenize(text): return re.findall(r"[a-z0-9]+(?:['-][a-z0-9]+)*",text.lower())
def bm25_search(query,chunks,top_k=5,k1=1.5,b=0.75):
    if top_k<1: raise ValueError('top_k must be >= 1')
    docs=[tokenize(c.text) for c in chunks]
    if not docs or not tokenize(query): return []
    avgdl=sum(map(len,docs))/len(docs) or 1.0; df=Counter(t for d in docs for t in set(d)); n=len(docs); terms=set(tokenize(query)); out=[]
    for chunk,tokens in zip(chunks,docs):
        counts=Counter(tokens); score=0.0; dl=len(tokens)
        for term in terms:
            freq=counts[term]
            if freq:
                idf=math.log(1+(n-df[term]+0.5)/(df[term]+0.5))
                score+=idf*(freq*(k1+1))/(freq+k1*(1-b+b*dl/avgdl))
        if score>0: out.append(RetrievedChunk(chunk,score,'bm25'))
    return sorted(out,key=lambda x:(-x.score,x.chunk.chunk_id))[:top_k]

# Conservative domain synonyms for business-document retrieval.
_QUERY_SYNONYMS = {
    "vendor": {"supplier"},
    "supplier": {"vendor"},
    "mismatch": {"discrepancy", "does", "not", "match"},
    "discrepancy": {"mismatch"},
    "match": {"mismatch"},
    "arrived": {"received"},
    "received": {"arrived"},
    "billed": {"invoiced", "invoice"},
    "invoiced": {"billed"},
    "total": {"amount"},
    "amount": {"total"},
    "replaced": {"superseded"},
    "superseded": {"replaced"},
    "refund": {"reimbursement"},
    "reimbursement": {"refund"},
}


def expand_query(query):
    """Add conservative domain synonyms while retaining original query terms."""
    terms = tokenize(query)
    expanded = list(terms)
    for term in terms:
        expanded.extend(sorted(_QUERY_SYNONYMS.get(term, set())))
    # Keep order stable and avoid repeating terms.
    return " ".join(dict.fromkeys(expanded))


def bm25_search_expanded(query, chunks, top_k=5):
    """Synonym-aware BM25 baseline; original bm25_search remains unchanged."""
    return bm25_search(expand_query(query), chunks, top_k=top_k)
