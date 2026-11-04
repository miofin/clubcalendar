"""Find the first date mentioned in a block of text (e.g., an email body)."""

import calendar
import email.utils
import re
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Optional


@dataclass
class ParsedDate:
    month: int
    day: int
    year: Optional[int]  # None when the text gave no year
    text: str            # the exact substring that was matched
    year_inferred: bool = False  # year was missing and guessed from the sent date
    relative: bool = False       # came from a phrase like "tomorrow" / "this Sunday"

    def to_date(self, default_year: Optional[int] = None) -> date:
        """Convert to a datetime.date, filling in a missing year."""
        year = self.year or default_year or date.today().year
        return date(year, self.month, self.day)


# --------------------------------------------------------------------------
# Building blocks
# --------------------------------------------------------------------------

MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sept": 9, "sep": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}
# Words that are also common English words; when written in lowercase we
# only trust them if the day is given as digits ("may 5", not "may second").
AMBIGUOUS_MONTHS = {"may", "march"}

_ONES = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
_ONES_ORD = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh",
             "eighth", "ninth"]
_TEENS = ["ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
          "sixteen", "seventeen", "eighteen", "nineteen"]
_TEENS_ORD = ["tenth", "eleventh", "twelfth", "thirteenth", "fourteenth",
              "fifteenth", "sixteenth", "seventeenth", "eighteenth",
              "nineteenth"]

# "twentyfourth" -> 24, "twenty-fourth" / "twenty fourth" normalize to this too.
WORD_DAYS = {}
for _i, _w in enumerate(_ONES_ORD + _ONES, start=0):
    WORD_DAYS[_w] = (_i % 9) + 1
for _i, _w in enumerate(_TEENS_ORD + _TEENS):
    WORD_DAYS[_w] = 10 + (_i % 10)
WORD_DAYS["twentieth"] = 20
WORD_DAYS["twenty"] = 20
WORD_DAYS["thirtieth"] = 30
WORD_DAYS["thirty"] = 30
for _tens, _base in (("twenty", 20), ("thirty", 30)):
    for _i, _w in enumerate(_ONES_ORD + _ONES):
        if _base + (_i % 9) + 1 <= 31:
            WORD_DAYS[_tens + _w] = _base + (_i % 9) + 1


def _word_pattern() -> str:
    """Regex alternation matching word days, tolerating '-', ' ', or no gap."""
    alts = []
    for w in WORD_DAYS:
        for tens in ("twenty", "thirty"):
            if w.startswith(tens) and w != tens and w != tens + "th":
                if w not in ("twentieth", "thirtieth"):
                    alts.append(tens + r"[-\s]?" + w[len(tens):])
                    break
        else:
            alts.append(w)
    alts.sort(key=len, reverse=True)  # longest first so "twenty-first" beats "twenty"
    return "|".join(alts)


_MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))
_WORD_RE = _word_pattern()
_YEAR = r"(?:19|20)\d{2}"

# Day as digits (with optional ordinal suffix) or as words. Group 1 = digits,
# group 2 = words.
_DAY = rf"(?:(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?|\b({_WORD_RE}))"

FLAGS = re.IGNORECASE

# "October 24", "Oct. 24th, 2026", "october twenty-fourth", "Oct the 2nd"
MONTH_FIRST = re.compile(
    rf"\b({_MONTH_RE})\b\.?[ \t]*,?[ \t]*(?:the[ \t]+)?{_DAY}(?!\w)"
    rf"(?:[ \t]*,?[ \t]*({_YEAR})(?!\d))?",
    FLAGS,
)

# "24 October", "24th of October 2026", "the twenty-fourth of Oct", "24-Oct-2026"
DAY_FIRST = re.compile(
    rf"(?<![\w/.-]){_DAY}(?:[ \t]+of[ \t]+|[ \t]*[-.,]?[ \t]*)\b({_MONTH_RE})\b\.?"
    rf"(?:[ \t]*,?[ \t]*({_YEAR})(?!\d))?",
    FLAGS,
)

# 2026-10-24, 2026/10/24, 2026.10.24
ISO = re.compile(rf"(?<![\d/.-])({_YEAR})([-/.])(\d{{1,2}})\2(\d{{1,2}})(?![\d/])")

# 10/24, 10 / 24, 10/24/2026, 10 / 24 / 26
SLASH = re.compile(
    r"(?<![\d/.-])(\d{1,2})[ \t]*/[ \t]*(\d{1,2})(?:[ \t]*/[ \t]*(\d{4}|\d{2}))?(?![\d/])"
)

# 10-24-2026, 10-24-26, 10.24.2026
DASH_DOT = re.compile(r"(?<![\d/.-])(\d{1,2})([-.])(\d{1,2})\2(\d{4}|\d{2})(?![\d/])")


