"""Working-day arithmetic for settlement cycles.

T+2 means two *working* days, not two calendar days. A Friday capture settles on
Tuesday, not Sunday. This is why "47 Friday orders land Tuesday" is the canonical
timing defect — it is not a bug, it is the settlement cycle behaving correctly, and
the engine must know that or it will report a third of a normal batch as missing money.

Kept deliberately separate from the classifier so the same calendar is used to
*generate* the data and to *judge* it. Using different logic in each would let a
generator bug hide behind a matching classifier bug.
"""

from __future__ import annotations

from datetime import date, timedelta

_WEEKDAY_NAMES = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


class WorkingCalendar:
    """Knows which days banks settle on.

    Holidays are supplied rather than computed. An incomplete holiday list produces
    false TIMING classifications, so a short known-correct list beats a guessed-at
    full one — see tolerances.yaml.
    """

    def __init__(
        self,
        weekend_days: tuple[str, ...] = ("saturday", "sunday"),
        holidays: tuple[str, ...] = (),
    ) -> None:
        unknown = set(weekend_days) - set(_WEEKDAY_NAMES)
        if unknown:
            raise ValueError(f"unknown weekday name(s): {sorted(unknown)}")
        self._weekend = {_WEEKDAY_NAMES[d] for d in weekend_days}
        self._holidays = {date.fromisoformat(h) for h in holidays}

    def is_working_day(self, day: date) -> bool:
        return day.weekday() not in self._weekend and day not in self._holidays

    def add_working_days(self, start: date, days: int) -> date:
        """The settlement date for a capture on `start` under a T+`days` cycle.

        T+0 still moves to the next working day if `start` is not one: money captured
        on a Saturday cannot settle on that Saturday.

        >>> cal = WorkingCalendar()
        >>> cal.add_working_days(date(2026, 9, 4), 2).isoformat()   # Friday + 2
        '2026-09-08'
        """
        if days < 0:
            raise ValueError(f"days must be non-negative, got {days}")

        current = start
        remaining = days
        while remaining > 0 or not self.is_working_day(current):
            current += timedelta(days=1)
            if self.is_working_day(current):
                remaining -= 1
            if remaining < 0:  # pragma: no cover - defensive
                break
        return current

    def working_days_between(self, start: date, end: date) -> int:
        """Count working days from `start` (exclusive) to `end` (inclusive).

        Negative if `end` precedes `start` — a settlement dated before its capture is
        a real anomaly and must not be silently clamped to zero.
        """
        if end < start:
            return -self.working_days_between(end, start)
        count = 0
        current = start
        while current < end:
            current += timedelta(days=1)
            if self.is_working_day(current):
                count += 1
        return count
