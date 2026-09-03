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

    monkeypatch.setattr(main, "DATA_ROOT", tmp_path / "data")
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
        detail = r.json()["detail"]
        assert "could not map required column" in detail
        assert "order_id" in detail
        assert "Accepted spellings" in detail

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
