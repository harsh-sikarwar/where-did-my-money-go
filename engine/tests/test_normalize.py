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


class TestExcelSerialDates:
    """Razorpay's dashboard exports carry Excel serial dates. ADR-037.

    The regression these guard is not a crash — it is a plausible wrong answer.
    Serial 44658 read as epoch seconds is 1970-01-01, which raises nothing, looks
    like a date, and makes every settlement appear ~52 years late.
    """

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            # Both of these appear in the SAME column of the real sample file.
            ("44658.44689814815", date(2022, 4, 7)),
            ("29/06/2022 07:34:39", date(2022, 6, 29)),
            # The bare-integer form is the one that was silently wrong.
            ("44658", date(2022, 4, 7)),
        ],
    )
    def test_real_sample_file_forms(self, tmp_path: Path, raw: str, expected: date) -> None:
        p = write_csv(tmp_path / "l.csv", f"order_id,amount,timestamp\nO1,100.00,{raw}")
        rows, _ = normalize_ledger(p)
        assert rows[0]["captured_at"].date() == expected

    def test_the_1970_regression(self, tmp_path: Path) -> None:
        """THE bug. 44658 must not become 1970-01-01."""
        p = write_csv(tmp_path / "l.csv", "order_id,amount,timestamp\nO1,100.00,44658")
        rows, _ = normalize_ledger(p)
        assert rows[0]["captured_at"].year != 1970
        assert rows[0]["captured_at"].date() == date(2022, 4, 7)

    def test_epoch_seconds_still_win_outside_the_serial_window(self, tmp_path: Path) -> None:
        """The fix must not break the API path. Epoch seconds are ~10^9, serials ~10^4."""
        p = write_csv(tmp_path / "l.csv", "order_id,amount,timestamp\nO1,100.00,1785769200")
        rows, _ = normalize_ledger(p)
        assert rows[0]["captured_at"].date() == date(2026, 8, 3)

    def test_fractional_outside_the_window_is_refused_not_coerced(self, tmp_path: Path) -> None:
        """A number we cannot place is an error, not a guess."""
        p = write_csv(tmp_path / "l.csv", "order_id,amount,timestamp\nO1,100.00,999.5")
        with pytest.raises(NormalizationError, match="Refusing to guess"):
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


class TestReconTypeSpelling:
    """Razorpay's export says `transaction_entity`; we wrote `type`. ADR-038.

    No prior test could catch this: both sides of every test used our spelling.
    """

    def test_razorpays_own_key_is_read(self) -> None:
        from finctl.schema import ReconType, is_recon_type, recon_type

        # Verbatim shape from sample-settlements-recon-report.xlsx.
        real = {"transaction_entity": "payment", "entity_id": "pay_JpAZJjN9O1lKuG"}
        assert recon_type(real) == "payment"
        assert is_recon_type(real, ReconType.PAYMENT)
        assert not is_recon_type(real, ReconType.REFUND)

    def test_the_reverse_refund_row_from_the_sample_file(self) -> None:
        """Row 10 of the real recon sample: a settlement-side refund, no order_id."""
        from finctl.schema import ReconType, is_recon_type

        real = {"transaction_entity": "refund", "entity_id": "rfnd_Jt7Bq2djxtuWo5",
                "debit": "1.0", "credit": "0.0", "settlement_id": "setl_JtAs2E7Uf55JMV"}
        assert is_recon_type(real, ReconType.REFUND)

    def test_our_own_spelling_still_works(self) -> None:
        """The generator and the live API both use `type`. Both must keep working."""
        from finctl.schema import ReconType, is_recon_type

        assert is_recon_type({"type": "payment"}, ReconType.PAYMENT)
        assert is_recon_type({"type": "refund"}, ReconType.REFUND)

    def test_an_unknown_discriminator_is_not_coerced(self) -> None:
        """A value we do not recognise stays visible rather than becoming a known one."""
        from finctl.schema import ReconType, is_recon_type, recon_type

        row = {"transaction_entity": "adjustment_of_some_new_kind"}
        assert recon_type(row) == "adjustment_of_some_new_kind"
        assert not is_recon_type(row, ReconType.PAYMENT)
        assert not is_recon_type(row, ReconType.REFUND)

    def test_a_row_with_no_discriminator_returns_none(self) -> None:
        from finctl.schema import recon_type

        assert recon_type({"entity_id": "pay_x"}) is None


