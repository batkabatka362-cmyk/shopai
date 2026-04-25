#!/usr/bin/env bash
#
# OpenClaw local install — clones the OpenClaw repo as a
# sibling directory (or into the path you specify) and runs
# `npm install`. ShopAI stays free of TypeScript source; the
# adapter wires to OpenClaw via subprocess once it's running.
#
# Usage:
#   bash scripts/setup_openclaw.sh                 # default: ~/projects/openclaw
#   SHOPAI_OPENCLAW_HOME=/opt/openclaw bash …      # override install path
#
# Prerequisites:
#   - git, node (>=18), npm
#   - Ollama running locally (http://localhost:11434) if you
#     want the local-AI path; otherwise set a cloud API key
#     (ANTHROPIC_API_KEY / OPENAI_API_KEY) in OpenClaw's
#     own config after install.
#
# This script is idempotent — re-running pulls latest + re-
# installs deps. Safe to run multiple times.
set -euo pipefail

OPENCLAW_REPO="${SHOPAI_OPENCLAW_REPO:-https://github.com/openclaw/openclaw.git}"
OPENCLAW_HOME="${SHOPAI_OPENCLAW_HOME:-$HOME/projects/openclaw}"

bold()   { printf '\033[1m%s\033[0m\n' "$*"; }
okay()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
fail()   { printf '  \033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }
info()   { printf '  • %s\n' "$*"; }

bold "OpenClaw installer"
echo

# ── 1. Tool prereq check ────────────────────────────────────
info "checking prerequisites…"
for tool in git node npm; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    fail "$tool not found on PATH — install it first"
  fi
done

NODE_MAJOR="$(node -v | sed 's/^v//; s/\..*//')"
if [ "$NODE_MAJOR" -lt 18 ]; then
  fail "node >= 18 required (you have $(node -v))"
fi
okay "git $(git --version | awk '{print $3}')"
okay "node $(node -v)"
okay "npm $(npm -v)"

# ── 2. Clone / update ───────────────────────────────────────
if [ -d "$OPENCLAW_HOME/.git" ]; then
  info "existing clone found at $OPENCLAW_HOME — pulling"
  (cd "$OPENCLAW_HOME" && git pull --ff-only) \
    || fail "git pull failed (uncommitted changes?)"
else
  mkdir -p "$(dirname "$OPENCLAW_HOME")"
  info "cloning $OPENCLAW_REPO → $OPENCLAW_HOME"
  git clone --depth 1 "$OPENCLAW_REPO" "$OPENCLAW_HOME" \
    || fail "git clone failed"
fi
okay "source at $OPENCLAW_HOME"

# ── 3. npm install ──────────────────────────────────────────
info "running npm install (may take ~2-5 min)…"
(cd "$OPENCLAW_HOME" && npm install) \
  || fail "npm install failed"
okay "deps installed"

# ── 4. Ollama check (advisory) ──────────────────────────────
if command -v ollama >/dev/null 2>&1; then
  if curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
    okay "Ollama reachable at localhost:11434"
  else
    info "ollama CLI found but server not responding — run:"
    info "  ollama serve &"
  fi
else
  info "Ollama not installed. For local-AI path:"
  info "  https://ollama.com/download"
  info "For cloud-AI path: set ANTHROPIC_API_KEY / OPENAI_API_KEY"
  info "in OpenClaw's config (see its README)."
fi

# ── 5. Next steps ───────────────────────────────────────────
echo
bold "Next steps"
cat <<EOF

  1. Configure OpenClaw's LLM backend:
       cd $OPENCLAW_HOME
       # follow its README (.env or config file)

  2. Start OpenClaw in chat mode to verify it works:
       cd $OPENCLAW_HOME
       npm start          # or ./bin/openclaw

  3. When OpenClaw is running, tell ShopAI where it lives:
       echo "SHOPAI_OPENCLAW_HOME=$OPENCLAW_HOME" >> .env

  4. ShopAI subprocess adapter (shipping soon) reads that env
     var and invokes OpenClaw on demand. See
     docs/OPENCLAW_INTEGRATION.md for the architecture.

EOF
okay "setup complete"
