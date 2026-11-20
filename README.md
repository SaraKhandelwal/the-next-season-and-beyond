# The Next Season | Merchandise Intelligence

Independent, evidence-first research into professional sports merchandise and women's sports fashion. **Not endorsed by Pacers Sports & Entertainment, the WNBA, NBA, or any retailer or team.** No internal sales, inventory, or revenue data.

## What's in the website

The GitHub Pages site is a self-contained publication **and** interactive research workspace, not a hosted API. It reads versioned local JSON so no backend has to be awake when someone opens the link.

1. **Intelligence overview:** Three documented, source-linked research directions and up to four evidence-based public-store signals. Each signal separates what was observed from what is not established. No invented opportunity scores.
2. **Compare stores:** Category-matched public product listings, sampled counts and median published prices, image gallery, and brand coverage matrix. Every comparison carries a sample-coverage warning.
3. **Product library:** Search by brand, product or retailer, filter by product group, examine supplied product imagery, visible size availability, original store URLs and export source-labelled CSV.
4. **Fashion research:** Fifteen separately documented launch case studies and five findings from the November 19, 2026 research archive. These are **not** represented as newly collected storefront inventory.
5. **Media & weather:** Google News headline counts (not fan demand), Indianapolis Open-Meteo forecasts, observed sizes on public outerwear listings, watch conditions, and collector health.

The visual theme is warm white, charcoal, slate borders and muted plum. No Pacers team branding or logos are used in the independent UI.

## Publish on GitHub Pages (no server required)

1. Unzip this project. Upload **all the contents** (including the hidden `.github/` directory, `site/` and `backend/`) to the root of your repository's `main` branch. Do not upload a nested ZIP folder.
2. On GitHub, open **Settings > Pages > Build and deployment > Source** and choose **GitHub Actions**, not "Deploy from a branch."
3. Open **Actions > Refresh public research and publish website > Run workflow**. The workflow also runs daily and on pushes to `main`.
4. The workflow installs Python dependencies, attempts permitted public-data refreshes, writes `site/snapshot.json`, and publishes the ready-to-view static `site/` directory. It stores a versioned cache of research observations across runs when available.
5. Inspect **Media & weather > Source collection health** after the first successful run. If retailers block access, they will be shown as unavailable or cached; they are **never** replaced by invented product lists. The research archive remains available regardless.

GitHub Pages does not perform real-time live research when a visitor opens it. A snapshot represents the **last successful observed source data**, not a live stock-feed. The UI hides the backend Refresh button when used statically.

**Important: at delivery the live store snapshot has no product rows.** This build environment cannot access external store APIs. The archive still has 15 documented cases, but the dynamic store comparison, prices, availability and live news sections require a successful collector run on GitHub Actions. Do not send the live-data parts as working intelligence until at least one refresh has actually collected the expected source observations.

## Project structure

```
site/                       # The deployable GitHub Pages website. No npm or Python runtime required by viewers.
  index.html, app.js, styles.css
  snapshot.json             # Exported public observations (initially empty, honestly labelled)
  research/*.json           # Dated, documented research cases (Nov 19, 2026)
backend/
  main.py                   # Optional FastAPI API for local work
  db.py                     # SQLite observations and variant availability
  scraper.py                # Public Shopify parsing logic
  signals.py                # Collectors, comparisons and transparent evidence briefs
  run_refresh.py            # One refresh and export, intended for GitHub Actions
  export_static.py          # Reproducible static JSON exporter
  tests/                    # Local unit tests
frontend/                   # Original React/Vite developer frontend, updated for static fallback.
.github/workflows/          # Daily refresh + GitHub Pages deployment
```

### Local preview of the deployable site

```
cd site
python -m http.server 8765
```

Visit `http://localhost:8765/`. Do not open `index.html` via a `file://` URL because browsers block local JSON fetches.

### Local research collection

```
python -m pip install -r backend/requirements.txt
python backend/run_refresh.py
```

A data refresh may fail if a source does not expose a public endpoint, restricts automated requests, changes its platform, blocks the IP, or limits requests. No bypasses or invented fallbacks are included. The Python/FastAPI backend is optional for the static GitHub Pages deployment.

### Unit and syntax tests

```
python -m unittest discover -s backend/tests -v
node --check site/app.js
python -m compileall -q backend
```

The `site/` UI was also exercised through a source-level JavaScript rendering smoke test of all five sections. A real Chromium page-level render check could not be completed in this build environment because browser navigation was blocked. The React/Vite developer build was not executed because npm packages could not be downloaded here. **The prebuilt static site does not require that build.**

## Methodological limitations

- Public pages sampled via Shopify first-page product JSON are **not complete retailer catalogs**. Price comparisons must use the same category and are still sensitive to source selection.
- A brand not observed in a sampled page is not proven absent from the full assortment.
- A publicly unavailable size does not prove an item was recently sold out, nor an internal inventory shortage.
- Google News headline counts and search-query matching **do not measure fan demand**.
- Cold-snap thresholds are documented screening heuristics. They do not predict sales.
- The case study archive is purposively collected. Its sample counts do not demonstrate market-wide growth.
- Product image URLs remain hosted by the original retailers. Some may stop working or may have restrictions on use.
- Monitor source terms and robots directives before enabling or expanding automated retail collection. A source failing to respond should stay marked unavailable.

## Data provenance

- Live store listings: public retailer product feeds, captured with timestamps in SQLite, exported as JSON; direct links in product cards.
- Media: Google News RSS search results, with publisher URLs; not sentiment analysis or demand.
- Weather: Open-Meteo Indianapolis daily forecast, with last-observed date.
- Fashion launch archive: original documented source URLs and research notes in `site/research/`.

Data collection is not a claim of access to the teams' private business systems.
