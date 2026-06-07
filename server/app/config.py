from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "papermind"

    # Documentos
    docs_path: str = "../data/samples"

    # Embeddings
    embeddings_model: str = "text-embedding-3-large"
    openai_api_key: str = ""

    # OCR
    gemini_api_key: str = ""
    ocr_model: str = "gemini-2.5-flash"

    # Reranking
    cohere_api_key: str = ""
    reranker_model: str = "rerank-multilingual-v3.0"

    model_config = {"env_file": ".env", "case_sensitive": False, "extra": "ignore"}


settings = Settings()
