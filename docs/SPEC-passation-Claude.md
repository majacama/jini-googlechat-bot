# Passation — Jin Investigator Agent (état au 18 sept. 2026)

Document pour un agent / un humain qui reprend le repo. **Ceci est la vérité runtime actuelle.**  
L'ancienne spec `docs/SPEC-Agent-Formulaire-GChat.md` décrit l'intention v1 ; plusieurs points y sont **périmés** (tâches de fond, format de formulaire plat, pas de validation d'interlocuteur).  
La cible en cours (routeur, RAG, registre de process) est documentée dans `docs/SPEC-Jin-Investigator-Cible-V2.md` — ce fichier-ci ne documente que ce qui est **construit et vérifié**, elle documente ce qui reste à construire.

Repo : `C:\Users\fredc\Projets\jini-googlechat-bot`  
GitHub : https://github.com/majacama/jini-googlechat-bot.git  
Compte : `fdiaz@jin.fr` (Owner GCP + super admin Workspace `jin.fr`)

**Migration de repo le 2026-09-18** : l'ancien dossier `C:\Users\fredc\Projets\Agent Conversationnel Gchat` (repo `JIN-Form-Gchat-Agent`) a été cloné avec tout son historique vers `jini-googlechat-bot`, remote repointé. L'ancien dossier reste en place comme filet de sécurité mais **ne plus y travailler** — tout le travail depuis le 2026-09-18 (Secret Manager, modèle de données, routeur, field_values) n'existe que dans `jini-googlechat-bot`.

---

## 1. Qu'est-ce que c'est

Bot **générique** JIN sur Google Chat, visant trois cas d'usage (détail et état d'avancement : `docs/SPEC-Jin-Investigator-Cible-V2.md`) :

1. **Question de connaissance** (RAG sur le corpus Drive) — **pas construit**, le bot répond un message d'attente.
2. **Process déclenché depuis le chat** — **livré et vérifié en direct le 2026-09-18**. Un message libre dans un DM sans session active passe par un routeur d'intention qui reconnaît la demande et enchaîne le questionnaire, dans le même DM, sans repasser par `/start`.
3. **Process déclenché par une app externe** (`POST /start`) — le mécanisme d'origine, toujours la base, cas C.

Dans tous les cas : l'agent ouvre/utilise le DM, envoie l'intro, vérifie que c'est la bonne personne, pose **une question à la fois**. Gemini extrait ; le **code** valide (JSON Schema), jamais le LLM. Formulaire complet → POST du JSON `answers` vers le webhook.

Le formulaire n'est **jamais** codé en dur. La spec métier actuelle est  
`forms/nouveau-dossier-client.json` (canevas : `forms/exemple-a-remplir.json`).

Nom affiché Chat / Marketplace : **Jin Investigator Agent**.  
Ne pas renommer le service Cloud Run, l'ID projet, ni le compte de service — ça a survécu à la migration de repo, ça doit survivre à tout le reste aussi.

---

## 2. Stack et infra

| Brique | Valeur |
|---|---|
| App | Python 3.12, FastAPI |
| Projet GCP | `admin-jin-fr`, région `europe-west1` |
| Cloud Run | `agent-formulaire-gchat` |
| URL | `https://agent-formulaire-gchat-531758065224.europe-west1.run.app` |
| Chat endpoint | cette URL + `/chat` (aussi `CHAT_AUDIENCE`) |
| Firestore | native `(default)`, collection `conversations`, doc id = `space_id` avec `/` → `__` = **canal** (`active_session_id`) ; sous-collection `sessions/{session_id}` = historique des formulaires |
| Registre de process | tout `forms/*.json` qui déclare `trigger_intent` devient déclenchable depuis le chat (`app/core/process_registry.py`), scanné au runtime — pas de base dédiée |
| LLM | Gemini `gemini-2.5-pro` via Vertex (`google-genai`), `thinking_budget=128`. Même mécanisme (sortie JSON structurée) pour le questionnaire (`decide_next_action`) et le routeur (`decide_route`) |
| SA Chat | `agent-formulaire-gchat@admin-jin-fr.iam.gserviceaccount.com` |
| Auth `/start` | Bearer `START_ENDPOINT_TOKEN`, en Secret Manager (`start-endpoint-token`) depuis le 2026-09-18, monté via `--set-secrets` sur Cloud Run — jamais en clair dans `--set-env-vars` |
| Auth `/chat` | JWT Google Chat (OIDC `chat@system.gserviceaccount.com`, fallback JWT n° projet) |
| Cloud Run | `--allow-unauthenticated` (même service pour `/start` et `/chat`), `min-instances=1`, `--no-cpu-throttling`, timeout 60s |

