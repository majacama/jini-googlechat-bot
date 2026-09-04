from functools import lru_cache

from app.config import get_settings
from app.core.chat_client import FakeChatClient, GoogleChatClient
from app.storage.base import ConversationRepo
from app.storage.firestore_repo import FirestoreConversationRepo
from app.storage.memory_repo import MemoryConversationRepo


@lru_cache
def get_repo() -> ConversationRepo:
    settings = get_settings()
    if settings.use_memory_store or (settings.app_env == "dev" and not settings.gcp_project):
        return MemoryConversationRepo()
    return FirestoreConversationRepo()


@lru_cache
def get_chat_client():
    settings = get_settings()
    if settings.use_real_chat:
        return GoogleChatClient()
    if settings.use_memory_store or (settings.app_env == "dev" and not settings.gcp_project):
        return FakeChatClient()
    return GoogleChatClient()
