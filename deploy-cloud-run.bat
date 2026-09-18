@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PROJECT=admin-jin-fr"
set "REGION=europe-west1"
set "SERVICE=agent-formulaire-gchat"

where gcloud >nul 2>&1
if errorlevel 1 (
  echo [deploy] gcloud introuvable. Installe Google Cloud SDK :
  echo          https://cloud.google.com/sdk/docs/install
  exit /b 1
)

echo [deploy] Projet %PROJECT% / region %REGION%
call gcloud config set project %PROJECT%
if errorlevel 1 exit /b 1

echo [deploy] Activation des API Cloud Run / Cloud Build / Artifact Registry / Agent Platform / Firestore / Admin SDK ...
call gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com aiplatform.googleapis.com firestore.googleapis.com admin.googleapis.com --project %PROJECT%
if errorlevel 1 exit /b 1

echo [deploy] Deploiement (2-5 min) ...
REM START_ENDPOINT_TOKEN vit dans Secret Manager (start-endpoint-token) depuis
REM le 2026-09-18, jamais en clair ici -- voir --set-secrets ci-dessous.
call gcloud run deploy %SERVICE% ^
  --source . ^
  --project %PROJECT% ^
  --region %REGION% ^
  --allow-unauthenticated ^
  --min-instances 1 ^
  --max-instances 5 ^
  --memory 512Mi ^
  --no-cpu-throttling ^
  --timeout 60 ^
  --set-env-vars "APP_ENV=dev,GCP_PROJECT=%PROJECT%,GCP_REGION=%REGION%,FIRESTORE_COLLECTION=conversations,LLM_PROVIDER=gemini,GEMINI_MODEL=gemini-2.5-pro,GOOGLE_CHAT_APP_ID=531758065224,CHAT_AUDIENCE=https://agent-formulaire-gchat-531758065224.europe-west1.run.app/chat,CHAT_AUTH_DISABLED=0,USE_MEMORY_STORE=0,USE_REAL_CHAT=1,CHAT_SERVICE_ACCOUNT=agent-formulaire-gchat@admin-jin-fr.iam.gserviceaccount.com" ^
  --set-secrets "START_ENDPOINT_TOKEN=start-endpoint-token:latest"
if errorlevel 1 exit /b 1

echo.
echo [deploy] URL a coller dans Google Chat (avec /chat) :
call gcloud run services describe %SERVICE% --project %PROJECT% --region %REGION% --format="value(status.url)"
echo /chat
echo.
echo Exemple : https://agent-formulaire-gchat-xxxxx.a.run.app/chat
