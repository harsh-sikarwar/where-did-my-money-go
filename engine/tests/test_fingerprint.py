"""The metrics fingerprint. See `finctl/fingerprint.py`.

The fingerprint exists to turn a prose claim about determinism into sixteen characters a
reader can check. That only works if it is stable for the right reasons and unstable for
the right reasons, which is what these tests pin down: it must ignore how fast the host
was, and it must not ignore anything the metrics table actually reports.
"""

from __future__ import annotations

from finctl.fingerprint import LENGTH, fingerprint


class TestItIgnoresTheHost:
    """A fingerprint that moved with the CPU would fail on a slower laptop and read as
    proof the engine is non-deterministic, when only the machine was different."""

    def test_wall_clock_timing_does_not_change_it(self) -> None:
        fast = {"recall": 1.0, "seconds": 0.012, "rows_per_second": 53_472}
        slow = {"recall": 1.0, "seconds": 9.9, "rows_per_second": 61}
        assert fingerprint(fast) == fingerprint(slow)

    def test_timing_is_ignored_at_any_depth(self) -> None:
        a = {"runs": [{"caught": 6, "seconds": 0.01}, {"caught": 2, "seconds": 0.02}]}
        b = {"runs": [{"caught": 6, "seconds": 88.0}, {"caught": 2, "seconds": 99.0}]}
        assert fingerprint(a) == fingerprint(b)

    def test_key_order_does_not_change_it(self) -> None:
        assert fingerprint({"a": 1, "b": 2}) == fingerprint({"b": 2, "a": 1})


class TestItDoesNotIgnoreTheClaims:
    """The point of the number is that it moves when a reported figure moves."""

    def test_a_changed_defect_count_changes_it(self) -> None:
        assert fingerprint({"caught": 11}) != fingerprint({"caught": 10})

    def test_a_changed_amount_changes_it(self) -> None:
        before = {"unexplained_after_paise": 0}
        after = {"unexplained_after_paise": 1}
        assert fingerprint(before) != fingerprint(after)

    def test_a_false_positive_appearing_changes_it(self) -> None:
        assert fingerprint({"false_positives": 0}) != fingerprint({"false_positives": 1})


class TestItIsReadable:
    def test_it_is_short_enough_to_compare_by_eye(self) -> None:
        digest = fingerprint({"anything": 1})
        assert len(digest) == LENGTH == 16
        assert all(c in "0123456789abcdef" for c in digest)

    def test_it_is_stable_across_calls(self) -> None:
        payload = {"recall": 1.0, "caught": 11, "by_type": {"x": {"missed": 0}}}
        assert fingerprint(payload) == fingerprint(payload)
