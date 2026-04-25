@echo off
REM ── ShopAI Windows launcher ──────────────────────────────
REM Double-click this file to start ShopAI on Windows.
REM
REM Prereqs (install once):
REM   1. Docker Desktop for Windows  https://docs.docker.com/desktop/install/windows-install/
REM   2. .env file in the same folder (copy .env.example → .env,
REM      fill in SHOPAI_SHOPIFY_URL + SHOPAI_SHOPIFY_KEY)
REM
REM What this does:
REM   1. Checks Docker Desktop is running
REM   2. Builds + starts 4 containers (daemon / api / ollama / tunnel)
REM   3. Waits until the tunnel URL is ready
REM   4. Prints the public webhook URL you paste into Shopify
REM   5. Opens the local API health page in your browser

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo  ShopAI launcher
echo  ==================

REM ── 1. Docker reachable? ─────────────────────────────────
docker info >nul 2>&1
if errorlevel 1 (
    echo.
    echo  X  Docker Desktop is not running.
    echo     Start Docker Desktop from the Start menu, wait
    echo     until the whale icon stops animating, then run
    echo     this launcher again.
    echo.
    pause
    exit /b 1
)
echo  OK Docker Desktop running

REM ── 2. .env present? ─────────────────────────────────────
if not exist ".env" (
    echo.
    echo  X  .env file not found.
    echo     1. Copy .env.example to .env:
    echo            copy .env.example .env
    echo     2. Open .env in Notepad and set at least
    echo        SHOPAI_SHOPIFY_URL and SHOPAI_SHOPIFY_KEY.
    echo     3. Save and re-run this launcher.
    echo.
    pause
    exit /b 1
)
echo  OK .env present

REM ── 3. Bring the stack up ────────────────────────────────
echo  -- Starting containers (first run downloads ~2 GB) ...
docker compose up -d
if errorlevel 1 (
    echo.
    echo  X  docker compose up failed. See output above.
    pause
    exit /b 1
)
echo  OK containers started

REM ── 4. Wait for cloudflared tunnel URL ───────────────────
echo  -- Waiting for public tunnel URL...
set "TUNNEL_URL="
set /a attempts=0
:wait_tunnel
set /a attempts+=1
if !attempts! GTR 30 (
    echo  !! tunnel URL not detected after 60s — check:
    echo         docker compose logs cloudflared
    goto after_tunnel
)
for /f "tokens=*" %%i in ('docker compose logs cloudflared 2^>nul ^| findstr trycloudflare.com') do (
    for /f "tokens=*" %%j in ('echo %%i ^| findstr /r "https://.*trycloudflare.com"') do (
        for %%k in (%%j) do (
            echo %%k | findstr /c:"trycloudflare.com" >nul && set "TUNNEL_URL=%%k"
        )
    )
)
if defined TUNNEL_URL goto after_tunnel
timeout /t 2 /nobreak >nul
goto wait_tunnel

:after_tunnel
echo.
if defined TUNNEL_URL (
    echo  === Public webhook URL (paste into .env) ===
    echo.
    echo     SHOPAI_WEBHOOK_CALLBACK_URL=%TUNNEL_URL%/api/webhook/shopify
    echo.
    echo  Then restart the daemon so it registers webhooks:
    echo     docker compose up -d --force-recreate shopai-daemon
) else (
    echo  See tunnel logs manually:
    echo     docker compose logs cloudflared
)

echo.
echo  -- Opening local health page in your browser ...
start "" http://localhost:8080/health
echo.
echo  Stack running in background. Common commands:
echo     docker compose logs -f shopai-daemon    (live daemon logs)
echo     docker compose logs -f cloudflared      (tunnel state)
echo     docker compose down                      (stop all)
echo.
pause
