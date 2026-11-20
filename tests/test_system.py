from island import system


def test_battery_popup_rules():
    bp = system.battery_popup
    assert bp(None, (True, 79, False)) is None, "startup reading is a baseline"
    assert bp((False, 79, False), (True, 79, True)) == ("Charger connected", "Charging · 79%")
    assert bp((False, 79, False), (True, 79, False)) == ("Charger connected", "Plugged in · 79%"), "conservation mode"
    assert bp((False, 100, False), (True, 100, False)) == ("Charger connected", "Fully charged")
    assert bp((True, 79, False), (False, 79, False)) == ("Charger unplugged", "On battery · 79%")
    assert bp((True, 99, True), (True, 100, False)) == ("Fully charged", "You can unplug")
    assert bp((True, 100, False), (True, 100, False)) is None
    assert bp((False, 21, False), (False, 20, False)) == ("Low battery", "Plug in soon")
    assert bp((False, 20, False), (False, 19, False)) is None, "low fires once, on crossing"
    assert bp((False, 11, False), (False, 10, False)) == ("Battery critical", "Plug in now")
    assert bp((False, 22, False), (False, 9, False)) == ("Battery critical", "Plug in now"), "big drop: critical wins"
    assert bp((True, 15, True), (True, 16, True)) is None, "charging upward: no low warning"


def test_battery_status_shape():
    status = system.battery_status()
    assert status is None or (isinstance(status[0], bool) and 0 <= status[1] <= 100), status


class FakeVolume(system.Volume):
    def __init__(self, level, muted):
        self.state = (level, muted)

    def get(self):
        return self.state

    def set(self, level, muted):
        self.state = (max(0.0, min(1.0, level)), muted)
        return self.state


def test_volume_step_and_mute():
    assert FakeVolume(0.99, True).step(0.02) == (1.0, False), "up clamps at 100 and unmutes"
    assert FakeVolume(0.01, False).step(-0.02) == (0.0, False), "down clamps at 0"
    assert FakeVolume(0.5, True).step(-0.02) == (0.48, True), "down keeps mute"
    assert FakeVolume(0.5, False).toggle_mute() == (0.5, True)


def test_real_volume_roundtrip():
    vol = system.Volume()
    before = vol.get()
    after = vol.set(*before)  # write back exactly what we read
    assert abs(after[0] - before[0]) < 0.005 and after[1] == before[1], (before, after)


def test_language_names():
    assert system.language_name(0x0409) == ("English (United States)", "EN-US")
    assert system.language_name(0x3809) == ("English (Indonesia)", "EN-ID")
