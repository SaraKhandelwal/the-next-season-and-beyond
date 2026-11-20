"""Independent merchandise intelligence from sampled public storefronts and media.

Signal 1  Rival store assortment & price architecture   (Shopify products.json, page 1 per store)
Signal 2  Fan & Cultural Merch Chatter                  (Google News RSS, fan-driven merch/drop queries)
Signal 3  Cultural & tunnel-fit momentum                (Google News RSS)
Signal 4  Indianapolis weather / cold-snap readiness    (Open-Meteo)
Signal 5  Source-backed issues to review (no pseudo-opportunity scores)

Nothing here ships sample data: every table is filled by a live request and read back from SQLite.
"""
import math
import os
import re
import statistics
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus, urlparse

import requests

import db
import scraper

# ------------------------------------------------------------------ configuration

PSE_HOST = urlparse(scraper.STORE).netloc


def _clean_host(h):
    """'://bulls.com', 'https://bulls.com/' and 'bulls.com' all become 'bulls.com'."""
    h = h.strip()
    h = re.sub(r"^(?:[a-z]+)?://", "", h, flags=re.I)
    return h.strip("/ ")


RIVAL_CANDIDATES = [h for h in (_clean_host(x) for x in os.environ.get(
    "RIVAL_HOSTS",
    "chicagoskyshop.com,lakersstore.com,://warriors.com,celticsstore.com,://bulls.com,://playasociety.com"
).split(",")) if h]
MAX_RIVALS = 3
MIN_RIVALS = 2
SHOPIFY_DELAY = 2.5               # seconds slept between consecutive Shopify requests
SHOPIFY_LIMIT = 250               # page=1 only
SHOPIFY_TIMEOUT = 8

FAN_QUERIES = [
    ("\"Indiana Fever\" merch OR jersey OR hoodie", "Indiana Fever"),
    ("\"Indiana Pacers\" merch OR jersey OR collab", "Indiana Pacers"),
    ("\"Caitlin Clark\" merch OR hoodie OR fashion", "Caitlin Clark"),
    ("\"Tyrese Haliburton\" fashion OR tunnel fit", "Tyrese Haliburton"),
]
FAN_DELAY = 1.0
FAN_WINDOW = "when:60d"
# default theme for a headline that matches no theme keywords, by the query that found it
FAN_DEFAULT_THEME = {"Indiana Fever": "Player & Signature Product Coverage", "Indiana Pacers": "Retro & City Design Coverage",
                     "Caitlin Clark": "Player & Signature Product Coverage", "Tyrese Haliburton": "Athlete Style & Streetwear Coverage"}

NEWS_QUERIES = ["Indiana Fever merchandise collaboration", "Indiana Fever tunnel fit fashion",
                "Indiana Pacers tunnel fit fashion", "Indiana Pacers apparel collab"]
NEWS_DELAY = 1.0

INDY_LAT, INDY_LON = 39.7684, -86.1581
COLD_SNAP_F = 38

TIERS = [("<$50", 0, 50), ("$50–$99", 50, 100), ("$100–$149", 100, 150), ("$150+", 150, math.inf)]

BOUTIQUE_BRANDS = {
    "Wild Collective": [r"wild\s+collective"],
    "Playa Society": [r"playa\s+society"],
    "Round21": [r"round\s?21"],
    "Sportiqe": [r"sportiqe"],
    "FEAR OF GOD": [r"fear\s+of\s+god"],
    "Homage": [r"\bhomage\b"],
    "Mitchell & Ness": [r"mitchell\s*(?:&|and)\s*ness"],
    "'47": [r"(?<!\w)['’]47(?!\d)", r"\b47\s+brand\b"],
    "Terez": [r"\bterez\b"],
    "Pro Standard": [r"pro\s+standard"],
    "Stadium Essentials": [r"stadium\s+essentials"],
    "500 Level": [r"\b500\s*level\b"],
    "Warren Lotas": [r"warren\s+lotas"],
    "FOCO": [r"\bfoco\b"],
    "Seen": [r"^seen$"],                      # vendor-only: 'seen' is a common word in titles/tags
    "Bleacher Report": [r"bleacher\s+report"],
    "Starter": [r"^starter$"],                # vendor-only: 'starter' is a common word in titles/tags
    "Antigua": [r"\bantigua\b"],
}
# Ambiguous one-word brands are matched against the product's vendor field only.
VENDOR_ONLY_BRANDS = {"Seen", "Starter"}
_BRAND_RES = {b: [re.compile(p, re.I) for p in pats] for b, pats in BOUTIQUE_BRANDS.items()}

WOMENS_RE = re.compile(r"\bwomen(?:['’]?s)?\b|\bwomens\b|\bladies\b|\bwmns?\b", re.I)
CROPPED_RE = re.compile(r"\bcrop(?:ped)?\b", re.I)
BOXY_RE = re.compile(r"\bboxy\b", re.I)
OUTERWEAR_RE = re.compile(r"\b(jacket|coat|puffer|parka|windbreaker|anorak|bomber|varsity|vest|full[- ]zip|"
                          r"quarter[- ]zip|1/4[- ]zip|half[- ]zip|sherpa)\b", re.I)

