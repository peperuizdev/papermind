import logging

import httpx
from openai import OpenAI
from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

from app.config import settings
from app.services.vector_store import get_client

log = logging.getLogger(__name__)

_CANDIDATE_MULTIPLIER = 3  # candidatos = top_k * multiplier antes de reranking


def search(
    query: str,
    top_k: int = 8,
    doc_type: str | None = None,
    sections: list[str] | None = None,
    study_id: str | None = None,
    keywords: list[str] | None = None,
) -> list[dict]:
    """
    Búsqueda semántica densa + reranking Cohere con filtros opcionales de metadata.

    Filtros disponibles:
      - doc_type: "full" | "short"
      - sections: ["abstract", "introduction", "methods", "results", "discussion", "conclusion"]
      - study_id: e.g. "FAM-107"
      - keywords: términos exactos del campo keywords del payload, e.g. ["retinol", "anti-aging"]
    """
    qdrant_filter = _build_filter(doc_type, sections, study_id, keywords)
    candidate_k = top_k * _CANDIDATE_MULTIPLIER

    vector = _embed_query(query)
    candidates = _vector_search(vector, candidate_k, qdrant_filter)

    if not candidates:
        return []

    return _rerank(query, candidates, top_k)


def get_study_chunks(study_id: str, doc_type: str | None = None) -> list[dict]:
    """Recupera todos los chunks de un estudio concreto, ordenados por sección IMRaD."""
    conditions: list = [FieldCondition(key="study_id", match=MatchValue(value=study_id))]
    if doc_type:
        conditions.append(FieldCondition(key="doc_type", match=MatchValue(value=doc_type)))

    client = get_client()
    result = client.scroll(
        collection_name=settings.qdrant_collection,
        scroll_filter=Filter(must=conditions),
        limit=50,
        with_payload=True,
        with_vectors=False,
    )

    points = result[0]
    log.info("get_study_chunks: %d chunks para %s (doc_type=%s)", len(points), study_id, doc_type)
    return _sort_imrad([p.payload for p in points])


def _build_filter(
    doc_type: str | None,
    sections: list[str] | None,
    study_id: str | None,
    keywords: list[str] | None = None,
) -> Filter | None:
    conditions = []
    if doc_type:
        conditions.append(FieldCondition(key="doc_type", match=MatchValue(value=doc_type)))
    if sections:
        conditions.append(FieldCondition(key="section", match=MatchAny(any=sections)))
    if study_id:
        conditions.append(FieldCondition(key="study_id", match=MatchValue(value=study_id)))
    if keywords:
        # MatchAny sobre campo array: coincide si alguno de los keywords está en el array del chunk
        conditions.append(FieldCondition(key="keywords", match=MatchAny(any=keywords)))
    return Filter(must=conditions) if conditions else None


def _embed_query(query: str) -> list[float]:
    client = OpenAI(api_key=settings.openai_api_key)
    response = client.embeddings.create(model=settings.embeddings_model, input=[query])
    return response.data[0].embedding


def _vector_search(
    vector: list[float],
    top_k: int,
    qdrant_filter: Filter | None,
    score_threshold: float = 0.0,
) -> list[dict]:
    client = get_client()
    result = client.query_points(
        collection_name=settings.qdrant_collection,
        query=vector,
        limit=top_k,
        score_threshold=score_threshold,
        with_payload=True,
        query_filter=qdrant_filter,
    )
    chunks = [hit.payload for hit in result.points]
    for i, hit in enumerate(result.points):
        chunks[i]["_vector_score"] = hit.score

    # Fallback: si el threshold filtró todo, busca sin restricción de score
    if not chunks and score_threshold >= 0.0:
        log.info("Vector: sin candidatos con threshold %.1f, reintentando sin filtro", score_threshold)
        return _vector_search(vector, top_k, qdrant_filter, score_threshold=-1.0)

    top_vector = chunks[0]["_vector_score"] if chunks else 0.0
    log.info("Vector: %d candidatos | top score: %.3f", len(chunks), top_vector)
    return chunks


def _rerank(query: str, candidates: list[dict], top_k: int) -> list[dict]:
    texts = [c.get("text", "") for c in candidates]

    try:
        response = httpx.post(
            "https://api.cohere.com/v2/rerank",
            headers={
                "Authorization": f"Bearer {settings.cohere_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.reranker_model,
                "query": query,
                "documents": texts,
                "top_n": top_k,
                "return_documents": False,
            },
            timeout=15.0,
        )
        response.raise_for_status()
        results = response.json()["results"]
    except Exception as e:
        log.warning("Reranker no disponible (%s), devolviendo orden vectorial", e)
        return candidates[:top_k]

    ranked = []
    for r in results:
        chunk = dict(candidates[r["index"]])
        chunk["score"] = round(r["relevance_score"], 4)
        ranked.append(chunk)

    top_score = ranked[0]["score"] if ranked else 0.0
    log.info("Reranker: %d → %d | top score: %.3f | query: %.50s", len(candidates), len(ranked), top_score, query)
    return ranked


_SECTION_ORDER = ["abstract", "introduction", "methods", "results", "discussion", "conclusion"]


def _sort_imrad(chunks: list[dict]) -> list[dict]:
    def key(c: dict) -> int:
        sec = c.get("section", "")
        try:
            return _SECTION_ORDER.index(sec)
        except ValueError:
            return 99
    return sorted(chunks, key=key)