def _valid(month: int, day: int, year: Optional[int]) -> bool:
    if not 1 <= month <= 12:
        return False
    # Without a year, allow Feb 29 (use a leap year for the check).
    return 1 <= day <= calendar.monthrange(year or 2000, month)[1]


def _year(raw: Optional[str]) -> Optional[int]:
    if not raw:
        return None
    y = int(raw)
    return 2000 + y if y < 100 else y


def _day_value(digits: Optional[str], words: Optional[str]) -> Optional[int]:
    if digits:
        return int(digits)
    return WORD_DAYS.get(re.sub(r"[-\s]", "", words.lower()))


def _candidates(text: str):
    """Yield (start, end, ParsedDate) for every plausible date in `text`."""

    def named(m, month_g, digits_g, words_g, year_g):
        month_txt = m.group(month_g)
        month = MONTHS[month_txt.lower()]
        digits, words = m.group(digits_g), m.group(words_g)
        # "may second-guess", "I march first..." -> not dates
        if month_txt.lower() in AMBIGUOUS_MONTHS and month_txt.islower():
            if words or m.re is DAY_FIRST:
                return None
        day = _day_value(digits, words)
        year = _year(m.group(year_g))
        if day and _valid(month, day, year):
            return ParsedDate(month, day, year, m.group(0))

    for m in MONTH_FIRST.finditer(text):
        p = named(m, 1, 2, 3, 4)
        if p:
            yield m.start(), m.end(), p

    for m in DAY_FIRST.finditer(text):
        p = named(m, 3, 1, 2, 4)
        if p:
            yield m.start(), m.end(), p

    for m in ISO.finditer(text):
        y, mo, d = int(m.group(1)), int(m.group(3)), int(m.group(4))
        if _valid(mo, d, y):
            yield m.start(), m.end(), ParsedDate(mo, d, y, m.group(0))

    for m in SLASH.finditer(text):
        a, b, y = int(m.group(1)), int(m.group(2)), _year(m.group(3))
        # Default to US order (M/D); flip if only D/M makes sense (e.g. 24/10).
        month, day = (b, a) if a > 12 and b <= 12 else (a, b)
        if _valid(month, day, y):
            yield m.start(), m.end(), ParsedDate(month, day, y, m.group(0))

    for m in DASH_DOT.finditer(text):
        a, sep, b, raw_y = int(m.group(1)), m.group(2), int(m.group(3)), m.group(4)
        if sep == "." and len(raw_y) == 2:  # "1.2.34" is more likely a version
            continue
        y = _year(raw_y)
        month, day = (b, a) if a > 12 and b <= 12 else (a, b)
        if _valid(month, day, y):
            yield m.start(), m.end(), ParsedDate(month, day, y, m.group(0))


# --------------------------------------------------------------------------
# Relative dates: "tomorrow", "this Sunday", "in 3 days", ...
# These need the date the message was sent.
# --------------------------------------------------------------------------

_WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2, "weds": 2, "thursday": 3, "thu": 3, "thur": 3,
    "thurs": 3, "friday": 4, "fri": 4, "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}
# Full names match any case; abbreviations only when capitalized, so the verb
# "sat" or the noun "sun" in lowercase is not read as a weekday.
_WD = (r"(?:(?i:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
       r"|Mon|Tues|Tue|Weds|Wed|Thurs|Thur|Thu|Fri|Sat|Sun)")
WEEKDAY_PHRASE = re.compile(
    rf"\b(?:(?P<mod>(?i:this|next|last))\s+(?:(?P<qual>(?i:coming|upcoming|past))\s+)?)?"
    rf"(?P<wd>{_WD})\b"
)
DAY_WORDS = re.compile(
    r"\b(?:(?:the\s+)?day\s+after\s+tomorrow|(?:the\s+)?day\s+before\s+yesterday"
    r"|last\s+night|this\s+(?:morning|afternoon|evening)"
    r"|tomorrow|tmrw|yesterday|today|tonight)\b",
    re.IGNORECASE,
)
_CARDINALS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
              "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
              "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
              "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
              "twenty": 20}
_NUM = r"(?:\d{1,3}|" + "|".join(sorted(_CARDINALS, key=len, reverse=True)) + ")"
IN_OFFSET = re.compile(rf"\bin\s+(?P<n>{_NUM})\s+(?P<u>days?|weeks?)\b", re.IGNORECASE)
FROM_NOW = re.compile(
    rf"\b(?P<n>{_NUM})\s+(?P<u>days?|weeks?)\s+(?:(?P<fut>from\s+(?:now|today))|(?P<ago>ago))\b",
    re.IGNORECASE,
)
# Text allowed between "Friday" and an explicit date it merely labels.
_GAP = re.compile(r"[ \t,:(\-–—]*(?:(?:on|the)\s+)?")