# ------------------------------------------------------------------ Signal 1: Shopify rivals


class ShopifyUnavailable(Exception):
    pass


def fetch_store_page1(host, sess):
    """products.json?limit=250&page=1 for one storefront. Raises ShopifyUnavailable unless it is a
    real Shopify JSON catalog. Returns (raw_products, final_host)."""
    url = f"https://{host}/collections/all/products.json?limit={SHOPIFY_LIMIT}&page=1"
    r = None
    for attempt in (0, 1):
        r = sess.get(url, timeout=SHOPIFY_TIMEOUT)
        if r.status_code == 429 and attempt == 0:
            time.sleep(min(scraper._retry_after(r) or 5, 5))
            continue
        break
    if r.status_code != 200:
        raise ShopifyUnavailable(f"HTTP {r.status_code}")
    try:
        data = r.json()
    except ValueError:
        raise ShopifyUnavailable("200 but not JSON (not a Shopify storefront at this host)")
    products = data.get("products") if isinstance(data, dict) else None
    if not isinstance(products, list) or not products:
        raise ShopifyUnavailable("JSON had no products array")
    return products, urlparse(r.url).netloc or host


def parse_rival(raw, host):
    tags = raw.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    prices = []
    for v in raw.get("variants", []):
        try:
            prices.append(float(v.get("price")))
        except (TypeError, ValueError):
            pass
    imgs = raw.get("images") or []
    options = raw.get("options") or []
    size_idx = next((i + 1 for i, o in enumerate(options) if (o.get("name") or "").lower() == "size"), None)
    size_available = {}
    if size_idx:
        for variant in raw.get("variants") or []:
            size = (variant.get(f"option{size_idx}") or "").strip()
            if size and size.lower() not in ("default title", "one size"):
                size_available[size] = size_available.get(size, False) or bool(variant.get("available"))
    sizes = [{"size": key, "available": value} for key, value in size_available.items()]
    return {
        "shopify_id": raw["id"], "title": raw.get("title", ""), "handle": raw.get("handle", ""),
        "vendor": raw.get("vendor"), "product_type": raw.get("product_type", ""), "tags": tags,
        "price": min(prices) if prices else None,
        "product_url": f"https://{host}/products/{raw.get('handle', '')}",
        "image_url": imgs[0].get("src") if imgs else None, "sizes": sizes,
    }


def sync_shopify(run_id, progress):
    sess = requests.Session()
    sess.headers.update({"User-Agent": scraper.UA, "Accept": "application/json"})
    first = True

    def throttle():
        nonlocal first
        if not first:
            time.sleep(SHOPIFY_DELAY)
        first = False

    # --- PS&E: reuse today's cached rows, otherwise one page=1 request
    notes, state = [], "ok"
    cached = db.store_fetched_today(PSE_HOST)
    if cached:
        pse_n = cached["product_count"]
        progress(f"Reusing today's cached Pacers Team Store catalog... {pse_n} SKUs")
        notes.append(f"Pacers Team Store: {pse_n} SKUs (cached today)")
        state = "cached"
    else:
        throttle()
        progress("Fetching Pacers Team Store catalog...")
        try:
            raw, _ = fetch_store_page1(PSE_HOST, sess)
            parsed = [scraper.parse_product(r) for r in raw]
            changes = db.upsert_catalog(run_id, parsed)
            db.log_store_fetch(run_id, PSE_HOST, True, 200, len(parsed))
            progress(f"Fetching Pacers Team Store catalog... {len(parsed)} SKUs found")
            notes.append(f"Pacers Team Store: {len(parsed)} SKUs, {changes} stock change(s) logged")
        except (ShopifyUnavailable, requests.RequestException) as e:
            db.log_store_fetch(run_id, PSE_HOST, False, note=str(e))
            if not db.get_pse_sample():
                raise RuntimeError(f"Could not fetch the Pacers Team Store catalog and none is cached: {e}")
            notes.append(f"Pacers Team Store fetch failed ({e}); using the previous snapshot")
            state = "partial"

    # --- Rivals: keep the first MAX_RIVALS candidates that return 200 Shopify JSON
    kept, tested = [], 0
    for host in RIVAL_CANDIDATES:
        if len(kept) >= MAX_RIVALS:
            break
        throttle()
        tested += 1
        progress(f"Testing rival store {host}... ({len(kept)} of {MAX_RIVALS} found)")
        try:
            raw, final_host = fetch_store_page1(host, sess)
        except (ShopifyUnavailable, requests.RequestException) as e:
            db.log_store_fetch(run_id, host, False, note=str(e))
            continue
        rows = [parse_rival(r, final_host) for r in raw]
        db.replace_rival_products(host, rows)
        db.log_store_fetch(run_id, host, True, 200, len(rows))
        kept.append(host)
    notes.append(f"Rivals: {', '.join(kept) if kept else 'none responded'} ({len(kept)} of {tested} tested)")
    if len(kept) < MIN_RIVALS:
        state = "partial"
        notes.append(f"Only {len(kept)} rival store(s) returned Shopify JSON (wanted {MIN_RIVALS}-{MAX_RIVALS})")
    return state, " · ".join(notes)


