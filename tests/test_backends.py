import json
import types

import pytest

from backends import orders_service as orders
from backends import refunds_service as refunds


def proxy_event(resource, **path_params):
    return {"resource": resource, "httpMethod": "GET", "pathParameters": path_params or None}


def body(response):
    return json.loads(response["body"])


# -- orders (API Gateway proxy integration) -------------------------------------------------
def test_get_order_returns_tracking_details():
    response = orders.lambda_handler(proxy_event("/orders/{order_id}", order_id="ord-7001"), None)
    assert response["statusCode"] == 200
    data = body(response)
    assert (data["status"], data["carrier"], data["tracking_number"]) == (
        "SHIPPED",
        "DHL",
        "DH5501234567",
    )


def test_customer_orders_and_profile():
    listing = body(
        orders.lambda_handler(
            proxy_event("/customers/{customer_id}/orders", customer_id="CUS-2001"), None
        )
    )
    assert {o["order_id"] for o in listing["orders"]} == {"ORD-7001", "ORD-7002"}
    profile = body(
        orders.lambda_handler(proxy_event("/customers/{customer_id}", customer_id="CUS-2001"), None)
    )
    assert (profile["tier"], profile["loyalty_points"]) == ("Gold", 5400)


@pytest.mark.parametrize(
    "event, status",
    [
        (proxy_event("/orders/{order_id}", order_id="ORD-0000"), 404),
        (proxy_event("/customers/{customer_id}", customer_id="CUS-0000"), 404),
        (proxy_event("/customers/{customer_id}/orders", customer_id="CUS-2003"), 404),
        (proxy_event("/unknown"), 400),
        (
            {
                "resource": "/orders/{order_id}",
                "httpMethod": "POST",
                "pathParameters": {"order_id": "ORD-7001"},
            },
            405,
        ),
    ],
)
def test_error_responses(event, status):
    assert orders.lambda_handler(event, None)["statusCode"] == status


# -- refunds (direct Lambda target; tool name arrives in the client context) ----------------
def context_for(tool):
    return types.SimpleNamespace(
        client_context=types.SimpleNamespace(
            custom={"bedrockAgentCoreToolName": f"refunds___{tool}"}
        )
    )


def call(tool, **args):
    return refunds.lambda_handler(args, context_for(tool))


def test_refund_for_a_delivered_order_is_approved():
    result = call("initiate_refund", order_id="ORD-7002", reason="changed my mind")
    assert result["status"] == "APPROVED" and result["amount"] == 119.00
    assert result["refund_id"] == refunds.refund_id_for("ORD-7002")
    assert "3-5 business days" in result["message"]


def test_refund_amount_is_capped_at_the_order_total():
    assert call("initiate_refund", order_id="ORD-7002", reason="x", amount=500)["amount"] == 119.00


@pytest.mark.parametrize(
    "order_id, code",
    [
        ("ORD-7001", "ORDER_NOT_DELIVERED"),
        ("ORD-7003", "ORDER_NOT_DELIVERED"),
        ("ORD-0", "ORDER_NOT_FOUND"),
    ],
)
def test_refund_rejected_for_orders_that_are_not_eligible(order_id, code):
    assert call("initiate_refund", order_id=order_id, reason="x")["code"] == code


def test_refund_status_round_trip():
    refund_id = call("initiate_refund", order_id="ORD-7002", reason="x")["refund_id"]
    status = call("check_refund_status", refund_id=refund_id)
    assert status["status"] == "APPROVED" and status["order_id"] == "ORD-7002"
    assert call("check_refund_status", refund_id="REF-DEADBEEF")["code"] == "REFUND_NOT_FOUND"


def test_return_label_and_unknown_tool():
    assert call("get_return_label", order_id="ORD-7002")["carrier"] == "UPS"
    assert call("get_return_label", order_id="ORD-0")["code"] == "ORDER_NOT_FOUND"
    assert refunds.lambda_handler({}, context_for("delete_everything"))["code"] == "UNKNOWN_TOOL"


def test_tool_schema_matches_the_implemented_tools():
    with open("backends/refund_tool_schema.json") as fh:
        schema = json.load(fh)
    assert {t["name"] for t in schema} == set(refunds.TOOLS)
    for tool in schema:
        assert tool["inputSchema"]["type"] == "object" and tool["inputSchema"]["required"]