def _parse_sent_date(sent) -> Optional[date]:
    """Accept an RFC 2822 string, a datetime, or a date. Returns the calendar date
    in the message's own time zone."""
    if sent is None:
        return None
    if isinstance(sent, datetime):
        return sent.date()
    if isinstance(sent, date):
        return sent
    try:
        return email.utils.parsedate_to_datetime(sent).date()
    except (TypeError, ValueError, IndexError) as e:
        raise ValueError(f"Unrecognized sent date: {sent!r}") from e


def _num_value(raw: str) -> int:
    return int(raw) if raw.isdigit() else _CARDINALS[raw.lower()]


def _rel(d: date, text: str) -> ParsedDate:
    return ParsedDate(d.month, d.day, d.year, text, relative=True)


def _relative_candidates(text: str, today: date):
    """Yield (start, end, ParsedDate) for relative-date phrases."""
    for m in DAY_WORDS.finditer(text):
        w = m.group(0).lower()
        if "after tomorrow" in w:
            off = 2
        elif "before yesterday" in w:
            off = -2
        elif w in ("tomorrow", "tmrw"):
            off = 1
        elif w == "yesterday" or w == "last night":
            off = -1
        else:  # today, tonight, this morning/afternoon/evening
            off = 0
        yield m.start(), m.end(), _rel(today + timedelta(days=off), m.group(0))

    for m in WEEKDAY_PHRASE.finditer(text):
        target = _WEEKDAYS[m["wd"].lower()]
        mod = (m["mod"] or "").lower()
        qual = (m["qual"] or "").lower()
        cur = today.weekday()
        if mod == "next":      # that weekday in the following Mon-Sun week
            d = today + timedelta(days=7 - cur + target)
        elif mod == "last" or (mod == "this" and qual == "past"):
            d = today - timedelta(days=(cur - target) % 7 or 7)
        elif mod == "this":    # today counts
            d = today + timedelta(days=(target - cur) % 7)
        else:                  # bare "Friday": the next one, not today
            d = today + timedelta(days=(target - cur) % 7 or 7)
        yield m.start(), m.end(), _rel(d, m.group(0))

    for m in IN_OFFSET.finditer(text):
        days = _num_value(m["n"]) * (7 if m["u"].lower().startswith("w") else 1)
        yield m.start(), m.end(), _rel(today + timedelta(days=days), m.group(0))

    for m in FROM_NOW.finditer(text):
        days = _num_value(m["n"]) * (7 if m["u"].lower().startswith("w") else 1)
        d = today + timedelta(days=days if m["fut"] else -days)
        yield m.start(), m.end(), _rel(d, m.group(0))


def _infer_year(month: int, day: int, today: date) -> int:
    """Pick the year that puts month/day closest to the sent date."""
    best = None
    for y in range(today.year - 4, today.year + 5):  # wide enough for Feb 29
        try:
            delta = abs((date(y, month, day) - today).days)
        except ValueError:
            continue
        if best is None or delta < best[0]:
            best = (delta, y)
    return best[1]


def find_first_date(text: str, sent_date=None) -> Optional[ParsedDate]:
    """Return the first (earliest-appearing) date in `text`, or None.

    `sent_date` is when the message was sent, as an RFC 2822 string such as
    "Fri, 23 Oct 2026 22:46:17 +0000" (a datetime or date also works). It is
    optional, but without it relative phrases are ignored and missing years
    stay None.

    Absolute formats (case-insensitive):
      October 24 / Oct 24 / Oct. 24th / October 24, 2026
      October twenty-fourth / twenty fourth / twentyfourth / second
      24 October / 24th of October / the twenty-fourth of October
      10/24, 10 / 24, 10/24/2026, 10-24-26, 10.24.2026, 2026-10-24

    Relative phrases (need `sent_date`):
      today, tonight, this morning/afternoon/evening, tomorrow, yesterday,
      last night, the day after tomorrow, the day before yesterday
      this Sunday (today counts), Sunday / on Sunday (the next one, not today),
      next Sunday (that day in the following Monday-Sunday week),
      last Sunday / this past Sunday
      in 3 days, in two weeks, in a week, 5 days from now, 3 days ago

    A weekday or "tomorrow" directly followed by an explicit date ("Friday,
    October 30") defers to the explicit date. If an absolute date has no year,
    the year closest to `sent_date` is used and `year_inferred` is True.
    """
    today = _parse_sent_date(sent_date)
    absolute = list(_candidates(text))
    relative = list(_relative_candidates(text, today)) if today else []

    # "Friday, October 30": the explicit date wins over the label before it.
    relative = [
        r for r in relative
        if not any(a[0] >= r[1] and _GAP.fullmatch(text, r[1], a[0]) for a in absolute)
    ]

    best = None
    for start, end, parsed in absolute + relative:
        if best is None or (start, -end) < (best[0], -best[1]):
            best = (start, end, parsed)
    if best is None:
        return None
    result = best[2]
    if result.year is None and today:
        result = replace(result, year=_infer_year(result.month, result.day, today),
                         year_inferred=True)
    return result