Orchestration : **machine à états maison**, pas LangGraph.

---

## 3. Flux conversation (ce qu'on a branché)

### 3.1 Message entrant sans session active (cas A / B, routeur)

```
POST /chat, repo.get(space_id) -> None (canal libre ou jamais contacté)
        │
        ├─ sender.type == "BOT" → ignoré (anti-boucle)
        │
        └─ decide_route(text, registre_de_process) — même mécanisme de
           sortie structurée que le questionnaire
                search_knowledge_base → message d'attente, RAG pas construit
                clarify_needed        → message_to_user du LLM tel quel
                start_process         → resolve_sender_email(sender)
                                         (sender.email direct, sinon
                                         résolution Directory API inverse)
                                       → resume_in_space() : lance le
                                         formulaire DANS ce DM, sans en
                                         ouvrir un nouveau
                                         (default_webhook_url du formulaire,
                                         PAS de field_values pour ce cas)
```

### 3.2 Déclenchement externe (cas C)

```
POST /start { form_spec, contact?, webhook_url, field_values? }
        │
        ├─ contact omis → form_spec.recipient.email
        ├─ field_values { field_id: valeur } validés contre le json_schema
        │     valide   → pré-rempli dans answers, sa question est sautée
        │     invalide → ignoré, question posée normalement
        ├─ findDirectMessage (ID Chat numérique, pas l'e-mail)
        ├─ 409 si une session est déjà in_progress sur cet espace
        └─ message d'ouverture = intro + question interlocuteur
                    (PAS la 1re question métier)
```

### 3.3 Suite (identique quel que soit le déclencheur)

```
Réponse Chat POST /chat, session active
        │
        ├─ phase interlocutor / awaiting_replacement
        │     oui  → ack + 1er champ non déjà pré-rempli
        │     non  → demander remplaçant (field_values d'origine hérités)
        │     e-mail remplaçant → abandon + nouvel /start sur cette personne
        │     inconnu → abandon + DM d'escalade : escalate_to_chat_email du
        │               formulaire si configuré, sinon DEFAULT_HANDOFF_CONTACT
        │               (fdiaz@jin.fr) — toujours quelqu'un de notifié,
        │               jamais un abandon silencieux
        │
        └─ phase questionnaire
              LLM → AgentAction
              code valide json_schema
              confirm_value OK → « C'est noté. » + question_hint du champ suivant
                                 (on ignore message_to_user du LLM : évite questions empilées)
              {{field_id}} dans un texte de spec → résolu avec la valeur
                           connue à cet instant (vide sinon)
              skip si champ optionnel (« non », « aucun »…)
              stop_values (ex. creation_dossier=non) → abandon, PAS de webhook
                           (ne se déclenche que sur une réponse EN DIRECT, pas
                           sur un field_values pré-rempli — non géré)
              tout requis rempli → webhook + completed, canal libéré
```

**Cloud Run gèle le CPU dès l'accusé HTTP.**  
`/chat` traite Gemini **dans** la requête (`asyncio.to_thread`).  
`/start` envoie l'ouverture **de façon synchrone**.  
Ne pas remettre ça en `BackgroundTasks`.

---

## 4. Format de spec

