# Passation — Jin Investigator Agent (état au 18 sept. 2026)

Document pour un agent / un humain qui reprend le repo. **Ceci est la vérité runtime actuelle.**  
L’ancienne spec `docs/SPEC-Agent-Formulaire-GChat.md` décrit l’intention v1 ; plusieurs points y sont **périmés** (tâches de fond, format de formulaire plat, pas de validation d’interlocuteur).

Repo : `C:\Users\fredc\Projets\Agent Conversationnel Gchat`  
GitHub : https://github.com/majacama/JIN-Form-Gchat-Agent.git  
Compte : `fdiaz@jin.fr` (Owner GCP + super admin Workspace `jin.fr`)

---

## 1. Qu’est-ce que c’est

Agent **générique** de recueil d’infos sur **Google Chat** (DM).

1. On POST une spec JSON + un destinataire + un webhook (`POST /start`).
2. L’agent ouvre le DM, envoie l’intro, vérifie que c’est la bonne personne, pose **une question à la fois**.
3. Gemini extrait ; le **code** valide (JSON Schema). Pas le LLM.
4. Formulaire complet → POST du JSON `answers` vers le webhook.

Le formulaire n’est **jamais** codé en dur. La spec métier actuelle est  
`forms/nouveau-dossier-client.json` (canevas : `forms/exemple-a-remplir.json`).

Nom affiché Chat / Marketplace : **Jin Investigator Agent**.  
Ne pas renommer le service Cloud Run, l’ID projet, ni le compte de service.

---

## 2. Stack et infra

| Brique | Valeur |
|---|---|
| App | Python 3.12, FastAPI |
| Projet GCP | `admin-jin-fr`, région `europe-west1` |
| Cloud Run | `agent-formulaire-gchat` |
| URL | `https://agent-formulaire-gchat-531758065224.europe-west1.run.app` |
| Chat endpoint | cette URL + `/chat` (aussi `CHAT_AUDIENCE`) |
| Firestore | native `(default)`, collection `conversations`, doc id = `space_id` avec `/` → `__` |
| LLM | Gemini `gemini-2.5-pro` via Vertex (`google-genai`), `thinking_budget=128` |
| SA Chat | `agent-formulaire-gchat@admin-jin-fr.iam.gserviceaccount.com` |
| Auth `/start` | Bearer `START_ENDPOINT_TOKEN` (encore `change-me` en POC) |
| Auth `/chat` | JWT Google Chat (OIDC `chat@system.gserviceaccount.com`, fallback JWT n° projet) |
| Cloud Run | `--allow-unauthenticated` (même service pour `/start` et `/chat`), `min-instances=1`, `--no-cpu-throttling`, timeout 60s |

Orchestration : **machine à états maison**, pas LangGraph.

---

## 3. Flux conversation (ce qu’on a branché)

```
POST /start { form_spec, contact?, webhook_url }
        │
        ├─ contact omis → form_spec.recipient.email
        ├─ findDirectMessage (ID Chat numérique, pas l’e-mail)
        ├─ Firestore : phase=interlocutor si gate activée
        └─ message d’ouverture = intro + question interlocuteur
                    (PAS la 1re question métier)

Réponse Chat POST /chat
        │
        ├─ phase interlocutor / awaiting_replacement
        │     oui  → ack + 1er champ
        │     non  → demander remplaçant
        │     e-mail remplaçant → abandon + nouvel /start sur cette personne
        │     inconnu → abandon + DM d’escalade (fdiaz@jin.fr)
        │
        └─ phase questionnaire
              LLM → AgentAction
              code valide json_schema
              confirm_value OK → « C'est noté. » + question_hint du champ suivant
                                 (on ignore message_to_user du LLM : évite questions empilées)
              skip si champ optionnel (« non », « aucun »…)
              stop_values (ex. creation_dossier=non) → abandon, PAS de webhook
              tout requis rempli → webhook + completed
```

**Cloud Run gèle le CPU dès l’accusé HTTP.**  
`/chat` traite Gemini **dans** la requête (`asyncio.to_thread`).  
`/start` envoie l’ouverture **de façon synchrone**.  
Ne pas remettre ça en `BackgroundTasks`.

---

## 4. Format de spec (entrée `/start`)

Deux formats acceptés :

- **Nouveau** (celui à utiliser) : `recipient`, `tone`, `introduction`, `interlocutor_validation`, `questionnaire.fields[]`
- **Ancien** (tests) : `intro_message`, `global_instructions`, `fields[]` avec `question_hint` / `constraints` / `format_advice`

