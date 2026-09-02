"""Normalizer tests.

The refusal to guess is the feature. A tool that silently maps a column it is unsure
about produces a confident wrong reconciliation, and a merchant cannot tell that from a
correct one.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from finctl.normalize.normalizer import (
    NormalizationError,
    load_collection,
    normalize_bank,
    normalize_ledger,
    resolve_columns,
    to_date,
)
from finctl.schema import LEDGER_ALIASES, LEDGER_REQUIRED


def write_csv(path: Path, text: str) -> Path:
    path.write_text(text.strip() + "\n")
    return path


class TestColumnMapping:
    def test_canonical_headers_map_directly(self) -> None:
        m = resolve_columns(
            ["order_id", "amount", "timestamp", "customer_id", "payment_method"],
            LEDGER_ALIASES, LEDGER_REQUIRED, "ledger",
        )
        assert m.resolved["order_id"] == "order_id"
        assert m.resolved["amount_paise"] == "amount"

    def test_reordered_columns_are_fine(self) -> None:
        """Order carries no meaning. Nothing here matches positionally."""
        m = resolve_columns(
            ["payment_method", "amount", "order_id"], LEDGER_ALIASES, LEDGER_REQUIRED, "ledger"
        )
        assert m.resolved["order_id"] == "order_id"

    @pytest.mark.parametrize(
        "header", ["Order ID", "order-id", "ORDER_ID", "orderid", "Order_Id", "order id"]
    )
    def test_case_and_separators_are_folded(self, header: str) -> None:
        """Adversarial case from build-spec 6e: renamed/reordered columns."""
        m = resolve_columns([header, "amount"], LEDGER_ALIASES, LEDGER_REQUIRED, "ledger")
        assert m.resolved["order_id"] == header

    @pytest.mark.parametrize("header", ["receipt", "reference", "order_ref"])
    def test_known_synonyms_resolve(self, header: str) -> None:
        m = resolve_columns([header, "amount"], LEDGER_ALIASES, LEDGER_REQUIRED, "ledger")
        assert m.resolved["order_id"] == header

    def test_multiple_aliases_folding_to_one_column_is_not_an_ambiguity(self) -> None:
        """'order_id' and 'orderid' both fold to the same key.

        The same input column hit twice is ONE candidate, not a conflict. This was a
        real bug: the first implementation raised on every well-formed file.
        """
        m = resolve_columns(["order_id", "amount"], LEDGER_ALIASES, LEDGER_REQUIRED, "ledger")
        assert m.resolved["order_id"] == "order_id"

    def test_two_distinct_candidate_columns_raise(self) -> None:
        """A genuine ambiguity is reported, never resolved by preference order."""
        with pytest.raises(NormalizationError, match="ambiguous"):
            resolve_columns(
                ["order_id", "receipt", "amount"], LEDGER_ALIASES, LEDGER_REQUIRED, "ledger"
            )

    def test_unmappable_required_column_raises_with_help(self) -> None:
        with pytest.raises(NormalizationError) as exc:
            resolve_columns(["widget_code", "amount"], LEDGER_ALIASES, LEDGER_REQUIRED, "ledger")
        msg = str(exc.value)
        assert "order_id" in msg
        assert "widget_code" in msg          # what we saw
        assert "Accepted spellings" in msg   # what we would have accepted
        assert "Refusing to guess" in msg

    def test_unknown_extra_columns_are_reported_not_fatal(self) -> None:
        """An unexpected column is not an error; silently using it would be."""
        m = resolve_columns(
            ["order_id", "amount", "warehouse_note"], LEDGER_ALIASES, LEDGER_REQUIRED, "ledger"
        )
        assert "warehouse_note" in m.unmapped

    def test_mapping_is_recorded_for_the_audit_trail(self) -> None:
        m = resolve_columns(["receipt", "gross"], LEDGER_ALIASES, LEDGER_REQUIRED, "ledger")
        assert "'receipt'->order_id" in m.describe()


class TestMoneyParsing:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("1,234.50", 123450), ("₹1,234.50", 123450), ("1234.5", 123450), ("1234", 123400)],
    )
    def test_rupee_strings_become_integer_paise(self, tmp_path: Path, raw: str, expected: int) -> None:
        """Adversarial case: amounts as '1,234.50' strings."""
        p = write_csv(tmp_path / "l.csv", f'order_id,amount\nO1,"{raw}"')
        rows, _ = normalize_ledger(p)
        assert rows[0]["amount_paise"] == expected
        assert isinstance(rows[0]["amount_paise"], int)

    def test_bad_amount_names_the_row_and_column(self, tmp_path: Path) -> None:
        p = write_csv(tmp_path / "l.csv", "order_id,amount\nO1,not-a-number")
        with pytest.raises(NormalizationError) as exc:
            normalize_ledger(p)
        assert "row 2" in str(exc.value)
        assert "amount" in str(exc.value)

    def test_negative_ledger_amount_is_refused(self, tmp_path: Path) -> None:
        p = write_csv(tmp_path / "l.csv", "order_id,amount\nO1,-100.00")
        with pytest.raises(NormalizationError):
            normalize_ledger(p)

    def test_negative_bank_credit_is_allowed(self, tmp_path: Path) -> None:
        """A settlement reversal legitimately debits the account."""
        p = write_csv(tmp_path / "b.csv", "utr,credit_amount\nU1,-500.00")
        rows, _ = normalize_bank(p)
        assert rows[0]["credit_paise"] == -50000


class TestTimestamps:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1785769200", date(2026, 8, 3)),
            ("2026-08-03", date(2026, 8, 3)),
            ("03/08/2026", date(2026, 8, 3)),
            ("2026-08-03T15:00:00Z", date(2026, 8, 3)),
        ],
    )
    def test_accepted_timestamp_forms(self, tmp_path: Path, raw: str, expected: date) -> None:
        p = write_csv(tmp_path / "l.csv", f"order_id,amount,timestamp\nO1,100.00,{raw}")
        rows, _ = normalize_ledger(p)
        assert rows[0]["captured_at"].date() == expected
        assert rows[0]["captured_at"].tzinfo is not None   # always tz-aware

    def test_unparseable_timestamp_raises_with_the_accepted_forms(self, tmp_path: Path) -> None:
        p = write_csv(tmp_path / "l.csv", "order_id,amount,timestamp\nO1,100.00,last tuesday")
        with pytest.raises(NormalizationError, match="Accepted"):
            normalize_ledger(p)


class TestAdversarialInput:
    def test_empty_file_with_a_header_is_not_an_error(self, tmp_path: Path) -> None:
        """'Nothing to reconcile' is a valid answer that must reach the verdict stage."""
        p = write_csv(tmp_path / "l.csv", "order_id,amount")
        rows, mapping = normalize_ledger(p)
        assert rows == []
        assert mapping.resolved["order_id"] == "order_id"

    def test_headerless_file_is_refused(self, tmp_path: Path) -> None:
        (tmp_path / "l.csv").write_text("")
        with pytest.raises(NormalizationError, match="no header"):
            normalize_ledger(tmp_path / "l.csv")

    def test_missing_file_names_the_path(self, tmp_path: Path) -> None:
        with pytest.raises(NormalizationError, match="not found"):
            normalize_ledger(tmp_path / "nope.csv")

    def test_bom_prefixed_header_is_handled(self, tmp_path: Path) -> None:
        """Excel exports carry a UTF-8 BOM. It must not corrupt the first column name."""
        (tmp_path / "l.csv").write_text("﻿order_id,amount\nO1,100.00\n", encoding="utf-8")
        rows, _ = normalize_ledger(tmp_path / "l.csv")
        assert rows[0]["order_id"] == "O1"

    def test_duplicate_headers_are_refused(self, tmp_path: Path) -> None:
        p = write_csv(tmp_path / "l.csv", "order_id,order-id,amount\nO1,O2,100.00")
        with pytest.raises(NormalizationError, match="collide"):
            normalize_ledger(p)

    def test_whitespace_is_stripped_from_identifiers(self, tmp_path: Path) -> None:
        p = write_csv(tmp_path / "l.csv", "order_id,amount\n  O1  ,100.00")
        rows, _ = normalize_ledger(p)
        assert rows[0]["order_id"] == "O1"


class TestCollections:
    def test_reads_a_razorpay_collection_envelope(self, tmp_path: Path) -> None:
        p = tmp_path / "c.json"
        p.write_text('{"entity":"collection","count":1,"items":[{"id":"pay_1"}]}')
        assert load_collection(p, "recon") == [{"id": "pay_1"}]

    def test_accepts_a_bare_list(self, tmp_path: Path) -> None:
        """A paginated fetch may be concatenated before it reaches us."""
        p = tmp_path / "c.json"
        p.write_text('[{"id":"pay_1"}]')
        assert load_collection(p, "recon") == [{"id": "pay_1"}]

    def test_truncated_page_is_refused(self, tmp_path: Path) -> None:
        """A partial page would silently under-report every downstream total."""
        p = tmp_path / "c.json"
        p.write_text('{"entity":"collection","count":5,"items":[{"id":"pay_1"}]}')
        with pytest.raises(NormalizationError, match="partial page"):
            load_collection(p, "recon")

    def test_invalid_json_names_the_file(self, tmp_path: Path) -> None:
        p = tmp_path / "c.json"
        p.write_text("{not json")
        with pytest.raises(NormalizationError, match="invalid JSON"):
            load_collection(p, "recon")


class TestToDate:
    @pytest.mark.parametrize(
        "value",
        [1785769200, "1785769200", date(2026, 8, 3),
         datetime(2026, 8, 3, 15, 0, tzinfo=UTC), "2026-08-03"],
    )
    def test_accepts_every_internal_timestamp_form(self, value) -> None:
        assert to_date(value) == date(2026, 8, 3)

    def test_none_passes_through(self) -> None:
        assert to_date(None) is None
