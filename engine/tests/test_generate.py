"""Generator tests.

The generator is the foundation of every metric this project reports. If it is wrong,
the accuracy numbers are confidently wrong — which is worse than having none.

Two properties matter above all:
  * determinism — same seed, same bytes, or golden-file tests are impossible
  * ground-truth completeness — an unrecorded defect is an unscoreable one
"""

from __future__ import annotations

import json
from datetime import UTC
from pathlib import Path

import pytest

from finctl.config.loader import Config, ConfigError, load_config
from finctl.generate.generator import Generator
from finctl.generate.ground_truth import DefectType, GroundTruth, PlantedDefect
from finctl.generate.writer import write_batch
from finctl.probe import analyse_fee_convention


@pytest.fixture
def config() -> Config:
    return load_config()


@pytest.fixture
def batch(config: Config):
    return Generator(config, seed=20260902, volume=200, defect_profile="demo").generate()


class TestDeterminism:
    """Same seed, same bytes. Golden-file testing depends on this absolutely."""

    def test_same_seed_produces_identical_output(self, config: Config) -> None:
        a = Generator(config, seed=42, volume=100).generate()
        b = Generator(config, seed=42, volume=100).generate()
        assert json.dumps(a.ledger, sort_keys=True) == json.dumps(b.ledger, sort_keys=True)
        assert json.dumps(a.recon, sort_keys=True) == json.dumps(b.recon, sort_keys=True)
        assert json.dumps(a.bank, sort_keys=True) == json.dumps(b.bank, sort_keys=True)
        assert json.dumps(a.payments, sort_keys=True) == json.dumps(b.payments, sort_keys=True)

    def test_different_seed_produces_different_output(self, config: Config) -> None:
        a = Generator(config, seed=42, volume=100).generate()
        b = Generator(config, seed=43, volume=100).generate()
        assert json.dumps(a.ledger, sort_keys=True) != json.dumps(b.ledger, sort_keys=True)

    def test_ground_truth_is_deterministic_too(self, config: Config) -> None:
        a = Generator(config, seed=42, volume=100).generate().ground_truth
        b = Generator(config, seed=42, volume=100).generate().ground_truth
        assert a is not None and b is not None
        assert a.to_dict() == b.to_dict()


class TestGroundTruthCompleteness:
    """ADR-004: a defect that cannot be scored does not get planted."""

    def test_every_planted_defect_is_recorded(self, batch) -> None:
        gt = batch.ground_truth
        assert gt is not None
        assert len(gt.real_defects) > 0
        for d in gt.defects:
            assert d.defect_id
            assert d.defect_type in DefectType.ALL
            assert d.expected_classification
            assert isinstance(d.impact_paise, int)

    def test_demo_profile_plants_exactly_six_halted_subscriptions(self, batch) -> None:
        """The demo centrepiece. Six customers, not 'about six'."""
        gt = batch.ground_truth
        assert len(gt.by_type(DefectType.HALTED_SUBSCRIPTION)) == 6
        halted = [s for s in batch.subscriptions if s["status"] == "halted"]
        assert len(halted) == 6
        # The batch also carries HEALTHY subscriptions, deliberately: those are the
        # decoys, and their whole purpose is to sit alongside the halted ones looking
        # similar. ADR-042.
        active = [s for s in batch.subscriptions if s["status"] == "active"]
        assert active, "the demo profile must plant healthy-subscription decoys"
        assert len(batch.subscriptions) == len(halted) + len(active)

    def test_every_defect_type_is_planted(self, batch) -> None:
        """The demo profile must exercise every type the generator knows about,
        so no defect type ships with its engine behaviour unverified.

        Decoy types are excluded from the REAL-defect set by construction: a decoy is
        planted with is_real_defect=False precisely so the scorer treats it as a trap
        rather than as something to find. They are asserted separately below.
        """
        decoy_types = {DefectType.HEALTHY_SUBSCRIPTION_DECOY}
        planted = {d.defect_type for d in batch.ground_truth.real_defects}
        assert planted == set(DefectType.ALL) - decoy_types
        assert not (planted & decoy_types), "a decoy must never be a real defect"

    def test_every_decoy_type_is_planted(self, batch) -> None:
        """A decoy that is never planted guards nothing. ADR-042."""
        planted = {d.defect_type for d in batch.ground_truth.decoys}
        assert planted == {DefectType.HEALTHY_SUBSCRIPTION_DECOY}
        assert all(not d.is_real_defect for d in batch.ground_truth.decoys)

    def test_impact_is_recorded_in_integer_paise(self, batch) -> None:
        for d in batch.ground_truth.defects:
            assert isinstance(d.impact_paise, int)
            assert not isinstance(d.impact_paise, bool)

    def test_ground_truth_survives_a_round_trip(self, batch, tmp_path: Path) -> None:
        path = tmp_path / "gt.json"
        batch.ground_truth.write(path)
        assert GroundTruth.read(path).to_dict() == batch.ground_truth.to_dict()

    def test_unknown_defect_type_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown defect type"):
            PlantedDefect(
                defect_id="x", defect_type="vibes_mismatch", order_id=None,
                impact_paise=100, expected_classification="X",
            )

    def test_float_impact_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="int paise"):
            PlantedDefect(
                defect_id="x", defect_type=DefectType.MISSING_ORDER, order_id=None,
                impact_paise=100.5, expected_classification="MISSING",  # type: ignore[arg-type]
            )


