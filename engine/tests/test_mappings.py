"""Remembered column mappings. ADR-045.

The refusal to guess is right and it is also a wall a merchant hits every week if the
answer is never remembered. What is stored is a decision a HUMAN made, reapplied only to
a file with the same columns — so a remembered mapping is never an inference about a
file whose shape nobody has confirmed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from finctl.normalize.mappings import MappingStore, header_fingerprint
from finctl.normalize.normalizer import (
    NormalizationError,
    UnmappedColumnsError,
    normalize_ledger,
)

HEADERS = ["txn_ref", "sale_value", "when"]
CHOICE = {"order_id": "txn_ref", "amount_paise": "sale_value", "captured_at": "when"}


def write_csv(path: Path, text: str) -> Path:
    path.write_text(text)
    return path


@pytest.fixture
def store(tmp_path: Path) -> MappingStore:
    return MappingStore(tmp_path / "column-mappings.json")


class TestFingerprint:
    def test_column_order_does_not_change_the_shape(self) -> None:
        """An export tool that reorders columns has not produced a different file."""
        assert header_fingerprint(["a", "b", "c"]) == header_fingerprint(["c", "a", "b"])

    def test_capitalisation_and_punctuation_do_not_either(self) -> None:
        """Exactly as tolerant as resolve_columns already is, and no more."""
        assert header_fingerprint(["Order ID"]) == header_fingerprint(["order_id"])

    def test_a_different_column_set_is_a_different_shape(self) -> None:
        """Correct: nobody has confirmed a mapping for the file with the extra column."""
        assert header_fingerprint(["a", "b"]) != header_fingerprint(["a", "b", "c"])


class TestStore:
    def test_nothing_is_remembered_until_a_human_decides(self, store) -> None:
        assert store.lookup("ledger", HEADERS) is None

    def test_a_decision_is_recalled_for_the_same_shape(self, store) -> None:
        store.remember("ledger", HEADERS, CHOICE)
        assert store.lookup("ledger", HEADERS) == CHOICE

    def test_it_survives_a_reload(self, store) -> None:
        store.remember("ledger", HEADERS, CHOICE)
        assert MappingStore(store.path).lookup("ledger", HEADERS) == CHOICE

    def test_a_mapping_does_not_leak_between_sources(self, store) -> None:
        """The same headers mean different things in a ledger and a bank statement."""
        store.remember("ledger", HEADERS, CHOICE)
        assert store.lookup("bank", HEADERS) is None

    def test_reconfirming_replaces_rather_than_merges(self, store) -> None:
        """A merchant correcting a mistake must not be left half-corrected."""
        store.remember("ledger", HEADERS, CHOICE)
        store.remember("ledger", HEADERS, {"order_id": "when"})
        assert store.lookup("ledger", HEADERS) == {"order_id": "when"}

    def test_a_corrupt_store_does_not_break_reconciliation(self, tmp_path: Path) -> None:
        """Cost of ignoring it: one more mapping question. Cost of raising: no recon."""
        path = tmp_path / "m.json"
        path.write_text("{ not json at all")
        assert MappingStore(path).lookup("ledger", HEADERS) is None

    def test_forget_removes_it(self, store) -> None:
        store.remember("ledger", HEADERS, CHOICE)
        assert store.forget("ledger", HEADERS)
        assert store.lookup("ledger", HEADERS) is None


class TestOverridesInNormalize:
    def test_an_unmappable_file_carries_what_a_picker_needs(self, tmp_path: Path) -> None:
        p = write_csv(tmp_path / "l.csv", "txn_ref,sale_value\nX1,10.00\n")
        with pytest.raises(UnmappedColumnsError) as exc:
            normalize_ledger(p)

        body = exc.value.as_dict()
        assert body["error"] == "unmapped_columns"
        assert {u["canonical"] for u in body["unmapped"]} == {"order_id", "amount_paise"}
        for entry in body["unmapped"]:
            assert entry["accepted_spellings"]
            assert entry["candidates"] == ["txn_ref", "sale_value"]

    def test_it_is_still_a_normalization_error(self, tmp_path: Path) -> None:
        """Existing handlers and tests must keep working — the message is unchanged."""
        p = write_csv(tmp_path / "l.csv", "txn_ref,sale_value\nX1,10.00\n")
        with pytest.raises(NormalizationError, match="Refusing to guess"):
            normalize_ledger(p)

    def test_a_human_mapping_resolves_the_file(self, tmp_path: Path) -> None:
        p = write_csv(tmp_path / "l.csv", "txn_ref,sale_value,when\nX1,1234.50,2022-06-29\n")
        rows, _ = normalize_ledger(p, CHOICE)
        assert rows[0]["order_id"] == "X1"
        assert rows[0]["amount_paise"] == 123450

    def test_the_audit_trail_says_which_fields_a_human_chose(self, tmp_path: Path) -> None:
        """'We recognised this column' and 'someone told us' are different claims."""
        p = write_csv(tmp_path / "l.csv", "txn_ref,sale_value,when\nX1,1234.50,2022-06-29\n")
        _, mapping = normalize_ledger(p, CHOICE)
        assert set(mapping.overridden) == set(CHOICE)
        assert "mapped by hand" in mapping.describe()

    def test_an_override_beats_the_alias_table(self, tmp_path: Path) -> None:
        """A person who looked at their own export knows more than our alias list."""
        p = write_csv(tmp_path / "l.csv", "order_id,amount,total\nX1,10.00,99.00\n")
        rows, _ = normalize_ledger(p, {"amount_paise": "total"})
        assert rows[0]["amount_paise"] == 9900

    def test_an_override_naming_a_missing_column_is_refused(self, tmp_path: Path) -> None:
        """Silently ignoring it would fall through and map something unasked-for."""
        p = write_csv(tmp_path / "l.csv", "txn_ref,sale_value\nX1,10.00\n")
        with pytest.raises(NormalizationError, match="not in the file"):
            normalize_ledger(p, {"order_id": "nope"})

    def test_an_override_for_an_unknown_field_is_refused(self, tmp_path: Path) -> None:
        p = write_csv(tmp_path / "l.csv", "txn_ref,sale_value\nX1,10.00\n")
        with pytest.raises(NormalizationError, match="unknown field"):
            normalize_ledger(p, {"not_a_field": "txn_ref"})

    def test_one_column_cannot_serve_two_fields(self, tmp_path: Path) -> None:
        p = write_csv(tmp_path / "l.csv", "a,b\nX1,10.00\n")
        with pytest.raises(NormalizationError, match="more than one field"):
            normalize_ledger(p, {"order_id": "a", "customer_id": "a"})


class TestStagingUsesRememberedMappings:
    def test_a_remembered_mapping_makes_an_unreadable_batch_readable(
        self, tmp_path: Path, store
    ) -> None:
        """The whole point: asked once, then never again for that file shape."""
        from finctl.schema import Source
        from finctl.stage.staging import stage_from_dir

        data = tmp_path / "batch"
        data.mkdir()
        write_csv(data / "ledger.csv", "txn_ref,sale_value,when\nX1,1234.50,2022-06-29\n")

        with pytest.raises(UnmappedColumnsError):
            stage_from_dir(data)

        store.remember("ledger", ["txn_ref", "sale_value", "when"], CHOICE)
        batch = stage_from_dir(data, mappings=store)
        assert batch.get(Source.LEDGER)
