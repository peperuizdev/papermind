import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import searcher

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["query"])


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=2)
    top_k: int = Field(8, ge=1, le=20)
    doc_type: str | None = Field(None)
    sections: list[str] | None = Field(None)
    study_id: str | None = Field(None)
    keywords: list[str] | None = Field(None)


class StudyRequest(BaseModel):
    study_id: str
    doc_type: str | None = None


def _score_to_relevance(score: float) -> str:
    if score >= 0.50:
        return "alta"
    if score >= 0.20:
        return "media"
    return "baja"


class ChunkOut(BaseModel):
    study_id: str
    title: str
    section: str
    doc_type: str
    relevance: str  # "alta" | "media" | "baja"
    text: str
    drive_link: str | None = None
    keywords: list[str] = []


class SearchResponse(BaseModel):
    query: str
    top_relevance: str
    chunks: list[ChunkOut]


@router.post("/search", response_model=SearchResponse)
def search(req: SearchRequest):
    """
    Búsqueda semántica + reranking Cohere con filtros opcionales de metadata.
    Diseñado para ser llamado como tool desde n8n AI Agent.
    """
    log.info(
        "Search: '%s' | top_k=%d | doc_type=%s | sections=%s | study_id=%s",
        req.query[:80], req.top_k, req.doc_type, req.sections, req.study_id,
    )

    chunks = searcher.search(
        query=req.query,
        top_k=req.top_k,
        doc_type=req.doc_type,
        sections=req.sections,
        study_id=req.study_id,
        keywords=req.keywords,
    )

    out = [
        ChunkOut(
            study_id=c.get("study_id", ""),
            title=c.get("title", ""),
            section=c.get("section", ""),
            doc_type=c.get("doc_type", ""),
            relevance=_score_to_relevance(c.get("score", 0.0)),
            text=c.get("text", ""),
            drive_link=c.get("drive_link"),
            keywords=c.get("keywords", []),
        )
        for c in chunks
    ]

    top_relevance = out[0].relevance if out else "baja"
    return SearchResponse(query=req.query, top_relevance=top_relevance, chunks=out)


@router.get("/study", response_model=dict)
def get_study(study_id: str, doc_type: str | None = None):
    return _study_response(study_id, doc_type)


@router.post("/study", response_model=dict)
def get_study_post(req: StudyRequest):
    """Igual que GET /api/study pero vía POST body — para tools de n8n."""
    return _study_response(req.study_id, req.doc_type)


def _study_response(study_id: str, doc_type: str | None) -> dict:
    log.info("Get study: %s (doc_type=%s)", study_id, doc_type)
    chunks = searcher.get_study_chunks(study_id, doc_type)

    if not chunks:
        raise HTTPException(status_code=404, detail=f"Estudio '{study_id}' no encontrado en la base de datos")

    title = chunks[0].get("title", "") if chunks else ""
    keywords = chunks[0].get("keywords", []) if chunks else []
    drive_link = chunks[0].get("drive_link") if chunks else None
    sections = list(dict.fromkeys(c.get("section", "") for c in chunks))

    return {
        "study_id": study_id,
        "title": title,
        "keywords": keywords,
        "drive_link": drive_link,
        "sections": sections,
        "chunks_count": len(chunks),
        "chunks": [
            {
                "section": c.get("section", ""),
                "doc_type": c.get("doc_type", ""),
                "text": c.get("text", ""),
            }
            for c in chunks
        ],
    }
