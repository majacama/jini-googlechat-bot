@echo off
setlocal EnableExtensions
cd /d "%~dp0"

rem Ports utilises par l'app (uvicorn local + Cloud Run / Docker)
set "PORTS=8000 8080"

echo.
echo [relancer] Dossier : %CD%
echo [relancer] Liberation des ports %PORTS% ...

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ports = @(8000, 8080); foreach ($p in $ports) { Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | ForEach-Object { $procId = $_.OwningProcess; if ($procId -and $procId -ne 0) { Write-Host ('[relancer] Port {0} -> kill PID {1}' -f $p, $procId); Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue } } }"

if not exist ".venv\Scripts\python.exe" (
  echo [relancer] ERREUR : .venv introuvable.
  echo           Cree-le avec : python -m venv .venv
  echo           puis         : .venv\Scripts\python.exe -m pip install -e ".[dev]"
  exit /b 1
)

echo [relancer] Demarrage : http://127.0.0.1:8000
echo [relancer] Docs      : http://127.0.0.1:8000/docs
echo.
".venv\Scripts\python.exe" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
