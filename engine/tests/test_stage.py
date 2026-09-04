"""Staging tests.

Immutability is what makes the audit trail possible. If a second run can mutate the
first run's records, the audit log describes a state that no longer exists.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from finctl.config.loader import load_config
from finctl.generate.generator import Generator
from finctl.generate.writer import write_batch
from finctl.schema import Source
from finctl.stage.staging import (
    DuplicateBatchError,
    StagedBatch,
    content_hash,
    stage_from_dir,
)


@pytest.fixture
def batch_dir(tmp_path: Path) -> Path:
    batch = Generator(load_config(), seed=1, volume=120, defect_profile="demo").generate()
    write_batch(batch, tmp_path)
    return tmp_path


class TestContentHash:
    def test_identical_content_hashes_identically(self) -> None:
        assert content_hash([{"a": 1}]) == content_hash([{"a": 1}])

    def test_key_order_does_not_change_the_hash(self) -> None:
        """The hash must depend on DATA, not on serialisation accidents."""
        assert content_hash([{"a": 1, "b": 2}]) == content_hash([{"b": 2, "a": 1}])

    def test_different_content_hashes_differently(self) -> None:
        assert content_hash([{"a": 1}]) != content_hash([{"a": 2}])


class TestDuplicateDetection:
    def test_same_content_twice_is_refused(self) -> None:
        """Adversarial case: the same file uploaded twice.

        Silently accepting would double every total, and the merchant could not tell
        that from real growth.
        """
        b = StagedBatch(batch_id="t")
        rows = [{"order_id": "O1", "amount_paise": 100}]
        b.add(Source.LEDGER, rows, "ledger.csv")
        with pytest.raises(DuplicateBatchError, match="already staged"):
            b.add(Source.BANK, list(rows), "ledger-copy.csv")

    def test_duplicate_detection_ignores_the_filename(self) -> None:
        """Same rows under a different name are still a duplicate."""
        b = StagedBatch(batch_id="t")
        rows = [{"utr": "U1", "credit_paise": 500}]
        b.add(Source.BANK, rows, "bank.csv")
        with pytest.raises(DuplicateBatchError):
            b.add(Source.RECON, list(rows), "bank_FINAL_v2.csv")

    def test_the_error_names_both_origins(self) -> None:
        b = StagedBatch(batch_id="t")
        rows = [{"order_id": "O1"}]
        b.add(Source.LEDGER, rows, "first.csv")
        with pytest.raises(DuplicateBatchError) as exc:
            b.add(Source.BANK, list(rows), "second.csv")
        assert "first.csv" in str(exc.value)
        assert "second.csv" in str(exc.value)

    def test_restaging_the_same_source_is_refused(self) -> None:
        b = StagedBatch(batch_id="t")
        b.add(Source.LEDGER, [{"order_id": "O1"}], "a.csv")
        with pytest.raises(ValueError, match="already staged"):
            b.add(Source.LEDGER, [{"order_id": "O2"}], "b.csv")


class TestImmutability:
    def test_a_sealed_batch_refuses_new_sources(self) -> None:
        b = StagedBatch(batch_id="t")
        b.add(Source.LEDGER, [{"order_id": "O1"}], "a.csv")
        b.seal()
        with pytest.raises(ValueError, match="sealed"):
            b.add(Source.BANK, [{"utr": "U1"}], "b.csv")

    def test_staged_rows_are_a_tuple_not_a_mutable_list(self) -> None:
        b = StagedBatch(batch_id="t")
        staged = b.add(Source.LEDGER, [{"order_id": "O1"}], "a.csv")
        assert isinstance(staged.rows, tuple)

    def test_mutating_the_caller_list_afterwards_does_not_change_the_batch(self) -> None:
        """Staging must snapshot, not alias. Otherwise a later edit rewrites history."""
        b = StagedBatch(batch_id="t")
        rows = [{"order_id": "O1"}]
        b.add(Source.LEDGER, rows, "a.csv")
        rows.append({"order_id": "O2"})
        assert len(b.get(Source.LEDGER)) == 1


class TestStageFromDir:
    def test_stages_every_source(self, batch_dir: Path) -> None:
        b = stage_from_dir(batch_dir)
        for source in (Source.LEDGER, Source.BANK, Source.RECON,
                       Source.PAYMENTS, Source.SUBSCRIPTIONS):
            assert b.get(source), source

    def test_result_is_sealed(self, batch_dir: Path) -> None:
        assert stage_from_dir(batch_dir).manifest()["sealed"] is True

    def test_missing_bank_file_is_two_way_recon_not_an_error(self, batch_dir: Path) -> None:
        """A supported configuration, not a failure. The manifest records the absence."""
        (batch_dir / "bank.csv").unlink()
        b = stage_from_dir(batch_dir)
        assert b.get(Source.BANK) == ()
        assert "bank" not in b.manifest()["sources"]

    def test_require_names_what_was_staged(self, batch_dir: Path) -> None:
        (batch_dir / "bank.csv").unlink()
        b = stage_from_dir(batch_dir)
        with pytest.raises(ValueError, match="no bank data staged"):
            b.require(Source.BANK)

    def test_manifest_records_the_column_mapping(self, batch_dir: Path) -> None:
        """'Which column did you read as the amount?' must be answerable."""
        m = stage_from_dir(batch_dir).manifest()
        assert "amount_paise" in m["sources"]["ledger"]["column_mapping"]

    def test_restaging_the_same_directory_is_reproducible(self, batch_dir: Path) -> None:
        """Re-running must not mutate anything or produce a different hash."""
        a = stage_from_dir(batch_dir).manifest()
        b = stage_from_dir(batch_dir).manifest()
        assert a["sources"] == b["sources"]


class TestExcelBatches:
    """A batch supplied as .xlsx must reconcile identically to the same batch as .csv.

    ADR-043. If the two formats can produce different answers, the upload path is a
    second implementation of the engine rather than a second door into it.
    """

    @staticmethod
    def _as_xlsx(src: Path, dst: Path) -> Path:
        import csv as _csv
        import shutil

        from openpyxl import Workbook

        for name in ("ledger", "bank"):
            csv_path = src / f"{name}.csv"
            if not csv_path.exists():
                continue
            wb = Workbook()
            with csv_path.open() as fh:
                for row in _csv.reader(fh):
                    wb.active.append(row)
            wb.save(dst / f"{name}.xlsx")
        for j in src.glob("*.json"):
            shutil.copy(j, dst / j.name)
        return dst

    def test_an_xlsx_batch_reconciles_identically_to_csv(self, tmp_path: Path) -> None:
        from finctl.config.loader import load_config
        from finctl.generate.generator import Generator
        from finctl.generate.writer import write_batch
        from finctl.pipeline import run

        src = tmp_path / "csv"
        src.mkdir()
        write_batch(Generator(load_config(), seed=20260902, volume=200,
                              defect_profile="demo").generate(), src)
        dst = tmp_path / "xlsx"
        dst.mkdir()
        self._as_xlsx(src, dst)

        from_csv, from_xlsx = run(src), run(dst)

        assert from_xlsx.verdict.gap_paise == from_csv.verdict.gap_paise
        assert from_xlsx.verdict.headline() == from_csv.verdict.headline()
        assert from_xlsx.scored.total_missed == from_csv.scored.total_missed == 0
        assert from_xlsx.scored.false_positives == from_csv.scored.false_positives == []
        assert from_xlsx.scored.decoys_claimed == from_csv.scored.decoys_claimed == []

    def test_the_manifest_records_which_file_was_actually_read(self, tmp_path: Path) -> None:
        """'Which column did you read as the amount?' must stay answerable per format."""
        from finctl.config.loader import load_config
        from finctl.generate.generator import Generator
        from finctl.generate.writer import write_batch

        src = tmp_path / "csv"
        src.mkdir()
        write_batch(Generator(load_config(), seed=1, volume=50,
                              defect_profile="clean").generate(), src)
        dst = tmp_path / "xlsx"
        dst.mkdir()
        self._as_xlsx(src, dst)

        manifest = stage_from_dir(dst).manifest()
        assert manifest["sources"]["ledger"]["origin"].endswith("ledger.xlsx")
        assert manifest["sources"]["ledger"]["column_mapping"]

