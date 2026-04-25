# Risk Gate — Operator Guide

The risk gate is the code half of owner's **"full autonomous AGI,
human-approve on high-risk"** vision. It sits at every
money-commit point in the launch pipeline and either:

  1. **Auto-approves** LOW / MEDIUM-with-both-flags actions
     (current behaviour — no change).
  2. **Queues** HIGH / CRITICAL actions + notifies owner via
     Telegram. Launch stops until the owner approves.

This doc is the operator guide — when to turn it on, what the
owner sees, how to approve/deny, troubleshooting.

Design doc: `docs/BUSINESS_MODEL_MATRIX.md` §Risk classification.
Code: `core/system/risk_gate.py`, `approval_queue.py`,
`approval_notifier.py`.

---

## Quick start

### 1. Enable live execution + risk gate

```bash
# Turn on live writes (you'd do this anyway for real launches)
export SHOPAI_ENABLE_LIVE_EXECUTION=1

# Turn on Telegram notifications (optional but strongly
# recommended — without it the owner must poll the CLI)
export SHOPAI_TELEGRAM_TOKEN=123456:ABC-DEF...
export SHOPAI_TELEGRAM_CHAT_ID=987654321
```

### 2. Run a launch with the gate

```python
from execution.launch.publisher_bundle import (
    LaunchRequest, PublisherBundle,
)

req = LaunchRequest(
    winner={
        "title": "Galaxy Projector",
        "price": 29.99,
        ...
    },
    shop_url="deguar.myshopify.com",
    api_key="shpat_...",
    ad_budget_daily=20.0,
    live=True,
    risk_gate_enabled=True,   # ← the magic flag
)
result = PublisherBundle().launch(req)

# Inspect the outcome
launch_step = next(
    s for s in result.steps if s.name == "launch_campaign"
)
if launch_step.status == "pending_approval":
    print(
        "Queued for approval:",
        launch_step.data["request_id"],
    )
elif launch_step.status == "success":
    print("Launched:", launch_step.data["campaign_id"])
```

### 3. Approve from Telegram (or CLI)

Owner's phone buzzes:

```
🚨 HIGH approval needed

request_id:  abc123def456789a
action:      ad_campaign_create
why gated:   Commits money or touches an external surface.
payload:     {"daily_budget_usd": 20, "store": "deguar", ...}

Reply with:
  approve abc123def456789a
  deny abc123def456789a <reason>

Expires in 30 min.
```

Owner types back into Telegram:

```
approve abc123def456789a
```

Bot confirms: `✓ Approved · ad_campaign_create · by owner`.

CLI alternative (if no Telegram):

```bash
shopai pending-approvals
# → shows the queue

shopai approve-request abc123def456789a --reason "budget is fine"
# → ✓ Approved abc123def456789a (ad_campaign_create, high)
```

### 4. Retry the launch with `approved_request_id`

```python
req = LaunchRequest(
    ...,
    risk_gate_enabled=True,
    approved_request_id="abc123def456789a",  # from step 2
)
result = PublisherBundle().launch(req)
# This time launch_step.status == "success" — the gate saw
# the approval and let the Meta Ads commit through.
```

---

## What triggers the gate

The classifier (`core/system/risk_gate.classify`) assigns one
of 4 levels per canonical action name:

| Level | Examples | Gate behaviour |
|---|---|---|
| **LOW** | metafield_write, tag_add, page_update, redirect_create | always auto-approve |
| **MEDIUM** | product_publish, image_upload, webhook_subscribe, price_change<10% | auto if `auto_approve=True` AND `SHOPAI_ENABLE_LIVE_EXECUTION=1` |
| **HIGH** | **ad_campaign_create**, **ad_campaign_resume**, discount_create, supplier_order, email_blast_send, product_delete | always queue |
| **CRITICAL** | live_execution_toggle, policy_rewrite, theme_publish, dns_change, ad_budget > $100/day | always queue |

Some actions **escalate** based on payload:
  * `price_change` with `|delta_pct| ≥ 10` → HIGH (from MEDIUM)
  * `ad_budget_set` / `ad_campaign_create` with
    `daily_budget_usd > 100` → CRITICAL
  * `inventory_update` with `delta_units < -100` → HIGH

