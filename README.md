# jini-googlechat-bot

Bot générique JIN sur Google Chat. Cible trois cas d'usage :

1. **Question de connaissance** — RAG sur le corpus Drive, réponse avec cards
   citant les documents source.
2. **Process déclenché depuis le chat** — l'utilisateur demande un traitement
   (ex. « crée un dossier client »), le bot enchaîne un questionnaire dans le
   même DM.
3. **Process déclenché par une app externe** — un système tiers (CRM, etc.)
   demande au bot de contacter un utilisateur pour mener ce questionnaire.

**État actuel** : seul le moteur de questionnaire est implémenté et testé —
on lui passe une spec JSON (`forms/nouveau-dossier-client.json` ou
`forms/exemple-a-remplir.json`) via `POST /start`, il ouvre un DM, valide
l'interlocuteur, pose les questions une à une, puis POST le JSON final vers
un webhook. C'est le cas d'usage 3 ci-dessus. Nom affiché sur Chat /
Marketplace : **Jin Investigator Agent**. Le routeur d'intention (cas 1 et 2)
et le RAG restent à construire.

- Vérité runtime actuelle : [`docs/SPEC-passation-Claude.md`](docs/SPEC-passation-Claude.md)
- Cible — routeur, RAG, registre de process : [`docs/SPEC-Jin-Investigator-Cible-V2.md`](docs/SPEC-Jin-Investigator-Cible-V2.md)
- Spec v1 (périmée, gardée pour mémoire) : [`docs/SPEC-Agent-Formulaire-GChat.md`](docs/SPEC-Agent-Formulaire-GChat.md)

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
  --token "change-me"

# 2. Répondre dans le DM (intro → « es-tu la bonne personne ? » → questions)
.\.venv\Scripts\python.exe .\scripts\reply.py `
  --space-id "spaces/fake-fdiaz@jin.fr" `
  --text "oui" `
  --token "change-me"
```

En local, le LLM est un stub : il reprend le texte tel quel (sauf listes d'e-mails
et « non » sur un champ optionnel). Le JSON final arrive sur
`http://127.0.0.1:8000/dev/webhook`. Le défaut de `--form-spec` est
`forms/nouveau-dossier-client.json` (destinataire = `recipient.email`).

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
