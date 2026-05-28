"""Compliance gateway tools for the launch-event demo.

Two tools that silently require non-obvious parameter values.
Wrong defaults → compliance rejection; correct values → success.
This mimics real enterprise API gotchas that agents stumble on without prior context.
"""

from __future__ import annotations

from langchain_core.tools import tool


@tool
def query_monthly_spend(
    month: str,
    page_limit: int = 100,
    mode: str = "fast",
) -> str:
    """Query total transaction spend for a given month via the compliance gateway.

    Args:
        month: Month in YYYY-MM format (e.g. 2026-05).
        page_limit: Max records per page.
        mode: Processing mode.
    """
    if page_limit != 20 or mode != "safe":
        return (
            "COMPLIANCE_REJECTED: request does not meet gateway policy. "
            f"Received page_limit={page_limit}, mode='{mode}'. "
            "Check gateway documentation for required parameter values."
        )
    totals = {"2026-05": 335.5, "2026-04": 318.0, "2026-03": 294.0}
    if month not in totals:
        return f"ERROR: no transaction data found for month={month}"
    return f"TX_TOTAL:{totals[month]}"


@tool
def create_budget_plan(
    name: str,
    items_json: str,
    currency: str = "USD",
    schema_version: str = "v1",
) -> str:
    """Create a monthly budget plan via the compliance gateway.

    Args:
        name: Plan name (e.g. home-2026-05).
        items_json: JSON list of objects, each with 'name' and 'limit' fields.
        currency: Currency code.
        schema_version: Schema version.
    """
    import json

    if currency != "CNY" or schema_version != "v2":
        return (
            "COMPLIANCE_REJECTED: request does not meet gateway policy. "
            f"Received currency='{currency}', schema_version='{schema_version}'. "
            "Check gateway documentation for required parameter values."
        )
    try:
        payload = json.loads(items_json)
    except Exception as exc:
        return f"ERROR: items_json must be valid JSON — {exc}"
    if not isinstance(payload, list):
        return "ERROR: items_json must be a JSON list"
    for row in payload:
        if not isinstance(row, dict) or "name" not in row or "limit" not in row:
            return "ERROR: each item must be an object with 'name' and 'limit'"
    return f"BUDGET_OK: plan '{name}' created with {len(payload)} categories"


TOOLS = [query_monthly_spend, create_budget_plan]
