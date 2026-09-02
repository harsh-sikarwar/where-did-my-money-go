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
