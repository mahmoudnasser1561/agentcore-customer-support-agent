import contextlib
import io
import json

import pytest

from support_agent.tools import loyalty
from tests.conftest import call_tool

REQUIRED_FIELDS = ["points_redeemed", "tier_discount_pct", "final_total", "remaining_points"]

# (points, tier, order_total, category) -> hand-computed expectations
CASES = [
    # Gold: cap = 150*0.40*50 = 3000 pts -> $60 off; 8% of the remaining $90 = 7.20
    (
        (5400, "Gold", 150.0, "standard"),
        dict(
            points_redeemed=3000,
            points_discount=60.0,
            subtotal_after_points=90.0,
            tier_discount=7.2,
            final_total=82.8,
            total_savings=67.2,
            points_earned=82,
            remaining_points=2400,
            tier_discount_pct=8.0,
        ),
    ),
    # Silver gets no tier discount
    (
        (5400, "Silver", 150.0, "standard"),
        dict(
            points_redeemed=3000,
            tier_discount=0.0,
            final_total=90.0,
            points_earned=90,
            tier_discount_pct=0.0,
        ),
    ),
    # Platinum + gadget (3 points per $): cap 4000 pts -> $80; 12% of $120 = 14.40
    (
        (12250, "Platinum", 200.0, "gadget"),
        dict(
            points_redeemed=4000,
            tier_discount=14.4,
            final_total=105.6,
            total_savings=94.4,
            points_earned=316,
            remaining_points=8250,
            tier_discount_pct=12.0,
        ),
    ),
    # Fewer points than one redemption block -> nothing redeemed
    (
        (240, "Gold", 100.0, "standard"),
        dict(points_redeemed=0, tier_discount=8.0, final_total=92.0, remaining_points=240),
    ),
    # Points round down to a 250-point block, grocery earns 4 points per $
    (
        (500, "Gold", 20.0, "grocery"),
        dict(
            points_redeemed=250,
            points_discount=5.0,
            final_total=13.8,
            points_earned=55,
            remaining_points=250,
        ),
    ),
    # Cents round half-up
    ((0, "Gold", 33.33, "standard"), dict(tier_discount=2.67, final_total=30.66)),
    # Unknown tier -> no discount; tier is case/whitespace tolerant
    ((0, "Bronze", 100.0, "standard"), dict(tier_discount=0.0, final_total=100.0)),
    ((0, " gold ", 100.0, "standard"), dict(tier="Gold", tier_discount=8.0)),
]


@pytest.mark.parametrize("args, expected", CASES)
def test_rules_match_hand_calculation(args, expected):
    result = loyalty.compute_locally(*args)
    for key, value in expected.items():
        assert result[key] == pytest.approx(value), key


def run_sandbox_code(code: str) -> dict:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        exec(code, {})  # noqa: S102 - the very program sent to the sandbox
    return json.loads(out.getvalue())


def test_sandbox_program_equals_local_calculation():
    """The program sent to the Code Interpreter must equal the tested calculation, on a whole grid."""
    for points in (0, 240, 250, 999, 5400, 100000):
        for tier in ("Silver", "Gold", "Platinum", "unknown"):
            for total in (1.0, 19.99, 150.0, 1234.56):
                for category in ("standard", "gadget", "grocery", "other"):
                    code = loyalty.build_sandbox_code(points, tier, total, category)
                    assert run_sandbox_code(code) == loyalty.compute_locally(
                        points, tier, total, category
                    )


def test_hostile_tier_string_is_data_not_code():
    hostile = "Gold'); import os; os._exit(3) #"
    result = run_sandbox_code(loyalty.build_sandbox_code(0, hostile, 10.0, "standard"))
    assert result["tier_discount"] == 0.0 and result["final_total"] == 10.0


class FakeSandbox:
    def __init__(self, stream=None, error=None):
        self.stream, self.error, self.calls = stream, error, []

    def invoke(self, method, params):
        self.calls.append((method, params))
        if self.error:
            raise self.error
        return {"stream": self.stream}


def install_sandbox(monkeypatch, sandbox):
    @contextlib.contextmanager
    def fake_session(region):
        yield sandbox

    monkeypatch.setattr(loyalty, "code_session", fake_session)


def sandbox_ok(code_ran):
    """A stream shaped like the real service response, computing from the program it was sent."""
    return [
        {"result": {"isError": False, "content": [{"type": "text", "text": json.dumps(code_ran)}]}}
    ]


def test_tool_runs_program_in_sandbox_and_returns_flat_json(monkeypatch):
    expected = loyalty.compute_locally(5400, "Gold", 150.0, "standard")
    sandbox = FakeSandbox(stream=sandbox_ok(expected))
    install_sandbox(monkeypatch, sandbox)

    out = json.loads(call_tool(loyalty.calculate_loyalty_discount, 5400, "Gold", 150.0))

    method, params = sandbox.calls[0]
    assert method == "executeCode"
    assert params["language"] == "python" and params["clearContext"] is True
    assert "compute_discount" in params["code"]
    assert all(field in out for field in REQUIRED_FIELDS)
    assert out["computed_by"] == "code_interpreter"
    assert (
        out["points_redeemed"],
        out["tier_discount_pct"],
        out["final_total"],
        out["remaining_points"],
    ) == (3000, 8.0, 82.8, 2400)


@pytest.mark.parametrize(
    "sandbox",
    [
        FakeSandbox(error=ConnectionError("down")),
        FakeSandbox(stream=[{"result": {"isError": True, "content": [{"text": "boom"}]}}]),
        FakeSandbox(stream=[]),
        FakeSandbox(stream=[{"result": {"isError": False, "content": [{"text": "not json"}]}}]),
    ],
    ids=["raises", "isError", "empty", "unparseable"],
)
def test_falls_back_to_tier_only_discount(monkeypatch, sandbox):
    install_sandbox(monkeypatch, sandbox)
    out = json.loads(call_tool(loyalty.calculate_loyalty_discount, 5400, "Gold", 150.0))
    assert out["computed_by"] == "fallback_tier_only"
    assert (
        out["tier_discount_pct"] == 8.0
        and out["tier_discount"] == 12.0
        and out["final_total"] == 138.0
    )
    assert "unavailable" in out["note"]


@pytest.mark.parametrize("points, total", [(100, 0), (100, -5), (-1, 50)])
def test_invalid_input_never_reaches_the_sandbox(monkeypatch, points, total):
    sandbox = FakeSandbox(stream=[])
    install_sandbox(monkeypatch, sandbox)
    out = json.loads(call_tool(loyalty.calculate_loyalty_discount, points, "Gold", total))
    assert "error" in out and sandbox.calls == []


def test_tool_is_registered_with_a_useful_description():
    spec = loyalty.calculate_loyalty_discount.tool_spec
    assert spec["name"] == "calculate_loyalty_discount"
    assert set(spec["inputSchema"]["json"]["required"]) == {"loyalty_points", "tier", "order_total"}
    assert "never do the arithmetic yourself" in spec["description"]
