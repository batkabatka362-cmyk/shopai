#!/usr/bin/env bash
# ShopAI Linux / Mac launcher.
#
# Prereqs:
#   1. Docker (or Docker Desktop on Mac)
#   2. .env file filled in (copy from .env.example)
#
# Usage:
#   ./start.sh              # up detached
#   ./start.sh logs         # tail daemon logs
#   ./start.sh down         # stop all services
set -euo pipefail
cd "$(dirname "$0")"

bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }
okay() { printf '  \033[32m✓\033[0m %s\n' "$*"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }

case "${1:-up}" in
  down)
    docker compose down
    exit 0
    ;;
  logs)
    docker compose logs -f "${2:-shopai-daemon}"
    exit 0
    ;;
  up)
    ;;  # fall through
  *)
    echo "Usage: $0 [up|down|logs <service>]"
    exit 1
    ;;
esac

bold "ShopAI launcher"

docker info >/dev/null 2>&1 || fail "Docker is not running — start it first"
okay "Docker reachable"

[ -f .env ] || fail ".env missing — copy .env.example and fill it in"
okay ".env present"

echo "  — building + starting containers (first run ~2 GB download)"
docker compose up -d
okay "containers up"

echo "  — waiting for cloudflared tunnel URL..."
TUNNEL_URL=""
for _ in $(seq 1 30); do
  TUNNEL_URL=$(docker compose logs cloudflared 2>/dev/null \
    | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' \
    | head -1 || true)
  [ -n "$TUNNEL_URL" ] && break
  sleep 2
done

echo
if [ -n "$TUNNEL_URL" ]; then
  bold "Public webhook URL (paste into .env)"
  echo "    SHOPAI_WEBHOOK_CALLBACK_URL=$TUNNEL_URL/api/webhook/shopify"
  echo
  echo "  Then restart the daemon:"
  echo "    docker compose up -d --force-recreate shopai-daemon"
else
  echo "  (tunnel URL not detected — check: docker compose logs cloudflared)"
fi

echo
okay "ShopAI running"
echo
echo "  Logs:   ./start.sh logs"
echo "  Stop:   ./start.sh down"
echo "  Health: http://localhost:8080/health"
