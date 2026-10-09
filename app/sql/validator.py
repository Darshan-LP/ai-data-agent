
"""
SQL safety layer.

Accepts only safe, single-statement SELECT queries against the
approved business tables. Adds or clamps LIMIT to MAX_ROWS.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError


ALLOWED_TABLES: set[str] = {
    "customers",
    "products",
    "orders",
    "order_items",
}

FORBIDDEN_EXPRESSIONS: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Alter,
    exp.Create,
    exp.TruncateTable,
    exp.Copy,
    exp.Grant,
    exp.Command,
)

FORBIDDEN_FUNCTIONS: set[str] = {
    "pg_sleep",
    "pg_read_file",
    "pg_read_binary_file",
    "pg_ls_dir",
    "pg_stat_file",
    "pg_terminate_backend",
    "pg_cancel_backend",
    "lo_import",
    "lo_export",
    "dblink",
    "dblink_exec",
    "current_setting",
    "set_config",
}

FORBIDDEN_SCHEMAS: set[str] = {
    "pg_catalog",
    "information_schema",
    "pg_toast",
}

MAX_ROWS = 1000


@dataclass
class ValidationResult:
    ok: bool
    reason: Optional[str]
    rewritten_sql: Optional[str]

    @classmethod
    def reject(cls, reason: str) -> "ValidationResult":
        return cls(ok=False, reason=reason, rewritten_sql=None)

    @classmethod
    def accept(cls, sql: str) -> "ValidationResult":
        return cls(ok=True, reason=None, rewritten_sql=sql)


def validate(sql: str) -> ValidationResult:
    """Validate a SQL query and return its safe, rewritten form."""

    # 1. Reject empty input.
    if not sql or not sql.strip():
        return ValidationResult.reject("Empty SQL.")

    # 2. Parse the input as PostgreSQL SQL.
    try:
        statements = sqlglot.parse(sql, read="postgres")
    except ParseError as exc:
        return ValidationResult.reject(f"Parse error: {exc}")

    # 3. Require exactly one statement.
    if len(statements) != 1:
        return ValidationResult.reject(
            f"Expected exactly 1 statement, got {len(statements)}."
        )

    tree = statements[0]

    if tree is None:
        return ValidationResult.reject("Empty statement after parse.")

    # 4. Only SELECT statements are allowed.
    if not isinstance(tree, exp.Select):
        return ValidationResult.reject(
            f"Only SELECT is allowed, got {type(tree).__name__}."
        )

    # 5. Inspect the entire syntax tree for forbidden expressions.
    for node in tree.walk():
        if isinstance(node, FORBIDDEN_EXPRESSIONS):
            return ValidationResult.reject(
                f"Forbidden expression: {type(node).__name__}."
            )

    # 6. Reject dangerous function calls.
    for func in tree.find_all(exp.Func):
        name = _func_name(func)

        if name and name.lower() in FORBIDDEN_FUNCTIONS:
            return ValidationResult.reject(
                f"Forbidden function: {name}."
            )

        # 6. Table allowlist + 7. schema check.
    # CTE names (such as "monthly") are query-local aliases,
    # not physical database tables.
    cte_names = {
        cte.alias_or_name.lower()
        for cte in tree.find_all(exp.CTE)
        if cte.alias_or_name
    }

    for table in tree.find_all(exp.Table):
        db = (table.db or "").lower()
        name = (table.name or "").lower()

        if db and db in FORBIDDEN_SCHEMAS:
            return ValidationResult.reject(f"Forbidden schema: {db}.")

        if db and db != "public":
            return ValidationResult.reject(
                f"Only 'public' schema is allowed, got '{db}'."
            )

        # Skip allowlist checking only for unqualified CTE references.
        if not db and not table.catalog and name in cte_names:
            continue

        if name not in ALLOWED_TABLES:
            return ValidationResult.reject(
                f"Table not allowed: '{name}'. "
                f"Allowed: {sorted(ALLOWED_TABLES)}."
            )

    # 8. Enforce the maximum row limit.
    rewritten = _enforce_limit(tree)

    return ValidationResult.accept(rewritten)


def _func_name(func: exp.Func) -> Optional[str]:
    """Get a normalized name for a SQL function expression."""

    if isinstance(func, exp.Anonymous):
        return func.name if isinstance(func.name, str) else None

    if hasattr(func, "sql_name"):
        return func.sql_name()

    return None


def _enforce_limit(tree: exp.Select) -> str:
    """Add LIMIT 1000 if missing, or clamp larger limits to 1000."""

    limit = tree.args.get("limit")

    if limit is None:
        tree = tree.limit(MAX_ROWS)
        return tree.sql(dialect="postgres")

    expr = limit.expression

    if isinstance(expr, exp.Literal) and expr.is_int:
        try:
            current = int(expr.this)
        except (TypeError, ValueError):
            current = None

        if current is None or current > MAX_ROWS:
            tree.set(
                "limit",
                exp.Limit(expression=exp.Literal.number(MAX_ROWS)),
            )
    else:
        # Parameterized or non-literal limits are replaced with a safe cap.
        tree.set(
            "limit",
            exp.Limit(expression=exp.Literal.number(MAX_ROWS)),
        )

    return tree.sql(dialect="postgres")