Full action list: `shopai classify_action <action_name>` (MCP
tool) or read `core/system/risk_gate._ACTION_RULES`.

---

## When to turn it on

### Turn it ON

  * **First live Meta Ads launch** — you want to review
    everything the brain does before committing real budget
  * **Large budget increases** — gate catches `daily_budget_usd
    > 100` automatically
  * **Overnight autonomous runs** — owner not at desk, brain
    queues high-risk actions for morning review
  * **New adapter integrations** — gate catches "category of
    action we don't auto-approve yet"

### Leave it OFF

  * Internal metafield / collection / page writes (all LOW
    anyway, would never queue)
  * Automated test suites (add `risk_gate_enabled=True` only
    in tests specifically verifying the gate itself)
  * Replay / backfill tools hitting historical data
  * Emergency kill-switch-style actions where blocking for
    approval would defeat the purpose

### Per-launch vs global?

The gate is **per-launch opt-in**. There's no global toggle —
each `LaunchRequest` or `ActivateRequest` sets its own
`risk_gate_enabled` flag. The brain can decide per decision
whether to gate (e.g. "I'm 95% confident → gate off" vs
"unfamiliar territory → gate on"). Future P2d may add a
controller-level default.

---

## Owner's Telegram flow

### Replies the bot understands

| Owner types | Effect |
|---|---|
| `approve <16-hex>` | Mark the action approved |
| `approve <8-32-hex> reason words` | Approve + record reason |
| `deny <16-hex>` | Mark denied |
| `deny <16-hex> reason words` | Deny + record reason |
| `pending approvals` / `what's pending` | List current queue |

No `confirm` suffix needed for approve/deny — the verb itself
is the confirmation. Every other write-intent tool
(`halt launches`, `set budget`, etc.) still needs the confirm
suffix.

### Idempotency

Double-approve is a no-op: the second call returns the row
as-is, doesn't overwrite owner or reason. Designed for flaky
Telegram webhooks that might retry.

### Expiry

Default TTL is 30 min. Configurable per-enqueue via
`queue.enqueue(..., ttl_minutes=60)`. After TTL:

  * Row becomes `expired`
  * Any approve/deny call on an expired row returns "expired"
    instead of silently flipping
  * `queue.expire_old()` sweeps periodically — wire into your
    cycle if you want aggressive cleanup

---

## CLI reference

```bash
# Read queue
shopai pending-approvals [--limit 20] [--json]

# Decide
shopai approve-request <request_id> [--reason "..."] [--owner "..."]
shopai deny-request <request_id> [--reason "..."] [--owner "..."]

# Introspect classification without triggering the action
# (via MCP — Claude Desktop / Cursor / any client):
#   Tool: classify_action
#   Args: {"action_type": "ad_campaign_create",
#          "payload": {"daily_budget_usd": 150}}
```

Exit codes on approve/deny:
  * `0` — decision applied
  * `1` — already decided (idempotent) or expired
  * `2` — no request with that ID

---

## MCP tools

| Tool | Write? | Purpose |
|---|---|---|
| `pending_approvals` | read | List queued rows |
| `approve_request` | write | Approve by request_id |
| `deny_request` | write | Deny by request_id |
| `classify_action` | read | Pre-classify without enqueueing |

All four are registered at startup — `shopai mcp list` or
`Claude Desktop` shows them alongside the 35 other tools.

---

## Telegram adapter setup (commodity layer)

The gate's notifier is pluggable — by default it uses
`core/adapters/telegram_bot/`. To swap for Discord or Slack
later, implement a class with `is_available()` +
`send_message(text)` and inject via:

```python
from core.system.approval_notifier import ApprovalNotifier
from core.system.approval_queue import get_queue

# Replace default factory
custom_notifier = ApprovalNotifier(
    adapter_factory=lambda: MyDiscordAdapter(),
)
get_queue().on_enqueue(custom_notifier.notify)
```

Default Telegram setup — add to `.env`:

```
SHOPAI_TELEGRAM_TOKEN=123456:ABCDEFG...
SHOPAI_TELEGRAM_CHAT_ID=987654321
```

Without these, the notifier silently degrades — enqueue still
works, owner polls via `shopai pending-approvals`.

---

## Troubleshooting

### Launch returns `pending_approval` but no Telegram message arrives

  1. Check creds: `echo $SHOPAI_TELEGRAM_TOKEN` +
     `$SHOPAI_TELEGRAM_CHAT_ID`
  2. Run the TG smoke test manually:
     ```python
     from core.adapters.telegram_bot import bot
     bot.get_bot().send_message("test from gate")
     ```
  3. Verify level is HIGH or CRITICAL —
     `shopai pending-approvals` shows only those
  4. Check the Telegram chat ID belongs to a chat you've
     already `/start`-ed with the bot (bot can't DM strangers)

### Owner approved but retry still queues

  * Verify the retry passes `approved_request_id=<id>` on the
    same kind of action (`ad_campaign_create`). Approval is
    action-type-scoped — an ad approval can't unlock a
    product_delete.
  * Check status: `shopai pending-approvals --json | grep <id>`
    — should say `"status": "approved"`.

### Tests fail after turning on risk_gate_enabled

  * Most existing tests use `live=True` to exercise the live
    path with mock adapters. They expect `status="success"`.
    With `risk_gate_enabled=True`, the gate enqueues instead,
    yielding `status="pending_approval"`.
  * Fix: in test fixtures that need the live path, either:
    (a) leave `risk_gate_enabled=False` (default — no change),
    (b) pre-create + approve a queue row, then pass
        `approved_request_id=<id>`.
  * Example: `tests/test_publisher_risk_gate_wire.py
    ::TestGateEnabledApproved`

### Queue full of stale pending rows

  * `shopai pending-approvals` sweeps expired before showing,
    so normally you don't see them.
  * Manual sweep from Python:
    ```python
    from core.system.approval_queue import get_queue
    get_queue().expire_old()  # returns count expired
    ```
  * Wire this into a daemon cycle if your store has many
    gates per hour.

### Classifier doesn't know my action_type

Unknown `action_type` defaults to MEDIUM. If you want it
explicit, add a row to `core/system/risk_gate._ACTION_RULES`
with a level + the canonical name. Then update
`tests/test_risk_gate.py::TestIntrospection::
test_known_actions_cover_4_levels` (asserts ≥3 per level).

---

## Files

| File | Role |
|---|---|
| `core/system/risk_gate.py` | Classification logic + check_and_enqueue |
| `core/system/approval_queue.py` | SQLite state + on_enqueue hooks |
| `core/system/approval_notifier.py` | Telegram render + fire-and-forget |
| `core/contracts/business_model.py` | BusinessModel + Channel + RiskLevel enums |
| `agents/owner_dialog/tool_dispatcher.py` | Parse "approve <id>" / "deny <id>" |
| `execution/launch/publisher_bundle.py` | Gate wire — ad_campaign_create |
| `execution/launch/campaign_activator.py` | Gate wire — ad_campaign_resume |

Owner can grep any of these for the exact flow. Every non-trivial
decision path has a `# Phase 2c of 4×4 matrix` comment pointing
back to `docs/BUSINESS_MODEL_MATRIX.md`.

---

## What's NOT yet built (Phase 2d+)

  * **Daemon expiry sweep** — `queue.expire_old()` isn't wired
    into the autopilot cycle yet. Stale rows accumulate until
    someone runs `shopai pending-approvals`.
  * **Dashboard panel** — live dashboard (`shopai dashboard
    --live`) doesn't show pending count yet.
  * **Gate on other commits** — discount_create,
    supplier_order_place, email_blast_send still commit
    directly. Each needs a commit-point hook symmetric with
    the publisher/activator wires.
  * **Controller-level default** — if you want the gate on
    for ALL launches without flipping the flag per-request,
    wait for P2d.

None of these block real use today. They're incremental
improvements to make after Deguar produces the first real
order.