class TestDefectsAreActuallyPresentInTheData:
    """A ground-truth entry with no corresponding data defect would be a lie."""

    def test_missing_orders_are_in_the_ledger_but_not_in_recon(self, batch) -> None:
        gt = batch.ground_truth
        recon_orders = {r["order_id"] for r in batch.recon if r.get("order_id")}
        ledger_orders = {r["order_id"] for r in batch.ledger}
        for d in gt.by_type(DefectType.MISSING_ORDER):
            assert d.order_id in ledger_orders
            assert d.order_id not in recon_orders

    def test_missing_orders_have_a_failed_payment_with_a_reason(self, batch) -> None:
        """This is what makes them CORRELATABLE rather than merely absent."""
        by_order = {p["order_id"]: p for p in batch.payments}
        for d in batch.ground_truth.by_type(DefectType.MISSING_ORDER):
            p = by_order[d.order_id]
            assert p["status"] == "failed"
            assert p["error_reason"]
            assert p["error_code"]

    def test_halted_subscriptions_have_an_invoice_but_no_settlement(self, batch) -> None:
        """The cruelty of the halted state: invoices keep coming, money never does."""
        recon_orders = {r["order_id"] for r in batch.recon if r.get("order_id")}
        by_order = {p["order_id"]: p for p in batch.payments}
        for d in batch.ground_truth.by_type(DefectType.HALTED_SUBSCRIPTION):
            assert d.order_id not in recon_orders
            p = by_order[d.order_id]
            assert p["invoice_id"] is not None       # an invoice WAS generated
            assert p["status"] == "failed"           # but no charge succeeded
            assert p["error_reason"] == "subscription_halted"
            assert p["subscription_id"] is not None

    def test_halted_subscriptions_show_exhausted_retries(self, batch) -> None:
        """auth_attempts > 0 is what distinguishes a real halt from a decoy.

        Now asserted against both sides of that distinction, since the decoys exist.
        """
        for s in batch.subscriptions:
            if s["status"] == "halted":
                assert s["auth_attempts"] > 0
                assert s["remaining_count"] > 0   # cycles still left to lose
            else:
                # The decoy: Razorpay has not given up, so nothing died silently.
                assert s["status"] == "active"
                assert s["auth_attempts"] == 0

    def test_fee_overcharges_exceed_the_contracted_rate(self, batch, config: Config) -> None:
        from finctl.fees import expected_fee
        by_order = {r["order_id"]: r for r in batch.recon if r.get("order_id")}
        for d in batch.ground_truth.by_type(DefectType.WRONG_FEE_RATE):
            row = by_order[d.order_id]
            contracted = expected_fee(row["amount"], row["method"], config.rate_card)
            assert row["fee"] > contracted.total_fee_paise
            assert d.impact_paise > 0

    def test_timing_defects_settle_later_than_the_cycle_allows(self, batch, config: Config) -> None:
        from datetime import datetime

        from finctl.calendar import WorkingCalendar
        cal = WorkingCalendar(config.tolerances.weekend_days, config.tolerances.holidays)
        by_order = {r["order_id"]: r for r in batch.recon if r.get("order_id")}
        for d in batch.ground_truth.by_type(DefectType.TIMING_LAG):
            row = by_order[d.order_id]
            captured = datetime.fromtimestamp(row["created_at"], tz=UTC).date()
            settled = datetime.fromtimestamp(row["settled_at"], tz=UTC).date()
            assert settled > cal.add_working_days(captured, batch.ground_truth.settlement_cycle_days)