SAMPLES = Path(__file__).resolve().parents[2] / "razorpay-sample-files"


class TestExcelIngest:
    """Razorpay's dashboard exports .xlsx, not CSV. ADR-043.

    "Export your settlement report" hands a merchant an Excel file. An upload path that
    accepts only CSV stops a real merchant on step one.
    """

    @staticmethod
    def _write(path: Path, rows: list[list]) -> Path:
        from openpyxl import Workbook

        wb = Workbook()
        for row in rows:
            wb.active.append(row)
        wb.save(path)
        return path

    def test_an_xlsx_ledger_reads_like_a_csv_one(self, tmp_path: Path) -> None:
        p = self._write(tmp_path / "l.xlsx", [
            ["order_id", "amount", "timestamp"],
            ["order_A", "1234.50", "2022-06-29"],
        ])
        rows, _ = normalize_ledger(p)
        assert rows[0]["amount_paise"] == 123450
        assert rows[0]["captured_at"].date() == date(2022, 6, 29)

    def test_numeric_cells_parse_as_money(self, tmp_path: Path) -> None:
        """Excel stores 1234.50 as a float, not the string "1234.50"."""
        p = self._write(tmp_path / "l.xlsx", [
            ["order_id", "amount"], ["order_A", 1234.50],
        ])
        rows, _ = normalize_ledger(p)
        assert rows[0]["amount_paise"] == 123450

    def test_a_real_datetime_cell_is_not_restringified(self, tmp_path: Path) -> None:
        """openpyxl returns datetime objects; re-parsing them would risk ADR-037 again."""
        p = self._write(tmp_path / "l.xlsx", [
            ["order_id", "amount", "timestamp"],
            ["order_A", 100, datetime(2022, 6, 29, 7, 34, 39)],
        ])
        rows, _ = normalize_ledger(p)
        assert rows[0]["captured_at"].date() == date(2022, 6, 29)
        assert rows[0]["captured_at"].tzinfo is not None

    def test_blank_spacer_rows_are_skipped(self, tmp_path: Path) -> None:
        """Excel files are full of them; one would fail money parsing as a row of ''."""
        p = self._write(tmp_path / "l.xlsx", [
            ["order_id", "amount"],
            ["order_A", 100],
            [None, None],
            ["order_B", 200],
        ])
        rows, _ = normalize_ledger(p)
        assert [r["order_id"] for r in rows] == ["order_A", "order_B"]

    def test_an_unmappable_xlsx_still_refuses_to_guess(self, tmp_path: Path) -> None:
        """The refusal is format-independent — it is the whole point of the stage."""
        p = self._write(tmp_path / "l.xlsx", [["foo", "bar"], ["a", "b"]])
        with pytest.raises(NormalizationError, match="could not map required column"):
            normalize_ledger(p)

    def test_an_unsupported_format_is_named(self, tmp_path: Path) -> None:
        p = tmp_path / "l.pdf"
        p.write_bytes(b"%PDF-1.4")
        with pytest.raises(NormalizationError, match="unsupported format"):
            normalize_ledger(p)


@pytest.mark.skipif(not SAMPLES.is_dir(), reason="sample files not present")
class TestRazorpaysOwnExports:
    """Read Razorpay's actual published sample reports. ADR-043.

    Not a substitute for real merchant data — these are tiny and synthetic — but they
    are authoritative for SCHEMA and FORMAT, which is what the upload path needs.
    """

    @pytest.mark.parametrize("name", [
        "sample-settlements-recon-report",
        "sample-payments-report",
        "sample-settlements-report",
        "sample-orders-report",
        "sample-refunds-report",
    ])
    def test_every_sample_export_is_readable(self, name: str) -> None:
        from finctl.normalize.normalizer import _read_tabular

        headers, rows = _read_tabular(SAMPLES / f"{name}.xlsx", name)
        assert headers, f"{name}: no headers"
        assert rows, f"{name}: no rows"
        assert all(h.strip() for h in headers), f"{name}: blank header survived"

    def test_the_settlements_reports_blank_leading_column_is_dropped(self) -> None:
        """That file opens with an empty spacer column. It must not become a field."""
        from finctl.normalize.normalizer import _read_tabular

        headers, _ = _read_tabular(SAMPLES / "sample-settlements-report.xlsx", "s")
        assert headers == ["id", "amount", "status", "fees", "tax", "utr", "created_at"]

    def test_the_recon_export_dates_are_not_1970(self) -> None:
        """The ADR-037 regression, read from the file that revealed it."""
        from finctl.normalize.normalizer import _parse_timestamp, _read_tabular

        _, rows = _read_tabular(SAMPLES / "sample-settlements-recon-report.xlsx", "r")
        for i, row in enumerate(rows, start=2):
            parsed = _parse_timestamp(row["entity_created_at"], "recon", i)
            assert parsed is None or parsed.year != 1970



