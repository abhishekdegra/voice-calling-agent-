"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # 1. Gemini Configuration
    gemini_api_key: Optional[str] = Field(default=None, alias="GEMINI_API_KEY")
    gemini_live_model: str = Field(default="models/gemini-3.1-flash-live-preview", alias="GEMINI_LIVE_MODEL")
    gemini_voice_name: str = Field(default="Aoede", alias="GEMINI_VOICE_NAME")

    # 2. TeleCMI / PIOPIY Configuration
    telecmi_app_id: int = Field(default=33338876, alias="TELECMI_APP_ID")
    telecmi_app_secret: str = Field(default="", alias="TELECMI_APP_SECRET")
    telecmi_sbc: str = Field(default="sbcind.telecmi.com", alias="TELECMI_SBC")
    telecmi_user_id: str = Field(default="5002_33338876", alias="TELECMI_USER_ID")
    telecmi_user_password: str = Field(default="", alias="TELECMI_USER_PASSWORD")
    telecmi_rest_base: str = Field(default="https://rest.telecmi.com", alias="TELECMI_REST_BASE")
    telecmi_caller_id: Optional[str] = Field(default="33338876", alias="TELECMI_CALLER_ID")

    # 3. Welfog External APIs
    welfog_api_base: str = Field(default="https://welfogapi.welfog.com", alias="WELFOG_API_BASE")
    supplier_service_base: str = Field(default="https://supplierservice.welfog.com", alias="SUPPLIER_SERVICE_BASE")

    # 4. Welfog Knowledge Base (Existing aidata.welfog.com API or direct Qdrant)
    welfog_knowledge_api_url: str = Field(default="https://aidata.welfog.com/api/search", alias="WELFOG_KNOWLEDGE_API_URL")
    welfog_knowledge_api_key: Optional[str] = Field(default=None, alias="WELFOG_KNOWLEDGE_API_KEY")
    qdrant_url: Optional[str] = Field(default=None, alias="QDRANT_URL")
    qdrant_api_key: Optional[str] = Field(default=None, alias="QDRANT_API_KEY")
    qdrant_collection: str = Field(default="company_knowledge", alias="QDRANT_COLLECTION")

    # 5. Database Configuration (MySQL / XAMPP)
    db_host: str = Field(default="localhost", alias="DB_HOST")
    db_port: int = Field(default=3306, alias="DB_PORT")
    db_user: str = Field(default="root", alias="DB_USER")
    db_password: str = Field(default="", alias="DB_PASSWORD")
    db_name: str = Field(default="welfog_ai", alias="DB_NAME")

    # 6. Server & Streaming URLs
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")
    voice_server_public_url: str = Field(default="http://localhost:8000", alias="VOICE_SERVER_PUBLIC_URL")
    telecmi_websocket_url: str = Field(default="ws://localhost:8000/ws/telecmi", alias="TELECMI_WEBSOCKET_URL")

    # 7. Runtime settings
    environment: str = Field(default="development", alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()
