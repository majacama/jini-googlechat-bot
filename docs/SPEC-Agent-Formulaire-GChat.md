# Spec — Agent conversationnel générique de remplissage de formulaire sur Google Chat

Document de passation pour Claude Code / Codex. Décrit l'architecture actée, les
contrats d'interface, les modèles de données et le plan d'implémentation. Ce n'est
pas un projet lié à l'AO Renault — dossier volontairement séparé.

## 1. Objectif

Un agent conversationnel générique qui :

1. Reçoit en entrée, avant toute conversation : un contact Google Chat, une spec de
   formulaire (liste de champs à obtenir, contraintes, conseils de formulation), et
   un JSON cible (schéma de sortie, éventuellement pré-rempli partiellement).
2. Ouvre une conversation en DM avec le collaborateur sur Google Chat et pose les
   questions une à une, reformule si la réponse ne respecte pas le format ou la
   contrainte attendue, jusqu'à ce que tous les champs requis soient validés.
3. Une fois le formulaire complet, envoie le JSON final à un webhook fourni au
   démarrage, et confirme à l'utilisateur dans le chat.

L'agent est générique : le formulaire n'est jamais codé en dur, il est fourni comme
donnée à chaque déclenchement (`/start`).

## 2. Décisions d'architecture actées

- **Compute** : Cloud Run (Python 3.12, FastAPI), scale-to-zero, un seul service.
- **État de conversation** : Firestore, un document par conversation (par espace
  Google Chat).
- **Modèle LLM** : Gemini via Vertex AI (cohérence avec le reste de la stack
  Google). L'appel LLM est isolé derrière une interface unique dans le code
  (voir §9), pour permettre de tester un autre modèle (ex. Claude via l'API
  Anthropic) sans toucher au reste de l'agent.
- **Orchestration** : machine à états explicite écrite à la main pour la v1, **pas
  LangGraph**. Raison : le graphe de décision par tour (poser / reformuler /
  confirmer / terminer) est simple, et LangGraph impose un checkpointer externe
  (Postgres en pratique) qui ajoute une dépendance sans bénéfice ici puisque
  Firestore joue déjà ce rôle. À reconsidérer si le dialogue se complexifie
  fortement (branches conditionnelles entre champs, sous-formulaires, agents
  multiples) — voir §15.
- **Déclenchement** : un endpoint HTTP `/start` sur le même service, protégé par
  authentification, appelé par un script, un `gcloud`, ou une tâche planifiée.
- **Sortie** : POST du JSON final vers un webhook fourni au démarrage, avec repli
  sur Firestore en cas d'échec (voir §8.3).

## 3. Vue d'ensemble du flux

```
Déclencheur (script / Scheduler)
        │  POST /start { contact, form_spec, webhook_url }
        ▼
Cloud Run service ── API Google Chat : créer le DM
        │              crée le document Firestore conversations/{doc_id}
        │              répond 202 { space_id }
        │              (tâche de fond) envoie intro + 1re question
        ▼
Google Chat ── DM avec le collaborateur

Collaborateur répond dans Chat
        │
        ▼
Google Chat POST /chat  (événement MESSAGE)
        │
Cloud Run:
  1. répond 200 immédiatement (accusé, sans attendre le LLM)
  2. (tâche de fond) lit l'état Firestore de cette conversation
  3. appelle Gemini (contexte = spec formulaire + état + message)
  4. Gemini renvoie une action structurée (voir §9.1)
  5. validation JSON Schema du champ concerné (code, pas le modèle)
  6. si valide → met à jour Firestore, choisit la prochaine question
     si invalide → reformule sans second appel LLM
  7. écrit la réponse via l'API Chat (`spaces.messages.create`)
        │
        ▼  (répété jusqu'à formulaire complet)

Formulaire complet
        │  POST webhook_url { form_id, answers, completed_at }
        ▼
Système destinataire
        │
        └── confirmation envoyée dans le chat au collaborateur
```

