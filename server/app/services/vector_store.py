import logging

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from app.config import settings

log = logging.getLogger(__name__)

_UPSERT_BATCH = 100  # tamaño de lote para upsert


def get_client() -> QdrantClient:
    """Devuelve cliente Qdrant configurado."""
    return QdrantClient(url=settings.qdrant_url)


def ensure_collection(client: QdrantClient) -> None:
    """Crea la colección si no existe (idempotente)."""
    existing = {c.name for c in client.get_collections().collections}
    if settings.qdrant_collection not in existing:
        client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=VectorParams(size=3072, distance=Distance.COSINE),
        )
        log.info("Colección '%s' creada", settings.qdrant_collection)
    else:
        log.debug("Colección '%s' ya existe", settings.qdrant_collection)


def upsert_chunks(chunks: list[dict]) -> int:
    """
    Inserta o actualiza chunks en Qdrant.
    Cada chunk debe tener 'vector', 'text' y 'metadata'.
    Devuelve el número de puntos insertados.
    """
    if not chunks:
        return 0

    client = get_client()
    ensure_collection(client)

    points = [_to_point(c) for c in chunks]

    # Upsert en lotes para no saturar la conexión
    for i in range(0, len(points), _UPSERT_BATCH):
        batch = points[i : i + _UPSERT_BATCH]
        client.upsert(collection_name=settings.qdrant_collection, points=batch)
        log.debug("  Upsert lote %d-%d", i, i + len(batch) - 1)

    log.info("Upsert completado: %d puntos en '%s'", len(points), settings.qdrant_collection)
    return len(points)


def _to_point(chunk: dict) -> PointStruct:
    """Convierte un chunk con vector a PointStruct de Qdrant."""
    # chunk_file_id ya es un UUID5 — coincide directamente con el ID del punto en Qdrant
    payload = {"text": chunk["text"], **chunk["metadata"]}
    return PointStruct(
        id=chunk["metadata"]["chunk_file_id"],
        vector=chunk["vector"],
        payload=payload,
    )
