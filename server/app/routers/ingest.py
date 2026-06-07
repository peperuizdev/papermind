import logging
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, UploadFile

from app.services import chunker, embedder, extractor, source, triage, vector_store

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


@router.post("")
def ingest_all():
    """Pipeline completo: extrae, chunkea, embebe e indexa todos los PDFs en Qdrant."""
    pdfs = source.list_pdfs()
    ok, errors = [], []

    for doc in pdfs:
        sid = f"{doc['study_id']} ({doc['doc_type']})"
        try:
            text, extraction = _extract(doc)
            chunks   = chunker.chunk_document(text, doc)
            embedded = embedder.embed_chunks(chunks)
            n        = vector_store.upsert_chunks(embedded)
            log.info("OK %s → %d chunks [%s]", sid, n, extraction)
            ok.append({"study_id": doc["study_id"], "doc_type": doc["doc_type"],
                       "extraction": extraction, "chunks": n})
        except Exception as e:
            log.error("ERROR %s: %s", sid, e)
            errors.append({"study_id": doc["study_id"], "doc_type": doc["doc_type"], "error": str(e)})

    total_chunks = sum(r["chunks"] for r in ok)
    log.info("Ingest completo: %d docs, %d chunks, %d errores", len(ok), total_chunks, len(errors))
    return {
        "processed": len(ok),
        "total_chunks": total_chunks,
        "errors": len(errors),
        "results": ok,
        "errors_detail": errors,
    }


@router.get("/triage")
def triage_preview():
    """Clasifica todos los PDFs en DOCS_PATH como native u ocr, sin ingestarlos."""
    log.info("Starting triage preview")
    pdfs = source.list_pdfs()
    result = []
    for doc in pdfs:
        pdf_type = triage.classify(doc["path"])
        log.info("  %-50s %s / %s", doc["path"].name, doc["doc_type"], pdf_type)
        result.append({
            "file": doc["path"].name,
            "study_id": doc["study_id"],
            "doc_type": doc["doc_type"],
            "related_study_id": doc["related_study_id"],
            "extraction": pdf_type,
        })

    native = sum(1 for r in result if r["extraction"] == "native")
    ocr = sum(1 for r in result if r["extraction"] == "ocr")
    log.info("Triage complete: %d native, %d ocr", native, ocr)
    return {"total": len(result), "native": native, "ocr": ocr, "docs": result}


def _find_doc(study_id: str, doc_type: str | None) -> dict:
    """Busca un documento por study_id, con filtro opcional de doc_type."""
    pdfs = source.list_pdfs()
    candidates = [d for d in pdfs if d["study_id"].lower() == study_id.lower()]
    if not candidates:
        raise HTTPException(status_code=404, detail=f"PDF not found: {study_id}")
    if doc_type:
        candidates = [d for d in candidates if d["doc_type"] == doc_type]
        if not candidates:
            raise HTTPException(status_code=404, detail=f"{study_id} with doc_type={doc_type} not found")
    # Si hay ambos (full + short), preferir full por defecto
    return next((d for d in candidates if d["doc_type"] == "full"), candidates[0])


@router.post("/file")
async def ingest_file(
    file: UploadFile,
    drive_link: str | None = Form(default=None),
):
    """Ingesta un PDF individual recibido como upload (desde n8n / Google Drive)."""
    meta = source._parse_filename(Path(file.filename or ""))
    if not meta:
        raise HTTPException(
            status_code=422,
            detail=f"Nombre de archivo no reconocido: '{file.filename}'. Usa 'FAM 123.pdf' o 'FAM 123 - titulo.pdf'",
        )

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        doc = {**meta, "path": tmp_path, "related_study_id": None, "drive_link": drive_link}
        text, extraction = _extract(doc)
        chunks = chunker.chunk_document(text, doc)
        embedded = embedder.embed_chunks(chunks)
        n = vector_store.upsert_chunks(embedded)
        log.info("Drive ingest: %s → %d chunks [%s]", meta["study_id"], n, extraction)
        return {
            "study_id": meta["study_id"],
            "doc_type": meta["doc_type"],
            "extraction": extraction,
            "chunks": n,
        }
    finally:
        tmp_path.unlink(missing_ok=True)


def _extract(doc: dict) -> tuple[str, str]:
    """Extract text from a document, returns (text, extraction_type)."""
    pdf_type = triage.classify(doc["path"])
    if pdf_type == "native":
        return extractor.extract_native(doc["path"]), "native"
    return extractor.extract_ocr(doc["path"]), "ocr"


@router.get("/extract/{study_id}")
def extract_preview(study_id: str, doc_type: str | None = None):
    """Devuelve el texto extraído de cualquier PDF — native u OCR (solo debug)."""
    doc = _find_doc(study_id, doc_type)
    text, extraction = _extract(doc)
    return {
        "study_id": doc["study_id"],
        "doc_type": doc["doc_type"],
        "extraction": extraction,
        "file": doc["path"].name,
        "chars": len(text),
        "preview": text[:2000],
    }


@router.get("/chunks/{study_id}")
def chunks_preview(study_id: str, doc_type: str | None = None):
    """Devuelve los chunks de cualquier PDF sin ingestarlo (solo debug)."""
    doc = _find_doc(study_id, doc_type)
    text, _ = _extract(doc)
    chunks = chunker.chunk_document(text, doc)

    return {
        "study_id": doc["study_id"],
        "total_chunks": len(chunks),
        "chunks": [
            {
                "chunk_file_id": c["metadata"]["chunk_file_id"],
                "section": c["metadata"]["section"],
                "chars": len(c["text"]),
                "keywords": c["metadata"]["keywords"],
                "title": c["metadata"]["title"],
                "preview": c["text"][:300],
            }
            for c in chunks
        ],
    }
