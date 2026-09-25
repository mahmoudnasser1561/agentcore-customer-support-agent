"""Order-lookup service (AWS Lambda behind an API Gateway REST API, Lambda-proxy integration).

Routes (the ``resource`` template is what API Gateway passes in the proxy event):
    GET /orders/{order_id}
    GET /customers/{customer_id}/orders
    GET /customers/{customer_id}

Data is in-memory sample data; a real service would query a database such as DynamoDB.
"""

import json
from datetime import date, timedelta


def _today() -> date:
    return date.today()


def _orders() -> dict:
    today = _today()
    return {
        "ORD-7001": {
            "order_id": "ORD-7001",
            "customer_id": "CUS-2001",
            "status": "SHIPPED",
            "items": [{"name": "Aurora Noise-Cancelling Headphones", "qty": 1, "price": 129.00}],
            "total": 129.00,
            "carrier": "DHL",
            "tracking_number": "DH5501234567",
            "estimated_delivery": (today + timedelta(days=2)).isoformat(),
        },
        "ORD-7002": {
            "order_id": "ORD-7002",
            "customer_id": "CUS-2001",
            "status": "DELIVERED",
            "items": [{"name": "Nimbus E-Reader", "qty": 1, "price": 119.00}],
            "total": 119.00,
            "carrier": "UPS",
            "tracking_number": "1ZNB4419000123",
            "delivered_date": (today - timedelta(days=3)).isoformat(),
        },
        "ORD-7003": {
            "order_id": "ORD-7003",
            "customer_id": "CUS-2002",
            "status": "PROCESSING",
            "items": [
                {"name": "Pulse Smart Plug", "qty": 2, "price": 24.50},
                {"name": "Halo Desk Lamp", "qty": 1, "price": 39.00},
            ],
            "total": 88.00,
            "estimated_delivery": (today + timedelta(days=5)).isoformat(),
        },
    }


CUSTOMERS = {
    "CUS-2001": {"name": "Maya Brooks", "tier": "Gold", "loyalty_points": 5400},
    "CUS-2002": {"name": "Omar Haddad", "tier": "Silver", "loyalty_points": 820},
    "CUS-2003": {"name": "Lena Fischer", "tier": "Platinum", "loyalty_points": 12250},
}


def _respond(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def lambda_handler(event, context):
    resource = event.get("resource", "")
    method = event.get("httpMethod", "GET")
    params = event.get("pathParameters") or {}

    if method != "GET":
        return _respond(405, {"error": f"Method {method} not allowed"})

    if resource == "/orders/{order_id}":
        order_id = params.get("order_id", "").upper()
        order = _orders().get(order_id)
        return (
            _respond(200, order)
            if order
            else _respond(404, {"error": f"Order {order_id} not found"})
        )

    if resource == "/customers/{customer_id}/orders":
        customer_id = params.get("customer_id", "").upper()
        orders = [o for o in _orders().values() if o["customer_id"] == customer_id]
        if not orders:
            return _respond(404, {"error": f"No orders found for {customer_id}"})
        return _respond(200, {"customer_id": customer_id, "orders": orders})

    if resource == "/customers/{customer_id}":
        customer_id = params.get("customer_id", "").upper()
        customer = CUSTOMERS.get(customer_id)
        if not customer:
            return _respond(404, {"error": f"Customer {customer_id} not found"})
        return _respond(200, {"customer_id": customer_id, **customer})

    return _respond(400, {"error": "Unrecognised route", "resource": resource})
