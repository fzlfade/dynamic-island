"""Calendar from an iCal link: pure parsing + recurrence (no Qt) and a background fetcher."""
import sys
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from island import http

_warned = []  # one stderr warning per run
CAP = 5000  # hard limit on recurrence steps per series
DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
FREQS = ("DAILY", "WEEKLY", "MONTHLY", "YEARLY")


@dataclass
class Event:
    start: datetime
    end: datetime
    summary: str
    all_day: bool


@dataclass
class Series:
    start: object  # date (all-day), naive datetime (floating) or aware datetime
    duration: timedelta
    summary: str
    rule: dict = None  # supported RRULE parts, or None for a single event
    exdates: list = field(default_factory=list)
    uid: str = ""
    rid: object = None  # RECURRENCE-ID: this event replaces that occurrence of the master with the same uid

    @property
    def all_day(self):
        return type(self.start) is date


def _unfold(text):
    out = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line[:1] in (" ", "\t") and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def _value(v, params):
    """DATE or DATE-TIME text -> date / naive datetime / aware datetime."""
    v = v.strip()
    if "T" not in v:
        return datetime.strptime(v, "%Y%m%d").date()
    d = datetime.strptime(v.rstrip("Z"), "%Y%m%dT%H%M%S")
    if v.endswith("Z"):
        return d.replace(tzinfo=timezone.utc)
    if "TZID" in params:
        try:
            return d.replace(tzinfo=ZoneInfo(params["TZID"].strip('"')))
        except (KeyError, ValueError, OSError):  # unknown zone: treat as floating
            pass
    return d


def _rule(text):
    parts = dict(p.split("=", 1) for p in text.split(";") if "=" in p)
    if parts.get("FREQ") not in FREQS or set(parts) - {"FREQ", "INTERVAL", "COUNT", "UNTIL", "BYDAY", "WKST"}:
        return None
    if "BYDAY" in parts and parts["FREQ"] != "WEEKLY":
        return None
    r = {"freq": parts["FREQ"], "interval": max(1, int(parts.get("INTERVAL", 1)))}
    if "COUNT" in parts:
        r["count"] = int(parts["COUNT"])
    if "UNTIL" in parts:
        r["until"] = _value(parts["UNTIL"], {})
    if "BYDAY" in parts:
        r["byday"] = sorted(DAYS.index(d[-2:]) for d in parts["BYDAY"].split(","))
    return r


def _unescape(s):
    return s.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def _like(v, base):
    """Convert date/datetime `v` to the kind of `base` (date, floating or aware) so they can be compared."""
    if type(base) is date:
        return v if type(v) is date else v.date()
    if type(v) is date:
        v = datetime.combine(v, base.timetz())
    if base.tzinfo is None:
        return v.astimezone().replace(tzinfo=None) if v.tzinfo else v
    return v if v.tzinfo else v.replace(tzinfo=base.tzinfo)


def _series(props):
    start = _value(*props["DTSTART"][0])
    if "DTEND" in props:
        duration = _like(_value(*props["DTEND"][0]), start) - start
    else:
        duration = timedelta(days=1) if type(start) is date else timedelta(0)
    rule = _rule(props["RRULE"][0][0]) if "RRULE" in props else None
    if rule and "until" in rule:
        rule["until"] = _like(rule["until"], start)
    ex = [_value(v, p) for vs, p in props.get("EXDATE", []) for v in vs.split(",")]
    summary = _unescape(props["SUMMARY"][0][0]) if "SUMMARY" in props else ""
    rid = _value(*props["RECURRENCE-ID"][0]) if "RECURRENCE-ID" in props else None
    return Series(start, duration, summary, rule, ex, props.get("UID", [("", 0)])[0][0].strip(), rid)


def parse_ics(text):
    out, props, cancelled = [], None, []
    for line in _unfold(text):
        key, _, val = line.partition(":")
        name, *plist = key.split(";")
        name = name.upper()
        if name == "BEGIN" and val.strip().upper() == "VEVENT":
            props = {}
        elif name == "END" and val.strip().upper() == "VEVENT" and props is not None:
            try:
                x = _series(props)
                (cancelled if props.get("STATUS", [("", 0)])[0][0].strip().upper() == "CANCELLED" else out).append(x)
            except (KeyError, ValueError, TypeError):  # no DTSTART or an unreadable value: skip the event
                pass
            props = None
        elif props is not None:
            params = dict(p.split("=", 1) for p in plist if "=" in p)
            props.setdefault(name, []).append((val, params))
    for o in out + cancelled:  # a moved or cancelled instance suppresses the master's original slot
        if o.rid is not None and o.uid:
            for m in out:
                if m.uid == o.uid and m.rid is None:
                    m.exdates.append(o.rid)
    return out


