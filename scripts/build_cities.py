"""Rebuilds radar/cities.tsv.gz from GeoNames (CC BY 4.0): every place with population >= 15,000.

    python scripts/build_cities.py
"""

import gzip
import io
import urllib.request
import zipfile
from pathlib import Path

BASE = "https://download.geonames.org/export/dump/"
OUT = Path(__file__).resolve().parent.parent / "radar" / "cities.tsv.gz"


def fetch(name: str) -> bytes:
    with urllib.request.urlopen(BASE + name, timeout=120) as r:
        return r.read()


def main() -> None:
    admin1 = dict(line.split("\t")[:2] for line in fetch("admin1CodesASCII.txt").decode("utf-8").splitlines() if line)
    countries = {}
    for line in fetch("countryInfo.txt").decode("utf-8").splitlines():
        if line and not line.startswith("#"):
            f = line.split("\t")
            countries[f[0]] = (f[4], f[1])  # name, ISO3
    raw = zipfile.ZipFile(io.BytesIO(fetch("cities15000.zip"))).read("cities15000.txt").decode("utf-8")

    rows = []
    for line in raw.splitlines():
        f = line.split("\t")
        cc, a1 = f[8], f[10]
        country, iso3 = countries.get(cc, ("", ""))
        # name, ascii name, country code, country, ISO3, admin1 code, admin1 name, lat, lon, population
        rows.append("\t".join([f[1], f[2], cc, country, iso3, a1, admin1.get(f"{cc}.{a1}", ""), f[4], f[5], f[14]]))
    with gzip.open(OUT, "wt", encoding="utf-8") as g:
        g.write("\n".join(rows) + "\n")
    print(f"wrote {len(rows)} places to {OUT}")


if __name__ == "__main__":
    main()
