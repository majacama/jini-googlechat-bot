import httpx

from app.core.webhook import build_payload, deliver_completion, sign_body
from app.models.conversation_state import ConversationState


def test_sign_body_is_hex_hmac() -> None:
    signature = sign_body(b'{"a":1}', "secret")
    assert len(signature) == 64
    assert signature == sign_body(b'{"a":1}', "secret")
    assert signature != sign_body(b'{"a":2}', "secret")


def test_deliver_success_sends_signature(conversation: ConversationState) -> None:
    conversation.webhook_secret = "s3cret"
    conversation.completed_at = "2026-09-03T14:22:00Z"
    conversation.answers = {"nom_fournisseur": "Acme SAS", "date_debut": "2026-03-15"}
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["signature"] = request.headers.get("X-Signature")
        seen["body"] = request.content
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        assert deliver_completion(conversation, client=client)

    assert seen["signature"] == sign_body(seen["body"], "s3cret")
    assert b"onboarding-fournisseur-v1" in seen["body"]


def test_deliver_retries_then_fails(conversation: ConversationState) -> None:
    sleeps: list[int] = []

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        ok = deliver_completion(conversation, client=client, sleep=sleeps.append)
    assert not ok
    assert sleeps == [1, 2]


def test_payload_shape(conversation: ConversationState) -> None:
    conversation.completed_at = "2026-09-03T14:22:00Z"
    payload = build_payload(conversation)
    assert set(payload) == {"form_id", "space_id", "contact", "answers", "completed_at"}
