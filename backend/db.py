"""SQLite layer for the 5-signal platform. Everything the dashboard shows is read back from here."""
import json
import os
import sqlite3
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone

# New filename so it never collides with the v1 database schema.
DB_PATH = os.environ.get("MERCH_DB", os.path.join(os.path.dirname(__file__), "merch_radar_v2.db"))

SIZE_ORDER = ["XS", "S", "M", "L", "XL", "2XL", "3XL", "ADJ", "EACH", "ONE SIZE"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS scrape_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,                  -- running | success | partial | error
    duration_s REAL,
    message TEXT
);

-- Latest state of each live signal (shopify | reddit | news | weather).
CREATE TABLE IF NOT EXISTS signal_status (
    signal TEXT PRIMARY KEY,
    status TEXT,                           -- ok | cached | partial | error
    detail TEXT,
    updated_at TEXT,
    last_ok_at TEXT,
    run_id INTEGER
);

-- One row per Shopify storefront request (PS&E and rival candidates), incl. failures.
CREATE TABLE IF NOT EXISTS store_fetches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    store TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    fetch_date TEXT NOT NULL,              -- local YYYY-MM-DD, drives the same-day PS&E cache
    ok INTEGER NOT NULL,
    http_status INTEGER,
    product_count INTEGER,
    note TEXT
);
CREATE INDEX IF NOT EXISTS idx_store_fetches_store ON store_fetches(store, id);

-- PS&E catalog (page 1 of the storefront) with snapshot diffing.
CREATE TABLE IF NOT EXISTS products (
    shopify_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    handle TEXT NOT NULL,
    product_type TEXT,
    vendor TEXT,
    tags TEXT,
    image_url TEXT,
    product_url TEXT NOT NULL,
    team TEXT,
    category TEXT,
    is_base_jersey INTEGER DEFAULT 0,
    retail_price REAL,
    core_stockout INTEGER DEFAULT 0,
    first_seen_run INTEGER,
    last_seen_run INTEGER,
    last_seen_at TEXT
);
CREATE TABLE IF NOT EXISTS variants (
    variant_id INTEGER PRIMARY KEY,
    shopify_id INTEGER NOT NULL REFERENCES products(shopify_id),
    color TEXT,
    size_label TEXT,
    sku TEXT,
    price REAL,
    available INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_variants_product ON variants(shopify_id);
CREATE TABLE IF NOT EXISTS stock_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    variant_id INTEGER NOT NULL,
    shopify_id INTEGER NOT NULL,
    color TEXT,
    size_label TEXT,
    was_available INTEGER,
    is_available INTEGER NOT NULL,
    changed_at TEXT NOT NULL
);

-- Signal 1: rival storefront products (page 1 of each responding rival).
CREATE TABLE IF NOT EXISTS rival_products (
    store TEXT NOT NULL,
    shopify_id INTEGER NOT NULL,
    title TEXT,
    handle TEXT,
    vendor TEXT,
    product_type TEXT,
    tags TEXT,
    price REAL,
    product_url TEXT,
    image_url TEXT,
    sizes_json TEXT DEFAULT '[]',
    fetched_at TEXT,
    PRIMARY KEY (store, shopify_id)
);

-- Signal 2: Reddit posts (real titles, scores, comment counts, permalinks).
CREATE TABLE IF NOT EXISTS reddit_posts (
    id TEXT PRIMARY KEY,
    subreddit TEXT,
    title TEXT,
    selftext TEXT,
    score INTEGER,
    num_comments INTEGER,
    created_utc REAL,
    url TEXT,
    flair TEXT,
    queries TEXT,                          -- JSON list of matching search terms
    classification TEXT,
    fetched_at TEXT
);

-- Signal 3: Google News RSS items.
CREATE TABLE IF NOT EXISTS news_items (
    link TEXT PRIMARY KEY,
    title TEXT,
    source TEXT,
    published_at TEXT,
    tags TEXT,                             -- JSON list
    query TEXT,
    fetched_at TEXT
);