# ------------------------------------------------------------------ Signal 2: Fan & Cultural Merch Chatter

FAN_THEMES = ("Player & Signature Product Coverage", "Athlete Style & Streetwear Coverage", "Limited-Release Coverage",
              "Retro & City Design Coverage")
FAN_THEME_RES = {
    "Player & Signature Product Coverage": re.compile(
        r"caitlin clark|haliburton|\bclark\b|\bhoodie|\bjerseys?\b|signature|capsule|player|merch|apparel|"
        r"t-?shirt|\btee\b|fan gear|best[- ]selling|top[- ]selling|shoe|sneaker|logo", re.I),
    "Athlete Style & Streetwear Coverage": re.compile(
        r"tunnel|\bfit\b|outfit|fashion|style|streetwear|designer|vogue|runway|wardrobe|\bgq\b|drip|look", re.I),
    "Limited-Release Coverage": re.compile(
        r"sold out|sells? out|sell-?out|limited|\bdrops?\b|dropped|restock|release[ds]?|launch(?:ed|es|ing)?|"
        r"collab|collaboration|\bx\b|exclusive|backorder", re.I),
    "Retro & City Design Coverage": re.compile(
        r"retro|throwback|vintage|city edition|classic edition|statement edition|hardwood classics|"
        r"heritage|nostalgi|uniform|new jerseys?|unveil", re.I),
}
FAN_RELEVANT_RE = re.compile(
    r"merch|jersey|hoodie|apparel|clothing|fashion|style|outfit|tunnel|\bfit\b|collab|drop|capsule|"
    r"sneaker|shoe|streetwear|gear|swag|shirt|\btee\b|hat\b|cap\b|store|sold out|retro|city edition|uniform", re.I)

# kept so older call sites keep working: the theme names double as the classification labels
CLASSES = FAN_THEMES


def classify_fan_theme(title, query_key):
    """Cluster a headline into one of FAN_THEMES by keyword score; fall back to the query's default theme."""
    best, best_score = None, 0
    for name, rx in FAN_THEME_RES.items():
        score = len(rx.findall(title or ""))
        if score > best_score:
            best, best_score = name, score
    return best or FAN_DEFAULT_THEME.get(query_key, FAN_THEMES[0])


def sync_reddit(run_id, progress):
    """Signal 2 (key kept as 'reddit' so DB/API/UI wiring is unchanged): fan-driven merch chatter from
    Google News RSS, which answers reliably where Reddit returns 403."""
    sess = requests.Session()
    sess.headers.update({"User-Agent": scraper.UA})
    posts, seen_results, ok_queries = {}, 0, 0
    for i, (q, key) in enumerate(FAN_QUERIES):
        if i:
            time.sleep(FAN_DELAY)
        progress(f"Reading fan & cultural merch chatter: {q}... ({i + 1}/{len(FAN_QUERIES)})")
        url = f"https://news.google.com/rss/search?q={quote_plus(q + ' ' + FAN_WINDOW)}&hl=en-US&gl=US&ceid=US:en"
        try:
            r = sess.get(url, timeout=10)
            if r.status_code == 429:
                time.sleep(min(scraper._retry_after(r) or 3, 5))
                r = sess.get(url, timeout=10)
            if r.status_code != 200:
                continue
            items = parse_news_rss(r.content, q)
        except (requests.RequestException, ET.ParseError, ValueError):
            continue
        ok_queries += 1
        for n in items:
            seen_results += 1
            p = posts.setdefault(n["link"], {
                "id": n["link"], "subreddit": n["source"] or "Google News", "title": n["title"],
                "selftext": "", "score": 0, "num_comments": 0,
                "created_utc": datetime.fromisoformat(n["published_at"]).timestamp() if n["published_at"] else None,
                "url": n["link"], "flair": None, "queries": [], "_key": key,
            })
            if key not in p["queries"]:
                p["queries"].append(key)
    if not posts:
        raise RuntimeError(f"Google News RSS returned no fan merch headlines ({ok_queries} of {len(FAN_QUERIES)} queries answered)")
    # Prefer headlines with real merch/fashion language; keep everything if that would leave too few.
    relevant = {k: p for k, p in posts.items() if FAN_RELEVANT_RE.search(p["title"])}
    kept = relevant if len(relevant) >= 6 else posts
    for p in kept.values():
        p["score"] = len(p["queries"])     # number of search queries returning this headline, NOT fan demand
        p["classification"] = classify_fan_theme(p["title"], p.pop("_key"))
    db.upsert_reddit_posts(list(kept.values()))
    detail = f"{len(kept)} fan merch headlines kept from {seen_results} results ({ok_queries} of {len(FAN_QUERIES)} queries)"
    return ("ok" if ok_queries == len(FAN_QUERIES) else "partial"), detail


