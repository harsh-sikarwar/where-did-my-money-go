"""Upload-path tests. ADR-044.

The upload endpoint is the difference between "a well-engineered engine demonstrated on
data it generated itself" and a tool a merchant can hand a file to. These tests exercise
it through the real ASGI app, against real generated batches.

What they deliberately do NOT do is re-test reconciliation. The endpoint calls the same
`run()` the CLI does (ADR-001), and if the upload path ever needs its own reconciliation
tests, that is the signal it has become a second implementation of the engine.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parents[2] / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from finctl.config.loader import load_config  # noqa: E402
from finctl.generate.generator import Generator  # noqa: E402
from finctl.generate.writer import write_batch  # noqa: E402


@pytest.fixture(scope="module")
def source_batch(tmp_path_factory) -> Path:
    """One generated batch, reused as the bytes every upload test posts."""
    out = tmp_path_factory.mktemp("source")
    write_batch(Generator(load_config(), seed=20260902, volume=200,
                          defect_profile="demo").generate(), out)
    return out


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A client whose DATA_ROOT is a fresh directory, so uploads never collide."""
    import main

    data_root = tmp_path / "data"
    monkeypatch.setattr(main, "DATA_ROOT", data_root)
    # MAPPINGS_PATH is derived from DATA_ROOT at import time, so it must be patched
    # too — otherwise remembered mappings leak between tests via the real data
    # directory, which is also how they would leak between merchants.
    monkeypatch.setattr(main, "MAPPINGS_PATH", data_root / "column-mappings.json")
    monkeypatch.setattr(main, "RATE_CARD_PATH", data_root / "merchant-rate-card.json")
    monkeypatch.setattr(main, "_cache", {})
    return TestClient(main.app)


def files_for(batch_dir: Path, *slots: str) -> dict:
    """Build a multipart payload from a generated batch directory."""
    names = {
        "ledger": ("ledger.csv", "text/csv"),
        "bank": ("bank.csv", "text/csv"),
        "recon": ("settlement_recon.json", "application/json"),
        "payments": ("payments.json", "application/json"),
        "subscriptions": ("subscriptions.json", "application/json"),
    }
    out = {}
    for slot in slots:
        filename, mime = names[slot]
        out[slot] = (filename, (batch_dir / filename).read_bytes(), mime)
    return out


ALL_SLOTS = ("ledger", "bank", "recon", "payments", "subscriptions")


class TestUpload:
    def test_a_complete_upload_reconciles(self, client, source_batch) -> None:
        r = client.post("/api/upload", data={"batch": "september"},
                        files=files_for(source_batch, *ALL_SLOTS))
        assert r.status_code == 200
        body = r.json()
        assert body["rows_processed"] > 0
        assert body["missing_sources"] == []
        assert body["note"] is None
        assert "customers" in body["headline"]

    def test_the_uploaded_batch_is_then_reachable(self, client, source_batch) -> None:
        """An upload that cannot be read back is a write-only endpoint."""
        client.post("/api/upload", data={"batch": "september"},
                    files=files_for(source_batch, *ALL_SLOTS))
        r = client.get("/api/verdict/september")
        assert r.status_code == 200
        assert r.json()["lines"]

        listed = client.get("/api/batches").json()["batches"]
        assert any(b["name"] == "september" and b["uploaded"] for b in listed)

    def test_the_manifest_says_what_was_actually_read(self, client, source_batch) -> None:
        """'Which column did you read as the amount?' must survive an upload."""
        r = client.post("/api/upload", data={"batch": "september"},
                        files=files_for(source_batch, *ALL_SLOTS))
        sources = r.json()["manifest"]["sources"]
        assert sources["ledger"]["column_mapping"]
        assert sources["ledger"]["sha256"]


class TestMissingLegsAreReportedNotRejected:
    """The engine has real answers for absent files. Refusing the upload discards them."""

    def test_ledger_and_recon_alone_still_reconcile(self, client, source_batch) -> None:
        r = client.post("/api/upload", data={"batch": "twoway"},
                        files=files_for(source_batch, "ledger", "recon"))
        assert r.status_code == 200
        assert set(r.json()["missing_sources"]) == {"bank", "payments", "subscriptions"}

    def test_a_missing_bank_file_is_explained_as_in_flight(self, client, source_batch) -> None:
        """The good demo: money in flight is a better answer than money missing."""
        r = client.post("/api/upload", data={"batch": "twoway"},
                        files=files_for(source_batch, "ledger", "recon"))
        assert "in flight" in r.json()["note"]

    def test_a_missing_subscriptions_file_names_the_lost_capability(
        self, client, source_batch
    ) -> None:
        r = client.post("/api/upload", data={"batch": "nosubs"},
                        files=files_for(source_batch, "ledger", "bank", "recon", "payments"))
        assert "halted-subscription correlation is unavailable" in r.json()["note"]

    def test_a_ledger_is_required(self, client, source_batch) -> None:
        """The one leg with no sensible default: there is nothing to reconcile against."""
        r = client.post("/api/upload", data={"batch": "noledger"},
                        files=files_for(source_batch, "recon"))
        assert r.status_code == 422


