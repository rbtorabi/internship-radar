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
        return [City(*p[:7], float(p[7]), float(p[8]), int(p[9] or 0))
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
