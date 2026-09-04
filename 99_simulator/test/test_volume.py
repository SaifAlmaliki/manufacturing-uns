"""Spec 9 and 14: the shipped default must not be a firehose.

The WTP plant is the single shipped profile, and the graphdb mapper MERGEs once per
topic level on every message - so the volume risk is Neo4j's write path, not Timescale's.
This file is what keeps the WTP profile honest: a family added to the profile, or a
tier_scale dropped, shows up here rather than in a mapper falling quietly behind in
production.

The assertions are bands, not numbers. A tight figure would break on every legitimate
device added, which trains people to edit the test; an order-of-magnitude band breaks
only when the shipped default has genuinely changed character.
"""

from pathlib import Path

import pytest
import yaml

from uns_simulator.profiles import TIER_DEFAULTS, load_profile, read_simulator_conf

CONF_DIR = Path(__file__).resolve().parents[2] / "conf"

# Spec 9: the WTP profile must stay a manageable default. The ceiling catches a firehose;
# the floor catches the opposite failure, a profile that resolves to almost nothing and
# passes by being broken.
WTP_MIN_MSG_PER_SEC = 1.0
WTP_MAX_MSG_PER_SEC = 40.0


@pytest.fixture
def raw():
    return read_simulator_conf(CONF_DIR)


@pytest.fixture
def settings_doc():
    return yaml.safe_load((CONF_DIR / "settings.yaml").read_text(encoding="utf-8"))


def test_the_shipped_default_profile_is_wtp(settings_doc):
    """The default is a deployment decision, so it is asserted against the shipped file."""
    assert settings_doc["simulator"]["simulation"]["profile"] == "wtp"


def test_the_shipped_config_declares_a_seed(settings_doc):
    """Spec 14 mitigates flaky correlation tests with a fixed default seed.

    Absent, every restart reshuffles every signal and two runs of the same profile cannot be
    compared - which is most of the value of having a profile.
    """
    assert isinstance(settings_doc["simulator"]["simulation"]["seed"], int)


def test_the_legacy_create_plc_config_is_no_longer_declared_in_settings(settings_doc):
    """The three keys of the legacy generator are one feature and leave together.

    `plc:` leaves because production.yaml declared those two templates now, and declared in
    both they publish twice. `equipment.mixer_tank` and `plc_count` leave with it because
    create_plc's two branches are mutually exclusive: with no `plc:` list it falls through to
    the fallback and builds `plc_count` MixerTanks per cell, so removing one key and not the
    other three would replace a double-publish with eight undeclared devices.

    simulator.py still reads all three for deployments that carry their own settings.yaml;
    test_targeting.py exercises both branches. This asserts about the shipped file only.
    """
    simulator = settings_doc["simulator"]
    assert "plc" not in simulator
    assert "mixer_tank" not in simulator.get("equipment", {})
    assert "plc_count" not in simulator["simulation"]


def test_the_settings_hierarchy_is_kept_as_the_no_conf_simulator_fallback(settings_doc):
    """Removing it would make raw_config["hierarchy"] a KeyError when conf/simulator/ is absent."""
    assert settings_doc["simulator"]["hierarchy"]["enterprise"] == "AcmeWater"


def test_wtp_stays_under_the_volume_ceiling(raw):
    rate = sum(load_profile(raw, "wtp").messages_per_second().values())
    assert WTP_MIN_MSG_PER_SEC < rate < WTP_MAX_MSG_PER_SEC, f"wtp resolved to {rate:.2f} msg/s"


def test_every_signal_lands_on_a_known_tier(raw):
    """The only check that a per-signal `tier` is spelled correctly.

    `_resolve_tiers` validates the keys of a `simulation.tiers` override, and nothing
    validates a `tier:` written on a signal. A typo there does not raise - the signal is
    simply never scheduled, and a silently unpublished topic is the hardest kind of bug to
    notice in a simulator whose whole output is topics.
    """
    for device in load_profile(raw, "wtp").devices:
        for signal in device.signals:
            assert signal.tier in TIER_DEFAULTS, f"{device.id}/{signal.name}: unknown tier {signal.tier!r}"


def test_messages_per_second_reports_every_tier(raw):
    """Sub-project B renders this per tier, so a missing key is a missing row, not a zero."""
    rates = load_profile(raw, "wtp").messages_per_second()
    assert set(rates) == set(TIER_DEFAULTS)
    assert rates["event"] == 0.0  # `event` publishes on change; it has no periodic rate
