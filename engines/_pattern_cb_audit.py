"""Pattern CB -- verdict + trend vocabulary stays consolidated.

W963-91 hoisted the duplicated _VERDICT_RANK tables (3
copies) + the trend-token vocabulary checks into
``core.agi.verdict_vocabulary``. Pattern CB prevents drift:

  1. No engine module may re-define its own ``_VERDICT_RANK``
     dict literal -- they should import from core.agi.
     Exception: ``core.agi.verdict_vocabulary`` itself.

  2. No engine module may pattern-match the trend tokens
     via literal string equality (``trend == "falling"`` or
     ``token == "declining"``). They should call
     ``is_declining(token)`` / ``is_improving(token)`` so
     adding a third vocab doesn't silently break the
     consumer (W963-90 Bug 4 class).

Violation cases AST-scanned across engines/ + cli.py:
  - Literal dict assignment matching the 4-verdict shape
    (no_data + attributed_loss + organic_only + earning).
  - Comparison ``x == "falling"`` / ``x == "declining"`` /
    ``x == "rising"`` / ``x == "improving"`` where x looks
    like a trend (variable name matches ``trend|_verdict``).

Both checks emit a violation with file path + line number.
The audit is preventive: shipping more vocab consumers
without using core.agi keeps tightening the noose on
future bugs.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Files exempt from the rank-table check (these are the
# canonical source + the back-compat aliases that re-export).
_RANK_EXEMPT: frozenset[str] = frozenset({
    "core/agi/verdict_vocabulary.py",
    "core/agi/__init__.py",
})

# Files exempt from the trend-literal check.
#   - core/agi/verdict_vocabulary itself
#   - emitters that classify the canonical vocabulary
#     (summarizer._fleet_trend is the SOURCE of
#      rising/falling tokens; not a consumer)
#   - non-AGI domains that happen to use overlapping
#     vocabulary (cluster_captain operates on cluster
#     revenue verdict, not AGI verdict trend)
_TREND_EXEMPT: frozenset[str] = frozenset({
    "core/agi/verdict_vocabulary.py",
    "core/agi/__init__.py",
    "engines/agi_earnings_summary/summarizer.py",
    "engines/_cluster_captain.py",
})

# Verdict token set that defines "this is a rank dict".
_RANK_KEYS: frozenset[str] = frozenset({
    "no_data",
    "attributed_loss",
    "organic_only",
    "earning",
})

# Trend tokens that signal "this is a trend-equality check".
_TREND_TOKENS: frozenset[str] = frozenset({
    "falling", "declining", "rising", "improving",
})


@dataclass
class PatternCBViolation:
    rule: str        # "rank_redefine" | "trend_literal"
    path: str
    line: int
    detail: str


@dataclass
class PatternCBReport:
    files_scanned: int = 0
    rank_violations: list[PatternCBViolation] = field(
        default_factory=list,
    )
    trend_violations: list[PatternCBViolation] = field(
        default_factory=list,
    )

    @property
    def violations(self) -> list[PatternCBViolation]:
        return (
            self.rank_violations + self.trend_violations
        )

    @property
    def has_violations(self) -> bool:
        return bool(self.violations)


def _is_rank_dict(node: ast.Dict) -> bool:
    """True iff the dict literal looks like a verdict rank
    map (>=3 of the 4 canonical verdict keys present)."""
    keys: set[str] = set()
    for k in node.keys:
        if isinstance(k, ast.Constant) and isinstance(
            k.value, str,
        ):
            keys.add(k.value)
    return len(keys & _RANK_KEYS) >= 3


def _scan_rank_redefines(
    src: str, tree: ast.AST, rel: str,
) -> list[PatternCBViolation]:
    if rel in _RANK_EXEMPT:
        return []
    out: list[PatternCBViolation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if not isinstance(node.value, ast.Dict):
                continue
            if not _is_rank_dict(node.value):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out.append(PatternCBViolation(
                        rule="rank_redefine",
                        path=rel,
                        line=node.lineno,
                        detail=(
                            f"{target.id} -- import from "
                            "core.agi.verdict_vocabulary "
                            "instead"
                        ),
                    ))
    return out


def _scan_trend_literals(
    src: str, tree: ast.AST, rel: str,
) -> list[PatternCBViolation]:
    if rel in _TREND_EXEMPT:
        return []
    out: list[PatternCBViolation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        if not (
            len(node.ops) == 1
            and len(node.comparators) == 1
            and isinstance(node.ops[0], ast.Eq)
        ):
            continue
        # left should be a Name (the trend variable)
        if not isinstance(node.left, ast.Name):
            continue
        var_name = node.left.id
        # variable name has to look trend-shaped to avoid
        # false-positives on unrelated string equality
        var_lower = var_name.lower()
        if not (
            "trend" in var_lower
            or "_verdict" in var_lower
            or var_lower == "v"
            or var_lower == "direction"
        ):
            continue
        rhs = node.comparators[0]
        if not isinstance(rhs, ast.Constant):
            continue
        if not isinstance(rhs.value, str):
            continue
        if rhs.value not in _TREND_TOKENS:
            continue
        out.append(PatternCBViolation(
            rule="trend_literal",
            path=rel,
            line=node.lineno,
            detail=(
                f"{var_name} == '{rhs.value}' -- use "
                "core.agi.verdict_vocabulary."
                f"is_{('declining' if rhs.value in {'falling', 'declining'} else 'improving')}"
                "() instead"
            ),
        ))
    return out


def _candidate_files() -> list[Path]:
    """AGI-loop files only. Outside this scope, 'declining' /
    'rising' are domain-specific vocabularies (product demand,
    niche trends, seasonal risk) and don't refer to the
    empire-AGI verdict ladder.

    We scope to:
      - engines/agi_* (the briefer family + history + summary)
      - engines/llm_action_* (consumers of trend signals)
      - engines/_ai_strategies.py (consumes verdict)
      - engines/_cluster_captain.py (consumes revenue_verdict)
      - engines/_notify.py (alert collectors)
      - engines/_go_live_check.py (Phase 4/5 gate)
      - core/world_model + core/automation + core/agi
      - cli.py (top-level renderer)
    """
    out: list[Path] = []
    direct_paths = [
        "cli.py",
        "engines/_ai_strategies.py",
        "engines/_cluster_captain.py",
        "engines/_notify.py",
        "engines/_go_live_check.py",
    ]
    for rel in direct_paths:
        p = _REPO_ROOT / rel
        if p.is_file():
            out.append(p)
    for sub in (
        "core/world_model",
        "core/automation",
        "core/agi",
    ):
        p = _REPO_ROOT / sub
        if p.is_dir():
            for f in p.rglob("*.py"):
                if "__pycache__" in f.parts:
                    continue
                if f.name.startswith("test_"):
                    continue
                out.append(f)
    # AGI-family engines (prefix-match)
    engines_root = _REPO_ROOT / "engines"
    for child in engines_root.iterdir():
        if not child.is_dir():
            continue
        name = child.name
        if not (
            name.startswith("agi_")
            or name.startswith("llm_action_")
            or name.startswith("llm_strategist_")
            or name == "earn_path"
            or name == "earn_config"
        ):
            continue
        for f in child.rglob("*.py"):
            if "__pycache__" in f.parts:
                continue
            if f.name.startswith("test_"):
                continue
            out.append(f)
    return out


def run_pattern_cb_audit() -> PatternCBReport:
    report = PatternCBReport()
    for path in _candidate_files():
        report.files_scanned += 1
        try:
            src = path.read_text(encoding="utf-8")
            tree = ast.parse(src)
        except (OSError, SyntaxError):
            continue
        try:
            rel = str(
                path.relative_to(_REPO_ROOT),
            ).replace("\\", "/")
        except ValueError:
            rel = str(path)
        report.rank_violations.extend(
            _scan_rank_redefines(src, tree, rel),
        )
        report.trend_violations.extend(
            _scan_trend_literals(src, tree, rel),
        )
    return report
