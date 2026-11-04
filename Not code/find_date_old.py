"""Find the first date mentioned in a block of text (e.g., an email body)."""

import calendar
import re
from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class ParsedDate:
    month: int
    day: int
    year: Optional[int]  # None when the text gave no year
    text: str            # the exact substring that was matched

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


def find_first_date(text: str) -> Optional[ParsedDate]:
    """Return the first (earliest-appearing) date in `text`, or None.

    Recognized formats (case-insensitive) include:
      October 24 / Oct 24 / Oct. 24th / October 24, 2026
      October twenty-fourth / twenty fourth / twentyfourth / second
      24 October / 24th of October / the twenty-fourth of October
      10/24, 10 / 24, 10/24/2026, 10-24-26, 10.24.2026, 2026-10-24
    """
    best = None
    for start, end, parsed in _candidates(text):
        if best is None or (start, -end) < (best[0], -best[1]):
            best = (start, end, parsed)
    return best[2] if best else None


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