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
    default_handoff_contact: str = "fdiaz@jin.fr"
    # Base de connaissances : synchronisation Drive partagé -> Supabase (app/kb)
    kb_drive_id: str = ""
    kb_db_host: str = "aws-1-eu-west-3.pooler.supabase.com"
    kb_db_port: int = 5432
    kb_db_name: str = "postgres"
    kb_db_user: str = "jin_kb_bot.afospuiklslsddxrseub"
    kb_db_password: str = ""
    kb_embedding_model: str = "gemini-embedding-001"
    kb_embedding_dim: int = 1536
    kb_top_k: int = 8
    # Les scores cosinus de gemini-embedding-001 sont resserrés : ~0.68-0.81 pour une vraie
    # correspondance, ~0.64 pour du bruit. Seuil à réajuster sur de vraies questions.
    kb_min_similarity: float = 0.66


@lru_cache
def get_settings() -> Settings:
    return Settings()