Le parseur aplatit le nouveau format (`app/models/form_spec.py`).  
Les clés qui commencent par `_` sont de l’aide, ignorées (`extra=ignore`).

Aliases champ : `question` → `question_hint`, `consignes` → `constraints`, `format_attendu` → `format_advice`, `exemples` → `examples`.

### Champ

| Clé | Rôle |
|---|---|
| `id` | snake_case, unique |
| `required` | false → skip possible |
| `max_attempts` | échecs de schéma avant skip (opt.) ou message d’escalade (req.) |
| `question` | texte Chat, une à la fois |
| `consignes` | règles pour le LLM |
| `format_attendu` | normalisation |
| `exemples` | **listes plates** (pas de tableaux imbriqués : Firestore les refuse) |
| `json_schema` | validation déterministe |
| `stop_values` | `{ "non": "message de fin" }` → abandon sans webhook |

### Formulaire métier actuel (`nouveau-dossier-client`)

Ordre : `creation_dossier` → `nom_dossier` → `niveau_securite` → `equipe_jinners` → `externes` (opt.) → `membres_externes_chat` (opt.) → `presales_folder_url` (opt.).

- `creation_dossier` : enum `oui`/`non`. `non` arrête tout (`stop_values`).
- `nom_dossier` : `^_[a-z0-9]+(?:-[a-z0-9]+)*$` (ex. `_moulin-de-valdonne`). Question actuelle en dur : `_acme` / ACME.
- `niveau_securite` : `SHOW FOLDER` \| `HIDE FOLDER`.
- Listes d’e-mails : type `array` ; le code parse virgules / « et » / retours ligne.
- Optionnels : « non » / « aucun » → `skip`, pas une valeur invalide.
- Plus de champ `responsable_dossier`. Plus de const `"Idem Externes"` : Gemini doit recopier les e-mails Drive si on dit « les mêmes ».

`contact` dans `/start` est optionnel si `recipient.email` est dans la spec.

---

## 5. Pièges Google Chat (ne pas « recasser »)

### 5.1 `chat.bot` ≠ utilisateur

- `chat.bot` **interdit** sur un user OAuth. Ne **jamais** `gcloud auth application-default login` avec le scope `chat.bot`.
- L’app parle en **compte de service** (impersonation IAM). Le DM est **Agent ↔ collaborateur**, pas Fred.

### 5.2 E-mail ≠ ID Chat

L’API refuse `users/fdiaz@jin.fr`. Il faut `users/{id numérique}` (ex. Fred : `users/113859878083610238922`).

Résolution, dans l’ordre (`app/core/chat_client.py`) :

1. Identifiant déjà numérique.
2. userinfo OAuth si l’ADC **est** cette personne (marche en local pour Fred).
3. Directory API (`admin.directory.user.readonly`) via le SA Chat.
4. Sinon fallback e-mail → `findDirectMessage` échoue en 404 trompeur (« aucun DM »).

`scripts/start_conversation.py` résout l’ID **en local** et l’envoie dans `contact.user_id`.  
`recipient.user_id` a été retiré du JSON : l’e-mail suffit **quand** cette résolution marche.

Sur Cloud Run, Directory / userinfo échouent souvent (403/401) si on n’envoie que l’e-mail. Pour un autre destinataire que Fred, passer `user_id` ou finir le rôle Workspace « Directory users read » sur le SA (voir `docs/SETUP-GCP.md` §4.1).

### 5.3 Le bot ne **crée** pas le 1er DM

`chat.bot` ne fait pas `spaces.setup`. Il faut que le DM app↔user **existe** (install Marketplace admin, ou la personne a déjà écrit à l’agent).  
`create_dm` = `spaces.findDirectMessage`.

### 5.4 JWT Chat

`app/core/auth.py` : d’abord OIDC URL (`email == chat@system.gserviceaccount.com`), puis JWT n° projet (issuer Chat, certs x509).  
Dans Chat API, public d’auth = **URL HTTP** `/chat` (celle `europe-west1.run.app`, pas l’alias `*.a.run.app` si `CHAT_AUDIENCE` pointe vers europe-west1).

### 5.5 Firestore

`InvalidArgument: Property form_spec contains an invalid nested entity` = tableaux dans des tableaux.  
`app/storage/firestore_repo.py` encapsule les listes imbriquées (`__list__`).  
Dans les specs JSON, garder des `exemples` **plats**.

---

## 6. LLM

