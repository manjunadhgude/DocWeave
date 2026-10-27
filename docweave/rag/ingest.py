"""Safe text/JSON/PDF ingestion with page provenance."""
import json
from pathlib import Path
from docweave.rag.chunking import chunk_pages
class RAGIngestError(ValueError): pass
def load_pages(path, *, max_bytes=25*1024*1024, max_pages=200, enable_ocr=False):
    path=Path(path)
    try:
        size=path.stat().st_size
        if size > max_bytes: raise RAGIngestError(f'{path.name}: file exceeds {max_bytes} bytes')
        suffix=path.suffix.lower()
        if suffix=='.pdf':
            from docweave.pdf_ingest import extract_pdf_text
            try:
                extracted, source = extract_pdf_text(
                    path,
                    role='rag_document',
                    max_bytes=max_bytes,
                    max_pages=max_pages,
                    enable_ocr=enable_ocr,
                )
            except RAGIngestError:
                raise
            except Exception as exc:
                raise RAGIngestError(
                    f'{path.name}: PDF extraction failed ({type(exc).__name__})'
                ) from exc
            return extracted['pages'], {
                'source_name': path.name,
                'format': 'pdf',
                **source,
            }
        raw=path.read_text(encoding='utf-8')
        if suffix in {'.txt','.md'}: text=raw
        elif suffix=='.json':
            try: obj=json.loads(raw)
            except (json.JSONDecodeError, ValueError) as exc: raise RAGIngestError(f'{path.name}: invalid JSON') from exc
            text=json.dumps(obj,ensure_ascii=False,indent=2)
        else: raise RAGIngestError(f'Unsupported extension {suffix!r}; use .txt, .md, .json or .pdf')
        if not text.strip(): raise RAGIngestError(f'{path.name}: no extractable text')
        return [{'page_number':None,'text':text}], {'source_name':path.name,'format':suffix[1:],'byte_size':size}
    except OSError as exc: raise RAGIngestError(f'Could not read {path.name}: {type(exc).__name__}') from exc
def ingest_file(path, *, document_id=None, chunk_size=900, overlap=120, enable_ocr=False):
    path=Path(path); pages, metadata=load_pages(path,enable_ocr=enable_ocr)
    chunks=chunk_pages(pages,document_id or path.stem,path.name,chunk_size,overlap)
    if not chunks: raise RAGIngestError(f'{path.name}: no non-empty chunks created')
    return chunks,metadata
