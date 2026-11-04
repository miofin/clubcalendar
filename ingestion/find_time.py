"""Find the first time of day mentioned in a block of text (e.g., an email body)."""

import re
from dataclasses import dataclass
from datetime import time
from typing import Optional


@dataclass
class ParsedTime:
    hour: int        # 0-23
    minute: int
    second: int
    text: str        # the exact substring that was matched (time zone excluded)
    tz: Optional[str]  # e.g. "EST", "PT", "UTC+5:30"; None if not given
    ambiguous: bool  # True if the text had no am/pm (e.g. "3:30") and it was inferred
    from_keyword: bool = False  # True if found only by the "at 3"-style fallback

    def to_time(self) -> time:
        """Convert to datetime.time."""
        return time(self.hour, self.minute, self.second)


# --------------------------------------------------------------------------
# Building blocks
# --------------------------------------------------------------------------

# Whitespace, including non-breaking spaces (macOS/Gmail often emit U+202F).
S = r"[ \t\u00a0\u202f]"
I = re.IGNORECASE

_UNITS = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
_TEENS = ["ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
          "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50}

# Number words 1-59. Keys are normalized (no spaces/hyphens), so
# "twenty-five", "twenty five" and "twentyfive" all map to 25.
NUM_WORDS = {}
_PATS = {}
for _i, _w in enumerate(_UNITS, 1):
    NUM_WORDS[_w], _PATS[_w] = _i, _w
for _i, _w in enumerate(_TEENS, 10):
    NUM_WORDS[_w], _PATS[_w] = _i, _w
for _t, _v in _TENS.items():
    NUM_WORDS[_t], _PATS[_t] = _v, _t
    for _i, _u in enumerate(_UNITS, 1):
        NUM_WORDS[_t + _u] = _v + _i
        _PATS[_t + _u] = _t + r"[-\s]?" + _u


def _alt(keys) -> str:
    # Longest first so "twenty-five" wins over "twenty".
    return "|".join(_PATS[k] for k in sorted(keys, key=len, reverse=True))


NUMW = _alt(NUM_WORDS)
HOURW = _alt([k for k, v in NUM_WORDS.items() if 1 <= v <= 12])
# Minutes in words: "thirty", "forty-five", "oh five"
MINW = rf"(?:(?:oh|o)[-\s]?(?:{'|'.join(_UNITS)})|{NUMW})"


def _word_value(words: str) -> Optional[int]:
    key = re.sub(r"[-\s]", "", words.lower())
    if key in NUM_WORDS:
        return NUM_WORDS[key]
    key = key[2:] if key.startswith("oh") else key[1:]  # "oh five" -> five
    return NUM_WORDS.get(key)


MER = r"(?P<mer>[ap])\.?m\.?(?![A-Za-z])"          # am, a.m., PM, p.m.
NO_NUM = r"(?<![\d:./-])"                           # not glued to other numbers
STRICT_PERIOD = rf"(?={S}+in{S}+the{S}+(?:morning|afternoon|evening)\b)"
PERIOD_RE = re.compile(
    rf"{S}+(?:(?:in{S}+the|this){S}+)?(?P<per>morning|afternoon|evening)\b"
    rf"|{S}+(?P<tn>tonight)\b", I)
MONTH_RE = (r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|"
            r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?")

# 3:30, 15:30, 3:30:45, 3:30 pm
COLON = re.compile(
    rf"{NO_NUM}(?P<h>\d{{1,2}}):(?P<m>\d{{2}})(?::(?P<s>\d{{2}}))?(?!\d|:\d)(?:{S}*{MER})?", I)
# 3.30pm (only with am/pm, otherwise it looks like a decimal)
DOT = re.compile(rf"{NO_NUM}(?P<h>\d{{1,2}})\.(?P<m>\d{{2}}){S}*{MER}", I)
# 3pm, 3 p.m.
BARE = re.compile(rf"{NO_NUM}(?P<h>\d{{1,2}}){S}*{MER}", I)
# 3-4pm, 9 to 5pm, 11:30 - 1pm  (first time inherits am/pm from the end)
RANGE = re.compile(
    rf"{NO_NUM}(?P<h>\d{{1,2}})(?::(?P<m>\d{{2}}))?{S}*(?:-|–|—|to|until|till){S}*"
    rf"(?P<h2>\d{{1,2}})(?::(?P<m2>\d{{2}}))?{S}*{MER}", I)
# 9 in the morning
PERIOD_ONLY = re.compile(
    rf"{NO_NUM}(?P<h>\d{{1,2}}){STRICT_PERIOD}", I)
# 3 o'clock, three o'clock, 3 o'clock pm
OCLOCK = re.compile(
    rf"(?<![\w:./-])(?:(?P<d>\d{{1,2}})|(?P<w>{HOURW})){S}*o['’]?{S}?clock\b"
    rf"(?:{S}*{MER})?", I)
# three pm, ten thirty am, twelve forty-five pm, nine in the morning
WORDTIME = re.compile(
    rf"\b(?P<hw>{HOURW})(?:[ \t-]+(?P<mw>{MINW}))?(?:{S}*{MER}|{STRICT_PERIOD})", I)
# half past 3, quarter to four, ten past two, 5 minutes to 4
RELATIVE = re.compile(
    rf"{NO_NUM}\b(?P<lead>quarter|half|(?P<n>\d{{1,2}}|{NUMW})(?P<mins>{S}+minutes?)?)"
    rf"{S}+(?P<dir>past|after|to|till|until|before){S}+"
    rf"(?P<hr>\d{{1,2}}(?![\d:])|(?:{HOURW})\b)(?:{S}*{MER})?", I)
# 1500 hours, 0900h
MILITARY = re.compile(
    rf"{NO_NUM}(?P<h>[01]\d|2[0-3])(?P<m>[0-5]\d){S}*(?:hours?|hrs?|h)\b", I)
NOON = re.compile(r"\b(?P<w>noon|midday|midnight)\b", I)

# Case-sensitive on purpose, so the word "et" or "ist" isn't read as a zone.
TZ_RE = re.compile(
    rf"{S}*\(?\b((?:UTC|GMT)(?:{S}?[+-]\d{{1,2}}(?::?\d{{2}})?)?"
    r"|[ECMP][SD]T|[ECMP]T|BST|CEST|CET|IST|JST|AEST|AEDT)\b")


# --------------------------------------------------------------------------
# Fallback: a bare hour after a time keyword ("see you at 3!!"). Only used
# when nothing else in the text looks like a time.
# --------------------------------------------------------------------------

_NOT_COUNT = (r"days?|weeks?|months?|years?|hours?|hrs?|minutes?|mins?|seconds?|secs?|"
              r"people|persons?|guests?|attendees?|members?|kids?|students?|items?|"
              r"things?|pieces?|pages?|slides?|points?|options?|reasons?|ways?|units?|"
              r"miles?|feet|percent|dollars?|bucks|cents?|times?|place|of|least|most|"
              r"more|less|other|another")
# What may NOT follow the number: a counted noun or a month ("at 3 people", "by 3 Oct").
_NOT_TIME = rf"{S}+(?:{_NOT_COUNT}|{MONTH_RE})\b"
FALLBACK = re.compile(
    rf"(?:(?<![\w.])@|\b(?:at|around|by|before|after|until|till|til|from)\b){S}*"
    rf"(?:(?P<h>1[0-2]|[1-9])(?!\d)(?:ish)?|(?P<w>{HOURW})\b)"
    rf"(?!\w|[%/]|:\d|[.,]\d|{_NOT_TIME}|{S}*(?:-|–|—|to){S}*\d+{_NOT_TIME})", I)


def _infer_window(hour: int, minute: int):
    """Pick am or pm so the time lies in [10:00, 22:00).

    Exactly one of x and x + 12h does, so 3:30 -> 15:30, 10:15 -> 10:15,
    9:59 -> 21:59, 12:30 -> 12:30.
    """
    x = (hour * 60 + minute) % 720
    if x == 11 * 60 + 59:          # ambiguous 11:59 -> 11:59 pm
        return 23, 59
    total = x if x >= 600 else x + 720
    return total // 60, total % 60


def _keyword_fallback(text: str) -> Optional[ParsedTime]:
    for m in FALLBACK.finditer(text):
        if m["w"]:
            if m.group(0).lower().startswith("by"):  # "one by one"
                continue
            h = _word_value(m["w"])
        else:
            h = int(m["h"])
        hour, minute = _infer_window(h, 0)
        tz = TZ_RE.match(text, m.end())
        return ParsedTime(hour, minute, 0, m.group(0),
                          tz.group(1) if tz else None, True, True)
    return None


def _to24(hour: int, mer: str) -> int:
    if mer.lower() == "a":
        return 0 if hour == 12 else hour
    return 12 if hour == 12 else hour + 12


def _resolve(text: str, m: re.Match, hour: int):
    """Apply an explicit am/pm or a following 'in the morning'-style phrase.

    Returns (hour24, end_index, ambiguous).
    """
    mer = m.groupdict().get("mer")
    if mer:
        return _to24(hour, mer), m.end(), False
    p = PERIOD_RE.match(text, m.end())
    if p:
        is_am = (p.group("per") or "").lower() == "morning"
        return _to24(hour, "a" if is_am else "p"), p.end(), False
    return hour, m.end(), True


def _candidates(text: str):
    """Yield (start, end, hour24, minute, second, ambiguous) for plausible times."""

    for m in COLON.finditer(text):
        h, mi, s = int(m["h"]), int(m["m"]), int(m["s"] or 0)
        if mi > 59 or s > 59:
            continue
        zero_padded = len(m["h"]) == 2 and m["h"][0] == "0"
        if m["mer"]:
            if not 1 <= h <= 12:
                continue
            hour, end, amb = _resolve(text, m, h)
        elif 1 <= h <= 12 and not zero_padded:
            hour, end, amb = _resolve(text, m, h)
        elif h <= 23:  # 0:xx, 13-23:xx, or 09:30 -> clearly 24-hour
            hour, end, amb = h, m.end(), False
        else:
            continue
        yield m.start(), end, hour, mi, s, amb

    for m in DOT.finditer(text):
        h, mi = int(m["h"]), int(m["m"])
        if 1 <= h <= 12 and mi <= 59:
            yield m.start(), m.end(), _to24(h, m["mer"]), mi, 0, False

    for m in BARE.finditer(text):
        h = int(m["h"])
        if 1 <= h <= 12:
            yield m.start(), m.end(), _to24(h, m["mer"]), 0, 0, False

    for m in RANGE.finditer(text):
        h1, h2, mi = int(m["h"]), int(m["h2"]), int(m["m"] or 0)
        if not (1 <= h1 <= 12 and 1 <= h2 <= 12) or mi > 59 or int(m["m2"] or 0) > 59:
            continue
        mer = m["mer"].lower()
        if h1 % 12 > h2 % 12:  # "9-5pm" -> 9am, "11-1pm" -> 11am
            mer = "p" if mer == "a" else "a"
        yield m.start(), m.end(), _to24(h1, mer), mi, 0, False

    for m in PERIOD_ONLY.finditer(text):
        h = int(m["h"])
        before = text[:m.start()]
        if re.search(rf"\b(?:{MONTH_RE})\.?{S}*$", before, I):  # "Oct 5 in the morning"
            continue
        if 1 <= h <= 12:
            hour, end, amb = _resolve(text, m, h)
            yield m.start(), end, hour, 0, 0, amb

    for m in OCLOCK.finditer(text):
        h = int(m["d"]) if m["d"] else _word_value(m["w"])
        if h and 1 <= h <= 12:
            hour, end, amb = _resolve(text, m, h)
            yield m.start(), end, hour, 0, 0, amb

    for m in WORDTIME.finditer(text):
        h = _word_value(m["hw"])
        mi = _word_value(m["mw"]) if m["mw"] else 0
        if h and mi is not None and mi <= 59:
            hour, end, amb = _resolve(text, m, h)
            yield m.start(), end, hour, mi, 0, amb

    for m in RELATIVE.finditer(text):
        lead = m["lead"].lower()
        direction = m["dir"].lower()
        later = direction in ("to", "till", "until", "before")
        if lead == "quarter":
            n = 15
        elif lead == "half":
            if later:
                continue
            n = 30
        else:
            n = int(m["n"]) if m["n"].isdigit() else _word_value(m["n"])
            # "10 to 5" is a range of hours, not a time; require "minutes" there.
            if later and not m["mins"]:
                continue
        hr = int(m["hr"]) if m["hr"].isdigit() else _word_value(m["hr"])
        if not n or not 1 <= n <= 59 or not hr or not 1 <= hr <= 12:
            continue
        hour, end, amb = _resolve(text, m, hr)
        total = hour * 60 + (-n if later else n)
        total %= 24 * 60
        yield m.start(), end, total // 60, total % 60, 0, amb

    for m in MILITARY.finditer(text):
        yield m.start(), m.end(), int(m["h"]), int(m["m"]), 0, False

    for m in NOON.finditer(text):
        hour = 0 if m["w"].lower() == "midnight" else 12
        yield m.start(), m.end(), hour, 0, 0, False


def find_first_time(text: str) -> Optional[ParsedTime]:
    """Return the first (earliest-appearing) time of day in `text`, or None.

    Recognized formats (case-insensitive) include:
      3pm, 3 PM, 3 p.m., 3:30pm, 3.30pm, 3:30:45 pm
      15:30, 9:05, 2026-10-24T15:30:00
      noon, midnight
      three o'clock, 3 o'clock in the afternoon, nine in the morning
      ten thirty am, twelve forty-five pm
      half past three, quarter to four pm, ten past two
      1500 hours, 0900h
      3-4pm, 9 to 5pm (reports the start time)
    A trailing zone (EST, PT, UTC+5:30, ...) is returned in `.tz`.

    If the text gives no am/pm or morning/afternoon/evening (e.g. "3:30",
    "half past three"), the time is assumed to fall in [10:00, 22:00) and
    `.ambiguous` is set to True. Explicit am/pm is always respected, as are
    clearly 24-hour times like "15:30" or "09:30".

    Only if no time is found at all, a fallback accepts a bare hour right after
    a keyword ("see you at 3!!" -> 15:00, `.from_keyword` is True). See
    FALLBACK above for the exact rules.
    """
    best = None
    for start, end, hour, minute, second, amb in _candidates(text):
        if best is None or (start, -end) < (best[0], -best[1]):
            best = (start, end, hour, minute, second, amb)
    if best is None:
        return _keyword_fallback(text)
    start, end, hour, minute, second, amb = best
    if amb:
        hour, minute = _infer_window(hour, minute)
    tz = TZ_RE.match(text, end)
    return ParsedTime(hour, minute, second, text[start:end],
                      tz.group(1) if tz else None, amb)


if __name__ == "__main__":
    # (text, expected (hour, minute, second, ambiguous, tz)) or None
    tests = [
        ("See you at 3pm", (15, 0, 0, False, None)),
        ("3 PM works", (15, 0, 0, False, None)),
        ("at 3 p.m. sharp", (15, 0, 0, False, None)),
        ("Come by 3:30 pm", (15, 30, 0, False, None)),
        ("3:30\u202fPM", (15, 30, 0, False, None)),
        ("3.30pm", (15, 30, 0, False, None)),
        ("3:30:45 pm", (15, 30, 45, False, None)),
        ("12am", (0, 0, 0, False, None)),
        ("12pm", (12, 0, 0, False, None)),
        ("12:30 AM", (0, 30, 0, False, None)),
        ("15:30", (15, 30, 0, False, None)),
        ("09:30", (9, 30, 0, False, None)),
        ("9:05", (21, 5, 0, True, None)),
        ("at 3:30: bring snacks", (15, 30, 0, True, None)),
        ("2026-10-24T15:30:00", (15, 30, 0, False, None)),
        ("9:00 tonight", (21, 0, 0, False, None)),
        ("10:15 in the morning", (10, 15, 0, False, None)),
        ("meet at noon", (12, 0, 0, False, None)),
        ("Midnight", (0, 0, 0, False, None)),
        ("good afternoon team", None),
        ("three o'clock", (15, 0, 0, True, None)),
        ("3 o'clock in the afternoon", (15, 0, 0, False, None)),
        ("nine in the morning", (9, 0, 0, False, None)),
        ("9 in the evening", (21, 0, 0, False, None)),
        ("ten thirty am", (10, 30, 0, False, None)),
        ("twelve forty-five PM", (12, 45, 0, False, None)),
        ("three pm", (15, 0, 0, False, None)),
        ("five oh five pm", (17, 5, 0, False, None)),
        ("half past three", (15, 30, 0, True, None)),
        ("quarter past 5", (17, 15, 0, True, None)),
        ("quarter to four pm", (15, 45, 0, False, None)),
        ("quarter to one pm", (12, 45, 0, False, None)),
        ("ten past two", (14, 10, 0, True, None)),
        ("5 minutes to 4 pm", (15, 55, 0, False, None)),
        ("open 10 to 5", None),
        ("1500 hours", (15, 0, 0, False, None)),
        ("0900h", (9, 0, 0, False, None)),
        ("3-4pm", (15, 0, 0, False, None)),
        ("9-5pm", (9, 0, 0, False, None)),
        ("11-1pm", (11, 0, 0, False, None)),
        ("12-1pm", (12, 0, 0, False, None)),
        ("3:00-4:30pm", (15, 0, 0, False, None)),
        ("3pm-4pm", (15, 0, 0, False, None)),
        ("3:30 pm EST", (15, 30, 0, False, "EST")),
        ("10 am (PT)", (10, 0, 0, False, "PT")),
        ("14:00 UTC+5:30", (14, 0, 0, False, "UTC+5:30")),
        ("Oct 24", None),
        ("10/24 and 10.24 and 2026-10-24", None),
        ("Oct 5 in the morning", None),
        ("I have 3 meetings and a ratio of 3 to 4", None),
        ("Back in 5 minutes", None),
        ("Earlier 8am, later 7pm", (8, 0, 0, False, None)),
        ("Lunch at 12:30, dinner at 7 PM", (12, 30, 0, True, None)),
        ("Nothing here.", None),
        # Range inference for times with no am/pm: [10:00, 22:00)
        ("10:15", (10, 15, 0, True, None)),
        ("11:45", (11, 45, 0, True, None)),
        ("12:00", (12, 0, 0, True, None)),
        ("1:00", (13, 0, 0, True, None)),
        ("9:59", (21, 59, 0, True, None)),
        ("ten o'clock", (10, 0, 0, True, None)),
        ("quarter to ten", (21, 45, 0, True, None)),
        ("quarter to eleven", (10, 45, 0, True, None)),
        ("quarter to one", (12, 45, 0, True, None)),
        ("9am", (9, 0, 0, False, None)),
        ("10pm", (22, 0, 0, False, None)),
        # Keyword fallback (only when no other time is found)
        ("see you at 3!!", (15, 0, 0, True, None)),
        ("See you AT 3.", (15, 0, 0, True, None)),
        ("meet @ 4", (16, 0, 0, True, None)),
        ("meet @4", (16, 0, 0, True, None)),
        ("around 10", (10, 0, 0, True, None)),
        ("at 11", (11, 0, 0, True, None)),
        ("at 12", (12, 0, 0, True, None)),
        ("at 9", (21, 0, 0, True, None)),
        ("at 10ish", (10, 0, 0, True, None)),
        ("at three", (15, 0, 0, True, None)),
        ("see you at one", (13, 0, 0, True, None)),
        ("by 5", (17, 0, 0, True, None)),
        ("from 2 to 4", (14, 0, 0, True, None)),
        ("at 3 EST", (15, 0, 0, True, "EST")),
        ("at 3-4", (15, 0, 0, True, None)),
        ("at 3 and 5pm", (17, 0, 0, False, None)),   # real time wins over fallback
        ("see you at 3, or 5:30", (17, 30, 0, True, None)),
        ("john@3m.com", None),
        ("at 3 people", None),
        ("after 3 days", None),
        ("at 3.5", None),
        ("at 3,000", None),
        ("at 2026", None),
        ("by 10/24", None),
        ("at 3rd", None),
        ("at 15", None),
        ("at 3m", None),
        ("at one point", None),
        ("one by one", None),
        ("at 3 October", None),
        ("from 5 to 10 days", None),
        ("up by 3%", None),
        ("format 3", None),
    ]
    for body, expected in tests:
        r = find_first_time(body)
        got = (r.hour, r.minute, r.second, r.ambiguous, r.tz) if r else None
        print(("PASS" if got == expected else "FAIL"), repr(body), "->", got)