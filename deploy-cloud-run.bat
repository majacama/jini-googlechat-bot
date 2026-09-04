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

echo [deploy] Activation des API Cloud Run / Cloud Build / Artifact Registry ...
call gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com --project %PROJECT%
if errorlevel 1 exit /b 1

echo [deploy] Deploiement (2-5 min) ...
call gcloud run deploy %SERVICE% ^
  --source . ^
  --project %PROJECT% ^
  --region %REGION% ^
  --allow-unauthenticated ^
  --min-instances 1 ^
  --max-instances 5 ^
  --memory 512Mi ^
  --set-env-vars "APP_ENV=dev,GCP_PROJECT=%PROJECT%,GCP_REGION=%REGION%,FIRESTORE_COLLECTION=conversations,LLM_PROVIDER=stub,START_ENDPOINT_TOKEN=change-me,GOOGLE_CHAT_APP_ID=531758065224,CHAT_AUTH_DISABLED=1,USE_MEMORY_STORE=1,USE_REAL_CHAT=1,CHAT_SERVICE_ACCOUNT=agent-formulaire-gchat@admin-jin-fr.iam.gserviceaccount.com"
if errorlevel 1 exit /b 1

echo.
echo [deploy] URL a coller dans Google Chat (avec /chat) :
call gcloud run services describe %SERVICE% --project %PROJECT% --region %REGION% --format="value(status.url)"
echo /chat
echo.
echo Exemple : https://agent-formulaire-gchat-xxxxx.a.run.app/chat