-- Signal 4: Open-Meteo daily forecast for Indianapolis (replaced on each fetch).
CREATE TABLE IF NOT EXISTS weather_days (
    date TEXT PRIMARY KEY,
    high_f REAL,
    low_f REAL,
    fetched_at TEXT
);
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today_local():
    return datetime.now().strftime("%Y-%m-%d")


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with connect() as c:
        c.executescript(SCHEMA)
        columns = {row["name"] for row in c.execute("PRAGMA table_info(rival_products)")}
        if "sizes_json" not in columns:
            c.execute("ALTER TABLE rival_products ADD COLUMN sizes_json TEXT DEFAULT '[]'")


# ---------------------------------------------------------------- runs & signal status

def start_run():
    with connect() as c:
        return c.execute("INSERT INTO scrape_runs (started_at, status) VALUES (?, 'running')",
                         (now_iso(),)).lastrowid


def finish_run(run_id, status, duration_s=None, message=None):
    with connect() as c:
        c.execute("UPDATE scrape_runs SET status=?, finished_at=?, duration_s=?, message=? WHERE id=?",
                  (status, now_iso(), duration_s, message, run_id))


def last_run():
    with connect() as c:
        r = c.execute("SELECT * FROM scrape_runs WHERE status != 'running' ORDER BY id DESC LIMIT 1").fetchone()
        return dict(r) if r else None


def set_signal_status(signal, status, detail, run_id):
    ts = now_iso()
    good = status in ("ok", "cached", "partial")
    with connect() as c:
        c.execute(
            """INSERT INTO signal_status (signal, status, detail, updated_at, last_ok_at, run_id)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(signal) DO UPDATE SET status=excluded.status, detail=excluded.detail,
               updated_at=excluded.updated_at, run_id=excluded.run_id,
               last_ok_at=CASE WHEN ? THEN excluded.updated_at ELSE signal_status.last_ok_at END""",
            (signal, status, detail, ts, ts if good else None, run_id, 1 if good else 0),
        )


def get_signal_statuses():
    with connect() as c:
        return {r["signal"]: dict(r) for r in c.execute("SELECT * FROM signal_status")}


# ---------------------------------------------------------------- store fetch log (+ same-day cache)

def log_store_fetch(run_id, store, ok, http_status=None, product_count=None, note=None):
    with connect() as c:
        c.execute(
            """INSERT INTO store_fetches (run_id, store, fetched_at, fetch_date, ok, http_status,
               product_count, note) VALUES (?,?,?,?,?,?,?,?)""",
            (run_id, store, now_iso(), today_local(), int(ok), http_status, product_count, note),
        )


def store_fetched_today(store):
    """Latest successful fetch of this store made today (local date), or None."""
    with connect() as c:
        r = c.execute(
            "SELECT * FROM store_fetches WHERE store=? AND ok=1 AND fetch_date=? ORDER BY id DESC LIMIT 1",
            (store, today_local())).fetchone()
        return dict(r) if r else None


def last_store_fetch(store):
    with connect() as c:
        r = c.execute("SELECT * FROM store_fetches WHERE store=? AND ok=1 ORDER BY id DESC LIMIT 1",
                      (store,)).fetchone()
        return dict(r) if r else None


def recent_store_failures(run_id):
    with connect() as c:
        return [dict(r) for r in c.execute(
            "SELECT store, http_status, note FROM store_fetches WHERE run_id=? AND ok=0 ORDER BY id", (run_id,))]


def latest_rival_stores(pse_host):
    """Rivals that responded in the most recent run that found any (so at most MAX_RIVALS)."""
    with connect() as c:
        row = c.execute("SELECT MAX(run_id) AS r FROM store_fetches WHERE ok=1 AND store != ?",
                        (pse_host,)).fetchone()
        if not row or row["r"] is None:
            return []
        return [dict(r) for r in c.execute(
            "SELECT store, fetched_at, product_count FROM store_fetches WHERE run_id=? AND ok=1 AND store != ? "
            "ORDER BY id", (row["r"], pse_host))]