## 4. Stack technique

| Brique | Choix | Version / notes |
|---|---|---|
| Langage | Python | 3.12 |
| Framework HTTP | FastAPI + Uvicorn | |
| LLM | Gemini via Vertex AI | SDK `google-genai`, modèle configurable (`GEMINI_MODEL` env var) |
| État | Firestore (mode natif) | 1 collection `conversations`, 1 doc par espace Chat |
| Validation | `pydantic` v2 + JSON Schema | schéma du formulaire fourni en JSON Schema standard |
| Chat | Google Chat API | Chat app enregistrée dans la console GCP, auth par compte de service |
| Déploiement | Cloud Run | région à définir, 1 service, min instances 0 |
| Secrets | Secret Manager | token `/start`, éventuel token API LLM si hors Vertex |
| Logs | Cloud Logging (stdout structuré) | inclure `space_id`, `form_id`, `field_id` sur chaque log |

## 5. Structure de repo

```
.
  app/
    main.py                 # FastAPI app, montage des routers
    config.py               # settings (env / Secret Manager)
    routers/
      chat.py                # POST /chat — événements Google Chat
      start.py                # POST /start — déclenchement d'une conversation
    core/
      state_machine.py        # logique de décision par tour
      llm.py                   # facade + contrat §9
      llm_gemini.py            # implémentation Gemini
      llm_anthropic.py         # stub / implémentation alternative
      validation.py            # validation des champs contre le JSON Schema
      chat_client.py           # wrapper API Google Chat (créer DM, envoyer message)
      webhook.py               # envoi du JSON final + retries
      auth.py                  # Bearer /start + JWT Chat
    models/
      form_spec.py             # pydantic: FormSpec, FieldSpec
      conversation_state.py    # pydantic: ConversationState, AgentAction
    storage/
      firestore_repo.py        # lecture/écriture des documents conversations/{id}
      memory_repo.py           # repo en mémoire (tests / dev local)
    prompts/
      system_prompt.md          # template, voir §10
  tests/
    test_state_machine.py
    test_validation.py
    test_webhook.py
    fixtures/
      form_spec_exemple.json
      conversations_exemple/    # transcripts pour rejouer et non-régresser les prompts
  deploy/
    Dockerfile
    cloudbuild.yaml
  pyproject.toml
  README.md
```

## 6. Modèle de données Firestore

Collection `conversations`. L'id de document **ne peut pas** contenir de `/`.
On persiste `space_id` (ex. `spaces/AAAAxxxxx`) comme champ, et on utilise comme
id de document `space_id` avec `/` remplacé par `__` (ex. `spaces__AAAAxxxxx`).

```jsonc
{
  "space_id": "spaces/AAAAxxxxx",
  "form_id": "onboarding-fournisseur-v1",
  "status": "in_progress",            // in_progress | completed | abandoned | failed
  "contact": {
    "user_email": "collaborateur@jin.fr",
    "display_name": "..."
  },
  "form_spec": { /* copie de la spec reçue à /start, voir §7 — figée pour toute la conversation */ },
  "target_schema": { /* JSON Schema de sortie, dérivé ou fourni à /start */ },
  "webhook_url": "https://...",
  "webhook_secret": "...",            // optionnel, jamais loggé
    "answers": {
    "nom_fournisseur": "Acme SAS",
    "date_debut": "2026-03-01"
    // uniquement les champs déjà validés
  },
  "skipped_field_ids": [],            // champs optionnels sautés après max_attempts
  "current_field_id": "adresse_facturation",
  "current_attempt_count": 1,          // reformulations sur le champ courant
  "history": [
    {"role": "agent", "field_id": "nom_fournisseur", "text": "...", "ts": "..."},
    {"role": "user", "field_id": "nom_fournisseur", "text": "...", "ts": "..."}
  ],
  "created_at": "...",
  "updated_at": "...",
  "completed_at": null
}
```

Notes :