# ------------------------------------------------------------------ Signal 3: Google News RSS

TUNNEL_RE = re.compile(r"tunnel|\bfit\b|fashion|style|outfit|runway|vogue|designer|streetwear", re.I)
COLLAB_RE = re.compile(r"collab|collaboration|partner|partnership|capsule|\bx\b|drop|launch|limited", re.I)
MERCH_NEWS_RE = re.compile(r"merch|jersey|apparel|store|clothing|sneaker|shoe|hoodie|collection", re.I)


def parse_news_rss(content, query):
    if b"<!DOCTYPE" in content or b"<!ENTITY" in content:
        raise ValueError("RSS contained a DTD/entity declaration; refusing to parse")
    root = ET.fromstring(content)
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        if not title or not link:
            continue
        src_el = it.find("source")
        source = (src_el.text or "").strip() if src_el is not None and src_el.text else ""
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3].strip()
        try:
            published = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc).isoformat(timespec="seconds")
        except (TypeError, ValueError):
            published = None
        tags = [t for t, rx in (("Tunnel Fit", TUNNEL_RE), ("Collab", COLLAB_RE), ("Merch", MERCH_NEWS_RE))
                if rx.search(title)]
        items.append({"title": title, "link": link, "source": source or None, "published_at": published,
                      "tags": tags, "query": query})
    return items


def sync_news(run_id, progress):
    sess = requests.Session()
    sess.headers.update({"User-Agent": scraper.UA})
    collected, ok_queries = {}, 0
    for i, q in enumerate(NEWS_QUERIES):
        if i:
            time.sleep(NEWS_DELAY)
        progress(f"Reading Google News RSS: {q}...")
        url = f"https://news.google.com/rss/search?q={quote_plus(q + ' when:30d')}&hl=en-US&gl=US&ceid=US:en"
        try:
            r = sess.get(url, timeout=10)
            if r.status_code != 200:
                continue
            for n in parse_news_rss(r.content, q):
                collected.setdefault(n["link"], n)
            ok_queries += 1
        except (requests.RequestException, ET.ParseError, ValueError):
            continue
    if not collected:
        raise RuntimeError(f"Google News RSS returned no items ({ok_queries} of {len(NEWS_QUERIES)} queries answered)")
    db.upsert_news(list(collected.values()))
    detail = f"{len(collected)} headlines from {ok_queries} of {len(NEWS_QUERIES)} queries"
    return ("ok" if ok_queries == len(NEWS_QUERIES) else "partial"), detail


# ------------------------------------------------------------------ Signal 4: Open-Meteo

def parse_open_meteo(payload):
    daily = payload["daily"]
    return [{"date": d, "high_f": hi, "low_f": lo}
            for d, hi, lo in zip(daily["time"], daily["temperature_2m_max"], daily["temperature_2m_min"])
            if hi is not None and lo is not None]


def sync_weather(run_id, progress):
    progress("Fetching 14-day Indianapolis forecast from Open-Meteo...")
    url = ("https://api.open-meteo.com/v1/forecast"
           f"?latitude={INDY_LAT}&longitude={INDY_LON}&daily=temperature_2m_max,temperature_2m_min"
           "&temperature_unit=fahrenheit&forecast_days=14&timezone=America%2FIndiana%2FIndianapolis")
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    days = parse_open_meteo(r.json())
    if not days:
        raise RuntimeError("Open-Meteo returned no forecast days")
    db.replace_weather(days)
    cold = sum(1 for d in days if d["low_f"] < COLD_SNAP_F)
    return "ok", f"{len(days)}-day forecast, {cold} day(s) with a low under {COLD_SNAP_F}°F"


# ------------------------------------------------------------------ refresh orchestration

