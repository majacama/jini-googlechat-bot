# Spec cible — Jin Investigator Agent v2 (routeur + RAG + process)

## 0. Statut de ce document

Ceci est un **document de cible**, pas une passation. La vérité runtime reste
`docs/SPEC-passation-Claude.md` (état au 18/09/2026) : tout ce qui y est décrit
fonctionne et est vérifié en pratique. Ce document décrit ce qu'il faut ajouter
pour couvrir trois cas d'usage validés, et ne doit pas être confondu avec un
état déjà construit. Une fois chaque phase implémentée et testée, c'est la
passation qui doit être mise à jour pour refléter le nouveau réel — pas ce
fichier, qui reste la note d'intention.

**Décision d'architecture actée** : on étend `agent-formulaire-gchat` en
place. Pas de nouvelle façade séparée (`agent.jin.fr` ou autre) devant lui.
Raisons : ce service porte déjà toute la plomberie Chat testée et non triviale
(JWT Chat, résolution e-mail → ID numérique, ouverture de DM, machine à
états) ; la dupliquer ailleurs pour un bénéfice non démontré serait le
mauvais calcul. Le nom du service Cloud Run, l'ID projet GCP (`admin-jin-fr`)
et le compte de service ne changent pas.

## 1. Les trois cas d'usage à couvrir

| Cas | Déclencheur | Ce que fait l'agent |
|---|---|---|
| **A — Question de connaissance** | L'utilisateur pose une question libre dans le DM | RAG sur le corpus Drive via Vertex AI Search, réponse avec cards citant les documents source |
| **B — Process déclenché depuis le chat** | L'utilisateur demande un traitement (« crée un dossier client pour Sephora ») | L'agent reconnaît l'intention, charge le bon formulaire, enchaîne en mode Investigator dans **le même DM** |
| **C — Process déclenché par une app externe** | Un système tiers détecte un besoin (ex. CRM qui marque un deal signé) | L'agent contacte l'utilisateur de façon proactive et mène le même questionnaire |

Le cas C est presque entièrement couvert par le mécanisme `/start` déjà en
production — voir §7.3. L'essentiel du travail neuf porte sur les cas A et B,
et sur un changement de modèle de données qui leur est commun.

## 2. Ce qui casse aujourd'hui, très précisément

Ces points sont vérifiés dans le code actuel (`app/core/turn.py`,
`app/routers/chat.py`), pas déduits :

1. **`process_user_message` ignore silencieusement tout message sans
   conversation existante.**
   ```python
   state = repo.get(space_id)
   if state is None:
       logger.warning("unknown_space", extra={"space_id": space_id})
       return
   ```
   Un utilisateur qui écrit spontanément au bot sans qu'un `/start` ait eu
   lieu avant ne reçoit **aucune réponse**. C'est le trou exact que les cas A
   et B doivent combler.

2. **Une fois `status != "in_progress"`, l'espace est mort pour toujours.**
   Même logique : `if state.status != "in_progress": ... return`. Un DM où un
   formulaire s'est terminé (complété, abandonné) ne peut plus jamais servir
   à autre chose — ni relancer le même formulaire, ni poser une question RAG,
   ni démarrer un autre process. C'est la vraie limite structurelle à lever,
   plus que l'absence de RAG elle-même.

3. **L'escalade à « je ne sais pas » n'a pas de filet de sécurité réel.**
   Dans `state_machine.py::apply_interlocutor`, si `interlocutor_unknown` est
   déclenché :
   ```python
   escalate_email = unknown.escalate_to_chat_email if unknown else None
   ```
   Si `if_unknown` n'est pas configuré dans la spec du formulaire, ou si
   `escalate_to_chat_email` y est vide, `escalate_email` vaut `None`. Dans
   `turn.py::_apply_side_effects` :
   ```python
   if result.escalate_to_email and result.escalate_message:
       ...  # sinon : rien n'est envoyé
   ```
   Résultat : la conversation passe `abandoned`, l'utilisateur reçoit un
   accusé de réception générique, et **personne n'est notifié**. Ce n'est pas
   qu'il manque un palier intermédiaire dans une chaîne à deux niveaux — c'est
   que le filet de sécurité peut être totalement absent selon la spec du
   formulaire. Le formulaire actuel (`nouveau-dossier-client.json`) échappe au
   problème parce qu'il configure explicitement `escalate_to_chat_email:
   fdiaz@jin.fr` — mais rien ne garantit ce filet pour un futur formulaire qui
   oublierait ce champ.

## 3. Modèle de données cible

**Aujourd'hui** : `conversations/{space_id}`, un document, un cycle de vie,
pour toujours.

**Cible** : séparer le canal (le DM, stable dans le temps) de l'épisode
(un formulaire ou une question, qui se termine).

```
conversations/{space_id}                  # doc canal, créé au 1er contact
  active_session_id: str | null           # session Investigator en cours, ou aucune
  recent_channel_history: HistoryTurn[]    # derniers échanges tous types confondus,
                                            # pour donner du contexte au routeur (ex. suivi
                                            # d'une question RAG précédente)
  sessions/{session_id}                    # sous-collection, une par formulaire lancé
     ...                                   # forme identique à ConversationState aujourd'hui
                                            # (form_id, status, phase, answers, history, etc.)
