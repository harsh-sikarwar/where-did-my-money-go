"""Money arithmetic. Integer paise only.

ADR-003: money is an integer count of paise, everywhere, with no exceptions. Rupees
exist only in display formatting.

Why this module exists rather than inline arithmetic: the engine's core calculation is
GST-on-MDR — 18% of 2% of an amount. Compounded percentages are exactly where binary
floating point drifts. The engine also has a ROUNDING classification, so if float drift
can manufacture a rounding "defect", the engine cannot distinguish its own numerical
noise from a real merchant discrepancy, and the honest-residual claim collapses.

Every rate here is in BASIS POINTS as an integer (1 bps = 0.01%), so a rate never
enters the calculation as a float at all.
"""

from __future__ import annotations

import re
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal

BPS_DENOMINATOR = 10_000

_ROUNDING_MODES = {
    "half_up": ROUND_HALF_UP,
    "half_even": ROUND_HALF_EVEN,
    "floor": ROUND_FLOOR,
    "ceil": ROUND_CEILING,
}

# Accepts "1,234.50", "₹1234.50", "1234.5", "-99.00", " 1 234.50 ".
_CURRENCY_NOISE = re.compile(r"[₹,\s]")


class MoneyError(ValueError):
    """Raised when a money value cannot be parsed or a rate is invalid.

    Deliberately loud: BEHAVIOR.md requires failing rather than guessing, and a
    silently coerced amount is how a confident wrong answer gets produced.
    """


def apply_bps(amount_paise: int, rate_bps: int, mode: str = "half_up") -> int:
    """Apply a basis-point rate to an amount, returning whole paise.

    Uses Decimal for the single division so the rounding boundary is exact and
    explicit, rather than inheriting whatever binary floating point happens to do.

    >>> apply_bps(1_000_000, 200)      # ₹10,000 at 2.00%
    20000
    >>> apply_bps(1_000_000, 0)        # UPI: zero MDR
    0
    """
    if not isinstance(amount_paise, int) or isinstance(amount_paise, bool):
        raise MoneyError(f"amount must be int paise, got {type(amount_paise).__name__}")
    if not isinstance(rate_bps, int) or isinstance(rate_bps, bool):
        raise MoneyError(f"rate_bps must be int, got {type(rate_bps).__name__}")
    if rate_bps < 0:
        raise MoneyError(f"rate_bps must be non-negative, got {rate_bps}")
    if mode not in _ROUNDING_MODES:
        raise MoneyError(f"unknown rounding mode {mode!r}; expected one of {sorted(_ROUNDING_MODES)}")

    exact = Decimal(amount_paise) * Decimal(rate_bps) / Decimal(BPS_DENOMINATOR)
    return int(exact.quantize(Decimal(1), rounding=_ROUNDING_MODES[mode]))


def parse_money(value: str | int | float, *, allow_negative: bool = False) -> int:
    """Parse a money value into integer paise.

    This is the ONLY place rupee strings are parsed (BEHAVIOR.md, stage `normalize`).

    Accepts the messy real-world forms an uploaded CSV actually contains:
    "1,234.50" · "₹1234.50" · "1234.5" · "1234" · 1234.5 · 123450 is NOT assumed
    to be paise — see below.

    A bare int is treated as RUPEES, not paise, because that is what a merchant's
    CSV export contains. Razorpay API values that are already paise must not go
    through this function; they are already canonical.

    >>> parse_money("1,234.50")
    123450
    >>> parse_money("₹10,000")
    1000000
    """
    if isinstance(value, bool):
        raise MoneyError("bool is not a money value")

    if isinstance(value, int):
        parsed = Decimal(value)
    elif isinstance(value, float):
        # A float reached us from somewhere. Convert via str to avoid inheriting
        # binary representation error: Decimal(0.1) is 0.1000000000000000055...
        parsed = Decimal(str(value))
    elif isinstance(value, str):
        cleaned = _CURRENCY_NOISE.sub("", value).strip()
        if not cleaned:
            raise MoneyError(f"empty money value: {value!r}")
        try:
            parsed = Decimal(cleaned)
        except Exception as exc:
            raise MoneyError(f"cannot parse money value {value!r}") from exc
    else:
        raise MoneyError(f"cannot parse money from {type(value).__name__}")

    if parsed < 0 and not allow_negative:
        raise MoneyError(f"negative amount {value!r} not allowed here; pass allow_negative=True")

    paise = parsed * 100
    if paise != paise.to_integral_value():
        raise MoneyError(
            f"money value {value!r} has sub-paise precision ({paise}); refusing to round silently"
        )
    return int(paise)


def format_rupees(paise: int, *, symbol: bool = True) -> str:
    """Format paise for display, Indian digit grouping (lakh/crore).

    Display only. Nothing in the engine may parse this back.

    >>> format_rupees(84000000)
    '₹8,40,000.00'
    """
    if not isinstance(paise, int) or isinstance(paise, bool):
        raise MoneyError(f"expected int paise, got {type(paise).__name__}")

    negative = paise < 0
    whole, frac = divmod(abs(paise), 100)

    s = str(whole)
    if len(s) > 3:
        # Indian grouping: last three digits, then pairs. 8400000 -> 84,00,000
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join([*parts, tail])

    out = f"{s}.{frac:02d}"
    if symbol:
        out = f"₹{out}"
    return f"-{out}" if negative else out
