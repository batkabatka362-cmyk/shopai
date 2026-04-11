#!/bin/sh
# ShopAI container entrypoint. Dispatches to one of:
#   daemon  — run the autonomous cycle loop (default)
#   api     — start the HTTP API server on port 8080
#   cli     — pass remaining args through to cli.py
#   sh      — drop to a shell (debugging)
set -e

cmd="${1:-daemon}"
shift || true

case "$cmd" in
    daemon)
        echo "[entrypoint] starting ShopAI daemon"
        exec python -u scripts/run_daemon.py "$@"
        ;;
    api)
        echo "[entrypoint] starting ShopAI API server on :8080"
        exec python -u -m api.server "$@"
        ;;
    cli)
        exec python -u cli.py "$@"
        ;;
    sh|bash)
        exec /bin/sh
        ;;
    *)
        # Allow passing arbitrary `python ...` or other commands
        exec "$cmd" "$@"
        ;;
esac
