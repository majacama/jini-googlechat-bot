from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    gcp_project: str = ""
    gcp_region: str = "europe-west1"
    firestore_collection: str = "conversations"
    llm_provider: str = "gemini"
    gemini_model: str = "gemini-2.5-pro"
    start_endpoint_token: str = ""
    chat_audience: str = ""
    google_chat_app_id: str = ""
    chat_auth_disabled: bool = False
    use_memory_store: bool = False
    use_real_chat: bool = False
    chat_service_account: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