class Progress:
    NAMES = ("shopify", "reddit", "news", "weather")
    DONE = {"ok", "cached", "partial", "error"}

    def __init__(self):
        self._lock = threading.Lock()
        self._t0 = 0.0
        self._s = self._blank()

    def _blank(self):
        return {"running": False, "step": "Idle", "pct": 0, "run_id": None, "error": None, "elapsed": 0.0,
                "signals": {n: {"state": "idle", "detail": ""} for n in self.NAMES}, "version": 0}

    def _bump(self):
        self._s["version"] += 1
        self._s["elapsed"] = round(time.monotonic() - self._t0, 1)

    def try_start(self, run_id):
        with self._lock:
            if self._s["running"]:
                return False
            self._t0 = time.monotonic()
            v = self._s["version"]
            self._s = self._blank()
            self._s.update(running=True, step="Starting live sync...", run_id=run_id, pct=2, version=v)
            self._bump()
            return True

    def set(self, signal, state, detail):
        with self._lock:
            self._s["signals"][signal] = {"state": state, "detail": detail}
            self._s["step"] = detail
            sig = self._s["signals"].values()
            done = sum(1 for x in sig if x["state"] in self.DONE)
            running = sum(1 for x in sig if x["state"] == "running")
            if self._s["running"]:
                self._s["pct"] = min(95, 25 * done + 5 * running)
            self._bump()

    def finish(self, step, error=None):
        with self._lock:
            self._s.update(running=False, step=step, pct=100, error=error)
            self._bump()

    def snapshot(self):
        with self._lock:
            s = dict(self._s)
            if s["running"]:
                s["elapsed"] = round(time.monotonic() - self._t0, 1)
            return s


progress = Progress()

JOBS = {"shopify": sync_shopify, "reddit": sync_reddit, "news": sync_news, "weather": sync_weather}


def _job(name, fn, run_id):
    progress.set(name, "running", f"Starting {name}...")
    try:
        state, detail = fn(run_id, lambda msg: progress.set(name, "running", msg))
    except Exception as e:  # one failing signal must never sink the others
        state, detail = "error", f"{type(e).__name__}: {e}"
    db.set_signal_status(name, state, detail, run_id)
    progress.set(name, state, detail)
    return state


def start_refresh():
    """Start all four live fetches in parallel. Returns (started, run_id)."""
    run_id = db.start_run()
    if not progress.try_start(run_id):
        db.finish_run(run_id, "error", message="A refresh was already running; this run did not start.")
        return False, progress.snapshot()["run_id"]
    threading.Thread(target=_run, args=(run_id,), daemon=True).start()
    return True, run_id


def _run(run_id):
    t0 = time.monotonic()
    try:
        with ThreadPoolExecutor(max_workers=len(JOBS)) as ex:
            futures = {n: ex.submit(_job, n, fn, run_id) for n, fn in JOBS.items()}
            states = {n: f.result() for n, f in futures.items()}
        dur = round(time.monotonic() - t0, 1)
        failed = [n for n, s in states.items() if s == "error"]
        status = ("error" if len(failed) == len(states)
                  else "partial" if failed or "partial" in states.values() else "success")
        msg = "; ".join(f"{n}: {s}" for n, s in states.items())
        db.finish_run(run_id, status, dur, msg)
        progress.finish(f"Synced in {dur}s ({msg})", error=("All signals failed" if status == "error" else None))
    except Exception as e:
        db.finish_run(run_id, "error", round(time.monotonic() - t0, 1), f"{type(e).__name__}: {e}")
        progress.finish("Refresh failed", error=f"{type(e).__name__}: {e}")


# ------------------------------------------------------------------ analysis (computed at read time)

def _tier(price):
    for name, lo, hi in TIERS:
        if lo <= price < hi:
            return name
    return TIERS[-1][0]


def _pct(n, d):
    return round(100 * n / d, 1) if d else 0.0


def _money0(v):
    return "n/a" if v is None else f"${v:,.0f}"


def _normalize_pse(p):
    return {"title": p["title"], "vendor": p.get("vendor"), "product_type": p.get("product_type"),
            "tags": p.get("tags", []), "price": p.get("retail_price"), "url": p["product_url"],
            "image_url": p.get("image_url"), "sizes": p.get("sizes", []), "team": p.get("team"),
            "category": p.get("category"), "source": "public_storefront"}


def _normalize_rival(p):
    return {"title": p["title"], "vendor": p.get("vendor"), "product_type": p.get("product_type"),
            "tags": p.get("tags", []), "price": p.get("price"), "url": p["product_url"],
            "image_url": p.get("image_url"), "sizes": p.get("sizes", []), "team": None,
            "source": "public_storefront"}


def _brand_hit(p, brand, rxs):
    if brand in VENDOR_ONLY_BRANDS:
        v = (p.get("vendor") or "").strip()
        return bool(v) and any(rx.search(v) for rx in rxs)
    return any(rx.search(_text(p)) for rx in rxs)


def _text(p):
    return " ".join([p["title"] or "", p.get("vendor") or "", p.get("product_type") or "", " ".join(p["tags"])])


CATEGORY_GROUPS = ("Fleece & Outerwear", "Tees & Tops", "Headwear", "Other Apparel")
HEADWEAR_GROUP = re.compile(r"\b(hat|cap|beanie|snapback|9twenty|9forty|bucket hat)\b", re.I)
TEE_GROUP = re.compile(r"\b(t[- ]?shirt|tee|top|tank|jersey|polo|crop top|bodysuit)\b", re.I)
FLEECE_GROUP = re.compile(r"\b(hoodie|sweatshirt|fleece|crewneck|pullover|jacket|coat|puffer|parka|windbreaker|anorak|bomber|varsity|vest|full[- ]zip|sherpa)\b", re.I)


