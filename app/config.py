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
    # Base de connaissances, cas A : par l'agent « jinbot » d'agent.jin.fr. L'ancien moteur local
    # (app/kb, index _jin_knowledge_base) reste en repli pendant la bascule (KB_ENGINE=local pour
    # le forcer) ; agent.jin.fr injoignable -> repli automatique sur le local s'il est configuré.
    kb_engine: str = "agent_jin"  # agent_jin | local
    agent_jin_url: str = "https://agent.jin.fr"
    agent_jin_agent: str = "jinbot"
    agent_jin_key: str = ""
    agent_jin_timeout_s: float = 25.0
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
