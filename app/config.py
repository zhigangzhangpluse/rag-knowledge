"""集中读取配置，密钥使用 SecretStr 防止被意外打印。"""
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    deepseek_api_key: SecretStr = SecretStr("")
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-flash"
    llm_temperature: float = 0.1
    llm_max_tokens: int = 1200
    llm_timeout: int = 90
    app_mode: str = "production"
    database_url: str = "sqlite:///./data/app.db"
    data_dir: Path = Path("data")
    milvus_uri: str = "http://127.0.0.1:19530"
    milvus_collection: str = "rag_chunks"
    redis_url: str = "redis://127.0.0.1:6379/0"
    embedding_model: str = "BAAI/bge-m3"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    model_device: str = "cpu"
    chunk_size: int = Field(500, ge=80, le=1600)
    chunk_overlap: int = Field(80, ge=0)
    recall_k: int = Field(30, ge=1, le=100)
    rerank_k: int = Field(20, ge=1, le=100)
    context_k: int = Field(6, ge=1, le=20)
    min_rerank_score: float = Field(0.2, ge=0, le=1)
    session_ttl: int = Field(86400, ge=60)
    max_upload_mb: int = 20

    @model_validator(mode="after")
    def validate_options(self):
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP 必须小于 CHUNK_SIZE")
        if self.app_mode not in {"production", "demo", "test"}:
            raise ValueError("APP_MODE 必须为 production、demo 或 test")
        return self