if __name__ == "__main__":
    tests = {
        "See you October 24!": (10, 24, None),
        "Let's meet on oct 24th at noon": (10, 24, None),
        "Due OCT. 24, 2026": (10, 24, 2026),
        "How about October twenty-fourth?": (10, 24, None),
        "october Twenty Fourth": (10, 24, None),
        "October twentyfourth works": (10, 24, None),
        "October second is fine": (10, 2, None),
        "Sept 3rd": (9, 3, None),
        "Call me 10/24": (10, 24, None),
        "Call me 10 / 24": (10, 24, None),
        "Deadline 10/24/2026": (10, 24, 2026),
        "24 October please": (10, 24, None),
        "the 24th of October": (10, 24, None),
        "the twenty-fourth of October": (10, 24, None),
        "2026-10-24": (10, 24, 2026),
        "24/10/2026": (10, 24, 2026),
        "1.2.3 release; ping me Dec 5 and Jan 2": (12, 5, None),
        "Hi, I may second-guess this. March 3rd instead": (3, 3, None),
        "Meet at 5pm, Oct 5pm no wait, Nov 9": (11, 9, None),
        "Feb 30 is bogus, but Feb 28 is not": (2, 28, None),
        "Dec 25, then Jan 1": (12, 25, None),
        "Jan 1 and earlier 12/25": (1, 1, None),
        "No date here, just 12 apples and 3 pm.": None,
    }
    for body, expected in tests.items():
        r = find_first_date(body)
        got = (r.month, r.day, r.year) if r else None
        print(("PASS" if got == expected else "FAIL"), repr(body), "->", got)

    # ---- relative dates and year inference (sent Fri, Oct 23, 2026) ----
    SENT = "Fri, 23 Oct 2026 22:46:17 +0000"
    ymd = lambda r: (r.year, r.month, r.day) if r else None
    rel_tests = [
        ("see you tomorrow", (2026, 10, 24)),
        ("Today works", (2026, 10, 23)),
        ("yesterday", (2026, 10, 22)),
        ("tonight", (2026, 10, 23)),
        ("this evening", (2026, 10, 23)),
        ("last night", (2026, 10, 22)),
        ("the day after tomorrow", (2026, 10, 25)),
        ("day before yesterday", (2026, 10, 21)),
        ("this Sunday", (2026, 10, 25)),
        ("this Friday", (2026, 10, 23)),
        ("Friday", (2026, 10, 30)),
        ("on saturday", (2026, 10, 24)),
        ("next Sunday", (2026, 11, 1)),
        ("next Monday", (2026, 10, 26)),
        ("next Friday", (2026, 10, 30)),
        ("last Friday", (2026, 10, 16)),
        ("last Sunday", (2026, 10, 18)),
        ("this past Wednesday", (2026, 10, 21)),
        ("this coming Tuesday", (2026, 10, 27)),
        ("See you Sat", (2026, 10, 24)),
        ("He sat there and the sun set", None),
        ("in 3 days", (2026, 10, 26)),
        ("in two weeks", (2026, 11, 6)),
        ("in a week", (2026, 10, 30)),
        ("5 days from now", (2026, 10, 28)),
        ("3 days ago", (2026, 10, 20)),
        ("next week", None),
        # year inference
        ("Oct 24", (2026, 10, 24)),
        ("January 5", (2027, 1, 5)),
        ("Oct 20", (2026, 10, 20)),
        ("Feb 29", (2028, 2, 29)),
        ("October 24, 2027", (2027, 10, 24)),
        # explicit date beats the label before it
        ("Friday, October 30", (2026, 10, 30)),
        ("Sat Oct 24", (2026, 10, 24)),
        ("tomorrow, October 28", (2026, 10, 28)),
        ("Friday the 30th of October", (2026, 10, 30)),
        # otherwise earliest wins
        ("tomorrow or October 30", (2026, 10, 24)),
        ("October 30 or tomorrow", (2026, 10, 30)),
    ]
    for body, expected in rel_tests:
        got = ymd(find_first_date(body, SENT))
        print(("PASS" if got == expected else "FAIL"), repr(body), "->", got)

    # no sent date: relative phrases ignored, years left as None
    assert find_first_date("tomorrow") is None
    assert find_first_date("Oct 24").year is None
    # datetime input works; bad strings raise
    assert ymd(find_first_date("tomorrow", datetime(2026, 10, 23))) == (2026, 10, 24)
    try:
        find_first_date("tomorrow", "not a date")
        print("FAIL bad sent date did not raise")
    except ValueError:
        print("PASS bad sent date raises ValueError")