- `history` sert de contexte au prompt (voir §10) et de trace d'audit. Troncature
  à 20 derniers tours pour le prompt (l'historique complet reste en base).
- `current_attempt_count` pilote le comportement après N échecs (voir §11).

## 7. Format de la spec de formulaire (entrée de `/start`)

C'est la donnée qui rend l'agent générique. Fournie en JSON à `/start`.

```jsonc
{
  "form_id": "onboarding-fournisseur-v1",
  "title": "Onboarding fournisseur",
  "language": "fr",
  "intro_message": "Bonjour, je vais te poser quelques questions pour créer la fiche fournisseur.",
  "global_instructions": "Ton professionnel et concis. Une question à la fois. Si l'utilisateur hésite, propose un exemple.",
  "fields": [
    {
      "id": "nom_fournisseur",
      "required": true,
      "max_attempts": 3,
      "json_schema": {"type": "string", "minLength": 2},
      "question_hint": "Quel est le nom exact du fournisseur (raison sociale) ?",
      "constraints": "Doit correspondre à la raison sociale légale, pas un nom commercial.",
      "format_advice": "Pas d'abréviation. Ex: 'Acme SAS', pas 'Acme'.",
      "examples": ["Acme SAS", "Renault Group"]
    },
    {
      "id": "date_debut",
      "required": true,
      "max_attempts": 3,
      "json_schema": {"type": "string", "format": "date"},
      "question_hint": "À quelle date le contrat démarre-t-il ?",
      "constraints": "Doit être au format ISO AAAA-MM-JJ, et ne peut pas être dans le passé.",
      "format_advice": "Accepte les formats naturels en entrée ('15 mars 2026') mais convertis toujours en ISO avant de stocker.",
      "examples": ["2026-03-15"]
    }
  ]
}
```

### 7.1 `target_schema` en v1

En v1, `target_schema` est **dérivé automatiquement** des `fields[].json_schema` :
un objet plat `{ "type": "object", "properties": { <id>: <json_schema> }, "required": [...] }`.

Un `target_schema` fourni à `/start` est accepté uniquement s'il décrit la même
liste plate de champs. Les objets imbriqués et les chemins JSONPath sont hors v1
(voir §15).

### 7.2 `max_attempts`

Optionnel, défaut **3**. Compte les validations échouées (schéma) sur le champ
courant, pas les `clarify_needed`.

## 8. Contrats HTTP

### 8.1 `POST /start`

Déclenche une nouvelle conversation. Auth v1 : header `Authorization: Bearer
<token>` comparé à `START_ENDPOINT_TOKEN` (Secret Manager). Pas d'accès anonyme.
(OIDC / IAM Cloud Run = évolution ultérieure.)

Requête :

```jsonc
{
  "contact": {"user_email": "collaborateur@jin.fr"},
  "form_spec": { /* voir §7 */ },
  "webhook_url": "https://.../ingest",
  "webhook_secret": "..."   // optionnel, utilisé pour signer l'appel sortant, voir §8.3
}
```

Séquence obligatoire (pour ne pas bloquer le client HTTP sur le LLM) :

1. Créer le DM via l'API Chat (auth applicative, compte de service).
2. Persister le document Firestore (`status=in_progress`, premier `current_field_id`).
3. Répondre **`202 Accepted`** avec `{"space_id": "..."}`.
4. En tâche de fond : envoyer `intro_message` + question du premier champ (texte
   déterministe à partir de `question_hint`, sans appel LLM).

Le dialogue qui suit est asynchrone, piloté par les événements Chat.

**Point bloquant Workspace (POC jour 1)** : l'ouverture d'un DM applicatif vers
un utilisateur arbitraire du domaine `jin.fr` dépend de la config admin
(Chat app installée, scopes, politique DM). À valider avant tout le reste.

### 8.2 `POST /chat`

Endpoint appelé par Google Chat à chaque événement (`ADDED_TO_SPACE`, `MESSAGE`,
`REMOVED_FROM_SPACE`). Contrainte forte : **Google Chat attend une réponse HTTP
sous ~30 secondes**, et l'appel LLM peut dépasser ce délai.

Stratégie v1 : répondre immédiatement par `200 OK` (corps vide ou `{}`), puis
traiter le tour et envoyer la vraie réponse via un appel **sortant** à l'API Chat
(`spaces.messages.create`), en tâche de fond FastAPI. Cloud Tasks si le volume
l'exige plus tard (§15).

Vérification d'origine : JWT Bearer émis par Google Chat, audience = URL de
l'endpoint Cloud Run `/chat`, projet / app id configurés (`CHAT_AUDIENCE`,
`GOOGLE_CHAT_APP_ID`). Ne pas se fier uniquement à une URL « secrète ».

