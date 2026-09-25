"""Loyalty-discount tool.

The arithmetic lives in ``CALC_SOURCE``, a self-contained block of Python. The same text is

* executed inside the AgentCore Code Interpreter sandbox in production, and
* executed locally by the tests and by the tier-only fallback's parity checks,

so the sandboxed calculation and the tested calculation cannot drift apart. Money uses ``Decimal``.
"""

from __future__ import annotations

import json
from typing import Any

from bedrock_agentcore.tools.code_interpreter_client import code_session
from strands import tool

from support_agent import logger
from support_agent.config import Settings

# Programme rules (also documented in data/catalog.md, which the knowledge base serves).
RULES: dict[str, Any] = {
    "points_per_dollar": 50,  # 50 points are worth $1
    "redemption_block": 250,  # points redeem in multiples of 250
    "max_redeem_share": "0.40",  # points may cover at most 40 % of the order
    "tier_discount": {"Silver": "0.00", "Gold": "0.08", "Platinum": "0.12"},
    "earn_rate": {"standard": 1, "gadget": 3, "grocery": 4},  # points earned per $ paid
}

CALC_SOURCE = """
def compute_discount(points, tier, order_total, category, rules):
    from decimal import Decimal, ROUND_HALF_UP

    def money(x):
        return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    order = Decimal(str(order_total))
    tier_name = str(tier).strip().title()
    rate = Decimal(rules["tier_discount"].get(tier_name, "0"))
    per_dollar = rules["points_per_dollar"]
    block = rules["redemption_block"]

    # Points may cover at most `max_redeem_share` of the order, and redeem in whole blocks.
    cap_points = int(order * Decimal(rules["max_redeem_share"]) * per_dollar)
    redeemed = (max(0, min(int(points), cap_points)) // block) * block
    points_value = Decimal(redeemed) / per_dollar

    subtotal = order - points_value                    # tier discount applies after points
    tier_discount = money(subtotal * rate)
    final_total = money(subtotal - tier_discount)
    earn = rules["earn_rate"].get(str(category).strip().lower(), 1)

    return {
        "tier": tier_name,
        "tier_discount_pct": float(rate * 100),
        "order_total": float(order),
        "points_redeemed": redeemed,
        "points_discount": float(points_value),
        "subtotal_after_points": float(subtotal),
        "tier_discount": float(tier_discount),
        "final_total": float(final_total),
        "total_savings": float(money(points_value + tier_discount)),
        "points_earned": int(final_total * earn),
        "remaining_points": int(points) - redeemed,
    }
"""


def compute_locally(points: int, tier: str, order_total: float, category: str = "standard") -> dict:
    """Run the exact sandbox source in-process (used by tests and for parity checks)."""
    namespace: dict[str, Any] = {}
    exec(CALC_SOURCE, namespace)  # noqa: S102 - trusted, constant source text
    return namespace["compute_discount"](points, tier, order_total, category, RULES)


def build_sandbox_code(points: int, tier: str, order_total: float, category: str) -> str:
    """Program sent to the Code Interpreter. Arguments are embedded as Python literals (repr)."""
    return (
        "import json\n"
        f"RULES = json.loads({json.dumps(json.dumps(RULES))})\n"
        f"{CALC_SOURCE}\n"
        f"args = ({points!r}, {tier!r}, {order_total!r}, {category!r})\n"
        "print(json.dumps(compute_discount(*args, RULES)))\n"
    )


def _fallback(tier: str, order_total: float, reason: str) -> dict:
    """Tier-only discount, used when the sandbox is unavailable (no points redemption)."""
    rate = float(RULES["tier_discount"].get(str(tier).strip().title(), "0"))
    discount = round(order_total * rate, 2)
    return {
        "tier": str(tier).strip().title(),
        "tier_discount_pct": rate * 100,
        "tier_discount": discount,
        "final_total": round(order_total - discount, 2),
        "computed_by": "fallback_tier_only",
        "note": f"Code Interpreter unavailable ({reason}); only the tier discount was applied.",
    }


@tool
def calculate_loyalty_discount(
    loyalty_points: int,
    tier: str,
    order_total: float,
    product_category: str = "standard",
) -> str:
    """
    Calculate a customer's loyalty discount for an order with exact arithmetic in a secure
    sandbox. Use this for every points-redemption, tier-discount, order-total or points-earned
    question; never do the arithmetic yourself.

    Args:
        loyalty_points: Customer's current points balance.
        tier: Loyalty tier - Silver, Gold or Platinum.
        order_total: Order total in USD (must be positive).
        product_category: standard, gadget or grocery (controls points earned).

    Returns:
        JSON with points_redeemed, tier_discount_pct, final_total, remaining_points and the
        rest of the breakdown.
    """
    if order_total <= 0 or loyalty_points < 0:
        return json.dumps({"error": "order_total must be positive and loyalty_points non-negative"})

    settings = Settings.from_env()
    code = build_sandbox_code(loyalty_points, tier, order_total, product_category)
    try:
        with code_session(settings.region) as sandbox:
            response = sandbox.invoke(
                "executeCode", {"code": code, "language": "python", "clearContext": True}
            )
        for event in response["stream"]:
            result = event["result"]
            if result.get("isError"):
                raise RuntimeError(f"sandbox reported an error: {result}")
            payload = json.loads(result["content"][0]["text"])
            payload["computed_by"] = "code_interpreter"
            return json.dumps(payload)
        raise RuntimeError("sandbox returned no result")
    except Exception as exc:  # noqa: BLE001 - any failure degrades to the tier-only answer
        logger.error("Code Interpreter unavailable, using tier-only fallback: %s", exc)
        return json.dumps(_fallback(tier, order_total, type(exc).__name__))
