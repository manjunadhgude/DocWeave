"""Synthetic RAG baseline evaluation; no API key or model required."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from docweave.rag.models import Chunk
from docweave.rag.keyword import bm25_search
from docweave.rag.reranking import rerank
from docweave.rag.answering import answer_question
from docweave.rag.providers import DeterministicProvider
CHUNKS=[
 Chunk('c1','invoice','Invoice total amount is 120 USD.','invoice.txt',1),
 Chunk('c2','receipt','Goods receipt received quantity is 8 units.','receipt.txt',1),
 Chunk('c3','review','Supplier mismatch requires manual review.','review.txt',1),
 Chunk('c4','other','Shipping address and delivery window.','other.txt',1)]
CASES=[
 {'question':'invoice total','expected':'c1','answerable':True},
 {'question':'received quantity','expected':'c2','answerable':True},
 {'question':'supplier mismatch','expected':'c3','answerable':True},
 {'question':'quantum tax deduction eligibility','expected':None,'answerable':False}]
def retrieval_metrics(rankings, cases):
    answerable=[]
    for ranked,case in zip(rankings,cases):
        gold=case['expected']
        if not gold:
            continue
        ids=[r.chunk.chunk_id for r in ranked]
        answerable.append((gold,ids))
    n=len(answerable)
    recall=sum(1 for gold,ids in answerable if gold in ids[:3])/max(1,n)
    reciprocal_ranks=[1/(ids.index(gold)+1) if gold in ids else 0.0 for gold,ids in answerable]
    return {'recall_at_3':recall,'mrr':sum(reciprocal_ranks)/max(1,n)}
def main():
    configurations={'bm25':[],'bm25_plus_rerank':[]}; details=[]
    abstention_correct=0; citation_reference_matches=0; supported_answer_cases=0
    for case in CASES:
        base=bm25_search(case['question'],CHUNKS,top_k=4)
        reranked=rerank(case['question'],base,top_k=4)
        configurations['bm25'].append(base); configurations['bm25_plus_rerank'].append(reranked)
        answer=answer_question(case['question'],base,DeterministicProvider())
        abstention_correct += int(answer.abstained == (not case['answerable']))
        citation_ids=[c.chunk_id for c in answer.citations]
        citation_match=bool(case['expected'] and case['expected'] in citation_ids)
        citation_reference_matches += int(citation_match)
        supported_answer_cases += int(not answer.abstained and citation_match)
        details.append({'question':case['question'],'expected_chunk_id':case['expected'],
            'answerable':case['answerable'],'bm25_ranked_ids':[r.chunk.chunk_id for r in base],
            'reranked_ids':[r.chunk.chunk_id for r in reranked],'abstained':answer.abstained,
            'citation_reference_match':citation_match,'synthetic_case':True})
    n=len(CASES)
    out={'dataset':'synthetic','case_count':n,
      'retrieval_metrics':{name:retrieval_metrics(ranks,CASES) for name,ranks in configurations.items()},
      'pipeline_metrics':{'abstention_decision_accuracy':abstention_correct/n,
        'citation_reference_match_rate_on_answerable_cases':citation_reference_matches/max(1,sum(c['answerable'] for c in CASES)),
        'answer_with_expected_evidence_reference_rate':supported_answer_cases/max(1,sum(c['answerable'] for c in CASES))},
      'cases':details,
      'limitations':['Tiny designed dataset; not representative real-world accuracy.',
        'Citation reference matching is not a semantic entailment check.',
        'Deterministic provider validates plumbing, not real LLM answer correctness.',
        'Semantic retrieval requires optional dependencies and model weights; this offline evaluation does not measure it.',
        'Lexical reranking is not a neural cross-encoder.']}
    target=Path('.docweave-rag-reports/rag-evaluation.json'); target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(out,indent=2),encoding='utf-8'); print(json.dumps(out,indent=2))
if __name__=='__main__': main()
