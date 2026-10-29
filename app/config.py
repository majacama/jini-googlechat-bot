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
    # Dossiers clients : serveur MCP admin.jin.fr (spec admin.jin.fr §11)
    admin_jin_url: str = "https://admin.jin.fr"
    admin_jin_bot_token: str = ""
    # Espace IT Operations : cartes de validation et suivi des demandes.
    it_ops_space: str = "spaces/AAQAT7GKGxc"
    # Compte de service de Cloud Scheduler, seul autorisé à appeler /tasks/bot-feed.
    feed_invoker: str = "agent-formulaire-gchat@admin-jin-fr.iam.gserviceaccount.com"
    dossier_model: str = "gemini-2.5-flash"
    # Base de connaissances, cas A : par l'agent « jinbot » d'agent.jin.fr (app/kb/agent_jin.py).
    agent_jin_url: str = "https://agent.jin.fr"
    agent_jin_agent: str = "jinbot"
    agent_jin_key: str = ""
    agent_jin_timeout_s: float = 25.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