def public_category(p):
    """Conservative product-group labels applied identically to all observed stores."""
    t = _text(p)
    if HEADWEAR_GROUP.search(t):
        return "Headwear"
    if FLEECE_GROUP.search(t):
        return "Fleece & Outerwear"
    if TEE_GROUP.search(t):
        return "Tees & Tops"
    return "Other Apparel"


def _store_stats(label, host, products, fetched_at, is_pse):
    priced = [p for p in products if p["price"] is not None]
    tier_counts = {t[0]: 0 for t in TIERS}
    for p in priced:
        tier_counts[_tier(p["price"])] += 1
    n = len(products)
    women = sum(1 for p in products if WOMENS_RE.search(_text(p)))
    cropped = sum(1 for p in products if CROPPED_RE.search(_text(p)))
    boxy = sum(1 for p in products if BOXY_RE.search(_text(p)))
    any_cut = sum(1 for p in products if WOMENS_RE.search(_text(p)) or CROPPED_RE.search(_text(p))
                  or BOXY_RE.search(_text(p)))
    brands, examples = {}, {}
    for b, rxs in _BRAND_RES.items():
        hits = [p for p in products if _brand_hit(p, b, rxs)]
        brands[b] = len(hits)
        examples[b] = [{"title": h["title"], "url": h["url"]} for h in hits[:3]]
    return {
        "label": label, "store": host, "is_pse": is_pse, "n": n, "fetched_at": fetched_at,
        "median_price": round(statistics.median([p["price"] for p in priced]), 2) if priced else None,
        "tiers": [{"tier": t, "count": tier_counts[t], "pct": _pct(tier_counts[t], len(priced))} for t, _, _ in TIERS],
        "cut": {"women_pct": _pct(women, n), "cropped_pct": _pct(cropped, n), "boxy_pct": _pct(boxy, n),
                "any_pct": _pct(any_cut, n)},
        "brands": brands, "brand_examples": examples,
        "category_counts": {c: sum(1 for x in products if public_category(x) == c) for c in CATEGORY_GROUPS},
        "products": [{**p, "category_group": public_category(p), "retailer": label,
                      "store": host, "observed_at": fetched_at} for p in products],
        "coverage_note": "Sample of up to 250 products from one public storefront listing page; not full assortment.",
    }


def analyze_assortment():
    pse_rows = [_normalize_pse(p) for p in db.get_pse_sample()]
    pse_fetch = db.last_store_fetch(PSE_HOST)
    stores = []
    if pse_rows:
        stores.append(_store_stats("PS&E", PSE_HOST, pse_rows, pse_fetch["fetched_at"] if pse_fetch else None, True))
    for r in db.latest_rival_stores(PSE_HOST):
        rows = [_normalize_rival(p) for p in db.get_rival_products(r["store"])]
        if rows:
            stores.append(_store_stats(r["store"], r["store"], rows, r["fetched_at"], False))
    pse = next((s for s in stores if s["is_pse"]), None)
    rivals = [s for s in stores if not s["is_pse"]]

    tier_chart = [{"tier": t} for t, _, _ in TIERS]
    cut_chart = [{"cut": c} for c in ("Women's", "Cropped", "Boxy", "Any of the three")]
    for s in stores:
        for i, t in enumerate(s["tiers"]):
            tier_chart[i][s["label"]] = t["pct"]
        for row, key in zip(cut_chart, ("women_pct", "cropped_pct", "boxy_pct", "any_pct")):
            row[s["label"]] = s["cut"][key]

    matrix = []
    for b in BOUTIQUE_BRANDS:
        counts = {s["label"]: s["brands"][b] for s in stores}
        carrying = [s["label"] for s in rivals if s["brands"][b] > 0]
        pse_n = pse["brands"][b] if pse else 0
        ex = [dict(e, store=s["label"]) for s in rivals for e in s["brand_examples"][b]][:3]
        matrix.append({"brand": b, "counts": counts, "rivals_carrying": len(carrying), "carried_by": carrying,
                       "rival_skus": sum(s["brands"][b] for s in rivals),
                       "missing_at_pse": bool(pse) and pse_n == 0 and len(carrying) > 0, "examples": ex})
    matrix.sort(key=lambda m: (not m["missing_at_pse"], -m["rivals_carrying"], -m["rival_skus"], m["brand"]))
    return {
        "stores": stores, "tier_chart": tier_chart, "cut_chart": cut_chart, "brand_matrix": matrix,
        "missing_brands": [m["brand"] for m in matrix if m["missing_at_pse"]],
        "labels": [s["label"] for s in stores], "categories": list(CATEGORY_GROUPS),
    }


