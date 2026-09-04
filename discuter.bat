@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [discuter] ERREUR : .venv introuvable.
  exit /b 1
)

echo [discuter] Dialogue local — tu joues le collaborateur.
echo            Si le serveur n'est pas lance, ouvre relancer.bat dans une autre fenetre.
echo.
".venv\Scripts\python.exe" "scripts\discuter.py" %*
