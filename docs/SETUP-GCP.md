# Setup GCP / Google Chat — POC jour 1

Objectif : qu’une Chat app puisse **ouvrir un DM** vers un utilisateur `@jin.fr`
et y poster un message. Tant que ça échoue, le reste de l’agent ne peut pas
passer en réel.

## 1. Projet GCP

1. Crée ou choisis un projet (ex. celui JIN déjà utilisé).
2. Active les API (liens directs, plus fiable que la recherche) :
   - [Google Chat API](https://console.cloud.google.com/apis/library/chat.googleapis.com) — **obligatoire dès le POC DM**
   - [API Gemini Enterprise Agent Platform](https://console.cloud.google.com/apis/library/aiplatform.googleapis.com)
     (ex-« Vertex AI API », identifiant technique `aiplatform.googleapis.com`) — pour Gemini, plus tard
   - Cloud Run, Firestore — pour le déploiement, plus tard

   **Ne cherche pas « gemini »** dans la bibliothèque d’API : tu tomberas sur Gemini
   (AI Studio / clé API grand public), Code Assist, Cloud Assist, etc. Ce n’est
   pas ce dont l’agent a besoin.

   Noms 2026 : Vertex AI s’appelle **Gemini Enterprise Agent Platform**. Dans la
   bibliothèque, cherche **Agent Platform** ou **Vertex AI API**. Le rôle IAM
   reste souvent libellé `Vertex AI User` / `roles/aiplatform.user`.
3. Note `GCP_PROJECT` et `GCP_REGION` (ex. `europe-west1`) dans `.env`.

## 2. Chat app (écran Configuration)

Dans **APIs et services → Google Chat API → Configuration**. Valeurs à coller
pour cet agent (un seul endpoint `POST /chat`).

### À décocher / régler en haut

- **« Créez cette application de chat en tant que module complémentaire Workspace »** :
  **décoche**. Un add-on impose 4 URL de déclencheurs et un manifeste Marketplace.
  Notre agent est une Chat app HTTP classique.
- Après décocher, tu dois retrouver **une seule** « URL du point de terminaison HTTP »
  (pas quatre champs Commande / Ajouté / Message / Supprimé).

### Informations sur l'application

| Champ | Valeur |
|---|---|
| Nom | `Jin Investigator Agent` |
| URL de l'avatar | PNG carré en HTTPS, min 256×256 (fichier public, Drive ne marche souvent pas). Ex. un PNG sur Cloud Storage « public ». |
| Description | `Remplit un formulaire via un DM Chat` (≤ 40 caractères) |

Note le **numéro du projet (ID de l'application)** (ex. `531758065224`) dans
`.env` : `GOOGLE_CHAT_APP_ID=...`

### Fonctionnalités interactives

- **Activer les fonctionnalités interactives** : **ON**
- **Rejoindre des espaces et des conversations de groupe** : **OFF**
  (l’agent parle en DM, pas dans les salles)

### Paramètres de connexion

- Choisir **URL du point de terminaison HTTP** (pas Apps Script, pas Pub/Sub, pas Dialogflow)

URL (même valeur partout si Google exige encore 4 champs) :

`https://<ton-service-cloud-run>/chat`

**Public de l'authentification** : **URL du point de terminaison HTTP** (pas le
numéro de projet). Doit être **exactement** cette URL `/chat` — c'est l'`aud`
du JWT vérifié par Cloud Run.

Tu n’as pas encore Cloud Run : tu peux **enregistrer le reste** et coller
l’URL plus tard, **ou** lancer un tunnel vers le PC :

```powershell
ngrok http 8000
```

Puis URL = `https://xxxx.ngrok-free.app/chat`

Sans URL HTTPS valide, Google refuse souvent d’enregistrer. Le test
`check-gchat.bat` (DM *sortant*) peut marcher **avant** que l’URL reçoive
du trafic, mais le formulaire Configuration, lui, veut un `https://`.

### Déclencheurs

Si tu as encore les 4 champs : mets **la même URL `/chat`** dans :

- Commande d'application
- Ajouté à l'espace
- Message
- Supprimé de l'espace

Ne pas ajouter de **commande** slash ni d’**aperçu de lien** en v1.

### Visibilité

- Coche **« accessible à certains utilisateurs et groupes du domaine Jin »**
- Saisis **ton e-mail** `...@jin.fr` (et celui du collaborateur de test)
- Ne publie pas tout le domaine tant que le POC n’est pas validé

### Journaux

- Coche **Consigner les erreurs dans Logging**

Enregistre (**Enregistrer** en bas de page). L’app doit passer en état
installable pour les e-mails listés.

## 3. Compte de service (obligatoire pour les DM)

`chat.bot` **ne peut pas** être accordé à un utilisateur (`fdiaz@jin.fr`).
Google répond `400 invalid_scope` si on le demande via
`gcloud auth application-default login`. C’est normal.

Il faut un **compte de service** du même projet que la Chat app, et
l’impersonner (pas de clé JSON) :

```powershell
gcloud iam service-accounts create agent-formulaire-gchat `
  --project admin-jin-fr `
  --display-name "Jin Investigator Agent"

gcloud iam service-accounts add-iam-policy-binding `
  agent-formulaire-gchat@admin-jin-fr.iam.gserviceaccount.com `
  --project admin-jin-fr `
  --member "user:fdiaz@jin.fr" `
  --role roles/iam.serviceAccountTokenCreator
```

Dans `.env` :

```
CHAT_SERVICE_ACCOUNT=agent-formulaire-gchat@admin-jin-fr.iam.gserviceaccount.com
```

ADC utilisateur **sans** `chat.bot` :

```powershell
gcloud auth application-default login
```

Le code demande `chat.bot` **au compte de service**, pas à toi.

## 4. Contacter un collaborateur sans qu’il écrive en premier

C’est le besoin métier. Ce n’est **pas** un réglage GCP manquant : Google Chat
sépare « parler **en tant qu’app** » et « parler **en tant que Fred** ».

### Pourquoi « à ma place » (comme fdiaz@jin.fr) ne marche pas

Si l’agent envoie les messages **avec ton identité**, le collaborateur voit un
DM **Fred ↔ lui**. Tes réponses à toi arrivent dans **ton** Chat, pas sur
Cloud Run (`POST /chat`). L’agent ne peut plus lire les réponses ni piloter
le formulaire.

L’agent doit donc être **l’interlocuteur** : DM **Jin Investigator Agent ↔ collaborateur**.
Toi tu déclenches (`/start`) ; l’app parle ensuite toute seule.

### Ce que Google autorise

| Mode | Qui écrit | L’agent reçoit les réponses ? | Qui doit agir |
|---|---|---|---|
| `chat.bot` seul | l’app, seulement si le DM existe déjà | oui | le collaborateur (ou l’admin) a déjà ouvert le chat |
| **Installation admin de l’app** pour le domaine / une UO | l’app | oui | **admin Workspace** : Google crée le DM avec chaque user |
| Scope `chat.app.spaces.create` | l’app crée le DM | oui | admin : approbation Marketplace / app auth (plus lourd) |

### Action (tu es super admin jin.fr)

**A. Autoriser les Chat apps (obligatoire)**

1. https://admin.google.com (compte `fdiaz@jin.fr`)
2. **Applications** → **Google Workspace** → **Google Chat**
3. **Applications Chat**
4. UO racine (tout le domaine) : **Autoriser les utilisateurs à installer des applications Chat** = **Activé**
5. Enregistre

**B. Rendre l’app visible dans Chat**

Dans GCP → Google Chat API → Configuration → Visibilité :

- Pour le POC : ton e-mail + les collaborateurs de test, **ou**
- Tout le domaine `jin.fr` si tu veux que chacun puisse trouver **Jin Investigator Agent**

**C. Installation Admin (c’est ça qui crée les DM tout seuls)**

Sans ça, chaque personne doit encore « ajouter » l’app une fois.
Avec une **installation Admin**, Google crée le DM app ↔ user.

1. Active l’API :  
   https://console.cloud.google.com/apis/library/appsmarket-component.googleapis.com?project=admin-jin-fr
2. Ouvre la page SDK (pas Métriques / Quotas) :  
   https://console.cloud.google.com/apis/api/appsmarket-component.googleapis.com/googleapps_sdk?project=admin-jin-fr
3. Onglet **Configuration de l'application** : visibilité **Privée**, installation **Individuelle + admin**, coche **Application Chat**, enregistre.
4. Onglet **Fiche Store** :  
   https://console.cloud.google.com/apis/api/appsmarket-component.googleapis.com/googleapps_sdk_publish?project=admin-jin-fr  
   Nom, textes, icônes, puis **Publier** (privée, jin.fr seulement).
5. **Ensuite seulement** admin.google.com → Marketplace → Installer une application → Jin Investigator Agent.

Tant que la fiche Store n’est pas publiée, Admin console ne trouvera **jamais** l’app.

En attendant, teste dans **Google Chat** : Nouveau chat → Jin Investigator Agent → « Bonjour ».

Attends 2–5 minutes, puis :

```powershell
.\check-gchat.bat fdiaz@jin.fr
```

Tu dois recevoir le message POC dans Google Chat, **sans** avoir écrit à l’app avant.

## 4.1 Directory API — résoudre l’e-mail en ID Chat (sans `user_id` dans le JSON)

L’API Chat `chat.bot` refuse `users/prenom@domaine`. Il faut `users/{id numérique}`.
Pour que **seul l’e-mail** dans `recipient` suffise, le compte de service doit lire
l’annuaire Workspace.

Compte de service :

`agent-formulaire-gchat@admin-jin-fr.iam.gserviceaccount.com`

1. Active l’API Admin SDK :  
   https://console.cloud.google.com/apis/library/admin.googleapis.com?project=admin-jin-fr
2. https://admin.google.com (compte super admin `fdiaz@jin.fr`)
3. **Compte** → **Rôles d'administrateur** → **Créer un rôle**
   - Nom : `Directory users read`
   - Onglet **Privilèges de l'API Admin** (pas seulement la console) :
     **Utilisateurs** → **Lire**
   - Enregistre
4. Ouvre ce rôle → **Admins** / **Attribuer** → **Attribuer des comptes de service**
   - Colle `agent-formulaire-gchat@admin-jin-fr.iam.gserviceaccount.com`
   - Attribue (propagation : 1–10 min)
5. Vérifie en local (ADC **sans** scope `chat.bot`) :

```powershell
.\.venv\Scripts\python.exe .\scripts\check_directory_user.py --email fdiaz@jin.fr
```

Tu dois voir `users/113859878083610238922` (pas `users/fdiaz@jin.fr`).
Ensuite tu peux retirer `recipient.user_id` du JSON.

## 5. Lancer le test

```powershell
.\check-gchat.bat fdiaz@jin.fr
```

Échecs fréquents :

| HTTP | Cause probable |
|---|---|
| 401 | ADC / clé de compte de service absente ou mauvais scope |
| 403 | App non installée, ou admin interdit les DM initiés par une app |
| 404 | API Chat inactive, ou e-mail hors domaine / introuvable |

## 6. Brancher l’app ensuite

Dans `.env`, pour que `/start` utilise le vrai Chat tout en gardant Firestore
en mémoire le temps du POC :

```
USE_REAL_CHAT=1
USE_MEMORY_STORE=1
GCP_PROJECT=ton-projet
```

L’endpoint `POST /chat` devra ensuite être l’URL Cloud Run (ou un tunnel)
déclarée dans la config de la Chat app.
