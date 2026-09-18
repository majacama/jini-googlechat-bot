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
    parser.add_argument(
        "--contact-email",
        default="",
        help="Destinataire du DM. Défaut : recipient.email de la spec.",
    )
    parser.add_argument(
        "--webhook-url",
        default="http://127.0.0.1:8000/dev/webhook",
    )
    parser.add_argument(
        "--form-spec",
        default=str(ROOT / "forms" / "nouveau-dossier-client.json"),
    )
    parser.add_argument("--token", default=os.getenv("START_ENDPOINT_TOKEN", ""))
    args = parser.parse_args()

    if not args.token:
        raise SystemExit(
            "START_ENDPOINT_TOKEN manquant. Passe --token ou définis la variable d'environnement."
        )

    form_spec = load_json(args.form_spec)
    recipient = form_spec.get("recipient") or {}
    email = args.contact_email or recipient.get("email")
    if not email:
        raise SystemExit(
            "Passe --contact-email ou définis recipient.email dans la spec JSON."
        )
    contact: dict[str, str] = {"user_email": email}
    if recipient.get("name"):
        contact["display_name"] = recipient["name"]
    user_id = resolve_user_id(email) or recipient.get("user_id")
    if user_id:
        contact["user_id"] = user_id
        print(f"ID Chat : {user_id}")
    else:
        print(
            "ID Chat introuvable pour cet e-mail. L'API Chat refuse users/email@domaine. "
            "Ajoute recipient.user_id dans la spec (users/123…) ou ouvre une session ADC "
            "avec ce compte, puis relance."
        )

    payload = {
        "contact": contact,
        "form_spec": form_spec,
        "webhook_url": args.webhook_url,
    }
    headers = {"Authorization": f"Bearer {args.token}"}

    start_url = f"{args.base_url.rstrip('/')}/start"
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(start_url, json=payload, headers=headers)
        if resp.is_error:
            print(f"HTTP {resp.status_code} sur {start_url}")
            print(resp.text)
            if "ton.email@" in email:
                print()
                print("« ton.email@jin.fr » était un exemple. Utilise ton vrai e-mail jin.fr.")
            raise SystemExit(1)
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
        print(f"Formulaire : {form_spec.get('title') or form_spec.get('form_id')}")
        print(f"JSON final : {args.webhook_url}")


if __name__ == "__main__":
    main()
