"""Config loading and validation.

BEHAVIOR.md, stage `config`:
  Promises  — every rate that could vary by merchant, method or contract lives here.
  Refuses   — to supply a default MDR. A missing rate is an error, not an assumed 2%.
  Bad input — raises, naming the offending key and file.

The refusal is the important part. A default MDR would mean a UPI-heavy merchant gets
charged 2% in our model and every row shows a fee discrepancy that is ours, not theirs.
Making that a loud failure at load time is the single cheapest correctness guarantee
available in this project.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULTS_DIR = Path(__file__).parent / "defaults"


class ConfigError(ValueError):
    """Raised when configuration is missing, malformed, or internally inconsistent."""


def _require(data: dict[str, Any], key: str, source: str) -> Any:
    if key not in data:
        raise ConfigError(f"missing required key {key!r} in {source}")
    return data[key]


@dataclass(frozen=True)
class MethodRate:
    """The contracted rate for one payment method."""

    method: str
    mdr_bps: int
    note: str = ""


@dataclass(frozen=True)
class RateCard:
    """What the merchant's contract says Razorpay should charge.

    Answers "was the fee what my contract says?" — NOT "how is the fee encoded in the
    data?", which is ADR-007 and is derived from the data, never from this file.
    """

    name: str
    gst_rate_bps: int
    gst_applies_to: str
    rounding_mode: str
    gst_on_rounded_mdr: bool
    fixed_fee_paise: int
    methods: dict[str, MethodRate] = field(default_factory=dict)

    def rate_for(self, method: str) -> MethodRate:
        """Look up a method's rate. Raises on unknown methods — never defaults.

        This refusal is deliberate and is the whole point of the config layer.
        """
        try:
            return self.methods[method]
        except KeyError:
            raise ConfigError(
                f"no rate card entry for payment method {method!r}. "
                f"Known methods: {sorted(self.methods)}. "
                "Refusing to assume a default MDR — see docs/BEHAVIOR.md, stage `config`."
            ) from None

    @classmethod
    def from_dict(cls, data: dict[str, Any], source: str = "<dict>") -> RateCard:
        gst = _require(data, "gst", source)
        applies_to = _require(gst, "applies_to", f"{source}:gst")
        if applies_to != "mdr":
            raise ConfigError(
                f"gst.applies_to is {applies_to!r} in {source}; must be 'mdr'. "
                "GST is levied on the MDR, never on the transaction amount — "
                "applying it to `amount` overstates fees by ~18x."
            )

        rounding = _require(data, "rounding", source)
        methods_raw = _require(data, "methods", source)
        if not methods_raw:
            raise ConfigError(f"rate card {source} defines no payment methods")

        methods = {}
        for name, spec in methods_raw.items():
            mdr = _require(spec, "mdr_bps", f"{source}:methods.{name}")
            if not isinstance(mdr, int) or isinstance(mdr, bool):
                raise ConfigError(f"methods.{name}.mdr_bps must be an integer in {source}, got {mdr!r}")
            if mdr < 0:
                raise ConfigError(f"methods.{name}.mdr_bps must be non-negative in {source}, got {mdr}")
            methods[name] = MethodRate(method=name, mdr_bps=mdr, note=spec.get("note", ""))

        if "upi" in methods and methods["upi"].mdr_bps != 0:
            raise ConfigError(
                f"rate card {source} sets UPI mdr_bps to {methods['upi'].mdr_bps}, expected 0. "
                "UPI carries zero MDR, mandated for banks. If a contract genuinely differs, "
                "remove this check deliberately and record why."
            )

        return cls(
            name=_require(data, "name", source),
            gst_rate_bps=_require(gst, "rate_bps", f"{source}:gst"),
            gst_applies_to=applies_to,
            rounding_mode=_require(rounding, "mode", f"{source}:rounding"),
            gst_on_rounded_mdr=bool(rounding.get("gst_on_rounded_mdr", True)),
            fixed_fee_paise=data.get("fixed_fee_paise", 0),
            methods=methods,
        )


@dataclass(frozen=True)
class Tolerances:
    """How much difference is "the same", and how late is "late"."""

    cycle_days: int
    count_working_days_only: bool
    grace_days: int
    weekend_days: tuple[str, ...]
    holidays: tuple[str, ...]
    rounding_paise: int
    material_paise: int
    always_benign: tuple[str, ...]
    always_actionable: tuple[str, ...]
    actionable_above_paise: int

    @classmethod
    def from_dict(cls, data: dict[str, Any], source: str = "<dict>") -> Tolerances:
        settlement = _require(data, "settlement", source)
        calendar = _require(data, "calendar", source)
        amount = _require(data, "amount", source)
        materiality = _require(data, "materiality", source)

        cycle = _require(settlement, "cycle_days", f"{source}:settlement")
        if not isinstance(cycle, int) or cycle < 0:
            raise ConfigError(f"settlement.cycle_days must be a non-negative int in {source}, got {cycle!r}")

        overlap = set(materiality.get("always_benign", [])) & set(materiality.get("always_actionable", []))
        if overlap:
            raise ConfigError(
                f"classifications in both always_benign and always_actionable in {source}: {sorted(overlap)}"
            )

        # A typo here would not raise at use time -- the name simply would not match,
        # and the classification would silently fall through to the amount threshold.
        # A benign-by-policy class would then become actionable purely because it was
        # large, which is precisely the ranking mistake this config exists to prevent.
        from finctl.classify.classifier import Classification

        known = {str(c) for c in Classification}
        for key in ("always_benign", "always_actionable"):
            unknown = [n for n in materiality.get(key, []) if n not in known]
            if unknown:
                raise ConfigError(
                    f"{source}: materiality.{key} names unknown classification(s) "
                    f"{unknown}. Known: {sorted(known)}"
                )

        return cls(
            cycle_days=cycle,
            count_working_days_only=bool(settlement.get("count_working_days_only", True)),
            grace_days=_require(settlement, "grace_days", f"{source}:settlement"),
            weekend_days=tuple(calendar.get("weekend_days", [])),
            holidays=tuple(calendar.get("holidays", [])),
            rounding_paise=_require(amount, "rounding_paise", f"{source}:amount"),
            material_paise=_require(amount, "material_paise", f"{source}:amount"),
            always_benign=tuple(materiality.get("always_benign", [])),
            always_actionable=tuple(materiality.get("always_actionable", [])),
            actionable_above_paise=_require(materiality, "actionable_above_paise", f"{source}:materiality"),
        )


@dataclass(frozen=True)
class PaymentMix:
    """A named distribution over payment methods. Must sum to 1.0."""

    name: str
    description: str
    mix: dict[str, float]

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any], source: str = "<dict>") -> PaymentMix:
        mix = _require(data, "mix", f"{source}:{name}")
        total = sum(mix.values())
        # Float tolerance is acceptable here and only here: these are population
        # proportions for a generator, not money. No money value is derived from them.
        if abs(total - 1.0) > 1e-9:
            raise ConfigError(f"payment mix {name!r} in {source} sums to {total}, must sum to 1.0")
        if any(v < 0 for v in mix.values()):
            raise ConfigError(f"payment mix {name!r} in {source} has a negative share")
        return cls(name=name, description=data.get("description", ""), mix=dict(mix))


@dataclass(frozen=True)
class Archetype:
    """A business shape. Each stresses different engine logic."""

    name: str
    description: str
    stresses: str
    ticket_min_paise: int
    ticket_max_paise: int
    payment_mix: dict[str, float]
    refund_rate: float
    subscription_share: float
    expected_correlation_gain: str

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any], source: str = "<dict>") -> Archetype:
        ticket = _require(data, "ticket_paise", f"{source}:{name}")
        lo, hi = _require(ticket, "min", f"{source}:{name}.ticket_paise"), _require(
            ticket, "max", f"{source}:{name}.ticket_paise"
        )
        if lo > hi:
            raise ConfigError(f"archetype {name!r} in {source}: ticket min {lo} exceeds max {hi}")

        mix = _require(data, "payment_mix", f"{source}:{name}")
        total = sum(mix.values())
        if abs(total - 1.0) > 1e-9:
            raise ConfigError(f"archetype {name!r} payment_mix sums to {total}, must sum to 1.0")

        return cls(
            name=name,
            description=data.get("description", ""),
            stresses=data.get("stresses", ""),
            ticket_min_paise=lo,
            ticket_max_paise=hi,
            payment_mix=dict(mix),
            refund_rate=data.get("refund_rate", 0.0),
            subscription_share=data.get("subscription_share", 0.0),
            expected_correlation_gain=data.get("expected_correlation_gain", "unknown"),
        )


@dataclass(frozen=True)
class Config:
    """Everything the engine needs that is not data."""

    rate_card: RateCard
    tolerances: Tolerances
    archetypes: dict[str, Archetype]
    payment_mixes: dict[str, PaymentMix]

    def archetype(self, name: str) -> Archetype:
        try:
            return self.archetypes[name]
        except KeyError:
            raise ConfigError(
                f"unknown archetype {name!r}. Known: {sorted(self.archetypes)}"
            ) from None

    def payment_mix(self, name: str) -> PaymentMix:
        try:
            return self.payment_mixes[name]
        except KeyError:
            raise ConfigError(
                f"unknown payment mix {name!r}. Known: {sorted(self.payment_mixes)}"
            ) from None


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a YAML mapping, got {type(data).__name__}")
    return data


def load_config(config_dir: Path | None = None) -> Config:
    """Load and validate all configuration.

    Every validation failure raises at load time rather than at use time, so a bad
    rate card is caught before a batch runs rather than midway through one.
    """
    d = config_dir or DEFAULTS_DIR

    rate_card = RateCard.from_dict(_load_yaml(d / "rate_card.yaml"), str(d / "rate_card.yaml"))
    tolerances = Tolerances.from_dict(_load_yaml(d / "tolerances.yaml"), str(d / "tolerances.yaml"))

    arch_src = str(d / "archetypes.yaml")
    archetypes = {
        name: Archetype.from_dict(name, spec, arch_src)
        for name, spec in _load_yaml(d / "archetypes.yaml").items()
    }

    mix_src = str(d / "payment_mixes.yaml")
    mixes = {
        name: PaymentMix.from_dict(name, spec, mix_src)
        for name, spec in _load_yaml(d / "payment_mixes.yaml").items()
    }

    # Cross-file validation: an archetype or mix naming a method the rate card does
    # not price would fail at fee time, deep in a batch. Catch it at load.
    for arch in archetypes.values():
        for method in arch.payment_mix:
            if method not in rate_card.methods:
                raise ConfigError(
                    f"archetype {arch.name!r} uses payment method {method!r}, "
                    f"which the rate card {rate_card.name!r} does not price."
                )
    for mix in mixes.values():
        for method in mix.mix:
            if method not in rate_card.methods:
                raise ConfigError(
                    f"payment mix {mix.name!r} uses payment method {method!r}, "
                    f"which the rate card {rate_card.name!r} does not price."
                )

    return Config(rate_card=rate_card, tolerances=tolerances, archetypes=archetypes, payment_mixes=mixes)
