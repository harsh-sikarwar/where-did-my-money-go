"""Tests over the Razorpay shape fixtures.

These are the contract the generator will be held to (ADR-006). They assert the
*shape* of reality, so that when the generator is written in Phase 1 it cannot quietly
invent a schema Razorpay does not use.

They also encode the three schema corrections the probe surfaced (ADR-008). If a future
edit reverts one of them, these fail.
"""

from __future__ import annotations

import pytest

from finctl.probe import analyse_fee_convention, field_inventory, load_fixture

FIXTURES = ("settlement_recon", "payment_failed", "subscription_halted")


@pytest.mark.parametrize("name", FIXTURES)
def test_fixture_loads_and_declares_provenance(name: str) -> None:
    """Every fixture must state where it came from and whether it is live-captured.

    Losing track of which fixtures are real is how a documented-shape guess gets
    mistaken for verified truth.
    """
    fixture = load_fixture(name)
    prov = fixture["_provenance"]
    assert prov["source"]
    assert isinstance(prov["live_capture"], bool)
    assert prov["status"] in {"documented-shape", "live-capture"}


def test_recon_payment_rows_carry_id_in_entity_id_not_payment_id() -> None:
    """ADR-008: on type='payment' rows, payment_id is NULL and the id is in entity_id.

    Our original schema sketch assumed settlement.payment_id identified the payment.
    Joining on it would have matched nothing and reported every order as MISSING.
    """
    recon = load_fixture("settlement_recon")
    payment_rows = [i for i in recon["items"] if i["type"] == "payment"]
    assert payment_rows, "fixture must contain payment rows"
    for row in payment_rows:
        assert row["payment_id"] is None
        assert row["entity_id"].startswith("pay_")


def test_recon_refunds_are_rows_not_a_column() -> None:
    """ADR-008: refunds arrive as their own type-discriminated rows.

    There is no `refund_adjustment` column. Refund logic must read `type`, and a refund
    is a DEBIT, not a negative credit.
    """
    recon = load_fixture("settlement_recon")
    refunds = [i for i in recon["items"] if i["type"] == "refund"]
    assert refunds, "fixture must contain a refund row"
    for row in refunds:
        assert row["debit"] > 0
        assert row["credit"] == 0
    assert not any("refund_adjustment" in i for i in recon["items"])


def test_recon_row_types_are_the_documented_discriminators() -> None:
    recon = load_fixture("settlement_recon")
    seen = {i["type"] for i in recon["items"]}
    assert seen <= {"payment", "refund", "transfer", "adjustment"}


def test_upi_rows_carry_zero_fee() -> None:
    """UPI carries zero MDR - mandated for banks.

    This is the assumption most likely to be silently wrong for Indian merchants, so it
    is asserted against the reference shape rather than trusted.
    """
    recon = load_fixture("settlement_recon")
    upi = [i for i in recon["items"] if i.get("method") == "upi"]
    assert upi, "fixture must contain a UPI row"
    for row in upi:
        assert row["fee"] == 0
        assert row["tax"] == 0


def test_money_fields_are_integers() -> None:
    """ADR-003: money is integer paise everywhere. A float here means a source is wrong."""
    recon = load_fixture("settlement_recon")
    for row in recon["items"]:
        for field in ("amount", "debit", "credit", "fee", "tax"):
            assert isinstance(row[field], int), f"{field} must be int paise, got {type(row[field])}"
            assert not isinstance(row[field], bool)


def test_failed_payments_carry_the_full_error_taxonomy() -> None:
    """The correlation input. Without these five fields there is no differentiator."""
    payments = load_fixture("payment_failed")
    failed = [p for p in payments["items"] if p["status"] == "failed"]
    assert failed
    for p in failed:
        for field in ("error_code", "error_description", "error_source", "error_step", "error_reason"):
            assert p[field], f"failed payment {p['id']} missing {field}"


def test_failed_payments_span_the_three_failure_buckets() -> None:
    """Card/account, bank/network, and risk block - they need different advice.

    Risk blocks in particular must never be recommended for retry.
    """
    payments = load_fixture("payment_failed")
    reasons = {p["error_reason"] for p in payments["items"] if p["status"] == "failed"}
    assert "incorrect_otp" in reasons
    assert "insufficient_funds" in reasons
    assert any("risk" in r for r in reasons)


def test_halted_subscription_shape() -> None:
    """The demo centrepiece: halted, with invoices generated and charges not attempted."""
    subs = load_fixture("subscription_halted")
    halted = [s for s in subs["items"] if s["status"] == "halted"]
    assert halted, "fixture must contain a halted subscription"
    for s in halted:
        assert s["status"] in {"created", "authenticated", "active", "pending", "halted",
                               "cancelled", "completed", "expired"}
        # Halting follows exhausted retries, so auth_attempts must be non-zero -
        # this is what distinguishes a genuinely halted sub from a decoy.
        assert s["auth_attempts"] > 0
        assert s["remaining_count"] > 0, "a halted sub still has billing cycles left to lose"


def test_fee_convention_is_undetermined_and_says_so() -> None:
    """ADR-007: the documented example has tax == 0, so both identities hold.

    This test asserts the engine reports UNDETERMINED rather than silently picking one.
    When Day-2 live capture lands real data with non-zero tax, this test is EXPECTED to
    fail - and that failure is the signal to update ADR-007 with the real answer.
    """
    analysis = analyse_fee_convention(load_fixture("settlement_recon"))
    assert analysis["verdict"].startswith("UNDETERMINED")
    assert not analysis["inconsistent_rows"]


def test_fee_convention_detects_a_mixed_batch() -> None:
    """A batch where both conventions appear must be a hard error, not a majority vote."""
    synthetic = {
        "items": [
            {"type": "payment", "settled": True, "entity_id": "pay_incl",
             "amount": 100000, "fee": 2360, "tax": 360, "credit": 97640},
            {"type": "payment", "settled": True, "entity_id": "pay_add",
             "amount": 100000, "fee": 2000, "tax": 360, "credit": 97640},
        ]
    }
    analysis = analyse_fee_convention(synthetic)
    assert analysis["verdict"].startswith("ERROR")


def test_field_inventory_reports_nullability() -> None:
    inv = field_inventory(load_fixture("settlement_recon"))
    assert inv["payment_id"]["nullable"] is True
    assert inv["entity_id"]["nullable"] is False
    assert inv["amount"]["types"] == ["int"]
