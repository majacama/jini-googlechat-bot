"""POC jour 1 : ouvrir un DM applicatif Google Chat vers un utilisateur."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from app.core.chat_client import ChatApiError, GoogleChatClient  # noqa: E402


HINTS = {
    401: "Jeton refusé. Vérifie ADC (sans scope chat.bot) et CHAT_SERVICE_ACCOUNT.",
    403: "Auth app : pas d'alias email (users/prenom@domaine). Il faut users/{id}. "
    "Ou l'admin n'autorise pas l'app à engager un DM.",
    404: "Pas encore de DM avec l'app. Installe « Jin Investigator Agent » dans Google Chat, "
    "envoie-lui un message, puis relance check-gchat.bat.",
}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Tente d'ouvrir un DM Google Chat (point bloquant Workspace)."
    )
    parser.add_argument("--email", required=True, help="ex. collaborateur@jin.fr")
    parser.add_argument(
        "--message",
        default="POC Jin Investigator Agent : si tu lis ceci, l'ouverture de DM fonctionne.",
    )
    parser.add_argument(
        "--no-message",
        action="store_true",
        help="Créer le DM sans envoyer de message.",
    )
    args = parser.parse_args()

    client = GoogleChatClient()
    print(f"Ouverture d'un DM vers {args.email} ...")
    try:
        space_id = client.create_dm(args.email)
    except ChatApiError as exc:
        print(f"ÉCHEC  {exc}")
        hint = HINTS.get(exc.status_code)
        if hint:
            print(f"Piste : {hint}")
        print("Voir docs/SETUP-GCP.md")
        raise SystemExit(1) from exc

    print(f"OK  space_id = {space_id}")
    if args.no_message:
        return

    try:
        client.send_message(space_id, args.message)
    except ChatApiError as exc:
        print(f"DM créé, mais l'envoi du message a échoué : {exc}")
        hint = HINTS.get(exc.status_code)
        if hint:
            print(f"Piste : {hint}")
        raise SystemExit(2) from exc

    print("OK  message envoyé. Vérifie Google Chat sur ce compte.")


if __name__ == "__main__":
    main()
