import unittest
try: import numpy as np
except ImportError: np=None
from docweave.rag.models import Chunk
from docweave.rag.vector_store import InMemoryVectorStore
@unittest.skipIf(np is None,'NumPy optional dependency is not installed')
class VectorTests(unittest.TestCase):
 def test_cosine_order(self):
  cs=[Chunk('a','d','first','a.txt'),Chunk('b','d','second','b.txt')]; s=InMemoryVectorStore(); s.add(cs,[[1,0],[0,1]]); self.assertEqual(s.search([.9,.1])[0].chunk.chunk_id,'a')
 def test_invalid_dimensions(self):
  s=InMemoryVectorStore()
  with self.assertRaises(ValueError): s.add([Chunk('a','d','x','x')],[[1,0],[0,1]])
if __name__=='__main__': unittest.main()
