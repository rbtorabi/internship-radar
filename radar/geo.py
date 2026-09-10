"""Turns "Toronto, Canada" + a commute radius into a location matcher, using GeoNames places (pop >= 15k)."""

import gzip
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

DATA = Path(__file__).with_name("cities.tsv.gz")

# GeoNames codes Canadian provinces as numbers; job postings use these abbreviations.
CA_PROVINCES = {"01": "AB", "02": "BC", "03": "MB", "04": "NB", "05": "NL", "07": "NS", "08": "ON",
                "09": "PE", "10": "QC", "11": "SK", "12": "YT", "13": "NT", "14": "NU"}
COUNTRY_ALIASES = {"US": ["US", "U.S.", "USA", "United States of America"], "GB": ["UK", "U.K."]}
# How postings commonly write a city whose GeoNames name differs. (Don't strip " City" in general:
# "Missouri City" would become "Missouri" and match the whole state.)
CITY_ALIASES = {"New York City": {"New York", "NYC"}}
US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky",
    "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota",
    "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "PR": "Puerto Rico",
}
STATE_BY_NAME = {name.lower(): code for code, name in US_STATES.items()}
# A place name with no state or "USA" next to it only counts if it's a big US city: bare "Houston" does,
# bare "Kensington" (London) or "Airport" doesn't.
BARE_NAME_MIN_POP = 100_000


@dataclass
class City:
    name: str
    ascii: str
    cc: str
    country: str
    iso3: str
    admin1: str
    admin1_name: str
    lat: float
    lon: float
    pop: int
    gid: int = 0  # GeoNames id

    @property
    def names(self) -> set[str]:
        names = {self.name, self.ascii} | CITY_ALIASES.get(self.ascii, set())
        return {n for n in names if n}

    @property
    def hints(self) -> list[str]:
        """Words that place a posting in this city's province/state/country."""
        hints = [self.admin1_name, self.country, self.iso3, *COUNTRY_ALIASES.get(self.cc, [])]
        if self.cc == "US":
            hints.append(self.admin1)
        elif self.cc == "CA":
            hints.append(CA_PROVINCES.get(self.admin1, ""))
        return [h for h in hints if h]

    def __str__(self) -> str:
        return ", ".join(filter(None, [self.name, self.admin1_name, self.country]))


def load() -> list[City]:
    with gzip.open(DATA, "rt", encoding="utf-8") as f:
        return [City(*p[:7], float(p[7]), float(p[8]), int(p[9] or 0), int(p[10]) if len(p) > 10 and p[10] else 0)
                for p in (line.rstrip("\n").split("\t") for line in f)]


def km(a: City, b: City) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def _words(options) -> re.Pattern:
    # Whole words; short all-caps codes (ON, CA, NY) stay case-sensitive so "on"/"ca" in prose don't count.
    parts = [f"(?-i:{re.escape(o)})" if len(o) <= 3 and o.isupper() else re.escape(o)
             for o in sorted(set(options), key=len, reverse=True)]
    return re.compile(rf"(?<!\w)({'|'.join(parts)})(?!\w)", re.I)


def find_city(query: str, cities: list[City]) -> City:
    """"Toronto", "London, Canada", "Cambridge, MA" -> best match (the most populous if still ambiguous)."""
    name, *hints = [p.strip() for p in query.split(",") if p.strip()]
    found = [c for c in cities if name.lower() in {n.lower() for n in c.names}]
    if hints:
        wanted = {h.lower() for h in hints}
        found = [c for c in found if wanted & {h.lower() for h in c.hints}]
    if not found:
        raise ValueError(f'City "{query}" not found. Try "City, Country" with a city of 15,000+ people.')
    return max(found, key=lambda c: c.pop)


class Area:
    def __init__(self, query: str, radius_km: float):
        cities = load()
        self.home = find_city(query, cities)
        dist = {id(c): km(self.home, c) for c in cities}
        self.nearby = sorted((c for c in cities if dist[id(c)] <= radius_km), key=lambda c: -c.pop)
        far_names = {n.lower() for c in cities if dist[id(c)] > radius_km for n in c.names}
        # A town named like a state/country ("Washington", "Georgia") needs a hint too, or it matches the whole region.
        far_names |= {n.lower() for c in cities for n in (c.admin1_name, c.country) if n}

        plain: set[str] = set()
        ambiguous: dict[str, set[str]] = defaultdict(set)
        for c in self.nearby:
            for n in c.names:
                if n.lower() in far_names:
                    ambiguous[n].update(c.hints)  # e.g. Cambridge ON vs Cambridge MA: need "ON"/"Ontario"/"Canada" too
                else:
                    plain.add(n)
        self._plain = _words(plain) if plain else None
        self._ambiguous = [(_words([n]), _words(h)) for n, h in ambiguous.items()]

    def matches(self, text: str) -> bool:
        if self._plain and self._plain.search(text):
            return True
        return any(n.search(text) and h.search(text) for n, h in self._ambiguous)


class USLocator:
    """Finds US cities in free-text job locations: "Houston, TX", "US-TX-Katy", "Chicago IL USA"."""

    def __init__(self):
        cities = load()
        self.cities = [c for c in cities if c.cc == "US"]
        self.by_gid = {c.gid: c for c in self.cities}
        self._by_name: dict[str, list[City]] = defaultdict(list)
        for c in self.cities:
            for n in c.names:
                self._by_name[n.lower()].append(c)
        # The most populous place with each name worldwide: "Paris" alone means France, "Houston" alone means Texas.
        self._biggest: dict[str, City] = {}
        for c in cities:
            for n in c.names:
                if c.pop > getattr(self._biggest.get(n.lower()), "pop", -1):
                    self._biggest[n.lower()] = c
        self._names = _words(n for c in self.cities for n in c.names)
        self._codes = _words(US_STATES)
        self._states = _words(US_STATES.values())
        self._usa = _words(["United States", "United States of America", "USA", "U.S.", "U.S.A.", "US"])
        foreign = {c.country for c in cities if c.cc != "US" and c.country} | {"UK", "U.K."}
        # "Georgia" and "Jersey" are also countries; don't let them hide US states.
        self._foreign = _words(f for f in foreign if not any(_words([f]).search(s) for s in US_STATES.values()))
        self._foreign_cities = _words(n for c in cities if c.cc != "US" and c.pop >= 100_000
                                      for n in c.names if self._biggest[n.lower()] is c)
        self._cache: dict[str, tuple[list[City], bool | None]] = {}

    def locate(self, text: str) -> tuple[list[City], bool | None]:
        """Returns (US cities named in the text, True = in the US / False = abroad / None = can't tell)."""
        if text in self._cache:
            return self._cache[text]
        states = {m.group(0) for m in self._codes.finditer(text)}
        states |= {STATE_BY_NAME[m.group(0).lower()] for m in self._states.finditer(text)}
        found: dict[int, City] = {}
        says_usa = bool(self._usa.search(text))
        for m in self._names.finditer(text):
            name = m.group(0).lower()
            options = [c for c in self._by_name[name] if not states or c.admin1 in states]
            biggest = self._biggest[name]
            if options and (states or says_usa or (biggest.cc == "US" and biggest.pop >= BARE_NAME_MIN_POP)):
                best = max(options, key=lambda c: c.pop)
                found[best.gid] = best
        if found:
            result = (list(found.values()), True)
        elif self._foreign.search(text) or self._foreign_cities.search(text):
            result = ([], False)
        else:
            result = ([], True if states or says_usa else None)
        self._cache[text] = result
        return result
