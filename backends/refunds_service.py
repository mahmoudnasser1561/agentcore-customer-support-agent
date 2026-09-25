"""Refund service (AWS Lambda invoked directly by an AgentCore Gateway Lambda target).

The Gateway passes the tool name in the Lambda client context as ``<target>___<tool>``;
the arguments arrive as the event. Tools: initiate_refund, check_refund_status, get_return_label.

Refund ids are derived from the order id so the sample service needs no database:
the same order always maps to the same refund id.
"""

import hashlib
from datetime import date, timedelta

# order_id -> (status, total). Mirrors the sample data in orders_service.py.
KNOWN_ORDERS = {
    "ORD-7001": ("SHIPPED", 129.00),
    "ORD-7002": ("DELIVERED", 119.00),
    "ORD-7003": ("PROCESSING", 88.00),
}


def refund_id_for(order_id: str) -> str:
    return "REF-" + hashlib.sha1(order_id.encode()).hexdigest()[:8].upper()


def _tool_name(context) -> str:
    custom = getattr(getattr(context, "client_context", None), "custom", None) or {}
    raw = custom.get("bedrockAgentCoreToolName", "")
    return raw.split("___", 1)[-1]


def _initiate_refund(event: dict) -> dict:
    order_id = str(event.get("order_id", "")).upper()
    order = KNOWN_ORDERS.get(order_id)
    if order is None:
        return {"error": f"Order {order_id} not found", "code": "ORDER_NOT_FOUND"}
    status, total = order
    if status != "DELIVERED":
        return {
            "error": f"Order {order_id} is {status}; only delivered orders can be refunded",
            "code": "ORDER_NOT_DELIVERED",
        }
    amount = min(float(event.get("amount") or total), total)
    return {
        "refund_id": refund_id_for(order_id),
        "order_id": order_id,
        "status": "APPROVED",
        "amount": amount,
        "reason": event.get("reason", ""),
        "message": "Refund approved. The credit appears in 3-5 business days.",
    }


def _check_refund_status(event: dict) -> dict:
    refund_id = str(event.get("refund_id", "")).upper()
    for order_id, (status, total) in KNOWN_ORDERS.items():
        if status == "DELIVERED" and refund_id_for(order_id) == refund_id:
            return {
                "refund_id": refund_id,
                "order_id": order_id,
                "status": "APPROVED",
                "amount": total,
            }
    return {"error": f"Refund {refund_id} not found", "code": "REFUND_NOT_FOUND"}


def _get_return_label(event: dict) -> dict:
    order_id = str(event.get("order_id", "")).upper()
    if order_id not in KNOWN_ORDERS:
        return {"error": f"Order {order_id} not found", "code": "ORDER_NOT_FOUND"}
    return {
        "order_id": order_id,
        "carrier": "UPS",
        "label_url": f"https://returns.example.com/label/{order_id}",
        "valid_until": (date.today() + timedelta(days=14)).isoformat(),
    }


TOOLS = {
    "initiate_refund": _initiate_refund,
    "check_refund_status": _check_refund_status,
    "get_return_label": _get_return_label,
}


def lambda_handler(event, context):
    name = _tool_name(context)
    handler = TOOLS.get(name)
    if handler is None:
        return {"error": f"Unknown tool '{name}'", "code": "UNKNOWN_TOOL"}
    return handler(event)
