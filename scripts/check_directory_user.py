"""Vérifie que le compte de service peut résoudre un e-mail jin.fr → users/{id} Chat."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from app.core.chat_client import resolve_chat_user_name  # noqa: E402


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Résout un e-mail Workspace en ID Google Chat (Directory API)."
    )
    parser.add_argument("--email", default="fdiaz@jin.fr")
    args = parser.parse_args()

    name = resolve_chat_user_name(args.email)
    print(name)
    if "@" in name:
        print()
        print("ÉCHEC : l'e-mail n'a pas été converti en ID numérique.")
        print("Le compte de service n'a pas encore le droit Directory (Users → Read).")
        print("Voir docs/SETUP-GCP.md § Directory API.")
        raise SystemExit(1)
    print("OK — tu peux retirer recipient.user_id de la spec JSON.")


if __name__ == "__main__":
    main()
