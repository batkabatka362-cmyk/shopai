"""DataTransformer — reshapes, renames, flattens, and derives fields."""
from __future__ import annotations

import logging
import operator
import re
from typing import Any

logger = logging.getLogger("data_pipeline.transformer")


class DataTransformer:
    """Transforms data records via a declarative transformation list.

    Each transformation in the list passed to :meth:`transform` is a dict::

        {"op": "rename",   "field_map": {"old": "new"}}
        {"op": "flatten",  "separator": "_"}
        {"op": "derive",   "field": "margin_pct",
                           "expression": "price - cost"}
        {"op": "drop",     "fields": ["internal_id", "raw_html"]}
        {"op": "keep",     "fields": ["id", "title", "price"]}
    """

    # ------------------------------------------------------------------
    # Primary entry point
    # ------------------------------------------------------------------

    def transform(
        self,
        data: list[dict[str, Any]],
        transformations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Apply a list of *transformations* to every record in *data*.

        Args:
            data:            Input records.
            transformations: Ordered list of transformation descriptors.

        Returns:
            Transformed records as a new list.
        """
        result = [dict(r) for r in data]
        for tdef in transformations:
            op = tdef.get("op", "")
            if op == "rename":
                result = [self.rename_fields(r, tdef.get("field_map", {})) for r in result]
            elif op == "flatten":
                result = [self.flatten(r, tdef.get("separator", "_")) for r in result]
            elif op == "derive":
                field = tdef.get("field", "")
                expr = tdef.get("expression", "")
                result = [self.compute_derived_field(r, field, expr) for r in result]
            elif op == "drop":
                drop_fields: list[str] = tdef.get("fields", [])
                result = [
                    {k: v for k, v in r.items() if k not in drop_fields}
                    for r in result
                ]
            elif op == "keep":
                keep_fields: list[str] = tdef.get("fields", [])
                result = [
                    {k: r[k] for k in keep_fields if k in r}
                    for r in result
                ]
            else:
                logger.warning("Unknown transformation op: '%s'; skipping", op)

        logger.info(
            "transform: applied %d ops to %d records",
            len(transformations),
            len(result),
        )
        return result

    # ------------------------------------------------------------------
    # Structural operations
    # ------------------------------------------------------------------

    def flatten(
        self,
        data: dict[str, Any],
        separator: str = "_",
    ) -> dict[str, Any]:
        """Recursively flatten a nested dict using *separator*.

        Example::

            {"a": {"b": 1, "c": {"d": 2}}}
            → {"a_b": 1, "a_c_d": 2}

        Args:
            data:      A (possibly nested) dict.
            separator: Key separator (default ``"_"``).

        Returns:
            Flat dict with no nested dicts.
        """
        return self._flatten_recursive(data, parent_key="", separator=separator)

    @staticmethod
    def _flatten_recursive(
        obj: Any,
        parent_key: str,
        separator: str,
    ) -> dict[str, Any]:
        items: dict[str, Any] = {}
        if isinstance(obj, dict):
            for k, v in obj.items():
                new_key = f"{parent_key}{separator}{k}" if parent_key else k
                if isinstance(v, dict):
                    items.update(
                        DataTransformer._flatten_recursive(v, new_key, separator)
                    )
                else:
                    items[new_key] = v
        else:
            items[parent_key] = obj
        return items

    @staticmethod
    def rename_fields(
        record: dict[str, Any],
        field_map: dict[str, str],
    ) -> dict[str, Any]:
        """Return a copy of *record* with keys renamed according to *field_map*.

        Keys absent from *field_map* are kept unchanged.

        Args:
            record:    Input record.
            field_map: ``{"old_name": "new_name"}`` mapping.

        Returns:
            New record dict with renamed keys.
        """
        return {field_map.get(k, k): v for k, v in record.items()}

    @staticmethod
    def compute_derived_field(
        record: dict[str, Any],
        field_name: str,
        expression: str,
    ) -> dict[str, Any]:
        """Compute a new field by evaluating *expression* against *record* values.

        Expression syntax supports:
        * Field name references (must match record keys exactly).
        * Arithmetic operators: ``+  -  *  /  **  %``.
        * Integer and float literals.
        * Parentheses for grouping.

        The result is added to the record as *field_name*.  If evaluation fails
        the field is set to ``None`` and a warning is logged.

        Args:
            record:     Input record.
            field_name: Name of the new derived field.
            expression: Arithmetic expression string.

        Returns:
            New record dict with *field_name* added (or updated).

        Example::

            record     = {"price": 10.0, "cost": 6.0}
            expression = "price - cost"
            → adds "margin": 4.0
        """
        new_rec = dict(record)
        try:
            new_rec[field_name] = _eval_expression(expression, record)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "compute_derived_field '%s' expression='%s' failed: %s",
                field_name,
                expression,
                exc,
            )
            new_rec[field_name] = None
        return new_rec

    def pivot(
        self,
        data: list[dict[str, Any]],
        key_field: str,
        value_field: str,
    ) -> dict[str, Any]:
        """Pivot *data* from a list of records into a mapping.

        Each record's *key_field* becomes a key in the output dict, and the
        corresponding *value_field* becomes the value.  When multiple records
        share the same key the values are collected into a list.

        Args:
            data:        Input records.
            key_field:   Field whose value becomes the output key.
            value_field: Field whose value becomes the output value.

        Returns:
            ``{key: value}`` dict (or ``{key: [values]}`` for duplicates).

        Example::

            data = [
                {"date": "2024-01", "revenue": 1000},
                {"date": "2024-02", "revenue": 1200},
            ]
            pivot(data, "date", "revenue")
            → {"2024-01": 1000, "2024-02": 1200}
        """
        result: dict[str, Any] = {}
        for record in data:
            key = record.get(key_field)
            val = record.get(value_field)
            if key is None:
                continue
            if key in result:
                existing = result[key]
                if isinstance(existing, list):
                    existing.append(val)
                else:
                    result[key] = [existing, val]
            else:
                result[key] = val
        return result


# ---------------------------------------------------------------------------
# Safe expression evaluator (arithmetic only, no builtins/exec)
# ---------------------------------------------------------------------------

_ALLOWED_OPS = {
    "+": operator.add,
    "-": operator.sub,
    "*": operator.mul,
    "/": operator.truediv,
    "**": operator.pow,
    "%": operator.mod,
}

# Tokeniser: numbers, identifiers, operators, parens
_TOKEN_RE = re.compile(
    r"(?P<float>\d+\.\d+)"
    r"|(?P<int>\d+)"
    r"|(?P<op>\*\*|[+\-*/%])"
    r"|(?P<lparen>\()"
    r"|(?P<rparen>\))"
    r"|(?P<ident>[A-Za-z_][A-Za-z0-9_]*)"
    r"|\s+"
)


def _tokenise(expr: str) -> list[tuple[str, Any]]:
    tokens: list[tuple[str, Any]] = []
    pos = 0
    while pos < len(expr):
        m = _TOKEN_RE.match(expr, pos)
        if not m:
            raise ValueError(f"Unexpected character at position {pos}: '{expr[pos]}'")
        pos = m.end()
        if m.lastgroup == "float":
            tokens.append(("NUM", float(m.group())))
        elif m.lastgroup == "int":
            tokens.append(("NUM", int(m.group())))
        elif m.lastgroup == "op":
            tokens.append(("OP", m.group()))
        elif m.lastgroup == "lparen":
            tokens.append(("LPAREN", "("))
        elif m.lastgroup == "rparen":
            tokens.append(("RPAREN", ")"))
        elif m.lastgroup == "ident":
            tokens.append(("IDENT", m.group()))
        # whitespace: skip
    return tokens


class _Parser:
    """Recursive-descent parser for arithmetic expressions."""

    def __init__(self, tokens: list[tuple[str, Any]], record: dict[str, Any]) -> None:
        self._tokens = tokens
        self._pos = 0
        self._record = record

    def _peek(self) -> tuple[str, Any] | None:
        if self._pos < len(self._tokens):
            return self._tokens[self._pos]
        return None

    def _consume(self) -> tuple[str, Any]:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def parse(self) -> float:
        result = self._expr()
        if self._pos != len(self._tokens):
            raise ValueError("Unexpected tokens at end of expression")
        return result

    def _expr(self) -> float:
        """Addition / subtraction level."""
        left = self._term()
        while True:
            tok = self._peek()
            if tok and tok[0] == "OP" and tok[1] in ("+", "-"):
                self._consume()
                right = self._term()
                left = _ALLOWED_OPS[tok[1]](left, right)
            else:
                break
        return left

    def _term(self) -> float:
        """Multiplication / division / modulo level."""
        left = self._power()
        while True:
            tok = self._peek()
            if tok and tok[0] == "OP" and tok[1] in ("*", "/", "%"):
                self._consume()
                right = self._power()
                left = _ALLOWED_OPS[tok[1]](left, right)
            else:
                break
        return left

    def _power(self) -> float:
        """Exponentiation (right-associative)."""
        base = self._unary()
        tok = self._peek()
        if tok and tok[0] == "OP" and tok[1] == "**":
            self._consume()
            exp = self._power()
            return _ALLOWED_OPS["**"](base, exp)
        return base

    def _unary(self) -> float:
        """Unary negation."""
        tok = self._peek()
        if tok and tok[0] == "OP" and tok[1] == "-":
            self._consume()
            return -self._primary()
        return self._primary()

    def _primary(self) -> float:
        tok = self._consume()
        kind, val = tok
        if kind == "NUM":
            return float(val)
        if kind == "IDENT":
            field_val = self._record.get(val)
            if field_val is None:
                raise ValueError(f"Unknown field '{val}' in expression")
            return float(field_val)
        if kind == "LPAREN":
            inner = self._expr()
            close = self._consume()
            if close[0] != "RPAREN":
                raise ValueError("Missing closing parenthesis")
            return inner
        raise ValueError(f"Unexpected token: {tok}")


def _eval_expression(expression: str, record: dict[str, Any]) -> float:
    """Safely evaluate an arithmetic *expression* using values from *record*."""
    tokens = _tokenise(expression)
    return _Parser(tokens, record).parse()
