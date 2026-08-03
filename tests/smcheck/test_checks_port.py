"""D010: D-PORT check. Written before smcheck/checks/port.py exists.

What the analog/I2C toggle does electrically is still an open question
(HANDOFF.md), so this check doesn't assert a specific mechanism -- it only
proves the practical, testable claim: toggling the switch measurably changes
the port's electrical state, using sensors.py's own selectsensor() technique
(drive pin 5 digital low then high, read back via ADC) sampled repeatedly
while a human flips the switch.

Classification is by SPREAD (high - low), not sensors.py's own
`low < 200 and high > 4000` formula. A live run against real hardware
(bad-unit-1, 2026-08-03) showed why: the floating-pin state's `high` reading
topped out around 3700-3998, never crossing sensors.py's 4000 threshold, so
reusing that exact formula would report "attached" for the entire run despite
a clear, real regime change (spread ~3680 in one state, spread <500 in the
other). sensors.py's own threshold may be marginal on real hardware; this
check works around that rather than assuming it's reliable.
"""

from smcheck.checks.port import check_d_port

# The exact low/high pairs captured on bad-unit-1 while flipping the toggle.
# sensors.py's own formula (low<200 and high>4000) never once returns "not
# attached" against this real data -- see the module docstring above.
REAL_BAD_UNIT_1_TOGGLE_SAMPLES = [
    (21, 3707), (24, 3998), (25, 3708), (25, 3708), (25, 3695), (27, 3707),
    (2456, 2171), (2408, 1952), (1848, 1710), (1738, 1728), (1740, 1736), (1608, 1600),
    (23, 3707), (25, 3707), (24, 3710), (26, 3706), (25, 3706), (25, 3960), (25, 3704), (23, 3706),
    (1709, 1690), (1472, 1472), (1530, 1520), (2185, 1528), (1613, 1610), (1536, 1533),
    (24, 3707), (24, 3707), (26, 3707), (25, 3706), (25, 3708), (25, 3706), (24, 3696), (23, 3704),
    (1629, 1552), (2075, 1502), (1502, 1504), (1515, 1496), (1512, 1480), (1499, 1498),
]


def test_passes_on_real_captured_toggle_data_despite_sensors_py_threshold_never_tripping():
    result = check_d_port(
        port=None, identity={}, sample_fn=lambda port, dur: REAL_BAD_UNIT_1_TOGGLE_SAMPLES, prompt_fn=lambda: None
    )
    assert result.status == "pass"
    assert result.detail["transitions"] == 5  # matches the real cluster boundaries in this captured run


def test_passes_when_spread_changes_during_the_window():
    # (low, high) pairs -- spread flips from wide (floating-like) to narrow.
    samples = [(10, 4090)] * 5 + [(1500, 1500)] * 5
    result = check_d_port(port=None, identity={}, sample_fn=lambda port, dur: samples, prompt_fn=lambda: None)
    assert result.status == "pass"


def test_fails_when_spread_never_changes():
    samples = [(10, 4090)] * 10
    result = check_d_port(port=None, identity={}, sample_fn=lambda port, dur: samples, prompt_fn=lambda: None)
    assert result.status == "fail"
    assert "no" in result.summary.lower() and "change" in result.summary.lower()


def test_detail_carries_transition_count_and_final_state():
    samples = [(10, 4090)] * 3 + [(1500, 1500)] * 3 + [(20, 4080)] * 3
    result = check_d_port(port=None, identity={}, sample_fn=lambda port, dur: samples, prompt_fn=lambda: None)
    assert result.detail["transitions"] == 2


def test_does_not_claim_a_specific_electrical_mechanism():
    # the summary should describe the observed behavior, not assert what the
    # switch "does" -- that's still an open question per HANDOFF.md.
    samples = [(10, 4090)] * 5 + [(1500, 1500)] * 5
    result = check_d_port(port=None, identity={}, sample_fn=lambda port, dur: samples, prompt_fn=lambda: None)
    for word in ("disconnect", "reroute", "pull-up", "pullup"):
        assert word not in result.summary.lower()
