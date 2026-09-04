import argparse
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def resolve_user_id(email: str) -> str | None:
    try:
        from app.core.chat_client import resolve_chat_user_name

        name = resolve_chat_user_name(email)
        if name and "@" not in name:
            return name
    except Exception as exc:
        print(f"ID Chat non résolu en local ({exc}). Cloud Run tentera à son tour.")
    return None


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Déclenche une conversation via POST /start (mode dev local possible)."
    )
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--contact-email", required=True)
    parser.add_argument(
        "--webhook-url",
        default="http://127.0.0.1:8000/dev/webhook",
    )
    parser.add_argument(
        "--form-spec",
        default=str(ROOT / "tests" / "fixtures" / "form_spec_exemple.json"),
    )
    parser.add_argument("--token", default=os.getenv("START_ENDPOINT_TOKEN", ""))
    args = parser.parse_args()

    if not args.token:
        raise SystemExit(
            "START_ENDPOINT_TOKEN manquant. Passe --token ou définis la variable d'environnement."
        )

    contact: dict[str, str] = {"user_email": args.contact_email}
    user_id = resolve_user_id(args.contact_email)
    if user_id:
        contact["user_id"] = user_id
        print(f"ID Chat résolu : {user_id}")

    payload = {
        "contact": contact,
        "form_spec": load_json(args.form_spec),
        "webhook_url": args.webhook_url,
    }
    headers = {"Authorization": f"Bearer {args.token}"}

    start_url = f"{args.base_url.rstrip('/')}/start"
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(start_url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    space_id = data.get("space_id")
    if not space_id:
        raise SystemExit(f"Réponse inattendue sans space_id: {data}")

    print(space_id)
    print()
    if "localhost" in args.base_url or "127.0.0.1" in args.base_url:
        print("Répondre ensuite avec :")
        print(
            f'  python .\\scripts\\reply.py --space-id "{space_id}" --text "Acme SAS" --token "{args.token}"'
        )
    else:
        print("Réponds dans Google Chat (même DM).")
        print("1) nom fournisseur  2) date AAAA-MM-JJ  3) commentaire (ou « skip »).")
        print(f"JSON final : {args.webhook_url}")


if __name__ == "__main__":
    main()
