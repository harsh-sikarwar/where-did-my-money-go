"""Working-day calendar tests.

T+2 means two WORKING days. If this is wrong, a third of a normal batch is reported as
missing money — the engine manufacturing the problem it exists to detect.
"""

from __future__ import annotations

from datetime import date

import pytest

from finctl.calendar import WorkingCalendar


@pytest.fixture
def cal() -> WorkingCalendar:
    return WorkingCalendar()


class TestTheCanonicalCase:
    def test_friday_orders_land_tuesday(self, cal: WorkingCalendar) -> None:
        """'47 Friday orders land Tuesday' — the story in the brief.

        It must EMERGE from the calendar, not be special-cased.
        """
        friday = date(2026, 9, 4)
        assert friday.weekday() == 4
        settled = cal.add_working_days(friday, 2)
        assert settled == date(2026, 9, 8)
        assert settled.strftime("%A") == "Tuesday"
        assert (settled - friday).days == 4  # four CALENDAR days for a T+2 cycle

    def test_midweek_order_settles_without_weekend_drag(self, cal: WorkingCalendar) -> None:
        tuesday = date(2026, 9, 1)
        assert cal.add_working_days(tuesday, 2) == date(2026, 9, 3)


class TestWeekends:
    @pytest.mark.parametrize("day", [date(2026, 9, 5), date(2026, 9, 6)])
    def test_weekends_are_not_working_days(self, cal: WorkingCalendar, day: date) -> None:
        assert not cal.is_working_day(day)

    def test_t_plus_zero_still_moves_off_a_weekend(self, cal: WorkingCalendar) -> None:
        """Money captured on a Saturday cannot settle that Saturday."""
        saturday = date(2026, 9, 5)
        assert cal.add_working_days(saturday, 0) == date(2026, 9, 7)  # Monday

    def test_settlement_never_lands_on_a_weekend(self, cal: WorkingCalendar) -> None:
        start = date(2026, 9, 1)
        for offset in range(30):
            for cycle in (1, 2, 7):
                from datetime import timedelta
                assert cal.is_working_day(cal.add_working_days(start + timedelta(days=offset), cycle))


class TestHolidays:
    def test_a_holiday_extends_the_cycle(self) -> None:
        cal = WorkingCalendar(holidays=("2026-09-07",))  # a Monday
        friday = date(2026, 9, 4)
        assert cal.add_working_days(friday, 2) == date(2026, 9, 9)  # Wednesday, not Tuesday

    def test_holidays_are_not_working_days(self) -> None:
        cal = WorkingCalendar(holidays=("2026-09-07",))
        assert not cal.is_working_day(date(2026, 9, 7))


class TestCounting:
    def test_working_days_between_excludes_weekends(self, cal: WorkingCalendar) -> None:
        assert cal.working_days_between(date(2026, 9, 4), date(2026, 9, 8)) == 2

    def test_backwards_is_negative_not_clamped(self, cal: WorkingCalendar) -> None:
        """A settlement dated BEFORE its capture is a real anomaly.

        Silently clamping to zero would hide it — the adversarial 'refund issued before
        the original settled' case depends on this being visible.
        """
        assert cal.working_days_between(date(2026, 9, 8), date(2026, 9, 4)) == -2

    def test_same_day_is_zero(self, cal: WorkingCalendar) -> None:
        assert cal.working_days_between(date(2026, 9, 4), date(2026, 9, 4)) == 0


class TestConfigurability:
    def test_cycle_length_is_not_hardcoded(self, cal: WorkingCalendar) -> None:
        """T+1 / T+2 / T+7 all vary on test day."""
        friday = date(2026, 9, 4)
        assert cal.add_working_days(friday, 1) == date(2026, 9, 7)
        assert cal.add_working_days(friday, 2) == date(2026, 9, 8)
        assert cal.add_working_days(friday, 7) == date(2026, 9, 15)

    def test_a_different_weekend_changes_the_answer(self) -> None:
        """Not every market rests on Saturday and Sunday."""
        cal = WorkingCalendar(weekend_days=("friday", "saturday"))
        assert not cal.is_working_day(date(2026, 9, 4))   # Friday
        assert cal.is_working_day(date(2026, 9, 6))        # Sunday

    def test_unknown_weekday_name_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown weekday"):
            WorkingCalendar(weekend_days=("caturday",))

    def test_negative_days_raises(self, cal: WorkingCalendar) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            cal.add_working_days(date(2026, 9, 4), -1)
