@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if "%~1"=="" (
  echo Usage: check-gchat.bat collaborateur@jin.fr
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [check-gchat] ERREUR : .venv introuvable.
  exit /b 1
)

".venv\Scripts\python.exe" "scripts\check_gchat_dm.py" --email "%~1" %2 %3 %4 %5
