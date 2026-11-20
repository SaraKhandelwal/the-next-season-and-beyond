"""Export a self-contained, source-labelled GitHub Pages snapshot of live public observations.

Run from repository root: python backend/export_static.py
Never writes simulated product, sales, stock or forecast data.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import db  # noqa: E402
import signals  # noqa: E402


def snapshot_payload():
    db.init_db()
    overview = signals.overview()
    rows = db.get_pse_sample()
    sku_items = [{
        "shopify_id": p["shopify_id"], "title": p["title"], "team": p.get("team"),
        "category": p.get("category"), "vendor": p.get("vendor"),
        "retail_price": p.get("retail_price"), "image_url": p.get("image_url"),
        "product_url": p.get("product_url"), "sizes": p.get("sizes", []),
        "core_stockout": bool(p.get("core_stockout")),
        "is_base_jersey": bool(p.get("is_base_jersey")),
    } for p in rows]
    run = overview.get("last_run")
    stores = overview.get("assortment", {}).get("stores", [])
    # A refresh completion time is not the same as a source observation time.
    # A failed refresh must never make cached listings appear freshly collected.
    timestamps = [s.get("fetched_at") for s in stores]
    timestamps += [x.get("fetched_at") for x in overview.get("reddit", {}).get("posts", [])]
    timestamps += [x.get("fetched_at") for x in overview.get("culture", {}).get("news", [])]
    timestamps += [x.get("fetched_at") for x in overview.get("culture", {}).get("weather", [])]
    observed_at = max((x for x in timestamps if isinstance(x, str) and x), default=None)
    return {
        "schema": "next-season-static-v1",
        "mode": "public_snapshot",
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "captured_at": observed_at,
        "last_refresh_attempt_at": (run or {}).get("finished_at"),
        "data_available": bool(stores or overview.get("reddit", {}).get("posts") or overview.get("culture", {}).get("weather") or overview.get("culture", {}).get("news")),
        "snapshot_note": "Independent public storefront and media research. Catalogs are sampled, not complete; availability is a listing observation, not a sale.",
        "overview": overview,
        "skus": {"total": len(sku_items), "items": sku_items,
                 "teams": sorted({p["team"] for p in sku_items if p["team"]}),
                 "categories": sorted({p["category"] for p in sku_items if p["category"]})},
    }


def write_snapshot(payload, paths):
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        tmp.replace(path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", action="append", help="Optional output path. Can be repeated")
    args = ap.parse_args()
    targets = [ROOT / x for x in args.out] if args.out else [ROOT / "frontend/public/snapshot.json", ROOT / "site/snapshot.json"]
    result = snapshot_payload()
    write_snapshot(result, targets)
    print(f"Exported snapshot; captured_at={result['captured_at']!r}; data_available={result['data_available']}; sources={len(result['overview']['assortment']['stores'])}")
