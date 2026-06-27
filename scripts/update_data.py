#!/usr/bin/env python3
"""
Fetch the canton of Zürich "Baugesuche" (building applications) open dataset,
filter it to the city of Zürich, reproject to WGS84, and write a slim GeoJSON
that the web map consumes.

Runs on GitHub Actions (full internet access). Designed to be resilient:
- Discovers the download URL via the opendata.swiss CKAN API.
- Falls back to a known direct URL if the API is unavailable.
- Accepts either GeoJSON or GeoPackage (GPKG) source formats.

Data source: Kanton Zürich / opendata.swiss
Dataset: "Baugesuche im Kanton Zürich"
License: Open use (see opendata.swiss dataset page).
"""

from __future__ import annotations

import json
import os
import re
import sys
import datetime as dt
from pathlib import Path

import requests
import geopandas as gpd

# --- Configuration ---------------------------------------------------------

CKAN_API = "https://ckan.opendata.swiss/api/3/action/package_show"
DATASET_ID = "baugesuche-im-kanton-zurich"

# Fallback direct resource URL (used if the CKAN API can't be reached).
# The CKAN lookup is preferred because resource URLs can change over time.
FALLBACK_URL = (
    "https://www.web.statistik.zh.ch/ogd/data/baugesuche/baugesuche.gpkg"
)

# BFS municipality number for the City of Zürich.
ZURICH_CITY_BFS = 261

# Field-name candidates. The canton publishes English camelCase columns
# (projectDescription, publicationDate, ...); we lowercase before matching
# and keep German alternatives so a column rename doesn't break us.
BFS_FIELDS = ["bfs", "bfs_nr", "bfsnr", "gemeinde_bfs", "bfs_nummer"]
DESC_FIELDS = ["projectdescription", "beschrieb", "projektbeschrieb",
               "beschreibung", "bezeichnung"]
DATE_FIELDS = ["publicationdate", "datum", "publikationsdatum",
               "eingangsdatum", "datum_publikation"]
EXPIRATION_FIELDS = ["expirationdate", "ablaufdatum", "expiry", "gueltig_bis"]
STATUS_FIELDS = ["status", "verfahrensstand", "stand"]
ADDRESS_FIELDS = ["address", "adresse", "strasse", "standort"]
URL_FIELDS = ["url", "link"]
ID_FIELDS = ["id", "publicationnumber", "gesuchsnr"]

# When no BFS column exists, fall back to address-pattern filtering:
# postcodes 80xx are all within Stadt Zürich.
ZURICH_CITY_ADDR_RE = re.compile(r"80\d{2}\s+Z[üu]rich", re.IGNORECASE)

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "data"
OUT_FILE = OUT_DIR / "baugesuche_zuerich.geojson"
META_FILE = OUT_DIR / "meta.json"

UA = {
    "User-Agent": (
        "zurich-baugesuche-map/1.0 (+https://github.com/) "
        "Mozilla/5.0 compatible data fetcher"
    )
}


# --- Helpers ---------------------------------------------------------------

def discover_resource_url() -> str:
    """Ask the CKAN API for the best downloadable resource URL."""
    try:
        r = requests.get(
            CKAN_API, params={"id": DATASET_ID}, headers=UA, timeout=90
        )
        r.raise_for_status()
        resources = r.json()["result"]["resources"]
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] CKAN lookup failed ({exc}); using fallback URL.")
        return FALLBACK_URL

    # Prefer GeoJSON, then GPKG, then anything geo-ish.
    def score(res: dict) -> int:
        fmt = (res.get("format") or "").lower()
        return {"geojson": 3, "json": 2, "gpkg": 2, "geopackage": 2}.get(fmt, 0)

    candidates = sorted(resources, key=score, reverse=True)
    for res in candidates:
        url = res.get("download_url") or res.get("url")
        if url and score(res) > 0:
            print(f"[info] Using resource: {res.get('format')} -> {url}")
            return url

    print("[warn] No suitable resource found via CKAN; using fallback URL.")
    return FALLBACK_URL


