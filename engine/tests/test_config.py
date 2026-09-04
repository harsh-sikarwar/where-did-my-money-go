"""Config layer tests.

BEHAVIOR.md, stage `config`: the layer must REFUSE to supply a default MDR. These
tests assert the refusals, because the refusals are the feature.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from finctl.config.loader import Config, ConfigError, RateCard, Tolerances, load_config


@pytest.fixture
def config() -> Config:
    return load_config()


class TestDefaultsLoad:
    def test_defaults_load_and_validate(self, config: Config) -> None:
        assert config.rate_card.name == "standard-india-2026"
        assert config.archetypes
        assert config.payment_mixes

    def test_upi_carries_the_platform_fee_in_shipped_defaults(self, config: Config) -> None:
        """The assumption that WAS silently wrong: UPI billed at zero.

        Zero MDR is statutory, but the aggregator's platform fee is deducted anyway
        and is what appears on the settlement row. See ADR-030.
        """
        assert config.rate_card.rate_for("upi").mdr_bps == 200

    def test_gst_applies_to_mdr_not_amount(self, config: Config) -> None:
        assert config.rate_card.gst_applies_to == "mdr"
        assert config.rate_card.gst_rate_bps == 1800

    def test_both_archetypes_state_expected_correlation_gain(self, config: Config) -> None:
        """Stated in advance so results cannot be retrofitted to the expectation."""
        assert config.archetype("saas_subscription").expected_correlation_gain == "high"
        assert config.archetype("d2c_ecommerce").expected_correlation_gain == "low"


class TestRefusals:
    """The config layer's job is to say no. Each of these is a designed failure."""

    def test_unknown_method_raises_and_never_defaults(self, config: Config) -> None:
        """The single most important refusal in the project.

        A default 2% would charge a UPI-heavy merchant 2% in our model, making every
        row show a fee discrepancy that is OURS, not theirs.
        """
        with pytest.raises(ConfigError) as exc:
            config.rate_card.rate_for("crypto")
        assert "crypto" in str(exc.value)
        assert "Refusing to assume a default MDR" in str(exc.value)
        assert "Known methods" in str(exc.value)

    def test_unknown_archetype_lists_valid_options(self, config: Config) -> None:
        with pytest.raises(ConfigError, match="unknown archetype"):
            config.archetype("crypto_casino")

    def test_unknown_payment_mix_lists_valid_options(self, config: Config) -> None:
        with pytest.raises(ConfigError, match="unknown payment mix"):
            config.payment_mix("vibes")


class TestValidation:
    def test_gst_applied_to_amount_is_rejected(self) -> None:
        """Applying 18% to the transaction rather than the MDR overstates fees ~18x."""
        data = {
            "name": "broken",
            "gst": {"rate_bps": 1800, "applies_to": "amount"},
            "rounding": {"mode": "half_up"},
            "methods": {"card_credit": {"mdr_bps": 200}},
        }
        with pytest.raises(ConfigError, match="GST is levied on the MDR"):
            RateCard.from_dict(data, "test")

    def test_zero_upi_rate_is_rejected(self) -> None:
        """A zero UPI rate means every UPI row gets flagged for a fee it really owes."""
        data = {
            "name": "broken",
            "gst": {"rate_bps": 1800, "applies_to": "mdr"},
            "rounding": {"mode": "half_up"},
            "methods": {"upi": {"mdr_bps": 0}},
        }
        with pytest.raises(ConfigError, match="platform fee"):
            RateCard.from_dict(data, "test")

    def test_float_mdr_is_rejected(self) -> None:
        """Rates are integer basis points so no float ever multiplies a money value."""
        data = {
            "name": "broken",
            "gst": {"rate_bps": 1800, "applies_to": "mdr"},
            "rounding": {"mode": "half_up"},
            "methods": {"card_credit": {"mdr_bps": 2.0}},
        }
        with pytest.raises(ConfigError, match="must be an integer"):
            RateCard.from_dict(data, "test")

    def test_missing_key_names_the_key_and_file(self) -> None:
        with pytest.raises(ConfigError) as exc:
            RateCard.from_dict({"name": "x"}, "myfile.yaml")
        assert "gst" in str(exc.value)
        assert "myfile.yaml" in str(exc.value)

    def test_materiality_overlap_is_rejected(self) -> None:
        """A classification cannot be both always-benign and always-actionable."""
        data = {
            "settlement": {"cycle_days": 2, "grace_days": 1},
            "calendar": {},
            "amount": {"rounding_paise": 1, "material_paise": 10000},
            "materiality": {
                "always_benign": ["FEE", "TIMING"],
                "always_actionable": ["TIMING", "MISSING"],
                "actionable_above_paise": 10000,
            },
        }
        with pytest.raises(ConfigError, match="both always_benign and always_actionable"):
            Tolerances.from_dict(data, "test")


class TestCrossFileValidation:
    def test_archetype_using_unpriced_method_fails_at_load_not_mid_batch(
        self, tmp_path: Path
    ) -> None:
        """Catch it at load time. Failing deep inside a 50k-row batch is expensive."""
        src = Path(__file__).parent.parent / "finctl" / "config" / "defaults"
        for name in ("rate_card.yaml", "tolerances.yaml", "payment_mixes.yaml"):
            (tmp_path / name).write_text((src / name).read_text())

        (tmp_path / "archetypes.yaml").write_text(
            textwrap.dedent("""
                broken_shop:
                  description: "uses a method the rate card does not price"
                  ticket_paise: {min: 100, max: 200}
                  payment_mix: {upi: 0.5, dogecoin: 0.5}
            """)
        )
        with pytest.raises(ConfigError, match="which the rate card"):
            load_config(tmp_path)

    def test_payment_mix_must_sum_to_one(self, tmp_path: Path) -> None:
        src = Path(__file__).parent.parent / "finctl" / "config" / "defaults"
        for name in ("rate_card.yaml", "tolerances.yaml", "archetypes.yaml"):
            (tmp_path / name).write_text((src / name).read_text())

        (tmp_path / "payment_mixes.yaml").write_text(
            yaml.safe_dump({"lopsided": {"mix": {"upi": 0.5, "card_credit": 0.2}}})
        )
        with pytest.raises(ConfigError, match=r"must sum to 1\.0"):
            load_config(tmp_path)

    def test_shipped_mixes_all_sum_to_one(self, config: Config) -> None:
        for mix in config.payment_mixes.values():
            assert abs(sum(mix.mix.values()) - 1.0) < 1e-9


class TestConfigIsOverridable:
    def test_a_different_rate_card_changes_the_answer(self, tmp_path: Path) -> None:
        """Config over constants: a merchant on a different contract needs no code change."""
        src = Path(__file__).parent.parent / "finctl" / "config" / "defaults"
        for name in ("tolerances.yaml", "archetypes.yaml", "payment_mixes.yaml"):
            (tmp_path / name).write_text((src / name).read_text())

        card = yaml.safe_load((src / "rate_card.yaml").read_text())
        card["name"] = "negotiated-enterprise"
        card["methods"]["card_credit"]["mdr_bps"] = 150  # negotiated 1.5%
        (tmp_path / "rate_card.yaml").write_text(yaml.safe_dump(card))

        cfg = load_config(tmp_path)
        assert cfg.rate_card.rate_for("card_credit").mdr_bps == 150
        assert load_config().rate_card.rate_for("card_credit").mdr_bps == 200