class TestRazorpayShapeCompliance:
    """ADR-008. Getting this wrong makes the Day-2 live swap a schema change."""

    def test_payment_rows_put_the_id_in_entity_id_not_payment_id(self, batch) -> None:
        for row in batch.recon:
            if row["type"] == "payment":
                assert row["payment_id"] is None
                assert row["entity_id"].startswith("pay_")

    def test_recon_types_are_the_documented_discriminators(self, batch) -> None:
        assert {r["type"] for r in batch.recon} <= {"payment", "refund", "transfer", "adjustment"}

    def test_all_money_fields_are_integer_paise(self, batch) -> None:
        for row in batch.recon:
            for f in ("amount", "debit", "credit", "fee", "tax"):
                assert isinstance(row[f], int) and not isinstance(row[f], bool)

    def test_failed_payments_carry_the_full_error_taxonomy(self, batch) -> None:
        for p in batch.payments:
            if p["status"] == "failed":
                for f in ("error_code", "error_description", "error_source",
                          "error_step", "error_reason"):
                    assert p[f], f"failed payment {p['id']} missing {f}"

    def test_captured_payments_carry_no_error_fields(self, batch) -> None:
        for p in batch.payments:
            if p["status"] == "captured":
                assert p["error_reason"] is None
                assert p["error_code"] is None


class TestFeeCorrectness:
    """'The most likely place your build is quietly wrong.'"""

    def test_upi_rows_are_charged_the_platform_fee(self, config: Config) -> None:
        """ADR-030. UPI rows carry ~2% + GST, so credit is strictly below amount."""
        batch = Generator(config, seed=7, volume=300, payment_mix="upi_heavy",
                          archetype="d2c_ecommerce", defect_profile="clean").generate()
        upi = [r for r in batch.recon if r["method"] == "upi"]
        assert upi, "upi_heavy mix must produce UPI rows"
        for row in upi:
            assert row["fee"] > 0
            assert row["tax"] > 0
            assert row["credit"] < row["amount"]

    def test_upi_heavy_is_no_longer_almost_free(self, config: Config) -> None:
        """Regression guard for ADR-030.

        The old rate card made a UPI-heavy batch cost ~1/5 of a card-heavy one.
        At the real platform fee the two are within a few percent, because the
        domestic rate is a flat 2% either way.
        """
        upi = Generator(config, seed=7, volume=300, payment_mix="upi_heavy",
                        defect_profile="clean").generate()
        card = Generator(config, seed=7, volume=300, payment_mix="card_heavy",
                         defect_profile="clean").generate()
        upi_fees = sum(r["fee"] for r in upi.recon)
        card_fees = sum(r["fee"] for r in card.recon)
        assert upi_fees > card_fees / 2

    def test_clean_profile_matches_the_rate_card_exactly(self, config: Config) -> None:
        """With no defects planted, every fee must equal the contracted fee."""
        from finctl.fees import expected_fee
        batch = Generator(config, seed=11, volume=200, defect_profile="clean").generate()
        for row in batch.recon:
            if row["type"] != "payment":
                continue
            exp = expected_fee(row["amount"], row["method"], config.rate_card)
            assert row["fee"] == exp.total_fee_paise
            assert row["tax"] == exp.gst_paise