# ---------------------------------------------------------------- PS&E catalog + snapshot diff

def upsert_catalog(run_id, parsed_products):
    """Store page-1 PS&E products and log every availability change vs. the previous snapshot."""
    ts = now_iso()
    changes = 0
    with connect() as c:
        for p in parsed_products:
            sid = p["shopify_id"]
            existed = c.execute("SELECT 1 FROM products WHERE shopify_id=?", (sid,)).fetchone()
            prev = {r["variant_id"]: r["available"]
                    for r in c.execute("SELECT variant_id, available FROM variants WHERE shopify_id=?", (sid,))}
            vals = (p["title"], p["handle"], p["product_type"], p["vendor"], json.dumps(p["tags"]),
                    p["image_url"], p["product_url"], p["team"], p["category"], int(p["is_base_jersey"]),
                    p["retail_price"], int(p["core_stockout"]))
            if existed:
                c.execute("""UPDATE products SET title=?, handle=?, product_type=?, vendor=?, tags=?, image_url=?,
                             product_url=?, team=?, category=?, is_base_jersey=?, retail_price=?, core_stockout=?,
                             last_seen_run=?, last_seen_at=? WHERE shopify_id=?""", (*vals, run_id, ts, sid))
            else:
                c.execute("""INSERT INTO products (title, handle, product_type, vendor, tags, image_url, product_url,
                             team, category, is_base_jersey, retail_price, core_stockout, shopify_id,
                             first_seen_run, last_seen_run, last_seen_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (*vals, sid, run_id, run_id, ts))
            for v in p["variants"]:
                vid, now_avail = v["variant_id"], int(v["available"])
                if vid in prev and prev[vid] != now_avail:
                    c.execute("""INSERT INTO stock_changes (run_id, variant_id, shopify_id, color, size_label,
                                 was_available, is_available, changed_at) VALUES (?,?,?,?,?,?,?,?)""",
                              (run_id, vid, sid, v["color"], v["size_label"], prev[vid], now_avail, ts))
                    changes += 1
                elif vid not in prev and existed:
                    c.execute("""INSERT INTO stock_changes (run_id, variant_id, shopify_id, color, size_label,
                                 was_available, is_available, changed_at) VALUES (?,?,?,?,?,NULL,?,?)""",
                              (run_id, vid, sid, v["color"], v["size_label"], now_avail, ts))
                    changes += 1
                c.execute("""INSERT INTO variants (variant_id, shopify_id, color, size_label, sku, price, available)
                             VALUES (?,?,?,?,?,?,?)
                             ON CONFLICT(variant_id) DO UPDATE SET shopify_id=excluded.shopify_id,
                             color=excluded.color, size_label=excluded.size_label, sku=excluded.sku,
                             price=excluded.price, available=excluded.available""",
                          (vid, sid, v["color"], v["size_label"], v.get("sku"), v["price"], now_avail))
    return changes


def recent_changes(limit=100):
    with connect() as c:
        return [dict(r) for r in c.execute(
            """SELECT sc.*, p.title, p.product_url FROM stock_changes sc
               JOIN products p ON p.shopify_id = sc.shopify_id ORDER BY sc.id DESC LIMIT ?""", (limit,))]


def _size_sort_key(s):
    return (SIZE_ORDER.index(s), "") if s in SIZE_ORDER else (len(SIZE_ORDER), s)


def get_pse_sample():
    """PS&E products from the most recent catalog fetch (one consistent page-1 sample), with
    per-size availability (a size is available if any color of it is)."""
    with connect() as c:
        prods = [dict(r) for r in c.execute(
            "SELECT * FROM products WHERE last_seen_run = (SELECT MAX(last_seen_run) FROM products)")]
        ids = {p["shopify_id"] for p in prods}
        vrows = [r for r in c.execute("SELECT shopify_id, size_label, available FROM variants")
                 if r["shopify_id"] in ids]
    sizes = defaultdict(dict)
    for v in vrows:
        cur = sizes[v["shopify_id"]]
        cur[v["size_label"]] = cur.get(v["size_label"], False) or bool(v["available"])
    for p in prods:
        sm = sizes.get(p["shopify_id"], {})
        p["sizes"] = [{"size": s, "available": sm[s]} for s in sorted(sm, key=_size_sort_key)]
        p["tags"] = json.loads(p["tags"] or "[]")
        p["is_base_jersey"] = bool(p["is_base_jersey"])
    return prods


# ---------------------------------------------------------------- Signal 1: rivals

def replace_rival_products(store, rows):
    ts = now_iso()
    with connect() as c:
        c.execute("DELETE FROM rival_products WHERE store=?", (store,))
        c.executemany(
            """INSERT INTO rival_products (store, shopify_id, title, handle, vendor, product_type, tags, price,
               product_url, image_url, sizes_json, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            [(store, r["shopify_id"], r["title"], r["handle"], r["vendor"], r["product_type"],
              json.dumps(r["tags"]), r["price"], r["product_url"], r["image_url"], json.dumps(r.get("sizes", [])), ts) for r in rows])


def get_rival_products(store):
    with connect() as c:
        out = []
        for r in c.execute("SELECT * FROM rival_products WHERE store=?", (store,)):
            d = dict(r)
            d["tags"] = json.loads(d["tags"] or "[]")
            d["sizes"] = json.loads(d.get("sizes_json") or "[]")
            out.append(d)
        return out


# ---------------------------------------------------------------- Signal 2: reddit

def upsert_reddit_posts(posts):
    ts = now_iso()
    with connect() as c:
        for p in posts:
            c.execute(
                """INSERT INTO reddit_posts (id, subreddit, title, selftext, score, num_comments, created_utc, url,
                   flair, queries, classification, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET title=excluded.title, selftext=excluded.selftext,
                   score=excluded.score, num_comments=excluded.num_comments, flair=excluded.flair,
                   queries=excluded.queries, classification=excluded.classification,
                   fetched_at=excluded.fetched_at""",
                (p["id"], p["subreddit"], p["title"], p["selftext"], p["score"], p["num_comments"],
                 p["created_utc"], p["url"], p["flair"], json.dumps(p["queries"]), p["classification"], ts))


def get_reddit_posts():
    with connect() as c:
        out = []
        for r in c.execute("SELECT * FROM reddit_posts ORDER BY score DESC"):
            d = dict(r)
            d["queries"] = json.loads(d["queries"] or "[]")
            out.append(d)
        return out


# ---------------------------------------------------------------- Signal 3: news

def upsert_news(items):
    ts = now_iso()
    with connect() as c:
        for n in items:
            c.execute(
                """INSERT INTO news_items (link, title, source, published_at, tags, query, fetched_at)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(link) DO UPDATE SET title=excluded.title, source=excluded.source,
                   published_at=excluded.published_at, tags=excluded.tags, fetched_at=excluded.fetched_at""",
                (n["link"], n["title"], n["source"], n["published_at"], json.dumps(n["tags"]), n["query"], ts))


def get_news(limit=60):
    with connect() as c:
        out = []
        for r in c.execute("SELECT * FROM news_items ORDER BY published_at DESC LIMIT ?", (limit,)):
            d = dict(r)
            d["tags"] = json.loads(d["tags"] or "[]")
            d["sizes"] = json.loads(d.get("sizes_json") or "[]")
            out.append(d)
        return out


# ---------------------------------------------------------------- Signal 4: weather

def replace_weather(days):
    ts = now_iso()
    with connect() as c:
        c.execute("DELETE FROM weather_days")
        c.executemany("INSERT INTO weather_days (date, high_f, low_f, fetched_at) VALUES (?,?,?,?)",
                      [(d["date"], d["high_f"], d["low_f"], ts) for d in days])


def get_weather():
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM weather_days ORDER BY date")]
