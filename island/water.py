"""Water reminder state: pure logic (no Qt), driven by the caller with an explicit `now`."""
from island import store

GLYPH = "\uE9CA"  # drop
DEFAULTS = {"bottle": 500, "goal": 1500, "start": 480, "end": 1440, "glass": 250, "every": 60}
REFILL = ("Time to Refill", "Your bottle is probably empty")


def minute(now):
    return now.hour * 60 + now.minute


class Water:
    def __init__(self, values):
        for k, default in DEFAULTS.items():
            v = store.get_int(values, k, default)
            setattr(self, k, v if v > 0 or k == "start" and v == 0 else default)
        self.day = values.get("day", "")
        self.taken = max(0, store.get_int(values, "taken", 0))
        self.last = store.get_int(values, "last", 0)

    def roll(self, now):
        today = now.strftime("%Y%m%d")
        if self.day != today:
            self.day, self.taken, self.last = today, 0, 0

    def due(self, now):
        self.roll(now)
        m = minute(now)
        return self.start <= m < self.end and self.taken < self.goal and m - self.last >= self.every

    def remind(self, now):
        """The popup to show if a drink is due; records the reminder so it repeats only after `every`."""
        if not self.due(now):
            return None
        self.last = minute(now)
        return ("popup", GLYPH, "Time to Drink", self.status())

    def drink(self, now):
        self.roll(now)
        before = self.taken
        self.taken += self.glass
        self.last = minute(now)
        return REFILL if before // self.bottle != self.taken // self.bottle else None

    def status(self):
        return f"{self.taken} / {self.goal} ml"

    def to_kv(self):
        return {k: getattr(self, k) for k in (*DEFAULTS, "day", "taken", "last")}
