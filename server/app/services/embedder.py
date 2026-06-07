import logging

from openai import OpenAI

from app.config import settings

log = logging.getLogger(__name__)

_BATCH_SIZE = 100  # límite conservador para evitar rate limits


def embed_chunks(chunks: list[dict]) -> list[dict]:
    """Añade vector de embedding a cada chunk. Devuelve nueva lista con clave 'vector'."""
    if not chunks:
        return []

    client = OpenAI(api_key=settings.openai_api_key)
    texts = [c["text"] for c in chunks]
    vectors = _embed_batched(client, texts)

    log.info("Embedded %d chunks with model %s", len(chunks), settings.embeddings_model)
    return [{**chunk, "vector": vector} for chunk, vector in zip(chunks, vectors)]


def _embed_batched(client: OpenAI, texts: list[str]) -> list[list[float]]:
    """Llama a la API en batches preservando el orden original."""
    all_vectors: list[list[float]] = []

    for i in range(0, len(texts), _BATCH_SIZE):
        batch = texts[i : i + _BATCH_SIZE]
        log.debug("  Embedding batch %d-%d", i, i + len(batch) - 1)

        response = client.embeddings.create(
            model=settings.embeddings_model,
            input=batch,
        )
        # La API garantiza el mismo orden que el input
        all_vectors.extend(r.embedding for r in response.data)

    return all_vectors