Deux formats acceptés pour le questionnaire lui-même :

- **Nouveau** (celui à utiliser) : `recipient`, `tone`, `introduction`, `interlocutor_validation`, `questionnaire.fields[]`
- **Ancien** (tests) : `intro_message`, `global_instructions`, `fields[]` avec `question_hint` / `constraints` / `format_advice`

Le parseur aplatit le nouveau format (`app/models/form_spec.py`).  
Les clés qui commencent par `_` sont de l'aide, ignorées (`extra=ignore`).

Aliases champ : `question` → `question_hint`, `consignes` → `constraints`, `format_attendu` → `format_advice`, `exemples` → `examples`.

### Champs racine ajoutés pour le routeur (2026-09-18)

| Clé | Rôle |
|---|---|
| `trigger_intent` | description courte ; sa présence rend le formulaire déclenchable depuis le chat (registre de process) |
| `default_webhook_url` | webhook utilisé **uniquement** quand ce process est déclenché depuis le chat — `/start` fournit toujours le sien explicitement |

### Champ (`questionnaire.fields[]`)

| Clé | Rôle |
|---|---|
| `id` | snake_case, unique |
| `required` | false → skip possible |
| `max_attempts` | échecs de schéma avant skip (opt.) ou message d'escalade (req.) |
| `question` | texte Chat, une à la fois — peut contenir `{{autre_field_id}}` |
| `consignes` | règles pour le LLM |
| `format_attendu` | normalisation |
| `exemples` | **listes plates** (pas de tableaux imbriqués : Firestore les refuse) |
| `json_schema` | validation déterministe |
| `stop_values` | `{ "non": "message de fin" }` → abandon sans webhook |

### `field_values` (payload `/start`, cas C uniquement)

`{ "field_id": "valeur" }` — validé contre le `json_schema` du champ (`app/core/validation.py::validate_field`) :
- valide → posé directement dans `answers`, sa question n'est jamais posée ;
- invalide ou `field_id` inconnu → ignoré silencieusement (log `field_values_invalid` / `field_values_unknown_field`), la question est posée normalement.

Le cas B (chat) ne pré-remplit jamais rien pour l'instant — confirmé, pas un oubli.

### `{{field_id}}` — placeholders dynamiques

Dans **n'importe quel texte** du form spec (question d'interlocuteur, acks, message d'escalade, question/consignes/format_attendu d'un champ) : résolu à chaque envoi de message avec la valeur connue **à cet instant précis** dans `state.answers` (vide si pas encore connue). Implémenté par simple remplacement de sous-chaîne (`app/core/text_utils.py::resolve_placeholders`), appliqué **avant** `render_template` (l'ancienne syntaxe à accolade simple `{form_id}` / `{recipient.email}` / `{space_id}`, qui continue de fonctionner sans changement pour le message d'escalade).

### Formulaire métier actuel (`nouveau-dossier-client`)

Ordre : `creation_dossier` → `nom_dossier` → `niveau_securite` → `equipe_jinners` → `externes` (opt.) → `membres_externes_chat` (opt.) → `presales_folder_url` (opt.).

- `creation_dossier` : enum `oui`/`non`. `non` arrête tout (`stop_values`).
- `nom_dossier` : `^_[a-z0-9]+(?:-[a-z0-9]+)*$` (ex. `_moulin-de-valdonne`). Question : `Est-ce que le nom de dossier "{{nom_dossier}}" est correct ?` — **plus d'ACME en dur** (retiré le 2026-09-18, avec le bloc `parameters` jamais utilisé qui l'avait temporairement remplacé).
- `niveau_securite` : `SHOW FOLDER` \| `HIDE FOLDER`.
- Listes d'e-mails : type `array` ; le code parse virgules / « et » / retours ligne.
- Optionnels : « non » / « aucun » → `skip`, pas une valeur invalide.
- Plus de champ `responsable_dossier`. Plus de const `"Idem Externes"` : Gemini doit recopier les e-mails Drive si on dit « les mêmes ».

