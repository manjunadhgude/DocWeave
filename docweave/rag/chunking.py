from hashlib import sha256
from docweave.rag.models import Chunk
def chunk_pages(pages, document_id, source_name, chunk_size=900, overlap=120):
    if chunk_size < 1 or overlap < 0 or overlap >= chunk_size:
        raise ValueError('Require chunk_size > overlap >= 0.')
    result=[]
    for page in pages:
        text=str(page.get('text','')).strip()
        if not text: continue
        page_no=page.get('page_number'); start=0
        while start < len(text):
            end=min(len(text),start+chunk_size); piece=text[start:end].strip()
            if piece:
                raw=f'{document_id}:{page_no}:{start}:{piece}'
                result.append(Chunk(sha256(raw.encode('utf-8')).hexdigest()[:20],str(document_id),piece,str(source_name),page_no,{'char_start':start,'char_end':end}))
            if end==len(text): break
            start=end-overlap
    return result
