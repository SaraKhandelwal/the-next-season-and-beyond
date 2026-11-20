"""Pacers Team Store ingestion (Shopify /collections/all/products.json) + categorization."""
import os
import re
import time

import requests

STORE = os.environ.get("STORE_URL", "https://pacersteamstore.com").rstrip("/")
PAGE_LIMIT = 250
PAGE_DELAY_SECONDS = 2.5          # pause between page requests
BACKOFF_SECONDS = (5, 10)         # waits after a 429 when no usable Retry-After header
MAX_RETRY_AFTER = 60

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class CatalogError(Exception):
    pass


class RateLimited(Exception):
    pass


def make_session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json", "Accept-Language": "en-US,en;q=0.9"})
    return s


def _retry_after(resp):
    raw = resp.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(1, min(float(raw), MAX_RETRY_AFTER))
    except ValueError:
        return None  # HTTP-date form: fall back to our own backoff


def _get_page(sess, page, progress=None):
    url = f"{STORE}/collections/all/products.json?limit={PAGE_LIMIT}&page={page}"
    for attempt in range(len(BACKOFF_SECONDS) + 1):
        r = sess.get(url, timeout=30)
        if r.status_code == 429:
            if attempt == len(BACKOFF_SECONDS):
                raise RateLimited(f"HTTP 429 on page {page} after {attempt} retries")
            wait = _retry_after(r) or BACKOFF_SECONDS[attempt]
            if progress:
                progress(f"Rate limited (429) on page {page}; retrying in {wait:.0f}s "
                         f"({attempt + 1}/{len(BACKOFF_SECONDS)})")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json().get("products", [])


def fetch_catalog(progress=None, session=None, page_delay=PAGE_DELAY_SECONDS):
    """Return (raw_products, info). Page 1 failing raises CatalogError; a failure on page 2+
    keeps everything already fetched and flags info['partial']."""
    sess = session or make_session()
    products, seen = [], set()
    info = {"pages": 0, "partial": False, "note": None}
    page = 1
    while True:
        try:
            batch = _get_page(sess, page, progress)
        except Exception as e:
            if page == 1:
                raise CatalogError(f"Could not fetch catalog page 1: {e}") from e
            info["partial"] = True
            info["note"] = (f"Stopped at page {page} ({e}). Kept {len(products)} products "
                            f"from the {info['pages']} page(s) already fetched.")
            break
        info["pages"] += 1
        if not batch:
            break
        for raw in batch:
            if raw["id"] not in seen:
                seen.add(raw["id"])
                products.append(raw)
        if progress:
            progress(f"Fetching Pacers Team Store catalog... {len(products)} SKUs found")
        if len(batch) < PAGE_LIMIT:
            break
        page += 1
        time.sleep(page_delay)
    return products, info


# ---------------------------------------------------------------- parsing

SIZE_ALIASES = {
    "XXL": "2XL", "2X": "2XL", "XXXL": "3XL", "3X": "3XL", "XXS": "2XS",
    "SMALL": "S", "MEDIUM": "M", "LARGE": "L", "X-LARGE": "XL", "XLARGE": "XL",
    "OSFA": "ADJ", "OSFM": "ADJ", "ONE SIZE": "ONE SIZE", "DEFAULT TITLE": "ONE SIZE",
}


def normalize_size(label):
    s = (label or "").strip().upper()
    return SIZE_ALIASES.get(s, s) or "ONE SIZE"


def _option_positions(raw):
    """Which optionN holds Size and Color. Defaults match the store's live schema
    (option1=Color, option2=Size) when option names are missing or ambiguous."""
    size_pos, color_pos = 2, 1
    for opt in raw.get("options") or []:
        name = (opt.get("name") or "").lower()
        if "size" in name:
            size_pos = opt.get("position", size_pos)
        elif "color" in name or "colour" in name:
            color_pos = opt.get("position", color_pos)
    if len(raw.get("options") or []) == 1 and not any("size" in (o.get("name") or "").lower()
                                                      for o in raw["options"]):
        size_pos = 1  # single-option products: that option is the only axis we have
    return size_pos, color_pos


FEVER_RE = re.compile(r"\bfever\b|\bwnba\b", re.I)
PACERS_RE = re.compile(r"\bpacers?\b|\bnba\b", re.I)
BASE_JERSEY_RE = re.compile(r"swingman|replica|(icon|association)\s+edition\s+jersey", re.I)

HEADWEAR_RE = re.compile(r"\b(hat|hats|cap|caps|beanie|visor|knit|bucket|snapback|trucker|headwear)\b", re.I)
FLEECE_RE = re.compile(r"\b(hoodie|hoody|crew|crewneck|fleece|pullover|sweatshirt|quarter[- ]zip|1/4|full[- ]zip|"
                       r"half[- ]zip|sweater)\b", re.I)
JERSEY_RE = re.compile(r"\bjersey\b", re.I)
TEE_RE = re.compile(r"\b(tee|tees|t-shirt|tshirt|shirt|long sleeve)\b", re.I)


def tag_team(title, tags, product_type=""):
    text = " ".join([title or "", " ".join(tags), product_type or ""])
    fever, pacers = bool(FEVER_RE.search(text)), bool(PACERS_RE.search(text))
    if fever and not pacers:
        return "Indiana Fever"
    if pacers and not fever:
        return "Indiana Pacers"
    return "Both/General"


def categorize(title, product_type=""):
    text = f"{title or ''} {product_type or ''}"
    if HEADWEAR_RE.search(text):
        return "Headwear"
    if FLEECE_RE.search(text):
        return "Fleece"
    if JERSEY_RE.search(text):
        return "Jerseys"
    if TEE_RE.search(text):
        return "Tees"
    return "Other"


def core_size_stockout(size_avail):
    """M or L sold out while S, XL or 2XL is still available.
    size_avail maps size -> bool (any color available); sizes the product doesn't carry are absent."""
    core_out = size_avail.get("M") is False or size_avail.get("L") is False
    others_in = any(size_avail.get(s) is True for s in ("S", "XL", "2XL"))
    return core_out and others_in


def parse_product(raw):
    tags = raw.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    size_pos, color_pos = _option_positions(raw)

    variants, size_avail, prices = [], {}, []
    for v in raw.get("variants", []):
        size = normalize_size(v.get(f"option{size_pos}"))
        try:
            price = float(v.get("price"))
        except (TypeError, ValueError):
            price = None
        available = bool(v.get("available"))
        variants.append({
            "variant_id": v["id"],
            "color": v.get(f"option{color_pos}") if color_pos != size_pos else None,
            "size_label": size,
            "sku": v.get("sku"),
            "price": price,
            "available": available,
        })
        size_avail[size] = size_avail.get(size, False) or available
        if price is not None:
            prices.append(price)

    images = raw.get("images") or []
    image_url = images[0].get("src") if images else None
    title = raw.get("title", "")
    ptype = raw.get("product_type", "")
    return {
        "shopify_id": raw["id"],
        "title": title,
        "handle": raw["handle"],
        "product_type": ptype,
        "vendor": raw.get("vendor"),
        "tags": tags,
        "image_url": image_url,
        "product_url": f"{STORE}/products/{raw['handle']}",
        "team": tag_team(title, tags, ptype),
        "category": categorize(title, ptype),
        "is_base_jersey": bool(BASE_JERSEY_RE.search(title)),
        "retail_price": min(prices) if prices else None,
        "core_stockout": core_size_stockout(size_avail),
        "variants": variants,
    }