```

- Quand `active_session_id` est posé, `/chat` continue **exactement** le
  chemin d'aujourd'hui (`decide_next_action` → `apply_action` →
  `state_machine.py`), sur la session pointée. Rien ne change dans cette
  mécanique déjà éprouvée.
- Quand `active_session_id` est `null` (canal libre, ou tout premier
  message), `/chat` bascule vers le routeur (§4).
- Une session terminée (`completed`/`abandoned`/`failed`) libère
  `active_session_id` (remise à `null`) mais reste lisible dans
  `sessions/` pour l'historique et l'audit — au lieu de bloquer le canal.

**Point à trancher, pas à ma charge** : si le volume reste faible et que
l'historique détaillé par session n'a pas de valeur métier immédiate, une
version plus simple consiste à réécrire le document `conversations/{space_id}`
à chaque nouvelle session (on perd la trace des sessions précédentes, mais on
évite la sous-collection). Je recommande la sous-collection — le coût
d'implémentation supplémentaire est faible et elle garde une trace de chaque
dossier client traité par ce canal — mais c'est un choix produit, pas
seulement technique.

## 4. Routeur d'intention

Nouveau point d'entrée dans `app/routers/chat.py` : quand
`active_session_id` est `null`, appeler une nouvelle fonction (ex.
`app/core/router.py::decide_route`) au lieu de `decide_next_action`.

Implémentation en function calling, avec deux familles d'outils exposées au
LLM :

- `chercher_dans_le_corpus(query: str)` — outil fixe, toujours présent
- `demarrer_process(process_id: str, contexte_libre: str)` — un choix parmi
  les process du registre (§5), `process_id` étant l'identifiant déclaré dans
  chaque fichier `forms/*.json`

Le routeur ne s'exécute **jamais** pendant une session active — voir §3. Pas
de conflit à gérer entre « répondre à une question de formulaire » et
« changer de sujet » : cette question a été tranchée en amont dans la
conversation qui a mené à ce document — une fois un formulaire lancé, on va
jusqu'au bout, un message hors sujet pendant une session active est recadré
par `clarify_needed` (mécanisme déjà existant), jamais traité comme une
nouvelle intention.

## 5. Registre de process

Pas de nouvelle base : chaque fichier `forms/*.json` gagne un champ describant
son intention de déclenchement, utilisé pour construire dynamiquement la
liste d'outils du routeur au démarrage du service.

```jsonc
{
  "form_id": "nouveau-dossier-client-v1",
  "trigger_intent": "Créer un nouveau dossier client dans le Drive et son espace Chat dédié",
  ...
}
```

Le service scanne `forms/*.json` au démarrage (ou en cache invalidé au
déploiement), construit un outil `demarrer_process` par fichier trouvé.
Ajouter un process = ajouter un fichier, rien à recompiler côté routeur.

## 6. RAG — Vertex AI Search sur Drive

Nouveau module `app/core/rag.py` : interroge un datastore Vertex AI Search
connecté à Drive, récupère des passages avec citations (titre du document,
extrait, lien). Nouveau module (ou fonction dans `chat_client.py`) pour
construire un payload `CardsV2` — un card par document cité, avec bouton
« Ouvrir dans Drive ».

**Point de vérification bloquant, à faire avant d'investir dans
l'implémentation** : confirmer si le connecteur Drive de Vertex AI Search
applique les droits d'accès Drive **à la requête** (chaque utilisateur ne
voit que ce qu'il a le droit de voir dans Drive) ou seulement **à
l'indexation** (les droits sont figés au moment du crawl, potentiellement
obsolètes ou communs à tous les appelants). Si c'est le second cas, il ne faut
pas s'appuyer sur ce mécanisme pour des documents à accès restreint sans un
filtrage additionnel — à valider dans la documentation Vertex AI Search /
connecteurs Workspace avant de coder quoi que ce soit ici.

Ce module ne crée pas de session dans `sessions/` — c'est un tour sans
webhook, sans cycle de vie de formulaire. Il peut alimenter
`recent_channel_history` pour permettre un suivi conversationnel léger
(« et celui du mois dernier ? »).

## 7. Cas d'usage illustrés

### 7.1 Cas A — Question de connaissance

> L'utilisateur écrit : *« Est-ce qu'on a déjà un contrat cadre avec
> Sephora ? »*

1. `POST /chat` reçoit l'événement `MESSAGE`. `active_session_id` est `null`
   sur le doc canal (ou le canal n'existe pas encore).
2. `decide_route` appelle Gemini avec les deux familles d'outils (§4). Le
   modèle choisit `chercher_dans_le_corpus(query="contrat cadre Sephora")`.
3. `app/core/rag.py` interroge Vertex AI Search, obtient des passages avec
   citations.
4. La réponse est envoyée dans le DM : texte de synthèse + une ou plusieurs
   cards pointant vers les documents Drive trouvés.
5. Aucune session Firestore n'est créée ; le tour est éventuellement ajouté à
   `recent_channel_history`.

### 7.2 Cas B — Process déclenché depuis le chat

> L'utilisateur écrit : *« Il faut créer un nouveau dossier client pour
> Sephora. »*

1. Même point d'entrée, même routeur. Le modèle choisit
   `demarrer_process(process_id="nouveau-dossier-client", contexte_libre="Sephora")`.
2. Le code charge `forms/nouveau-dossier-client.json` et le valide avec
   `FormSpec.model_validate` — **exactement** comme aujourd'hui côté `/start`.
3. **Point ouvert à trancher, pas à ma charge** : la spec actuelle du
   formulaire est rédigée pour un client nommé « ACME » en dur
   (`interlocutor_validation.question`: *« Es-tu responsable du dossier
   client ACME ? »*, `nom_dossier.question` : *« Est-ce que le nom de dossier
   _acme est correct ? »*). Aujourd'hui, ce texte est visiblement pensé pour
   être personnalisé avant l'appel à `/start` (par le script ou l'app
   appelante, cas C). Pour le cas B, il n'y a personne pour faire ce travail
   de personnalisation avant le déclenchement — c'est le message libre de
   l'utilisateur qui contient le nom du client. Deux options :
   - **(a)** Généraliser le texte du formulaire pour ne plus nommer de client
     en dur (« Es-tu responsable du dossier client dont on vient de parler ? »),
     et laisser `nom_dossier` porter seul le nom réel.
   - **(b)** Ajouter une étape de templating entre `demarrer_process` et le
     chargement du formulaire, qui substitue le nom extrait du message
     déclencheur dans les textes qui le nécessitent.
   Je recommande (a) — plus simple, pas de nouvelle mécanique de templating à
   maintenir — mais c'est un choix de rédaction produit, à valider avec qui
   écrit les formulaires.
4. Une nouvelle entrée est créée dans `sessions/{session_id}` avec l'état
   initial identique à `build_initial_state` aujourd'hui. **Différence de
   code nécessaire** : `begin_conversation` actuel appelle toujours
   `chat_client.create_dm(...)` pour obtenir un `space_id` — il faut une
   variante (`resume_in_space`) qui réutilise le `space_id` déjà ouvert
   puisqu'on est déjà dans le DM, sans ouvrir un second DM.
5. `active_session_id` du doc canal pointe vers cette session. À partir de
   là, tout le déroulé est celui déjà documenté dans la passation : machine à
   états, validation JSON Schema, `stop_values`, escalade interlocuteur,
   webhook final.
6. Une fois le formulaire complet ou abandonné, `active_session_id` repasse à
   `null` — le canal redevient disponible pour une future question ou un
   futur process, sans que rien ne soit perdu de l'historique de cette
   session.

### 7.3 Cas C — Process déclenché par une app externe

> Le CRM détecte qu'un deal vient d'être marqué « signé » pour Sephora.

1. L'app externe appelle `POST /start` — **strictement le flux déjà en
   production**, sans changement. Elle fournit `form_spec` (déjà personnalisé
   avec le nom du client, cf. §7.2 point 3), `contact`, `webhook_url`.
2. `begin_conversation` classique s'exécute, DM ouvert comme aujourd'hui.
3. Seul changement réel : le doc canal résultant expose désormais
   `active_session_id` (modèle §3) au lieu d'un doc unique bloqué à vie une
   fois le formulaire terminé.

**Confort optionnel, non bloquant** : permettre à l'app externe d'envoyer
`{"process_id": "nouveau-dossier-client", "contact": {...}, "webhook_url":
"..."}` sans réémettre tout le JSON du formulaire, le serveur résolvant
`process_id` via le registre (§5). Utile si plusieurs systèmes externes
doivent déclencher le même formulaire, pas nécessaire si un seul appelant
existe aujourd'hui.

## 8. Escalade — combler le filet de sécurité manquant

Comme détaillé en §2.3, le vrai problème n'est pas un palier manquant dans une
chaîne à deux niveaux, mais l'absence de filet quand `escalate_to_chat_email`
n'est pas renseigné. Correctif :

1. Ajouter une constante de repli dans `app/config.py`, ex.
   `ops_fallback_email: str = "fdiaz@jin.fr"` (variable d'env
   `OPS_FALLBACK_EMAIL` pour ne pas coder l'adresse en dur dans le repo).
2. Dans `state_machine.py::apply_interlocutor`, branche
   `interlocutor_unknown` :
   ```python
   escalate_email = (
       (unknown.escalate_to_chat_email if unknown else None)
       or get_settings().ops_fallback_email
   )
   escalate_message = escalate_message or (
       f"Formulaire {state.form_id} : {state.contact.user_email} "
       f"n'a pas pu être validé comme interlocuteur et n'a pas indiqué de "
       f"remplaçant. Space : {state.space_id}."
   )
   ```
   Un message part **toujours** vers quelqu'un, que la spec du formulaire ait
   pensé à configurer `if_unknown` ou non.
3. `InterlocutorUnknown.escalate_to_chat_email` (dans `form_spec.py`) devient
   optionnel plutôt que requis, cohérent avec le filet ajouté au niveau code.

## 9. Fichiers impactés, par phase

| Phase | Fichiers |
|---|---|
| Modèle de données (§3) | `app/models/conversation_state.py`, `app/storage/firestore_repo.py`, `app/storage/base.py`, `app/storage/memory_repo.py`, `app/core/turn.py` |
| Escalade (§8) — indépendant, peut se faire en premier | `app/config.py`, `app/core/state_machine.py`, `app/models/form_spec.py` |
| Registre de process (§5) | chaque `forms/*.json` (+ `trigger_intent`), nouveau chargeur dans `app/core/` |
| Routeur (§4) | nouveau `app/core/router.py`, `app/routers/chat.py`, `app/core/turn.py` (nouvelle fonction `resume_in_space`) |
| RAG (§6) | nouveau `app/core/rag.py`, ajout à `app/core/chat_client.py` (construction des cards) |

## 10. Ordre d'implémentation recommandé

1. **Debloquants infra** — `START_ENDPOINT_TOKEN` vers Secret Manager :
   **fait (2026-09-18)**. Rôle Directory API sur le compte de service :
   **toujours à faire**, reste bloquant pour tester avec quelqu'un d'autre
   que Fred.
2. **Escalade (§8)** : **fait (2026-09-18)**, commit `bdff011`.
3. **Modèle de données (§3)** : **fait (2026-09-18)**, commit `2507c04` —
   `conversations/{space_id}` = canal, `sessions/{session_id}` = historique,
   `/start` refuse (409) d'écraser une session `in_progress`.
4. **Routeur + registre (§4, §5)** — débloque le cas B en interne (sans
   encore le RAG, `chercher_dans_le_corpus` peut temporairement répondre
   « fonctionnalité à venir »). **Prochaine étape.**
5. **RAG (§6)** — après le spike de vérification des ACL Drive.
6. **Bout en bout** sur les 3 cas avec un utilisateur réel autre que Fred,
   puis mise à jour de `SPEC-passation-Claude.md` avec le comportement
   effectivement vérifié.

## 11. Risques et points non tranchés dans ce document

- ACL du connecteur Drive de Vertex AI Search (§6) — bloquant pour le cas A
  si mal compris.
- Personnalisation du texte de formulaire pour le cas B (§7.2 point 3) — a
  un impact sur la rédaction de tous les futurs formulaires, pas seulement
  celui-ci.
- Sous-collection `sessions/` vs document réécrit à chaque fois (§3) — arbitrage
  effort d'implémentation contre traçabilité.
- Budget de latence Cloud Run une fois le routeur (un aller-retour LLM
  supplémentaire) et le RAG dans la boucle — à mesurer contre le timeout
  actuel de 60s avant d'exclure un ajustement de la config Cloud Run.