### 8.3 Webhook de sortie (appelé par l'agent, pas exposé par lui)

À la complétion du formulaire, POST vers `webhook_url` (uniquement l'URL fournie
à `/start`) :

```jsonc
{
  "form_id": "onboarding-fournisseur-v1",
  "space_id": "spaces/AAAAxxxxx",
  "contact": {"user_email": "collaborateur@jin.fr"},
  "answers": { /* toutes les valeurs validées, conformes à target_schema */ },
  "completed_at": "2026-09-03T14:22:00Z"
}
```

En-tête `X-Signature` = HMAC-SHA256(corps, `webhook_secret`) si un secret a été
fourni à `/start`.

Retries : 3 tentatives avec backoff exponentiel. En cas d'échec définitif,
`status` du document Firestore passe à `failed` (pas `completed`), le JSON reste
récupérable dans Firestore, et un log d'erreur explicite est émis pour alerte.

## 9. Interface LLM (isolation du modèle)

### 9.1 Contrat de fonction

Un seul point d'entrée dans `app/core/llm.py`, quel que soit le modèle derrière :

```python
def decide_next_action(
    form_spec: FormSpec,
    state: ConversationState,
    user_message: str | None,
) -> AgentAction:
    ...
```

`AgentAction` est une sortie structurée (pydantic, validée via structured output /
schema-constrained generation côté Gemini) :

```jsonc
{
  "action": "ask" | "confirm_value" | "reformulate" | "complete" | "clarify_needed",
  "field_id": "date_debut",
  "extracted_value": "2026-03-15",   // null si rien d'exploitable extrait
  "message_to_user": "Le format attendu est JJ/MM/AAAA ou une date en toutes lettres, peux-tu préciser ?"
}
```

Sémantique v1 des actions, **après** le garde-fou de validation :

| Action | `extracted_value` valide | Effet |
|---|---|---|
| `ask` | ignorée si absente | Envoie `message_to_user` (question) |
| `confirm_value` | obligatoire | Accepte la valeur et passe au champ suivant (pas de second tour « oui/non ») |
| `reformulate` | absente ou invalide | Renvoie `message_to_user` ; incrémente `current_attempt_count` seulement si une valeur a échoué le schéma |
| `clarify_needed` | absente | Demande une précision, **sans** incrémenter `current_attempt_count` |
| `complete` | — | N'est honorée que si tous les champs **required** sont déjà validés ; sinon l'agent ignore et pose le prochain champ manquant |

Le code, pas le modèle, décide si `extracted_value` est accepté : validation contre
`field.json_schema` dans `app/core/validation.py`. Si le modèle prétend une valeur
valide mais qu'elle échoue au schéma, l'agent reformule automatiquement sans
redemander au LLM — un garde-fou déterministe.

### 9.2 Remplacer Gemini par un autre modèle

Pour tester Claude (API Anthropic ou Vertex) à la place : implémenter la même
signature `decide_next_action` dans `app/core/llm_anthropic.py`, sélection par
`LLM_PROVIDER=gemini|anthropic`. Aucune autre couche (state machine, Firestore,
Chat, webhook) ne doit connaître le fournisseur.

## 10. Prompt système