- Facade `app/core/llm.py` : Gemini / stub / Anthropic (non implémenté).
- Tests : `LLM_PROVIDER=stub` (conftest).
- Prompt questionnaire : `app/prompts/system_prompt.md`.
- Prompt interlocuteur : `app/prompts/interlocutor_prompt.md`.
- Actions : `ask`, `confirm_value`, `reformulate`, `skip`, `complete`, `clarify_needed`, `interlocutor_yes|no|unknown`, `provide_replacement`.
- `extracted_value` : scalaire **ou liste** (e-mails).
- Après `confirm_value` valide, le code pose **uniquement** `question_hint` du suivant (« C'est noté. »). Gemini n’a pas le droit d’empiler la question d’après (régression : il inventait un champ e-mail).

---

## 7. Fichiers clés

```
app/main.py
app/routers/start.py          # POST /start, contact optionnel
app/routers/chat.py           # POST /chat, sync dans la requête
app/core/turn.py              # begin_conversation, process_user_message, remplacement, escalade
app/core/state_machine.py     # phases, skip, stop_values, opening
app/core/llm.py + llm_gemini.py
app/core/chat_client.py       # DM + résolution ID
app/core/auth.py              # Bearer + JWT Chat
app/core/validation.py + text_utils.py
app/core/webhook.py
app/models/form_spec.py + conversation_state.py
app/storage/firestore_repo.py
app/prompts/*.md
forms/nouveau-dossier-client.json
forms/exemple-a-remplir.json
scripts/start_conversation.py
scripts/discuter.py / reply.py
scripts/check_directory_user.py
deploy-cloud-run.bat
```

---

## 8. Comment tester

**Local (stub, pas Chat)**  
1. `.\relancer.bat`  
2. `.\discuter.bat`  
   Intro → interlocuteur → `oui` → `oui` (création) → `_acme` → `SHOW FOLDER` → e-mails → `non` sur les optionnels.

**Unitaire** : `.\.venv\Scripts\python.exe -m pytest -q`

**Chat réel** (après `.\deploy-cloud-run.bat`) :

```powershell
.\.venv\Scripts\python.exe .\scripts\start_conversation.py `
  --base-url "https://agent-formulaire-gchat-531758065224.europe-west1.run.app" `
  --token "change-me" `
  --webhook-url "https://agent-formulaire-gchat-531758065224.europe-west1.run.app/dev/webhook"
```

Le destinataire est `recipient.email`. Répondre dans le DM Google Chat.  
`APP_ENV=dev` sur Cloud Run : `/dev/webhook` existe.

---

## 9. Décisions / historique utile

- Agent générique : une spec JSON par déclenchement, pas un formulaire figé dans le code.
- Gemini, pas Claude, pour rester dans la stack Google (Vertex).
- Tutoiement, une question à la fois, ton interne JIN.
- Interlocuteur obligatoire avant le questionnaire ; redirection ou escalade OPS.
- `creation_dossier=non` = stop métier, pas un formulaire « vide » webhooké.
- Token `/start` encore `change-me` (POC).
- Webhook métier réel **pas** encore branché (catch `/dev/webhook` en dev).

---

## 10. Reste à faire

- Redéployer Cloud Run si le code local (stop_values, Firestore nested lists, spec à jour) n’est pas sur la révision en prod.
- Vrai webhook métier (création Drive / espace Chat), pas `/dev/webhook`.
- `START_ENDPOINT_TOKEN` ≠ `change-me`.
- Directory API fiable **sur Cloud Run** pour n’importe quel `@jin.fr` (rôle admin « Users → Lire » API sur le SA, voir SETUP-GCP §4.1). En local, Fred est résolu via userinfo.
- Commit / push : beaucoup de fichiers encore uncommitted par rapport au commit initial.
- Questions ACME / `_acme` encore en dur dans la spec JSON (paramétrer par dossier).
- `docs/SPEC-Agent-Formulaire-GChat.md` à ne pas suivre aveuglément (flux BackgroundTasks obsolète).

---

## 11. Interdits opérationnels

- Ne pas coller le scope `chat.bot` sur l’ADC utilisateur.
- Ne pas traiter Gemini après avoir renvoyé 200 à Chat (CPU Cloud Run gelé).
- Ne pas appeler Chat avec `users/email@domaine`.
- Ne pas stocker des `exemples` en tableaux de tableaux dans Firestore sans encapsuler.
- Ne pas laisser le LLM poser la question du champ suivant : le code s’en charge.
