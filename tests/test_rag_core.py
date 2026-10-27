import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from docweave.rag.models import Chunk,RetrievedChunk
from docweave.rag.chunking import chunk_pages
from docweave.rag.keyword import bm25_search
from docweave.rag.retrieval import reciprocal_rank_fusion,hybrid_search
from docweave.rag.reranking import rerank
from docweave.rag.answering import answer_question
from docweave.rag.providers import DeterministicProvider
from docweave.rag.ingest import load_pages,RAGIngestError
class RAGCoreTests(unittest.TestCase):
 def setUp(self): self.chunks=[Chunk('a','d1','Invoice total is 120 dollars.','invoice.pdf',1),Chunk('b','d2','Purchase order total is 100 dollars.','po.pdf',2),Chunk('c','d3','Supplier contact information.','supplier.txt')]
 def test_page_preserved_and_overlap(self):
  cs=chunk_pages([{'page_number':4,'text':'abcdefghij'}],'d','f.pdf',6,2); self.assertEqual([x.page_number for x in cs],[4,4]); self.assertEqual(cs[0].text[-2:],cs[1].text[:2])
 def test_bad_chunk_config(self):
  with self.assertRaises(ValueError): chunk_pages([],'d','f',4,4)
 def test_bm25_relevant_first(self): self.assertEqual(bm25_search('invoice total',self.chunks,2)[0].chunk.chunk_id,'a')
 def test_fusion_deduplicates(self):
  a=RetrievedChunk(self.chunks[0],1,'semantic'); b=RetrievedChunk(self.chunks[1],.5,'semantic'); self.assertEqual(len(reciprocal_rank_fusion([a,b],[b,a])),2)
 def test_hybrid_keyword_fallback(self): self.assertTrue(hybrid_search('invoice total',self.chunks,[],2))
 def test_rerank(self):
  c=[RetrievedChunk(self.chunks[2],.9,'hybrid'),RetrievedChunk(self.chunks[0],.2,'hybrid')]; self.assertEqual(rerank('invoice total',c)[0].chunk.chunk_id,'a')
 def test_citation_page(self):
  a=answer_question('invoice total',[RetrievedChunk(self.chunks[0],.8,'bm25')],DeterministicProvider()); self.assertFalse(a.abstained); self.assertEqual(a.citations[0].page_number,1)
 def test_abstains_without_evidence(self): self.assertTrue(answer_question('unknown',[],DeterministicProvider()).abstained)
 def test_provider_abstention(self):
  class P:
   def generate(self,q,e): return 'INSUFFICIENT_EVIDENCE'
  self.assertTrue(answer_question('unknown',[RetrievedChunk(self.chunks[0],.8,'bm25')],P()).abstained)
 def test_text_json_ingestion(self):
  with TemporaryDirectory() as d:
   p=Path(d)/'a.txt'; p.write_text('hello world',encoding='utf-8'); self.assertEqual(load_pages(p)[0][0]['text'],'hello world')
   j=Path(d)/'a.json'; j.write_text('{"ok": true}',encoding='utf-8'); self.assertIn('true',load_pages(j)[0][0]['text'])
 def test_unsupported_ingestion(self):
  with TemporaryDirectory() as d:
   p=Path(d)/'a.exe'; p.write_text('no')
   with self.assertRaises(RAGIngestError): load_pages(p)
if __name__=='__main__': unittest.main()