class TestTheArithmeticAgainstRazorpaysOwnFile:
    """Not just readable — RECONCILED. ADR-056.

    `test_every_sample_export_is_readable` proves the parser survives Razorpay's real
    export. It does not prove the money arithmetic agrees with it, and those are
    different claims: every accuracy figure in METRICS.md is measured against data this
    project generated, where the generator defines truth. That is a closed loop, stated
    plainly at the top of METRICS.md.

    These tests break the loop as far as the available files allow. `sample-settlements-
    recon-report.xlsx` is Razorpay's own document, ten rows, not written by us and not
    written for us. The identity below is the engine's central claim, checked against
    numbers nobody here chose.

    Ten rows is not a merchant's month. The honest description is: the engine's core
    identity holds on real Razorpay-authored rows, and nothing larger has been tested.
    """

    @staticmethod
    @pytest.fixture(scope="class")
    def real_rows() -> list[dict]:
        from finctl.normalize.normalizer import _read_tabular

        # `_read_tabular` already yields dicts keyed by the file's own headers.
        _headers, rows = _read_tabular(
            SAMPLES / "sample-settlements-recon-report.xlsx", "settlements-recon"
        )
        return list(rows)

    def test_the_file_is_razorpays_not_ours(self, real_rows: list[dict]) -> None:
        """Guard against this silently becoming a test of our own fixtures."""
        assert len(real_rows) == 10
        assert all(str(r["entity_id"]).startswith(("pay_", "rfnd_")) for r in real_rows)

    def test_net_equals_amount_less_fee_and_tax_on_every_payment(
        self, real_rows: list[dict]
    ) -> None:
        """The identity the whole engine rests on, on rows we did not write.

        credit - debit == amount - fee - tax, for every payment row. Checked in integer
        paise through the engine's own parser, not in float: the reason `money.py` exists
        is that this arithmetic is where binary floating point drifts, and checking it in
        float would be checking the wrong thing.
        """
        from finctl.money import parse_money

        payments = [r for r in real_rows if r["transaction_entity"] == "payment"]
        assert payments, "the sample file must contain payment rows"

        for row in payments:
            amount = parse_money(row["amount"])
            fee = parse_money(row["fee (exclusive tax)"])
            tax = parse_money(row["tax"])
            credit = parse_money(row["credit"])
            debit = parse_money(row["debit"])

            assert credit - debit == amount - fee - tax, (
                f"{row['entity_id']}: net {credit - debit} != "
                f"{amount} - {fee} - {tax} = {amount - fee - tax}"
            )

    def test_a_refund_row_inverts_the_sign(self, real_rows: list[dict]) -> None:
        """The one row where the identity does NOT hold, and must not.

        A refund is a DEBIT: money leaving the settlement to go back to a customer. It
        nets negative against an amount that is positive, which is exactly why gap.py
        books refunds as their own signed component rather than folding them in with
        payments. Asserting the exception is what makes the rule above meaningful.
        """
        from finctl.money import parse_money

        refunds = [r for r in real_rows if r["transaction_entity"] == "refund"]
        assert len(refunds) == 1, "row 10 of Razorpay's sample is the refund"

        row = refunds[0]
        assert parse_money(row["debit"]) > 0
        assert parse_money(row["credit"]) == 0
        assert not row.get("order_id"), (
            "this refund carries no order_id — the fact ADR-039 was written for"
        )

    def test_the_engine_parses_both_date_formats_in_one_column(
        self, real_rows: list[dict]
    ) -> None:
        """Razorpay's own file mixes them, in the same column.

        `entity_created_at` holds real datetimes on some rows and the string
        '29/06/2022 07:34:39' on others — DD/MM/YYYY, which a naive parser reads as
        29 June or as an error, and a US-defaulting one reads as neither. This is the
        kind of thing no generator produces because nobody would think to generate it.
        """
        from finctl.normalize.normalizer import to_date

        parsed = [to_date(r["entity_created_at"]) for r in real_rows]
        assert all(d is not None for d in parsed), (
            "a date in Razorpay's own export failed to parse"
        )
        # All ten rows are from 2022; a DD/MM read as MM/DD would still land in 2022,
        # so the year alone proves little — the day-of-month is what separates them.
        assert {d.year for d in parsed} == {2022}

    def test_fees_are_a_plausible_rate_of_the_amount(self, real_rows: list[dict]) -> None:
        """A sanity check on real numbers, not a rate-card assertion.

        These rows are ₹1.00 test transactions with a ₹0.01 fee — 1%, which is not any
        published Razorpay rate and is an artefact of the sample being a test account.
        So this asserts only that the fee is a SANE fraction of the amount: the check
        that would catch a parser reading paise as rupees, which is the actual risk when
        ingesting a file whose amounts are written in rupees with decimals.
        """
        from finctl.money import parse_money

        for row in real_rows:
            amount = parse_money(row["amount"])
            fee = parse_money(row["fee (exclusive tax)"])
            if amount and fee:
                assert 0 < fee < amount, (
                    f"{row['entity_id']}: fee {fee} is not a sane fraction of {amount}"
                )

    def test_a_naive_datetime_is_not_shifted_by_the_machines_timezone(self) -> None:
        """openpyxl returns NAIVE datetimes, and they are already UTC. ADR-056.

        `.astimezone(UTC)` interprets a naive value as LOCAL time, so on an IST machine
        (+5:30) a settlement stamped 02:00 read as the PREVIOUS day. Silent, machine-
        dependent, and an off-by-one on a settlement date — the exact class of error this
        engine exists to find in other people's systems.

        The sample file's own rows are afternoon timestamps, so the bug was latent there:
        it needed a value near midnight to surface, which is why it survived until the
        arithmetic was run against a real file and the parsing was checked directly.
        """
        from finctl.normalize.normalizer import to_date

        for hour in (0, 2, 5, 12, 23):
            naive = datetime(2022, 6, 29, hour, 0)
            assert to_date(naive) == date(2022, 6, 29), (
                f"a naive {hour:02d}:00 datetime moved off 2022-06-29"
            )

    def test_an_aware_datetime_is_still_converted(self) -> None:
        """The fix must not stop honouring a timezone that IS declared."""
        from datetime import timedelta, timezone

        from finctl.normalize.normalizer import to_date

        ist = timezone(timedelta(hours=5, minutes=30))
        # 02:00 IST is 20:30 UTC the previous day, and that conversion is correct.
        assert to_date(datetime(2022, 6, 29, 2, 0, tzinfo=ist)) == date(2022, 6, 28)

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("29/06/2022 07:34:39", date(2022, 6, 29)),   # verbatim from the real file
            ("29-06-2022", date(2022, 6, 29)),
            ("2022-06-29", date(2022, 6, 29)),
            ("1656460800", date(2022, 6, 29)),            # epoch seconds
        ],
    )
    def test_to_date_reads_every_format_the_real_parser_does(
        self, raw: str, expected: date
    ) -> None:
        """There were two date parsers and only one of them was good. ADR-056.

        `to_date` reached only `date.fromisoformat`, so it raised a bare ValueError on
        '29/06/2022 07:34:39' — a string taken verbatim from Razorpay's own settlement
        export, in the very column `_parse_timestamp`'s docstring cites. It now delegates.
        """
        from finctl.normalize.normalizer import to_date

        assert to_date(raw) == expected

    def test_an_unreadable_date_still_says_how_to_fix_it(self) -> None:
        """A bare ValueError is a stack trace; this engine's errors are instructions."""
        from finctl.normalize.normalizer import NormalizationError, to_date

        with pytest.raises(NormalizationError) as exc:
            to_date("not-a-date")
        assert "Accepted" in str(exc.value)
