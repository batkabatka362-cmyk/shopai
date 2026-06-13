"""Pattern S audit: autonomy CLI --json flag consistency (W181).

Every autonomy domain ships a 4-command CLI suite:
``{domain}-status / -health / -pause / -resume``. Operators
and downstream automation rely on every one of these
accepting ``--json`` for machine-readable output. Pattern S
prevents drift -- a future CLI surface that forgets the flag
breaks JSON pipelines without anybody noticing.

Implementation: parse cli.py with argparse introspection. For
each registered subparser matching one of the autonomy suffix
patterns, walk its actions and verify a `--json` long-flag
exists.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# Autonomy CLI command name suffixes
_AUTONOMY_SUFFIXES: tuple[str, ...] = (
    "-status",
    "-health",
    "-pause",
    "-resume",
)

# Autonomy command name prefixes (curated -- we only audit
# commands actually owned by the autonomy domains; avoids
# false positives like 'health' or 'cycle-status')
_AUTONOMY_PREFIXES: tuple[str, ...] = (
    "refund",
    "marketing",
    "fulfillment",
    "inventory",
    "discount-cleanup",
    "order-followup",
    "support",   # support-status is Wave 105
    "autonomy",  # autonomy-status is Wave 149
)


@dataclass
class PatternSViolation:
    command: str
    reason: str = ""


@dataclass
class PatternSReport:
    commands_scanned: list[str] = field(default_factory=list)
    clean_commands: list[str] = field(default_factory=list)
    violations: list[PatternSViolation] = field(default_factory=list)

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


def _is_autonomy_command(name: str) -> bool:
    """Match name against the curated prefix + suffix
    taxonomy. e.g. 'refund-status' / 'order-followup-pause'.
    """
    if not any(name.endswith(suf) for suf in _AUTONOMY_SUFFIXES):
        return False
    # Strip the suffix + check the remainder is a known
    # autonomy prefix
    for suf in _AUTONOMY_SUFFIXES:
        if name.endswith(suf):
            prefix = name[: -len(suf)]
            if prefix in _AUTONOMY_PREFIXES:
                return True
            # Some commands like 'autonomy-status' have just
            # the prefix
            if prefix.startswith(tuple(_AUTONOMY_PREFIXES)):
                return True
    return False


def _subparser_has_json_action(action: Any) -> bool:
    """Inspect a subparser's actions list for a --json
    long-flag."""
    try:
        actions = action._actions  # argparse internal
    except AttributeError:
        return False
    for sub_action in actions:
        option_strings = getattr(
            sub_action, "option_strings", [],
        )
        if "--json" in option_strings:
            return True
    return False


def run_pattern_s_audit() -> PatternSReport:
    """Probe every autonomy CLI command for --json support."""
    report = PatternSReport()
    try:
        from cli import build_parser
    except Exception as exc:  # noqa: BLE001
        logger.debug("Pattern S import build_parser: %s", exc)
        return report
    try:
        parser = build_parser()
    except Exception as exc:  # noqa: BLE001
        report.violations.append(PatternSViolation(
            command="<parser_init>",
            reason=f"_build_parser raised: {exc}",
        ))
        return report

    # The parser's subparsers live in its _subparsers_action.
    # argparse stores them in ._actions; find the subparsers
    # action then iterate its choices dict.
    subparsers_action = None
    for act in parser._actions:
        if hasattr(act, "choices") and isinstance(
            act.choices, dict,
        ):
            subparsers_action = act
            break
    if subparsers_action is None:
        return report

    for cmd_name, subparser in (
        subparsers_action.choices.items()
    ):
        if not _is_autonomy_command(cmd_name):
            continue
        report.commands_scanned.append(cmd_name)
        if _subparser_has_json_action(subparser):
            report.clean_commands.append(cmd_name)
        else:
            report.violations.append(PatternSViolation(
                command=cmd_name,
                reason="missing --json flag",
            ))
    return report
