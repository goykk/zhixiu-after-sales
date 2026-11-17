"""集中配置：所有运行期参数通过环境变量或 `.env` 覆盖。"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_name: str = "zhixiu-v12"
    env: str = "local"
    database_url: str = "sqlite:///./data/app.db"
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 480
    upload_dir: str = "data/uploads"
    trace_dir: str = "data/traces"
    report_dir: str = "data/reports"
    ai_provider: str = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gemma4:12b"
    ollama_timeout: float = 180.0
    ollama_embedding_model: str = ""
    embedding_dim: int = 768
    ocr_provider: str = "mock"
    ocr_lang: str = "ch"
    ocr_min_confidence: float = 0.5
    ocr_pdf_text_layer: bool = True
    max_upload_bytes: int = 10485760
    min_confidence: float = 0.5
    relevance_threshold: float = 0.15
    max_probe_steps: int = 5
    vector_backend: str = "json"
    pgvector_dim: int = 768
    workflow_engine: str = "native"
    task_backend: str = "sync"
    redis_url: str = "redis://127.0.0.1:6379/1"
    task_ttl_seconds: int = 86400
    otel_enabled: bool = False
    otel_exporter: str = "none"
    otel_endpoint: str = "http://localhost:4318"
    otel_service_name: str = "zhixiu-v12"
    otel_headers: str = ""
    otel_sample_ratio: float = 1.0
    jwt_min_secret_bytes: int = 32
    rate_limit_enabled: bool = False
    rate_limit_per_minute: int = 60
    rate_limit_burst: int = 20


settings = Settings()