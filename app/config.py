# ----------------------------------------------------------------------
# 阅读入口：读取 .env 和环境变量，定义所有可调参数，并在启动时检查不合法配置。
# 配置与代码分离后，更换模型、数据库或分块策略无需修改业务算法。SecretStr 默认遮盖密钥；只有创建模型客户端时才交给 SDK。环境变量优先于 .env。
# ----------------------------------------------------------------------
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ----------------------------------------------------------------------
# 配置：同一套代码，换一张“运行参数表”就能换环境。
# 例如本机用 localhost，服务器用内网地址；密钥由 .env 或环境变量提供。
# 代码示例（仅供阅读）：settings = Settings(chunk_size=600, chunk_overlap=100)
# chunk_size 在本项目按字符数计算，不等于模型 tokenizer 的 token 数。
# SecretStr 只是防止常规打印直接露出密钥；不是加密保险箱，仍不能提交真实 .env。
# 类似用法：数据库连接、超时时间、模型名称都应配置化，业务函数不写死它们。
# 面试问：为什么启动时校验参数？答：错误越早暴露越容易定位，避免后台任务跑到一半才失败。
# ----------------------------------------------------------------------
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
