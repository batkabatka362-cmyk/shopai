"""Catalog patcher (Wave 536).

Phase 29's `autonomy-init` generates the 5 module files for a
new domain. Phase 30 mechanically patches 22 simple substrate
catalogs that need a new entry whenever a domain is added.

Three patch shapes, all AST-located + text-edited:

  - `dict_append`: add `"key": value,` to a module-level dict
    Assign/AnnAssign whose value is a Dict literal. New entry
    is inserted on its own line(s) directly before the closing
    brace, mirroring the indentation of the existing entries.

  - `list_append`: add an item to a module-level list Assign
    whose value is a List literal. Same shape as dict.

  - `constant_set`: replace the integer value of a module-level
    `name = N` Assign.

Safety rails:

  - Refuses to patch if the target Assign/AnnAssign is not
    found exactly once.
  - Refuses to patch if the file fails to parse before OR
    after the proposed edit (the patcher re-parses the
    modified source and rolls back on SyntaxError).
  - Dry-run mode returns the would-be modified source as a
    string without writing to disk.
  - Refuses to patch if the new key/literal already appears
    in the file (so reruns are idempotent).

Used by `shopai autonomy-init --patch-catalogs` to atomically
update 22 catalogs after scaffolding a new domain.
"""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PatchResult:
    path: Path
    var_name: str
    success: bool
    reason: str = ""
    dry_run: bool = True


class PatcherError(Exception):
    """Raised when a patcher refuses to apply."""


def _find_target_assign(
    tree: ast.Module, var_name: str,
) -> ast.Assign | ast.AnnAssign | None:
    """Find the single module-level Assign or AnnAssign whose
    target is `var_name`. Returns None if zero matches; raises
    PatcherError if multiple matches."""
    matches: list[ast.Assign | ast.AnnAssign] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if (
                    isinstance(tgt, ast.Name)
                    and tgt.id == var_name
                ):
                    matches.append(node)
                    break
        elif isinstance(node, ast.AnnAssign):
            if (
                isinstance(node.target, ast.Name)
                and node.target.id == var_name
            ):
                matches.append(node)
    if len(matches) > 1:
        raise PatcherError(
            f"target {var_name!r} matched "
            f"{len(matches)}× at module level"
        )
    return matches[0] if matches else None


def _detect_inner_indent(
    lines: list[str], close_line_idx: int,
) -> str:
    """Look at the line just before the closing brace; copy
    its leading whitespace. Falls back to 4 spaces."""
    if close_line_idx > 0:
        prev = lines[close_line_idx - 1]
        stripped = prev.lstrip()
        if stripped:
            return prev[: len(prev) - len(stripped)]
    return "    "


def _verify_reparse(src: str, path: Path) -> None:
    """Reparse modified source; raise PatcherError on failure."""
    try:
        ast.parse(src, filename=str(path))
    except SyntaxError as exc:
        raise PatcherError(
            f"patch produced unparseable file: {exc}"
        )


def patch_dict_append(
    path: Path,
    var_name: str,
    new_entry: str,
    *,
    skip_if_contains: str | None = None,
    dry_run: bool = True,
) -> PatchResult:
    """Append `new_entry` (already-formatted lines, no
    trailing newline) before the closing brace of the named
    dict.

    Args:
        path: target file
        var_name: module-level dict variable name
        new_entry: text to insert. Caller controls indentation
                   + trailing comma. Should NOT end with newline.
        skip_if_contains: if this substring already exists in
                          the file, treat as already-patched
                          (idempotent success).
        dry_run: if True, don't write; just return.
    """
    result = PatchResult(
        path=path, var_name=var_name,
        success=False, dry_run=dry_run,
    )
    try:
        src = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        result.reason = f"read failed: {exc!s:.80}"
        return result

    if skip_if_contains and skip_if_contains in src:
        result.success = True
        result.reason = "already patched (idempotent)"
        return result

    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as exc:
        result.reason = f"parse failed: {exc!s:.80}"
        return result

    try:
        target = _find_target_assign(tree, var_name)
    except PatcherError as exc:
        result.reason = str(exc)
        return result

    if target is None:
        result.reason = f"target {var_name!r} not found"
        return result

    value = target.value
    if not isinstance(value, ast.Dict):
        result.reason = (
            f"target {var_name!r} is not a Dict literal "
            f"(got {type(value).__name__})"
        )
        return result

    # End line is 1-indexed; the closing brace lives on that line.
    end_line = value.end_lineno
    if end_line is None:
        result.reason = "AST missing end_lineno"
        return result

    lines = src.splitlines(keepends=True)
    close_idx = end_line - 1  # 0-indexed
    indent = _detect_inner_indent(lines, close_idx)
    insertion = "\n".join(
        indent + ln for ln in new_entry.splitlines()
    ) + "\n"

    new_lines = (
        lines[:close_idx] + [insertion] + lines[close_idx:]
    )
    new_src = "".join(new_lines)

    try:
        _verify_reparse(new_src, path)
    except PatcherError as exc:
        result.reason = str(exc)
        return result

    if not dry_run:
        path.write_text(new_src, encoding="utf-8")

    result.success = True
    return result