`contact` dans `/start` est optionnel si `recipient.email` est dans la spec.

---

## 5. Pièges (ne pas « recasser »)

### 5.1 `chat.bot` ≠ utilisateur

- `chat.bot` **interdit** sur un user OAuth. Ne **jamais** `gcloud auth application-default login` avec le scope `chat.bot`.
- L'app parle en **compte de service** (impersonation IAM). Le DM est **Agent ↔ collaborateur**, pas Fred.

### 5.2 E-mail ≠ ID Chat (et l'inverse)

L'API refuse `users/fdiaz@jin.fr`. Il faut `users/{id numérique}` (ex. Fred : `users/113859878083610238922`).

Résolution email → ID, dans l'ordre (`app/core/chat_client.py::resolve_chat_user_name`) :

1. Identifiant déjà numérique.
2. userinfo OAuth si l'ADC **est** cette personne (marche en local pour Fred).
3. Directory API (`admin.directory.user.readonly`) via le SA Chat.
4. Sinon fallback e-mail → `findDirectMessage` échoue en 404 trompeur (« aucun DM »).

Direction **inverse** (ID numérique reçu dans un événement `/chat` → e-mail), ajoutée le 2026-09-18 pour le routeur (`resolve_sender_email`) : `sender.email` direct si présent, sinon résolution Directory API inverse (`_directory_user_email`). **Jamais observé en conditions réelles lequel des deux chemins sert réellement** — à noter au prochain test du cas B.

`scripts/start_conversation.py` résout l'ID **en local** et l'envoie dans `contact.user_id`.  
`recipient.user_id` a été retiré du JSON : l'e-mail suffit **quand** cette résolution marche.

Sur Cloud Run, Directory / userinfo échouent souvent (403/401) si on n'envoie que l'e-mail. Pour un autre destinataire que Fred, passer `user_id` ou finir le rôle Workspace « Directory users read » sur le SA (voir `docs/SETUP-GCP.md` §4.1) — **toujours pas fait**, reste bloquant pour tester avec quelqu'un d'autre que Fred, cas C ou B.

### 5.3 Le bot ne **crée** pas le 1er DM

`chat.bot` ne fait pas `spaces.setup`. Il faut que le DM app↔user **existe** (install Marketplace admin, ou la personne a déjà écrit à l'agent).  
`create_dm` = `spaces.findDirectMessage`.

### 5.4 JWT Chat

`app/core/auth.py` : d'abord OIDC URL (`email == chat@system.gserviceaccount.com`), puis JWT n° projet (issuer Chat, certs x509).  
Dans Chat API, public d'auth = **URL HTTP** `/chat` (celle `europe-west1.run.app`, pas l'alias `*.a.run.app` si `CHAT_AUDIENCE` pointe vers europe-west1).

### 5.5 Firestore

`InvalidArgument: Property form_spec contains an invalid nested entity` = tableaux dans des tableaux.  
`app/storage/firestore_repo.py` encapsule les listes imbriquées (`__list__`).  
Dans les specs JSON, garder des `exemples` **plats**.

### 5.6 Le Dockerfile ne copie que `app/` — `forms/` doit l'être aussi

Trouvé en testant le routeur en direct le 2026-09-18 : premier message live, le bot a répondu qu'il ne pouvait démarrer aucun process — alors que le formulaire avait bien `trigger_intent`. Cause : `Dockerfile` faisait `COPY app ./app` sans jamais copier `forms/`, donc `process_registry.py` (qui résout son chemin par rapport à son propre fichier, trois niveaux au-dessus) trouvait un dossier **inexistant** dans le conteneur → registre vide, silencieusement, pas d'erreur. Marche en local (le dossier existe sur disque) mais pas dans l'image. Corrigé (`COPY forms ./forms`), mais **tout ajout futur de dossier lu au runtime** (docs ? assets ?) doit se poser la même question avant de supposer qu'il est présent en prod.