def reddit_insights():
    """Tab 2 / Card 04 data. Rows come from the reddit_posts table (now Google News fan headlines);
    legacy Reddit rows with old classification labels are ignored."""
    posts = [p for p in db.get_reddit_posts() if p["classification"] in FAN_THEMES]
    posts.sort(key=lambda p: (-(p["score"] or 0), -(p["created_utc"] or 0)))
    counts = {c: 0 for c in FAN_THEMES}
    by_theme = {c: [] for c in FAN_THEMES}
    for p in posts:
        counts[p["classification"]] += 1
        by_theme[p["classification"]].append(p)
    total_count = len(posts) or 1
    ranked = []
    for name in FAN_THEMES:
        ps = by_theme[name]
        if not ps:
            continue
        w = len(ps)
        ranked.append({"theme": name, "posts": len(ps), "weight": w, "share_pct": round(100 * w / total_count, 1),
                       "top_posts": [{"title": p["title"], "url": p["url"], "score": p["score"],
                                      "subreddit": p["subreddit"]} for p in ps[:3]]})
    ranked.sort(key=lambda t: -t["weight"])
    return {"posts": posts, "counts": counts, "themes": ranked,
            "basis": "Google News RSS headline counts for four preset queries. Not consumer sentiment, search volume, sales, or demand."}


def is_heavy_outerwear(p):
    return p.get("category") == "Fleece" or bool(OUTERWEAR_RE.search(p["title"] or ""))


def cold_snap_readiness():
    weather = db.get_weather()
    cold = [d for d in weather if d["low_f"] < COLD_SNAP_F]
    pool = [p for p in db.get_pse_sample() if is_heavy_outerwear(p)]
    carrying = [p for p in pool if any(s["size"] in ("M", "L") for s in p["sizes"])]

    def core_out(p):
        sz = {s["size"]: s["available"] for s in p["sizes"]}
        return sz.get("M") is False or sz.get("L") is False

    out = [p for p in carrying if core_out(p)]
    pct = _pct(len(out), len(carrying)) if carrying else None
    if not weather or pct is None:
        level = "unknown"
    elif not cold:
        level = "none"
    elif len(cold) >= 3 and pct >= 30:
        level = "critical"
    elif pct >= 15:
        level = "elevated"
    else:
        level = "watch"
    return {
        "level": level, "stockout_pct": pct, "skus_tracked": len(carrying), "skus_out": len(out),
        "cold_days": len(cold), "threshold_f": COLD_SNAP_F,
        "coldest": min(cold, key=lambda d: d["low_f"]) if cold else None,
        "first_cold_day": cold[0]["date"] if cold else None,
        "out_of_stock": [{"title": p["title"], "url": p["product_url"], "image_url": p["image_url"],
                          "price": p["retail_price"], "sizes": p["sizes"]} for p in out[:12]],
        "rules": f"Cold day = forecast low under {COLD_SNAP_F}°F. Stockout % = share of fleece/outerwear SKUs "
                 "with M or L sold out (across all colors). Critical: 3+ cold days and 30%+; Elevated: 15%+ "
                 "with any cold day; Watch: any cold day below 15%.",
    }


def news_momentum(news):
    now = datetime.now(timezone.utc)
    last7 = prior = 0
    for n in news:
        if not n["published_at"]:
            continue
        age = (now - datetime.fromisoformat(n["published_at"])).days
        if age <= 7:
            last7 += 1
        else:
            prior += 1
    return {"last_7d": last7, "prior_23d": prior,
            "tunnel_fit": sum(1 for n in news if "Tunnel Fit" in n["tags"]),
            "collab": sum(1 for n in news if "Collab" in n["tags"])}


def culture_overview():
    news = db.get_news(60)
    return {"news": news, "momentum": news_momentum(news), "weather": db.get_weather(),
            "readiness": cold_snap_readiness()}


# ------------------------------------------------------------------ Signal 5: whitespace opportunity cards

