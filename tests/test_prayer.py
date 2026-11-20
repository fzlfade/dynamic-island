from datetime import date, datetime, time

from island import prayer, store

JAKARTA = (-6.2088, 106.8456)
DAY = date(2026, 11, 21)


def mins(t):
    return t.hour * 60 + t.minute


def test_kemenag_jakarta():
    got = prayer.times(DAY, *JAKARTA, 7, "Kemenag RI")
    want = {"Subuh": "04:05", "Dzuhur": "11:42", "Ashar": "15:04", "Maghrib": "17:54", "Isya": "19:08"}
    assert list(got) == list(want)
    for name, hhmm in want.items():
        h, m = map(int, hhmm.split(":"))
        assert abs(mins(got[name]) - (h * 60 + m)) <= 2, (name, got[name], hhmm)


def test_umm_al_qura_isha_is_maghrib_plus_90():
    t = prayer.times(DAY, 21.4225, 39.8262, 3, "Umm al-Qura")
    assert mins(t["Isya"]) - mins(t["Maghrib"]) == 90


def test_hanafi_asr_later_than_shafii():
    assert mins(prayer.times(DAY, *JAKARTA, 7, "Kemenag RI", asr_factor=2)["Ashar"]) > mins(
        prayer.times(DAY, *JAKARTA, 7, "Kemenag RI")["Ashar"])


def test_ihtiyat_only_kemenag_and_adjustments():
    base = prayer.times(DAY, *JAKARTA, 7, "Muslim World League")
    mwl_fajr = prayer.times(DAY, *JAKARTA, 7, "JAKIM")  # same angles as Kemenag, no ihtiyat
    kem = prayer.times(DAY, *JAKARTA, 7, "Kemenag RI")
    assert mins(kem["Dzuhur"]) - mins(mwl_fajr["Dzuhur"]) == 2
    assert prayer.times(DAY, *JAKARTA, 7, "nonsense") == kem
    adj = prayer.times(DAY, *JAKARTA, 7, "JAKIM", adj={"Ashar": 5})
    assert mins(adj["Ashar"]) - mins(mwl_fajr["Ashar"]) == 5 and base


def settings(**kw):
    return prayer.Prayer({"prayer": "1", **{k: str(v) for k, v in kw.items()}})


def located(**kw):
    p = settings(**kw)
    p.set_location(*JAKARTA)
    return p


def test_off_by_default_and_no_location():
    assert prayer.Prayer({}).rows(datetime(2026, 11, 21, 8)) == []
    assert settings().rows(datetime(2026, 11, 21, 8)) == []


def test_next_row_and_tomorrow_subuh():
    p = located()
    p.tz = 7
    row = p.rows(datetime(2026, 11, 21, 12, 0))
    assert row[0][0] == "Next prayer" and row[0][1].startswith("Ashar ") and len(row) == 1
    assert p.rows(datetime(2026, 11, 21, 21, 0))[0][1].startswith("Subuh ")


def test_due_once_early_adj_and_no_burst():
    p = located(prayer_early=10)
    p.tz = 7
    sched = p.schedule(DAY)
    name, t = "Ashar", sched["Ashar"]
    at = mins(t) - 10
    assert p.due(datetime(2026, 11, 21, at // 60, at % 60), at - 1) == [(name, t.strftime("%H:%M"))]
    assert p.due(datetime(2026, 11, 21, at // 60, at % 60), at) == []
    # woke from sleep at 23:00: only the latest due prayer, not all five
    assert [n for n, _ in p.due(datetime(2026, 11, 21, 23, 0), 3 * 60)] == ["Isya"]
    assert prayer.Prayer({}).due(datetime(2026, 11, 21, 23, 0), 0) == []


def test_settings_parse():
    p = prayer.Prayer({"prayer": "1", "prayer_method": "x", "prayer_adj_isya": "3", "prayer_early": "bad"})
    assert p.method == "Kemenag RI" and p.adj == {"Isya": 3} and p.early == 0


def test_cached_per_day(monkeypatch):
    p = located()
    p.tz = 7
    p.schedule(DAY)
    monkeypatch.setattr(prayer, "times", lambda *a, **k: 1 / 0)
    p.rows(datetime(2026, 11, 21, 9))
    assert store  # cache hit raised nothing