---

## 6. LLM

- Facade `app/core/llm.py` : Gemini / stub / Anthropic (non implémenté), pour **deux** décisions distinctes qui partagent le même provider et le même mécanisme de sortie structurée :
  - `decide_next_action` (questionnaire) — `app/prompts/system_prompt.md` / `interlocutor_prompt.md`.
  - `decide_route` (routeur, cas A/B) — `app/prompts/router_prompt.md`, schéma `RouteAction` (`app/models/route.py`), `process_id` contraint par énumération dynamique aux formulaires du registre.
- Tests : `LLM_PROVIDER=stub` (conftest) — `StubProvider` implémente les deux méthodes, déterministe.
- Actions questionnaire : `ask`, `confirm_value`, `reformulate`, `skip`, `complete`, `clarify_needed`, `interlocutor_yes|no|unknown`, `provide_replacement`.
- Actions routeur : `search_knowledge_base`, `start_process`, `clarify_needed`.
- `extracted_value` : scalaire **ou** liste (e-mails).
- Après `confirm_value` valide, le code pose **uniquement** `question_hint` du suivant (« C'est noté. »). Gemini n'a pas le droit d'empiler la question d'après (régression : il inventait un champ e-mail).

---

## 7. Fichiers clés

```
app/main.py
app/routers/start.py          # POST /start, contact optionnel, field_values
app/routers/chat.py           # POST /chat, sync dans la requête, transmet sender
app/core/turn.py              # begin_conversation (cas C), resume_in_space (cas B),
                               # process_user_message, _route_new_conversation (routeur),
                               # remplacement, escalade
                               # (pas de router.py séparé : decide_route vit dans llm.py,
                               # au même endroit que decide_next_action)
app/core/process_registry.py  # scan forms/*.json -> ProcessDefinition (trigger_intent)
app/core/state_machine.py     # phases, skip, stop_values, opening, resolve_placeholders
app/core/llm.py + llm_gemini.py + llm_anthropic.py
app/core/chat_client.py       # DM + résolution ID (email<->numérique, les deux sens)
app/core/auth.py              # Bearer + JWT Chat
app/core/validation.py + text_utils.py (render_template + resolve_placeholders)
app/core/webhook.py
app/models/form_spec.py + conversation_state.py (session_id) + route.py (RouteAction)
app/storage/firestore_repo.py + memory_repo.py (canal/session)
app/prompts/*.md               # system, interlocutor, router
forms/nouveau-dossier-client.json
forms/exemple-a-remplir.json
scripts/start_conversation.py
scripts/discuter.py / reply.py
scripts/check_directory_user.py
deploy-cloud-run.bat           # START_ENDPOINT_TOKEN via --set-secrets, PAS --set-env-vars
Dockerfile                     # COPY app ./app ET COPY forms ./forms
```

---

## 8. Comment tester

**Local (stub, pas Chat)**  
1. `.\relancer.bat`  
2. `.\discuter.bat`  
   Intro → interlocuteur → `oui` → `oui` (création) → nom de dossier → `SHOW FOLDER` → e-mails → `non` sur les optionnels.

**Unitaire** : `.\.venv\Scripts\python.exe -m pytest -q` (67 tests au 2026-09-18)

**Chat réel, cas C** (après déploiement) :

```powershell
.\.venv\Scripts\python.exe .\scripts\start_conversation.py `
  --base-url "https://agent-formulaire-gchat-531758065224.europe-west1.run.app" `
  --token "<valeur du secret start-endpoint-token, PAS change-me>" `
  --webhook-url "https://agent-formulaire-gchat-531758065224.europe-west1.run.app/dev/webhook"
```

Le destinataire est `recipient.email`. Répondre dans le DM Google Chat.  
`APP_ENV=dev` sur Cloud Run : `/dev/webhook` existe.

**Chat réel, cas B (routeur)** — vérifié le 2026-09-18 : écrire directement dans le DM Jin Investigator Agent, sans `/start` préalable, un message du type « il faut créer un nouveau dossier client ». Fonctionne si le canal n'a pas de session `in_progress` en cours.

**Déploiement** :

```bat
.\deploy-cloud-run.bat
```

ou l'équivalent `gcloud run deploy --source . ... --set-secrets "START_ENDPOINT_TOKEN=start-endpoint-token:latest"` — ne jamais repasser `START_ENDPOINT_TOKEN` en `--set-env-vars` littéral, ça écrase le secret.

---

## 9. Décisions / historique utile

- Agent générique : une spec JSON par déclenchement, pas un formulaire figé dans le code.
- Gemini, pas Claude, pour rester dans la stack Google (Vertex).
- Tutoiement, une question à la fois, ton interne JIN.
- Interlocuteur obligatoire avant le questionnaire ; redirection ou escalade OPS.
- `creation_dossier=non` = stop métier, pas un formulaire « vide » webhooké.
- Token `/start` en Secret Manager depuis le 2026-09-18 (`start-endpoint-token`), plus de `change-me` en prod.
- `conversations/{space_id}` : canal + sous-collection `sessions/{session_id}` depuis le 2026-09-18 — un formulaire terminé libère le canal au lieu de le bloquer, `/start` refuse (409) d'écraser une session `in_progress`.
- Routeur d'intention + registre de process livrés et **vérifiés en direct** le 2026-09-18 (après correctif Dockerfile, voir §5.6) : un message chat sans session active peut démarrer un formulaire sans passer par `/start`.
- Personnalisation des textes par `field_values` + `{{field_id}}` (2026-09-18) : plus besoin de coder un nom de client en dur dans une spec — voir §4. Le cas B ne pré-remplit toujours rien, décision explicite, pas un oubli.
- Webhook métier réel **pas** encore branché (catch `/dev/webhook` en dev, y compris pour `default_webhook_url` du cas B).

---

## 10. Reste à faire

- Vrai webhook métier (création Drive / espace Chat), pas `/dev/webhook` — vaut aussi pour `default_webhook_url`.
- Directory API fiable **sur Cloud Run** pour n'importe quel `@jin.fr` (rôle admin « Users → Lire » API sur le SA, voir SETUP-GCP §4.1). En local, Fred est résolu via userinfo. Bloquant pour tester le cas B ou C avec quelqu'un d'autre que Fred.
- RAG (cas A, recherche corpus) — pas construit, `search_knowledge_base` répond un message d'attente. Point de vérification préalable : les ACL du connecteur Drive de Vertex AI Search (voir Cible V2 §6).
- Confirmer en réel lequel des deux chemins de `resolve_sender_email` (email direct de l'événement Chat vs résolution Directory inverse) sert effectivement — jamais observé explicitement.
- `stop_values` sur un champ pré-rempli via `field_values` n'interrompt pas la conversation avant ouverture — non géré, à trancher si le cas se présente.
- `docs/SPEC-Agent-Formulaire-GChat.md` à ne pas suivre aveuglément (flux BackgroundTasks obsolète, ne concerne plus que l'historique).

---

## 11. Interdits opérationnels

- Ne pas coller le scope `chat.bot` sur l'ADC utilisateur.
- Ne pas traiter Gemini après avoir renvoyé 200 à Chat (CPU Cloud Run gelé).
- Ne pas appeler Chat avec `users/email@domaine`.
- Ne pas stocker des `exemples` en tableaux de tableaux dans Firestore sans encapsuler.
- Ne pas laisser le LLM poser la question du champ suivant : le code s'en charge.
- Ne pas repasser `START_ENDPOINT_TOKEN` en `--set-env-vars` littéral au déploiement : ça écrase le secret Secret Manager.
- Ne pas ajouter un dossier lu au runtime (comme `forms/`) sans vérifier qu'il est copié dans le `Dockerfile` — l'échec est silencieux (registre vide), pas une erreur.