def patch_list_append(
    path: Path,
    var_name: str,
    new_entry: str,
    *,
    skip_if_contains: str | None = None,
    dry_run: bool = True,
) -> PatchResult:
    """Same as patch_dict_append but for List literals."""
    result = PatchResult(
        path=path, var_name=var_name,
        success=False, dry_run=dry_run,
    )
    try:
        src = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        result.reason = f"read failed: {exc!s:.80}"
        return result

    if skip_if_contains and skip_if_contains in src:
        result.success = True
        result.reason = "already patched (idempotent)"
        return result

    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as exc:
        result.reason = f"parse failed: {exc!s:.80}"
        return result

    try:
        target = _find_target_assign(tree, var_name)
    except PatcherError as exc:
        result.reason = str(exc)
        return result

    if target is None:
        result.reason = f"target {var_name!r} not found"
        return result

    value = target.value
    if not isinstance(value, ast.List):
        result.reason = (
            f"target {var_name!r} is not a List literal "
            f"(got {type(value).__name__})"
        )
        return result

    end_line = value.end_lineno
    if end_line is None:
        result.reason = "AST missing end_lineno"
        return result

    lines = src.splitlines(keepends=True)
    close_idx = end_line - 1
    indent = _detect_inner_indent(lines, close_idx)
    insertion = "\n".join(
        indent + ln for ln in new_entry.splitlines()
    ) + "\n"

    new_lines = (
        lines[:close_idx] + [insertion] + lines[close_idx:]
    )
    new_src = "".join(new_lines)

    try:
        _verify_reparse(new_src, path)
    except PatcherError as exc:
        result.reason = str(exc)
        return result

    if not dry_run:
        path.write_text(new_src, encoding="utf-8")

    result.success = True
    return result


def patch_constant_set(
    path: Path,
    var_name: str,
    new_value: int,
    *,
    dry_run: bool = True,
) -> PatchResult:
    """Replace the integer value of a module-level
    `var_name = N` assignment. Idempotent: if the value is
    already `new_value`, returns success without writing."""
    result = PatchResult(
        path=path, var_name=var_name,
        success=False, dry_run=dry_run,
    )
    try:
        src = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        result.reason = f"read failed: {exc!s:.80}"
        return result

    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as exc:
        result.reason = f"parse failed: {exc!s:.80}"
        return result

    try:
        target = _find_target_assign(tree, var_name)
    except PatcherError as exc:
        result.reason = str(exc)
        return result

    if target is None:
        result.reason = f"target {var_name!r} not found"
        return result

    value_node = target.value
    if not (
        isinstance(value_node, ast.Constant)
        and isinstance(value_node.value, int)
    ):
        result.reason = (
            f"target {var_name!r} is not an int Constant "
            f"(got {type(value_node).__name__})"
        )
        return result

    current = value_node.value
    if current == new_value:
        result.success = True
        result.reason = (
            f"already {new_value} (idempotent)"
        )
        return result

    # Replace the literal int on its line.
    start_line = value_node.lineno - 1
    end_line = value_node.end_lineno - 1
    if start_line != end_line:
        result.reason = (
            "int literal spans multiple lines (unexpected)"
        )
        return result

    lines = src.splitlines(keepends=True)
    line = lines[start_line]
    # value_node.col_offset / end_col_offset are valid
    # for single-line int Constants
    start_col = value_node.col_offset
    end_col = value_node.end_col_offset
    if (
        start_col is None
        or end_col is None
        or end_col <= start_col
    ):
        result.reason = "AST missing col_offset"
        return result
    new_line = (
        line[:start_col] + str(new_value) + line[end_col:]
    )
    lines[start_line] = new_line
    new_src = "".join(lines)

    try:
        _verify_reparse(new_src, path)
    except PatcherError as exc:
        result.reason = str(exc)
        return result

    if not dry_run:
        path.write_text(new_src, encoding="utf-8")

    result.success = True
    return result


def patch_set_add(
    path: Path,
    var_name: str,
    new_member: str,
    *,
    skip_if_contains: str | None = None,
    dry_run: bool = True,
) -> PatchResult:
    """Append `new_member` text before the closing brace of a
    module-level frozenset({...}) or set literal assignment.
    Used for Pattern O's _EXEMPT_WRITERS frozenset.

    Note: AST treats frozenset({...}) as a Call whose first
    arg is a Set literal -- we patch the Set literal's closing
    brace.
    """
    result = PatchResult(
        path=path, var_name=var_name,
        success=False, dry_run=dry_run,
    )
    try:
        src = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        result.reason = f"read failed: {exc!s:.80}"
        return result

    if skip_if_contains and skip_if_contains in src:
        result.success = True
        result.reason = "already patched (idempotent)"
        return result

    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as exc:
        result.reason = f"parse failed: {exc!s:.80}"
        return result

    try:
        target = _find_target_assign(tree, var_name)
    except PatcherError as exc:
        result.reason = str(exc)
        return result

    if target is None:
        result.reason = f"target {var_name!r} not found"
        return result

    value_node = target.value
    set_node: ast.Set | None = None
    if isinstance(value_node, ast.Set):
        set_node = value_node
    elif (
        isinstance(value_node, ast.Call)
        and isinstance(value_node.func, ast.Name)
        and value_node.func.id == "frozenset"
        and value_node.args
        and isinstance(value_node.args[0], ast.Set)
    ):
        set_node = value_node.args[0]

    if set_node is None:
        result.reason = (
            f"target {var_name!r} is not a Set or frozenset "
            f"of a Set literal (got "
            f"{type(value_node).__name__})"
        )
        return result

    end_line = set_node.end_lineno
    if end_line is None:
        result.reason = "AST missing end_lineno"
        return result

    lines = src.splitlines(keepends=True)
    close_idx = end_line - 1
    indent = _detect_inner_indent(lines, close_idx)
    insertion = "\n".join(
        indent + ln for ln in new_member.splitlines()
    ) + "\n"

    new_lines = (
        lines[:close_idx] + [insertion] + lines[close_idx:]
    )
    new_src = "".join(new_lines)

    try:
        _verify_reparse(new_src, path)
    except PatcherError as exc:
        result.reason = str(exc)
        return result

    if not dry_run:
        path.write_text(new_src, encoding="utf-8")

    result.success = True
    return result