Fichier `app/prompts/system_prompt.md`, rempli à chaque appel avec :

- `global_instructions` de la spec
- la définition du champ courant (`question_hint`, `constraints`, `format_advice`,
  `examples`)
- l'historique récent tronqué (20 tours)
- rappel explicite du contrat de sortie structurée (schéma `AgentAction`)

Point d'attention : insister sur *abstention explicite* si le message de
l'utilisateur ne permet pas d'extraire une valeur exploitable (`clarify_needed`)
plutôt que de forcer une extraction approximative.

## 11. Comportement après N échecs (v1)

`max_attempts` défaut 3, surchargeable par champ.

- **Champ optionnel** : à `max_attempts`, le champ est sauté (non écrit dans
  `answers`), message à l'utilisateur, passage au champ suivant.
- **Champ obligatoire** : à `max_attempts`, l'agent envoie un message
  d'escalade (l'utilisateur doit fournir une valeur exploitable ou un humain
  reprendra), `status` reste `in_progress`, le champ n'est **pas** abandonné.
  Les messages suivants sur ce champ restent traités.

Pas de retour arrière sur une valeur déjà validée en v1 (« corrige le champ
précédent » n'est pas interprété).

## 12. Sécurité

- **`/start`** : Bearer `START_ENDPOINT_TOKEN`, jamais d'accès anonyme.
- **`/chat`** : JWT Bearer Google Chat (audience = URL `/chat`, app id). En
  `APP_ENV=dev` uniquement, la vérif peut être désactivée (`CHAT_AUTH_DISABLED=1`).
- **Webhook sortant** : signature HMAC si secret fourni ; uniquement l'URL
  fournie à `/start`.
- **Données** : les réponses transitent par Gemini via Vertex AI dans le projet
  GCP JIN. Champs sensibles (RIB, identifiants) : hors de ce flux, jamais saisis
  dans le chat.

## 13. Plan de tests

- **Unitaires** : `state_machine` (transitions par action, max_attempts,
  skip optionnel, escalade required), `validation` (contraintes JSON Schema),
  `webhook` (signature, retries).
- **Rejouabilité des prompts** : transcripts dans
  `tests/fixtures/conversations_exemple/` rejoués contre `decide_next_action`
  pour détecter une régression de prompt ou un changement de modèle (§9.2).
- **Bout en bout** : formulaire de test à 3-4 champs, `/start` sur un espace
  Chat de test, webhook de test pour le JSON final.

## 14. Déploiement

- Chat app enregistrée dans la console Google Cloud (API Google Chat), endpoint =
  URL Cloud Run + `/chat`, visibilité limitée au domaine `jin.fr`.
- Compte de service dédié : Firestore (lecture/écriture), Vertex AI User, scopes
  Chat (création de DM + envoi de messages en tant qu'app).
- Variables d'environnement : `GEMINI_MODEL`, `GCP_PROJECT`, `GCP_REGION`,
  `FIRESTORE_COLLECTION`, `START_ENDPOINT_TOKEN` (Secret Manager),
  `LLM_PROVIDER`, `CHAT_AUDIENCE`, `GOOGLE_CHAT_APP_ID`.
- `min instances = 0`, `max instances` selon le volume (ordre de grandeur :
  10-15 conversations simultanées).

## 15. Roadmap / hors v1

- **LangGraph** si le dialogue se ramifie (sous-sections conditionnelles,
  plusieurs agents). `ConversationState` reste conçu pour un futur checkpointer.
- **Cloud Tasks** à la place des tâches de fond FastAPI si besoin de garantie
  de livraison plus forte.
- **Relance automatique** si l'utilisateur ne répond pas pendant N heures.
- **Plusieurs formulaires** dans le même DM (aujourd'hui : une conversation
  active par espace).
- **`target_schema` imbriqué** + JSONPath.
- **Retour arrière** sur une réponse déjà validée.
- Auth `/start` par OIDC / IAM au lieu d'un Bearer statique.