def first_present(columns, candidates):
    """Return the first candidate column name that exists (case-insensitive)."""
    lower = {c.lower(): c for c in columns}
    for cand in candidates:
        if cand in lower:
            return lower[cand]
    return None


def download(url: str, dest: Path) -> Path:
    print(f"[info] Downloading {url}")
    with requests.get(url, headers=UA, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 16):
                fh.write(chunk)
    print(f"[info] Saved {dest} ({dest.stat().st_size/1e6:.1f} MB)")
    return dest


# --- Main ------------------------------------------------------------------

def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    url = discover_resource_url()

    suffix = ".gpkg" if url.lower().endswith(".gpkg") else ".geojson"
    raw = OUT_DIR.parent.parent / f"_raw{suffix}"
    download(url, raw)

    print("[info] Reading with geopandas ...")
    gdf = gpd.read_file(raw)
    print(f"[info] {len(gdf)} total features; columns: {list(gdf.columns)}")

    # Filter to City of Zürich. Prefer a BFS column; fall back to an
    # address-pattern check (postcode 80xx + "Zürich").
    bfs_col = first_present(gdf.columns, BFS_FIELDS)
    addr_col = first_present(gdf.columns, ADDRESS_FIELDS)
    before = len(gdf)
    if bfs_col is not None:
        gdf = gdf[gdf[bfs_col].astype(str).str.strip() == str(ZURICH_CITY_BFS)]
        print(f"[info] Filtered by {bfs_col}=={ZURICH_CITY_BFS}: "
              f"{before} -> {len(gdf)}")
    elif addr_col is not None:
        mask = gdf[addr_col].astype(str).str.contains(ZURICH_CITY_ADDR_RE, na=False)
        gdf = gdf[mask]
        print(f"[info] Filtered by {addr_col} matching '80xx Zürich': "
              f"{before} -> {len(gdf)}")
    else:
        print("[warn] No BFS or address column found; keeping all features.")

    if gdf.empty:
        print("[warn] No features after filtering. Writing empty FeatureCollection.")

    # Reproject to WGS84 for web mapping.
    if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
        print(f"[info] Reprojecting from {gdf.crs} to EPSG:4326")
        gdf = gdf.to_crs(4326)

    # Slim down properties to a predictable set for the frontend.
    cols = gdf.columns
    desc_col = first_present(cols, DESC_FIELDS)
    date_col = first_present(cols, DATE_FIELDS)
    exp_col = first_present(cols, EXPIRATION_FIELDS)
    status_col = first_present(cols, STATUS_FIELDS)
    addr_col = first_present(cols, ADDRESS_FIELDS)
    url_col = first_present(cols, URL_FIELDS)
    id_col = first_present(cols, ID_FIELDS)

    def prop(row, col):
        if col is None or col not in row:
            return None
        val = row[col]
        return None if (val is None or (isinstance(val, float) and val != val)) else str(val)

    features = []
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        # Use centroid for non-point geometries so the map always gets a marker.
        pt = geom if geom.geom_type == "Point" else geom.centroid
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [pt.x, pt.y]},
            "properties": {
                "id": prop(row, id_col),
                "description": prop(row, desc_col),
                "date": prop(row, date_col),
                "expiration": prop(row, exp_col),
                "status": prop(row, status_col),
                "address": prop(row, addr_col),
                "url": prop(row, url_col),
            },
        })

    fc = {"type": "FeatureCollection", "features": features}
    OUT_FILE.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    print(f"[info] Wrote {len(features)} features to {OUT_FILE}")

    meta = {
        "updated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source_url": url,
        "feature_count": len(features),
        "fields_detected": {
            "bfs": bfs_col, "description": desc_col,
            "date": date_col, "expiration": exp_col,
            "status": status_col, "address": addr_col,
            "url": url_col, "id": id_col,
        },
    }
    META_FILE.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[info] Wrote metadata to {META_FILE}")

    # Clean up raw download to keep the repo small.
    try:
        raw.unlink()
    except OSError:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
