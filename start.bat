@echo off
REM start.bat — Start AgentForge on Windows
REM Usage: start.bat

echo.
echo   AgentForge
echo   -------------------------------------------

REM Check .env
if not exist .env (
    echo   No .env found — copying .env.example
    copy .env.example .env
    echo   Edit .env and add your ANTHROPIC_API_KEY, then re-run.
    pause
    exit /b 1
)

REM Install Python deps
echo   Installing Python dependencies...
pip install -q -r requirements.txt

REM Install frontend deps
if not exist ui\frontend\node_modules (
    echo   Installing frontend dependencies...
    cd ui\frontend
    npm install --silent
    cd ..\..
)

echo.
echo   Starting servers:
echo   Backend  - http://localhost:8000
echo   Frontend - http://localhost:5173
echo   -------------------------------------------
echo   Close this window to stop.
echo.

start "AgentForge Backend" cmd /k "set PYTHONPATH=%CD% && uvicorn ui.backend.main:app --reload --port 8000"
start "AgentForge Frontend" cmd /k "cd ui\frontend && npm run dev"