class TestFeeConvention:
    """ADR-007. We do not know which convention Razorpay uses, so we support both."""

    def test_generator_emits_a_self_consistent_gst_inclusive_batch(self, config: Config) -> None:
        batch = Generator(config, seed=3, volume=150, fee_convention="gst_inclusive").generate()
        analysis = analyse_fee_convention({"items": batch.recon})
        assert analysis["verdict"].startswith("fee is GST-INCLUSIVE")
        assert not analysis["inconsistent_rows"]

    def test_generator_emits_a_self_consistent_mdr_only_batch(self, config: Config) -> None:
        """Proves the detector is not merely agreeing with our default."""
        batch = Generator(config, seed=3, volume=150, fee_convention="mdr_only").generate()
        analysis = analyse_fee_convention({"items": batch.recon})
        assert analysis["verdict"].startswith("fee is MDR-ONLY")
        assert not analysis["inconsistent_rows"]

    def test_unknown_convention_is_rejected(self, config: Config) -> None:
        with pytest.raises(ValueError, match="fee_convention"):
            Generator(config, fee_convention="whatever_feels_right")


class TestInternalConsistency:
    def test_bank_credits_equal_the_settlements_that_produced_them(self, batch) -> None:
        """The PSP->Bank leg must reconcile in a batch with no bank-side defects."""
        by_utr: dict[str, int] = {}
        for row in batch.recon:
            by_utr[row["settlement_utr"]] = by_utr.get(row["settlement_utr"], 0) + (
                row["credit"] - row["debit"]
            )
        for bank_row in batch.bank:
            assert bank_row["credit_amount"] == by_utr[bank_row["utr"]]

    def test_every_settled_recon_row_belongs_to_a_settlement_with_a_utr(self, batch) -> None:
        """Every row EXCEPT one being withheld, which by definition has no settlement.

        Two ways a payment is withheld: `on_hold` (ADR-036) and an open dispute
        (ADR-041). Both mean Razorpay is keeping the money, so neither has a settlement
        or a UTR.
        """
        for row in batch.recon:
            if row.get("on_hold") or row.get("dispute_id"):
                continue
            assert row["settlement_id"] and row["settlement_id"].startswith("setl_")
            assert row["settlement_utr"]

    def test_a_disputed_recon_row_has_no_settlement(self, batch) -> None:
        """The inverse invariant for disputes, mirroring the held case.

        If a disputed row acquired a UTR the money would appear in the bank while the
        engine reported it withheld pending the dispute. See ADR-041.
        """
        disputed = [r for r in batch.recon if r.get("dispute_id")]
        assert disputed, "the demo profile must plant disputes"
        for row in disputed:
            assert row["settlement_id"] is None
            assert row["settlement_utr"] is None
            assert row["settled_at"] is None
            assert row["dispute_reason"]

    def test_a_held_recon_row_has_no_settlement(self, batch) -> None:
        """The inverse invariant: being held means no settlement, no UTR, no settled_at.

        If a held row ever acquired a UTR the money would appear in the bank while the
        engine reported it withheld. See ADR-036.
        """
        held = [r for r in batch.recon if r.get("on_hold")]
        assert held, "demo profile must plant held payments"
        for row in held:
            assert row["settlement_id"] is None
            assert row["settlement_utr"] is None
            assert row["settled_at"] is None
            assert row["settled"] is False

    def test_ledger_totals_match_ground_truth(self, batch) -> None:
        assert sum(r["amount"] for r in batch.ledger) == batch.ground_truth.total_gross_paise
        assert len(batch.ledger) == batch.ground_truth.total_orders


class TestRefusals:
    def test_zero_volume_raises(self, config: Config) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            Generator(config, volume=0)

    def test_unknown_archetype_lists_valid_options(self, config: Config) -> None:
        with pytest.raises(ConfigError, match="unknown archetype"):
            Generator(config, archetype="crypto_casino")

    def test_unknown_defect_profile_lists_valid_options(self, config: Config) -> None:
        with pytest.raises(ConfigError, match="unknown defect profile"):
            Generator(config, defect_profile="maximum_chaos")

    def test_unknown_payment_mix_raises(self, config: Config) -> None:
        with pytest.raises(ConfigError, match="unknown payment mix"):
            Generator(config, payment_mix="vibes")