class TestExcelUpload:
    def test_an_xlsx_ledger_uploads(self, client, source_batch, tmp_path) -> None:
        """Razorpay's dashboard exports .xlsx. ADR-043."""
        from openpyxl import Workbook

        wb = Workbook()
        with (source_batch / "ledger.csv").open() as fh:
            for row in csv.reader(fh):
                wb.active.append(row)
        xlsx = tmp_path / "ledger.xlsx"
        wb.save(xlsx)

        r = client.post("/api/upload", data={"batch": "excel"}, files={
            "ledger": ("ledger.xlsx", xlsx.read_bytes(),
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            "recon": ("settlement_recon.json",
                      (source_batch / "settlement_recon.json").read_bytes(),
                      "application/json"),
        })
        assert r.status_code == 200
        assert r.json()["rows_processed"] > 0


class TestBadInput:
    def test_unmappable_columns_surface_the_normalizers_message(
        self, client, source_batch
    ) -> None:
        """That message names the column and lists accepted spellings — it IS the fix.

        Flattening it to "bad file" would discard the most useful part, and it is what
        the column-mapping UI will render.
        """
        r = client.post("/api/upload", data={"batch": "bad"},
                        files={"ledger": ("l.csv", b"foo,bar\n1,2\n", "text/csv")})
        assert r.status_code == 422
        # Structured since ADR-045: the picker needs data, not a paragraph. The
        # paragraph is still there, under `message`, because it is what a CLI user reads.
        detail = r.json()["detail"]
        assert detail["error"] == "unmapped_columns"
        assert "could not map required column" in detail["message"]
        assert "order_id" in detail["message"]
        assert "Accepted spellings" in detail["message"]

    def test_a_wrong_format_for_the_slot_is_named(self, client) -> None:
        r = client.post("/api/upload", data={"batch": "pdf"},
                        files={"ledger": ("l.pdf", b"%PDF-1.4", "application/pdf")})
        assert r.status_code == 400
        assert "expected" in r.json()["detail"]

    def test_a_json_slot_refuses_a_csv(self, client, source_batch) -> None:
        """Recon is a Razorpay collection envelope, not a tabular export (ADR-008)."""
        r = client.post("/api/upload", data={"batch": "csvrecon"}, files={
            "ledger": ("ledger.csv", (source_batch / "ledger.csv").read_bytes(), "text/csv"),
            "recon": ("recon.csv", b"a,b\n1,2\n", "text/csv"),
        })
        assert r.status_code == 400

    @pytest.mark.parametrize("name", ["../escape", "a/b", ".hidden", "", "has space"])
    def test_batch_names_that_could_escape_are_refused(
        self, client, source_batch, name: str
    ) -> None:
        r = client.post("/api/upload", data={"batch": name},
                        files=files_for(source_batch, "ledger", "recon"))
        assert r.status_code in (400, 422)

    def test_reusing_a_batch_name_is_refused(self, client, source_batch) -> None:
        """Staging entries are immutable; corrections create a new batch."""
        payload = files_for(source_batch, "ledger", "recon")
        assert client.post("/api/upload", data={"batch": "dup"},
                           files=payload).status_code == 200
        r = client.post("/api/upload", data={"batch": "dup"},
                        files=files_for(source_batch, "ledger", "recon"))
        assert r.status_code == 409
        assert "immutable" in r.json()["detail"]

    def test_a_failed_upload_leaves_no_half_written_batch(self, client) -> None:
        """A partial directory would be staged on the next request and silently
        reconcile an incomplete upload."""
        import main

        client.post("/api/upload", data={"batch": "willfail"},
                    files={"ledger": ("l.csv", b"foo,bar\n1,2\n", "text/csv")})
        assert not (main.DATA_ROOT / "willfail").exists()
        assert client.get("/api/batches").json()["batches"] == []


class TestColumnMappingFlow:
    """Refuse -> inspect -> remember -> succeed. ADR-045.

    The refusal is correct and it is also a dead end unless a merchant can act on it.
    These four steps are the loop that turns a 422 into a one-time question.
    """

    @pytest.fixture
    def weird_ledger(self, source_batch, tmp_path) -> bytes:
        """The same ledger with column names our alias table does not know."""
        rows = list(csv.reader((source_batch / "ledger.csv").open()))
        rows[0] = ["txn_ref", "sale_value", "when", "buyer", "rail"]
        out = tmp_path / "weird.csv"
        with out.open("w", newline="") as fh:
            csv.writer(fh).writerows(rows)
        return out.read_bytes()

    @staticmethod
    def _payload(source_batch, weird: bytes) -> dict:
        return {
            "ledger": ("weird.csv", weird, "text/csv"),
            "recon": ("settlement_recon.json",
                      (source_batch / "settlement_recon.json").read_bytes(),
                      "application/json"),
        }

    def test_an_unfamiliar_file_returns_a_pickable_error(
        self, client, source_batch, weird_ledger
    ) -> None:
        r = client.post("/api/upload", data={"batch": "weird"},
                        files=self._payload(source_batch, weird_ledger))
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert detail["error"] == "unmapped_columns"
        assert {u["canonical"] for u in detail["unmapped"]} == {"order_id", "amount_paise"}
        # Every unclaimed column is offered — not a ranked guess. A plausible wrong
        # suggestion accepted without thought is worse than no suggestion.
        assert "txn_ref" in detail["unmapped"][0]["candidates"]

    def test_inspect_shows_the_columns_and_real_sample_values(
        self, client, weird_ledger
    ) -> None:
        """A merchant choosing between two columns needs to see what is IN them."""
        r = client.post("/api/inspect", data={"source": "ledger"},
                        files={"file": ("weird.csv", weird_ledger, "text/csv")})
        assert r.status_code == 200
        body = r.json()
        assert body["headers"][:2] == ["txn_ref", "sale_value"]
        assert body["remembered_mapping"] is None
        assert body["sample_rows"]
        assert body["sample_rows"][0]["txn_ref"].startswith("order_")

    def test_remembering_makes_the_next_upload_succeed(
        self, client, source_batch, weird_ledger
    ) -> None:
        """THE loop. Asked once, then never again for that file shape."""
        headers = ["txn_ref", "sale_value", "when", "buyer", "rail"]
        assert client.post("/api/mappings", json={
            "source": "ledger", "headers": headers,
            "mapping": {"order_id": "txn_ref", "amount_paise": "sale_value",
                        "captured_at": "when"},
        }).status_code == 200

        r = client.post("/api/upload", data={"batch": "weird"},
                        files=self._payload(source_batch, weird_ledger))
        assert r.status_code == 200
        assert r.json()["rows_processed"] > 0

    def test_the_manifest_distinguishes_recognised_from_told(
        self, client, source_batch, weird_ledger
    ) -> None:
        """'We recognised this column' and 'someone told us' are different claims."""
        headers = ["txn_ref", "sale_value", "when", "buyer", "rail"]
        client.post("/api/mappings", json={
            "source": "ledger", "headers": headers,
            "mapping": {"order_id": "txn_ref", "amount_paise": "sale_value",
                        "captured_at": "when"},
        })
        r = client.post("/api/upload", data={"batch": "weird"},
                        files=self._payload(source_batch, weird_ledger))
        recorded = r.json()["manifest"]["sources"]["ledger"]["column_mapping"]
        assert "mapped by hand" in recorded
        # `rail` was resolved by the alias table, not by the human.
        assert "'rail'->payment_method" in recorded

    def test_a_reordered_export_next_month_is_still_recognised(
        self, client, source_batch, tmp_path
    ) -> None:
        """Export tools reorder columns. That is not a different file."""
        rows = list(csv.reader((source_batch / "ledger.csv").open()))
        rows[0] = ["txn_ref", "sale_value", "when", "buyer", "rail"]
        reordered = [[r[2], r[0], r[1], r[3], r[4]] for r in rows]
        out = tmp_path / "reordered.csv"
        with out.open("w", newline="") as fh:
            csv.writer(fh).writerows(reordered)

        client.post("/api/mappings", json={
            "source": "ledger", "headers": ["txn_ref", "sale_value", "when", "buyer", "rail"],
            "mapping": {"order_id": "txn_ref", "amount_paise": "sale_value",
                        "captured_at": "when"},
        })
        r = client.post("/api/upload", data={"batch": "nextmonth"}, files={
            "ledger": ("reordered.csv", out.read_bytes(), "text/csv"),
            "recon": ("settlement_recon.json",
                      (source_batch / "settlement_recon.json").read_bytes(),
                      "application/json"),
        })
        assert r.status_code == 200

    def test_a_mapping_naming_a_column_not_in_the_file_is_refused(self, client) -> None:
        """Refusing to remember a mapping that cannot apply to the file it describes."""
        r = client.post("/api/mappings", json={
            "source": "ledger", "headers": ["a", "b"],
            "mapping": {"order_id": "nope"},
        })
        assert r.status_code == 400

    def test_remembered_mappings_are_listable(self, client) -> None:
        """A merchant must be able to see, and therefore correct, what was recorded."""
        client.post("/api/mappings", json={
            "source": "ledger", "headers": ["a", "b"], "mapping": {"order_id": "a"},
        })
        listed = client.get("/api/mappings").json()["mappings"]
        assert len(listed) == 1
        assert listed[0]["source"] == "ledger"
        assert listed[0]["mapping"] == {"order_id": "a"}


class TestMerchantRateCard:
    """"You were charged this, your contract says that" — with THEIR number. ADR-046."""

    @staticmethod
    def _upload(client, source_batch):
        return client.post("/api/upload", data={"batch": "b"},
                           files=files_for(source_batch, *ALL_SLOTS))

    @staticmethod
    def _fee_findings(client) -> tuple[int, int]:
        body = client.get("/api/detail/b/FEE").json()
        return body["count"], body["total"]["paise"]

    def test_the_default_card_is_ours_and_says_so(self, client) -> None:
        body = client.get("/api/rate-card").json()
        assert body["name"] == "standard-india-2026"
        assert body["is_merchant_supplied"] is False
        assert all(m["source"] == "standard" for m in body["methods"])

    def test_setting_contracted_rates_marks_only_those_lines(self, client) -> None:
        """A merchant must be able to see which comparison used their number."""
        body = client.put("/api/rate-card",
                          json={"name": "acme", "methods": {"upi": 175}}).json()
        assert body["is_merchant_supplied"] is True
        by_method = {m["method"]: m for m in body["methods"]}
        assert by_method["upi"]["source"] == "merchant"
        assert by_method["upi"]["mdr_bps"] == 175
        assert by_method["netbanking"]["source"] == "standard"

    def test_a_lower_contracted_rate_finds_more_overcharge(
        self, client, source_batch
    ) -> None:
        """THE product question. Same data, different contract, different answer."""
        self._upload(client, source_batch)
        standard_count, standard_paise = self._fee_findings(client)

        client.put("/api/rate-card", json={"methods": {
            m: 175 for m in ("upi", "card_credit", "card_debit", "netbanking", "wallet")
        }})
        merchant_count, merchant_paise = self._fee_findings(client)

        assert merchant_count > standard_count
        assert merchant_paise > standard_paise

    def test_changing_the_card_invalidates_cached_runs(
        self, client, source_batch
    ) -> None:
        """A cached run was scored against the OLD card. Serving it would show a
        merchant fee findings computed from rates they have just replaced."""
        self._upload(client, source_batch)
        before = self._fee_findings(client)
        client.put("/api/rate-card", json={"methods": {"card_credit": 100}})
        assert self._fee_findings(client) != before

    def test_clearing_reverts_to_the_standard_card(self, client, source_batch) -> None:
        self._upload(client, source_batch)
        before = self._fee_findings(client)
        client.put("/api/rate-card", json={"methods": {"card_credit": 100}})
        client.delete("/api/rate-card")
        assert self._fee_findings(client) == before
        assert client.get("/api/rate-card").json()["is_merchant_supplied"] is False

    def test_a_unit_error_is_refused_before_it_is_stored(self, client) -> None:
        """"2" meaning 2% is 0.02% in bps and would flag every row. Refuse the absurd end."""
        r = client.put("/api/rate-card", json={"methods": {"upi": 20_000}})
        assert r.status_code == 422
        assert "BASIS POINTS" in r.json()["detail"]
        assert client.get("/api/rate-card").json()["is_merchant_supplied"] is False

    def test_an_empty_payload_is_refused(self, client) -> None:
        assert client.put("/api/rate-card", json={}).status_code == 400

