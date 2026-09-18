"""Conversation locale interactive : tu joues le collaborateur dans le terminal."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SPEC = ROOT / "forms" / "nouveau-dossier-client.json"


def _load_token(explicit: str) -> str:
    load_dotenv(ROOT / ".env")
    return explicit or os.getenv("START_ENDPOINT_TOKEN", "change-me")


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def wait_for_server(client: httpx.Client, base: str, attempts: int = 15) -> None:
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            client.get(f"{base}/health").raise_for_status()
            return
        except httpx.HTTPError as exc:
            last_error = exc
            time.sleep(1)
    raise SystemExit(
        "Le serveur ne répond pas. Lance d'abord relancer.bat "
        f"puis réessaie.\n({last_error})"
    ) from last_error


def fetch_state(client: httpx.Client, base: str, space_id: str, token: str) -> dict:
    resp = client.get(
        f"{base}/conversations",
        params={"space_id": space_id},
        headers=_headers(token),
    )
    resp.raise_for_status()
    return resp.json()


def last_agent_message(state: dict) -> str:
    for turn in reversed(state.get("history") or []):
        if turn.get("role") == "agent":
            return turn.get("text") or ""
    return ""


def print_agent(text: str) -> None:
    print()
    print("Agent :")
    print(text)
    print()


def start_conversation(
    client: httpx.Client,
    base: str,
    token: str,
    email: str,
    webhook_url: str,
    form_spec: dict,
) -> str:
    resp = client.post(
        f"{base}/start",
        headers=_headers(token),
        json={
            "contact": {"user_email": email},
            "form_spec": form_spec,
            "webhook_url": webhook_url,
        },
    )
    resp.raise_for_status()
    space_id = resp.json().get("space_id")
    if not space_id:
        raise SystemExit(f"Réponse /start sans space_id : {resp.text}")
    return space_id


def send_reply(client: httpx.Client, base: str, space_id: str, text: str) -> None:
    resp = client.post(
        f"{base}/chat",
        json={
            "type": "MESSAGE",
            "space": {"name": space_id},
            "message": {"text": text},
        },
    )
    resp.raise_for_status()


def show_completion(client: httpx.Client, base: str, state: dict) -> None:
    print(f"Statut : {state.get('status')}")
    print("Réponses :")
    print(json.dumps(state.get("answers") or {}, ensure_ascii=False, indent=2))
    try:
        inbox = client.get(f"{base}/dev/webhook").json()
        if inbox:
            print()
            print("Dernier webhook :")
            print(json.dumps(inbox[-1].get("body"), ensure_ascii=False, indent=2))
    except httpx.HTTPError:
        pass


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Dialogue local avec l'agent formulaire.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--contact-email", default="")
    parser.add_argument("--webhook-url", default="http://127.0.0.1:8000/dev/webhook")
    parser.add_argument("--form-spec", default=str(DEFAULT_SPEC))
    parser.add_argument("--token", default="")
    args = parser.parse_args()

    token = _load_token(args.token)
    form_spec = json.loads(Path(args.form_spec).read_text(encoding="utf-8"))
    base = args.base_url.rstrip("/")

    with httpx.Client(timeout=30.0) as client:
        wait_for_server(client, base)
        space_id = start_conversation(
            client,
            base,
            token,
            args.contact_email
            or (form_spec.get("recipient") or {}).get("email")
            or "collaborateur@jin.fr",
            args.webhook_url,
            form_spec,
        )
        state = fetch_state(client, base, space_id, token)
        print(f"Conversation {space_id}  —  {form_spec.get('title') or form_spec.get('form_id')}")
        print("Tape tes réponses. /quit pour sortir.")
        print_agent(last_agent_message(state))

        while state.get("status") == "in_progress":
            try:
                text = input("Toi > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nInterrompu.")
                return
            if not text:
                continue
            if text in {"/quit", "/exit"}:
                return
            send_reply(client, base, space_id, text)
            state = fetch_state(client, base, space_id, token)
            print_agent(last_agent_message(state))

        show_completion(client, base, state)


if __name__ == "__main__":
    main()