def build_brief(assort=None, reddit=None, readiness=None):
    """Evidence cards. Fixed research order, no arbitrary priority numbers or rankings."""
    assort = assort if assort is not None else analyze_assortment()
    reddit = reddit if reddit is not None else reddit_insights()
    readiness = readiness if readiness is not None else cold_snap_readiness()
    stores = assort.get("stores", [])
    home = next((s for s in stores if s["is_pse"]), None)
    rivals = [s for s in stores if not s["is_pse"]]
    cards = []

    if home and rivals:
        category = "Fleece & Outerwear"
        home_count = home["category_counts"].get(category, 0)
        rival_count = sum(s["category_counts"].get(category, 0) for s in rivals)
        cards.append({
            "id": "assortment", "tag": "Store comparison", "metric": {"value": str(home_count), "label": "observed home-store outerwear listings"},
            "headline": "Compare outerwear within the sampled storefronts",
            "detail": f"{home_count} outerwear listings observed at {home['label']} and {rival_count} across {len(rivals)} other sampled stores. These are listing counts, not sales or complete assortments.",
            "observed": f"{home_count} of {home['n']} home-store listings and {rival_count} across selected rival samples are classified as outerwear.",
            "inferred": "Differences may reflect catalog sampling, store positioning, or timing. They do not prove a product opportunity.",
            "evidence": [{"label": s["label"] + " listings", "url": f"https://{s['store']}/collections/all"} for s in stores[:4]],
            "product_examples": [x for s in stores for x in s["products"] if x["category_group"] == category][:6]
        })
    else:
        cards.append({"id":"assortment","tag":"Store comparison","metric":None,
            "headline":"Store comparison needs at least two successful samples",
            "detail":"Refresh permitted storefront sources to compare product groups with the same category rules.",
            "observed":"Comparable storefront data not available.",
            "inferred":"No product gap can be assessed without observed listings.","evidence":[],"product_examples":[]})

    missing = [m for m in assort.get("brand_matrix", []) if m.get("missing_at_pse")]
    if home and rivals and missing:
        x = missing[0]
        cards.append({"id":"brand","tag":"Brand coverage",
            "metric":{"value":str(len(missing)),"label":"brands not observed in home sample"},
            "headline":"Brands seen elsewhere, not in this home-store sample",
            "detail":f"{x['brand']} appears in {x['rivals_carrying']} comparison sample(s); this snapshot did not capture it at the home store.",
            "observed": f"{len(missing)} tracked brands appear in rival samples but not the sampled home-store records.",
            "inferred":"This is not proof that a brand is absent from the full assortment, available to license, or commercially desirable.",
            "evidence":[{"label":e['store']+': '+e['title'][:45],"url":e['url']} for e in x['examples'][:3]],
            "product_examples":[]})
    else:
        cards.append({"id":"brand","tag":"Brand coverage","metric":None,
            "headline":"Brand coverage review",
            "detail":"No supported brand absence conclusion can be drawn from the currently available samples.",
            "observed":"No qualifying brand difference observed or insufficient store coverage.",
            "inferred":"No evidence of an assortment gap.","evidence":[],"product_examples":[]})

    themes = reddit.get("themes", [])
    if themes:
        lead = themes[0]
        cards.append({"id":"media","tag":"Merchandise Media Attention",
            "metric":{"value": str(lead['posts']),"label":"sampled headlines in leading theme"},
            "headline":"The most-covered merchandise theme in this news sample",
            "detail": f"{lead['theme']} accounts for {lead['share_pct']:.0f}% of {len(reddit['posts'])} collected, keyword-matched headlines.",
            "observed":f"{lead['posts']} matching headlines classified in {lead['theme']}.",
            "inferred":"Media coverage is not evidence of fan purchase intent, search interest, or product demand.",
            "evidence":[{"label":p['title'][:66],"url":p['url']} for p in lead['top_posts'][:3]],"product_examples":[]})
    else:
        cards.append({"id":"media","tag":"Merchandise Media Attention","metric":None,
            "headline":"No recent merchandise headlines collected",
            "detail":"News queries may be unavailable or have no relevant headlines.",
            "observed":"No qualifying headlines in the stored sample.",
            "inferred":"No inference about public interest or demand is possible.","evidence":[],"product_examples":[]})

    if readiness["stockout_pct"] is None:
        cards.append({"id":"weather","tag":"Weather and listing availability","metric":None,
            "headline":"Outerwear readiness needs observed sizes and forecast data",
            "detail":"A forecast and size-level public listings are required before comparing them.",
            "observed":"No complete weather-plus-size observation available.",
            "inferred":"No stockout, weather-driven demand, or replenishment conclusion can be drawn.",
            "evidence":[],"product_examples":[]})
    else:
        n, total = readiness["skus_out"], readiness["skus_tracked"]
        cards.append({"id":"weather","tag":"Weather and listing availability",
            "metric":{"value":f"{n}/{total}","label":"sampled outerwear styles with M or L unavailable"},
            "headline":"Review publicly unavailable outerwear sizes against the forecast",
            "detail":f"{n} of {total} sampled fleece/outerwear styles list M or L as unavailable; {readiness['cold_days']} forecast day(s) fall below {readiness['threshold_f']}°F.",
            "observed":f"M or L not currently listed as available on {n} sampled outerwear pages; weather is a separate public forecast.",
            "inferred":"The 38°F screening threshold is a configurable heuristic, not a forecast of apparel sales. An unavailable size is not a proven sellout.",
            "evidence":[{"label":x['title'][:65],"url":x['url']} for x in readiness['out_of_stock'][:3]],
            "product_examples":readiness['out_of_stock'][:6]})
    return cards


def overview():
    assort, reddit, culture = analyze_assortment(), reddit_insights(), culture_overview()
    return {
        "brief": build_brief(assort, reddit, culture["readiness"]),
        "assortment": assort,
        "reddit": reddit,
        "culture": culture,
        "signals": db.get_signal_statuses(),
        "last_run": db.last_run(),
        "pse_sku_count": len(db.get_pse_sample()),
    }
