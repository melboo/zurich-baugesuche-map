# Zürich Baugesuche Map

An interactive map of **building applications (Baugesuche) filed in the city of Zürich**, refreshed automatically every day. Each pin is a project that has been submitted to the authorities — proposed, under review, or approved.

Built on free official open data from the Canton of Zürich (via opendata.swiss). No server, no database, no cost: a daily GitHub Action downloads the latest data and the map is served as a static page from GitHub Pages.

![screenshot placeholder](docs/screenshot.png)

---

## What the data is (and isn't)

- **Source:** [*Baugesuche im Kanton Zürich*](https://opendata.swiss/de/dataset/baugesuche-im-kanton-zurich) on opendata.swiss, published by the Canton of Zürich. The canton checks for new applications daily.
- **Coverage:** every building application requires a Baugesuch, so this captures proposed projects, permit applications, and approved/under-construction work — all three at once, distinguished by the `status` field.
- **Window:** the canton only began collecting this centrally in autumn 2024, and applications stay public for roughly **one year**. So this is a rolling ~12-month view, not full history.
- **Important caveat:** a filed application does **not** prove construction started or that a project was ever realised. The dataset can't confirm completion. Names and addresses of applicants are deliberately stripped for privacy; project location and description are kept.
- **Scope:** the source is canton-wide; this project filters to the **City of Zürich** (BFS municipality number `261`). Change `ZURICH_CITY_BFS` in `scripts/update_data.py` to target a different municipality.

---

## How it works

```
opendata.swiss (CKAN)  ──►  scripts/update_data.py  ──►  docs/data/*.geojson  ──►  docs/index.html (map)
        ▲                          ▲                                                    ▲
   daily dataset           GitHub Action (cron)                              GitHub Pages (static)
```

1. **`scripts/update_data.py`** asks the opendata.swiss CKAN API for the dataset's current download URL (so it survives URL changes), downloads the GeoJSON/GeoPackage, filters to Zürich city, reprojects from Swiss LV95 (EPSG:2056) to WGS84, slims the fields, and writes `docs/data/baugesuche_zuerich.geojson` + `meta.json`.
2. **`.github/workflows/update-data.yml`** runs that script daily (and on demand), then commits the refreshed data.
3. **`docs/index.html`** is a self-contained MapLibre GL map that loads the GeoJSON. Filter by text, status, and how recently an application was filed.

---

## Deploy it (about 5 minutes)

1. **Create a repo** and push these files, or upload them via GitHub's web UI.

2. **Enable GitHub Pages**
   Repo → **Settings → Pages** → *Source:* **Deploy from a branch** → branch `main`, folder **`/docs`** → Save.
   Your map will be at `https://<your-username>.github.io/<repo-name>/`.

3. **Allow the Action to commit data**
   Repo → **Settings → Actions → General → Workflow permissions** → select **Read and write permissions** → Save.

4. **Run the updater once now** (don't wait for the nightly cron)
   Repo → **Actions** tab → **Update Baugesuche data** → **Run workflow**.
   When it finishes, refresh your Pages URL — the pins appear.

That's it. From then on it refreshes itself every day around 05:00 Zürich time.

---

## Run locally

```bash
pip install -r requirements.txt        # needs GDAL; see note below
python scripts/update_data.py          # writes docs/data/*.geojson

cd docs && python -m http.server 8000  # then open http://localhost:8000
```

> **GDAL note:** `geopandas` needs GDAL. On Ubuntu: `sudo apt-get install gdal-bin libgdal-dev`. On macOS: `brew install gdal`. The GitHub Action installs this for you.

---

## Customising

| Want to… | Change |
|---|---|
| Track a different municipality | `ZURICH_CITY_BFS` in `scripts/update_data.py` |
| Track the whole canton | Remove/disable the BFS filter in `update_data.py` |
| Change refresh time | the `cron` line in `.github/workflows/update-data.yml` |
| Restyle the map | CSS variables at the top of `docs/index.html` |
| Different basemap | the `style:` URL in `docs/index.html` |

If the canton renames columns, the script tries several common spellings (see the `*_FIELDS` lists) and logs which it detected in `docs/data/meta.json` under `fields_detected`. If a field comes back `null`, add the new column name to the relevant list.

---

## Licence & attribution

Code: MIT (see `LICENSE`). Data: © Canton of Zürich, provided as open government data via opendata.swiss under its open-use terms — attribute the source when you publish. This project is not affiliated with the Canton of Zürich.
