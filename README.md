# Agent formulaire Google Chat

Agent conversationnel générique : on lui passe un contact, une spec de
formulaire et un webhook ; il ouvre un DM Google Chat, pose les questions,
valide les réponses, puis POST le JSON final.

Spec détaillée : [`docs/SPEC-Agent-Formulaire-GChat.md`](docs/SPEC-Agent-Formulaire-GChat.md).

## Prérequis

- Python 3.12+
- Projet GCP avec API Google Chat, Firestore et Vertex AI
- Chat app visible sur le domaine `jin.fr`

## Dev local

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env
pytest
uvicorn app.main:app --reload
```

En local (`APP_ENV=dev`, `USE_MEMORY_STORE=1`), Firestore et Chat sont remplacés
par des implémentations mémoire / factices.

`POST /start` exige `Authorization: Bearer $START_ENDPOINT_TOKEN`.

### Boucle locale (sans Google Chat)

Le serveur doit déjà tourner (`uvicorn app.main:app --reload`).

```powershell
# 1. Démarrer une conversation — affiche un space_id
.\.venv\Scripts\python.exe .\scripts\start_conversation.py `
  --contact-email "collaborateur@jin.fr" `
  --token "change-me"

# 2. Répondre comme le collaborateur (une fois par champ)
.\.venv\Scripts\python.exe .\scripts\reply.py `
  --space-id "spaces/fake-collaborateur@jin.fr" `
  --text "Acme SAS" `
  --token "change-me"

.\.venv\Scripts\python.exe .\scripts\reply.py `
  --space-id "spaces/fake-collaborateur@jin.fr" `
  --text "2026-03-15" `
  --token "change-me"

.\.venv\Scripts\python.exe .\scripts\reply.py `
  --space-id "spaces/fake-collaborateur@jin.fr" `
  --text "RAS" `
  --token "change-me"
```

En local, le LLM est un stub : il reprend le texte tel quel. Pour `date_debut`,
utilise le format ISO `AAAA-MM-JJ`. Le JSON final arrive sur
`http://127.0.0.1:8000/dev/webhook`.

Raccourcis :

- `relancer.bat` — tue les ports 8000/8080 et démarre le serveur
- `discuter.bat` — dialogue interactif dans le terminal (serveur déjà lancé)

## POC jour 1 (Google Chat réel)

Guide : [`docs/SETUP-GCP.md`](docs/SETUP-GCP.md).

```powershell
.\check-gchat.bat collaborateur@jin.fr
```

Sans serveur : ouvre un DM applicatif et envoie un message test. C’est le
point bloquant Workspace.

## Variables d'environnement

Voir `.env.example` : `GEMINI_MODEL`, `GCP_PROJECT`, `GCP_REGION`,
`FIRESTORE_COLLECTION`, `START_ENDPOINT_TOKEN`, `LLM_PROVIDER`,
`CHAT_AUDIENCE`, `GOOGLE_CHAT_APP_ID`.