class TestAdversarialCases:
    """build-spec 6e, exercised at the generator level."""

    def test_clean_profile_plants_nothing(self, config: Config) -> None:
        batch = Generator(config, seed=5, volume=100, defect_profile="clean").generate()
        assert batch.ground_truth.real_defects == []
        assert len(batch.recon) == len(batch.ledger)   # nothing dropped

    def test_single_order_batch(self, config: Config) -> None:
        batch = Generator(config, seed=5, volume=1, defect_profile="clean").generate()
        assert len(batch.ledger) == 1

    def test_refuses_when_demanded_defects_exceed_the_batch(self, config: Config) -> None:
        """A real bug, found by a staging test at volume=40.

        The demo profile demands more defects than a small batch has orders. Below that
        volume the index slices ran off
        the end and the LAST defect types silently got nothing -- while ground truth
        still claimed they were planted. Zero halted subscriptions, ground truth
        insisting on six. A batch whose metrics are confidently wrong is the one failure
        this project cannot tolerate, so the generator now refuses and shows the
        arithmetic.
        """
        with pytest.raises(ValueError, match=r"demands \d+ defects"):
            Generator(config, volume=40, defect_profile="demo").generate()

    def test_the_error_names_the_offending_counts(self, config: Config) -> None:
        with pytest.raises(ValueError) as exc:
            Generator(config, volume=45, defect_profile="demo").generate()
        msg = str(exc.value)
        assert "wrong_fee_rate=30" in msg
        assert "raise --volume" in msg

    def test_rate_based_profiles_scale_down_safely(self, config: Config) -> None:
        """'scale' uses rates, so it never over-demands however small the batch."""
        batch = Generator(config, seed=5, volume=20, defect_profile="scale").generate()
        assert len(batch.ledger) == 20

    def test_chaos_profile_does_not_crash_and_records_everything(self, config: Config) -> None:
        batch = Generator(config, seed=5, volume=100, defect_profile="chaos").generate()
        assert len(batch.ground_truth.real_defects) > 0

    @pytest.mark.parametrize("cycle", [1, 2, 7])
    def test_every_settlement_cycle_works(self, config: Config, cycle: int) -> None:
        batch = Generator(config, seed=5, volume=50, settlement_cycle_days=cycle,
                          defect_profile="clean").generate()
        assert batch.ground_truth.settlement_cycle_days == cycle

    @pytest.mark.parametrize("archetype", ["d2c_ecommerce", "saas_subscription"])
    def test_every_archetype_works(self, config: Config, archetype: str) -> None:
        batch = Generator(config, seed=5, volume=100, archetype=archetype).generate()
        assert len(batch.ledger) == 100


class TestWriter:
    def test_writes_every_artefact(self, batch, tmp_path: Path) -> None:
        paths = write_batch(batch, tmp_path)
        for name in ("ledger", "bank", "recon", "payments", "subscriptions", "ground_truth"):
            assert paths[name].exists(), name

    def test_ledger_csv_holds_rupee_strings_not_paise(self, batch, tmp_path: Path) -> None:
        """A merchant's export contains rupees. Normalize converts; nothing else may."""
        write_batch(batch, tmp_path)
        lines = (tmp_path / "ledger.csv").read_text().splitlines()
        assert lines[0] == "order_id,amount,timestamp,customer_id,payment_method"
        assert "." in lines[1].split(",")[1]

    def test_json_uses_razorpays_collection_envelope(self, batch, tmp_path: Path) -> None:
        """So the same reader works on generated data and a live API response."""
        write_batch(batch, tmp_path)
        data = json.loads((tmp_path / "settlement_recon.json").read_text())
        assert data["entity"] == "collection"
        assert data["count"] == len(data["items"])

    def test_empty_batch_still_writes_a_header(self, config: Config, tmp_path: Path) -> None:
        """'Nothing to reconcile' is a valid answer and must reach the verdict stage."""
        batch = Generator(config, seed=1, volume=1, defect_profile="clean").generate()
        batch.ledger = []
        batch.bank = []
        write_batch(batch, tmp_path)
        assert (tmp_path / "ledger.csv").read_text().strip() == (
            "order_id,amount,timestamp,customer_id,payment_method"
        )

    def test_refuses_to_write_a_batch_with_no_ground_truth(self, batch, tmp_path: Path) -> None:
        batch.ground_truth = None
        with pytest.raises(ValueError, match="unscoreable"):
            write_batch(batch, tmp_path)


class TestScale:
    def test_five_thousand_orders(self, config: Config) -> None:
        batch = Generator(config, seed=9, volume=5000, defect_profile="scale").generate()
        assert len(batch.ledger) == 5000
        assert batch.ground_truth.total_gross_paise == sum(r["amount"] for r in batch.ledger)
