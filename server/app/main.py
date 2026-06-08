import logging

from fastapi import FastAPI
from qdrant_client import QdrantClient

from app.config import settings
from app.routers import ingest, query

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s  %(name)s  %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

app = FastAPI(title="PaperMind API", version="0.1.0")
app.include_router(ingest.router)
app.include_router(query.router)


@app.get("/api/health")
async def health():
    try:
        client = QdrantClient(url=settings.qdrant_url)
        client.get_collections()
        qdrant_status = "connected"
    except Exception:
        qdrant_status = "unreachable"

    return {
        "status": "ok",
        "qdrant": qdrant_status,
        "collection": settings.qdrant_collection,
        "embeddings_model": settings.embeddings_model,
    }
