"""Timeline tests.

The chart on the analysis screen sits directly under the gap figure, so the only thing
that makes it worth drawing is that it adds up to that figure. These defend two claims:

    dated + undated == gap          — nothing is dropped on the floor
    a bar is amber because it needs a decision, never because it is tall

The second is the one worth stating. Colour in this product means something about money;
a chart that coloured by magnitude would be the first place that stopped being true.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import ClassVar

import pytest

from finctl.classify.classifier import Classification, Classifier
from finctl.config.loader import load_config
from finctl.correlate.correlator import Correlator
from finctl.gap import GapComponent, GapDecomposition, decompose
from finctl.generate.generator import Generator
from finctl.generate.writer import write_batch
from finctl.match.matcher import match
from finctl.stage.staging import stage_from_dir
from finctl.timeline import Timeline, TimelineDay, build_timeline


@pytest.fixture
def demo(tmp_path: Path) -> Path:
    write_batch(Generator(load_config(), seed=20260902, volume=200,
                          defect_profile="demo").generate(), tmp_path)
    return tmp_path


def timeline_for(path: Path, actionable: frozenset[Classification] = frozenset()) -> Timeline:
    cfg = load_config()
    batch = stage_from_dir(path)
    matches = match(batch)
    correlated = Correlator(batch).correlate(Classifier(cfg).classify(matches))
    return build_timeline(matches, decompose(matches, correlated.findings), actionable)


class TestTheIdentity:
    def test_dated_plus_undated_equals_the_gap(self, demo: Path) -> None:
        t = timeline_for(demo)
        assert t.dated_paise + t.undated_paise == t.gap_paise

    def test_check_raises_when_it_does_not_balance(self) -> None:
        t = Timeline(
            days=[TimelineDay(day=date(2026, 8, 1), paise=100, order_count=1)],
            undated_paise=0,
            gap_paise=250,
        )
        with pytest.raises(ArithmeticError, match="does not balance"):
            t.check()

    def test_most_of_the_gap_is_datable(self, demo: Path) -> None:
        """Not an identity — a quality bar. A timeline that could date a third of the
        gap would balance perfectly and still be worthless on screen."""
        t = timeline_for(demo)
        assert abs(t.dated_paise) > abs(t.gap_paise) * 0.8


class TestAttribution:
    def test_undated_money_is_declared_not_spread(self) -> None:
        """An order with no capture date must not be assigned to a day."""
        d = GapDecomposition(expected_paise=5000, received_paise=0)
        d.components.append(GapComponent(
            classification=Classification.MISSING,
            amount_paise=5000,
            count=1,
            order_ids=["order_undateable"],
            per_order=[("order_undateable", 5000)],
        ))

        class _NoOrders:
            order_matches: ClassVar[list[object]] = []

        t = build_timeline(_NoOrders(), d)  # type: ignore[arg-type]
        assert t.days == []
        assert t.undated_paise == 5000
        t.check()

    def test_quiet_days_inside_the_span_are_kept(self, demo: Path) -> None:
        """Dropping zero days compresses the axis and makes a steady leak look spiky."""
        t = timeline_for(demo)
        days = [d.day for d in t.days]
        assert days == sorted(days)
        assert len(days) == (days[-1] - days[0]).days + 1


class TestTheTwoLines:
    """The detailed view draws expected and received as two lines. The only thing that
    makes that chart honest is that each line totals the figure printed at the top of
    the page, and that the space between them is the gap."""

    def test_expected_totals_the_headline_expected(self, demo: Path) -> None:
        cfg = load_config()
        batch = stage_from_dir(demo)
        matches = match(batch)
        correlated = Correlator(batch).correlate(Classifier(cfg).classify(matches))
        t = build_timeline(matches, decompose(matches, correlated.findings))
        assert sum(d.expected_paise for d in t.days) == matches.expected_paise

    def test_the_space_between_the_lines_is_the_dated_gap(self, demo: Path) -> None:
        t = timeline_for(demo)
        expected = sum(d.expected_paise for d in t.days)
        received = sum(d.received_paise for d in t.days)
        assert expected - received == t.dated_paise

    def test_received_is_derived_never_summed_independently(self) -> None:
        """One subtraction, so the lines cannot drift apart by construction."""
        day = TimelineDay(day=date(2026, 8, 1), paise=250, order_count=1,
                          expected_paise=1000)
        assert day.received_paise == 750


class TestSeverityMeansMoney:
    def test_no_actionable_classes_means_no_actionable_money(self, demo: Path) -> None:
        t = timeline_for(demo, actionable=frozenset())
        assert all(d.actionable_paise == 0 for d in t.days)

    def test_actionable_money_is_a_subset_of_the_day(self, demo: Path) -> None:
        t = timeline_for(demo, actionable=frozenset({
            Classification.HALTED_SUBSCRIPTION, Classification.PAYMENT_FAILED,
        }))
        assert any(d.actionable_paise for d in t.days), "fixture plants no actionable money"
        for d in t.days:
            assert abs(d.actionable_paise) <= abs(d.paise) or d.paise < 0

    def test_peak_prefers_the_day_that_needs_a_decision(self) -> None:
        """A tall benign day must not outrank a smaller day that needs action."""
        t = Timeline(
            days=[
                TimelineDay(day=date(2026, 8, 1), paise=9000, order_count=3,
                            actionable_paise=0),
                TimelineDay(day=date(2026, 8, 2), paise=4000, order_count=1,
                            actionable_paise=4000),
            ],
            undated_paise=0,
            gap_paise=13000,
        )
        assert t.peak is not None
        assert t.peak.day == date(2026, 8, 2)