def _add_months(d, n):
    m = d.month - 1 + n
    return d.replace(year=d.year + m // 12, month=m % 12 + 1)  # ValueError for a day the month lacks: that one is skipped


def _utc(v, like=None):
    if type(v) is date:
        return datetime.combine(v, time.min)
    if v.tzinfo is None and like is not None and like.tzinfo is not None:
        v = v.replace(tzinfo=like.tzinfo)
    return v.astimezone(timezone.utc) if v.tzinfo else v


def _occurrences(s):
    """Start values of a series in ascending order (at most CAP steps; callers stop earlier)."""
    base, r = s.start, s.rule
    if not r:
        yield base
        return
    n, i = 0, r["interval"]
    for k in range(CAP):
        if r["freq"] == "WEEKLY" and "byday" in r:
            monday = base - timedelta(days=base.weekday()) + timedelta(weeks=k * i)
            cands = [monday + timedelta(days=d) for d in r["byday"]]
        else:
            try:
                cands = [{"DAILY": lambda: base + timedelta(days=k * i),
                          "WEEKLY": lambda: base + timedelta(weeks=k * i),
                          "MONTHLY": lambda: _add_months(base, k * i),
                          "YEARLY": lambda: base.replace(year=base.year + k * i)}[r["freq"]]()]
            except ValueError:
                continue
        for c in cands:
            if c < base:
                continue
            if "count" in r and n >= r["count"]:
                return
            n += 1
            if "until" in r and _utc(c) > _utc(r["until"], c):
                return
            yield c


def _excluded(s, occ):
    for x in s.exdates:
        if type(x) is date:
            if x == (occ if s.all_day else occ.date()):
                return True
        elif not s.all_day and _utc(x, occ) == _utc(occ):
            return True
    return False


def events_on(series, day, tz):
    """Events on `day` in local `tz`, sorted. Timed events start that day; all-day ones cover it."""
    out = []
    for s in series:
        found = []
        try:
            for occ in _occurrences(s):
                if s.all_day:
                    if occ > day:
                        break
                    end = occ + s.duration
                    if end > day and not _excluded(s, occ):
                        found.append(Event(datetime.combine(occ, time.min, tz), datetime.combine(end, time.min, tz), s.summary, True))
                    continue
                local = occ.astimezone(tz) if occ.tzinfo else occ.replace(tzinfo=tz)
                if local.date() > day:
                    break
                if local.date() == day and not _excluded(s, occ):
                    found.append(Event(local, local + s.duration, s.summary, False))
        except (TypeError, ValueError, OverflowError):  # one malformed series must not break paint or the timer
            if not _warned:
                _warned.append(1)
                print("calendar: skipped an event that could not be expanded", file=sys.stderr)
            continue
        out += found
    return sorted(out, key=lambda e: (e.start, e.summary))


def rows(series, now):
    """Today-page rows (summary, "13:00" | "All day") for the day of aware `now`."""
    return [(e.summary, "All day" if e.all_day else e.start.strftime("%H:%M")) for e in events_on(series, now.date(), now.tzinfo)]


def due_reminders(series, now, seen):
    """Summaries of timed events starting within 10 minutes that were not reminded yet (`seen` is updated)."""
    out = []
    for day in (now.date(), now.date() + timedelta(days=1)):
        for e in events_on(series, day, now.tzinfo):
            key = (e.summary, e.start)
            if not e.all_day and timedelta(0) < e.start - now <= timedelta(minutes=10) and key not in seen:
                seen.add(key)
                out.append(e.summary)
    return out


class Calendar:
    def __init__(self, url):
        self.url = url.strip()
        if self.url.lower().startswith("webcal://"):
            self.url = "https://" + self.url[9:]
        self.series = []

    def fetch_once(self):
        if not self.url:
            return
        try:
            status, _, body = http.get(self.url, timeout=10)
            if status != 200:
                raise OSError(f"HTTP {status}")
            self.series = parse_ics(body.decode("utf-8"))  # one atomic assignment; the Qt side only reads it
        except (OSError, ValueError) as e:
            print(f"calendar fetch failed: {type(e).__name__}", file=sys.stderr)  # never the URL: it is a secret

    def refresh(self):
        threading.Thread(target=self.fetch_once, daemon=True).start()
