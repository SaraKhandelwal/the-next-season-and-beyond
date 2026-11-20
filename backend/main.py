"""FastAPI app for The Next Season (public merchandise intelligence).
Run from backend/:  uvicorn main:app --reload --port 8000
"""
import json
import os
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import db
import signals

app = FastAPI(title="The Next Season | Merchandise Intelligence")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def _startup():
    db.init_db()


@app.get("/api/overview")
def overview():
    """Everything the dashboard needs, computed from the SQLite signal tables."""
    return signals.overview()


@app.get("/api/skus")
def skus(q: str = "", team: str = "All", category: str = "All"):
    """PS&E SKU explorer (page-1 sample of the storefront)."""
    rows = db.get_pse_sample()
    ql = q.strip().lower()
    out = []
    for p in rows:
        if team != "All" and p["team"] != team:
            continue
        if category != "All" and p["category"] != category:
            continue
        if ql and ql not in f"{p['title']} {p.get('vendor') or ''} {p.get('product_type') or ''}".lower():
            continue
        out.append({
            "shopify_id": p["shopify_id"], "title": p["title"], "team": p["team"], "category": p["category"],
            "vendor": p["vendor"], "retail_price": p["retail_price"], "image_url": p["image_url"],
            "product_url": p["product_url"], "sizes": p["sizes"], "is_base_jersey": p["is_base_jersey"],
            "core_stockout": bool(p["core_stockout"]),
        })
    out.sort(key=lambda p: p["title"].lower())
    return {"total": len(rows), "items": out,
            "categories": sorted({p["category"] for p in rows if p["category"]}),
            "teams": sorted({p["team"] for p in rows if p["team"]})}


@app.post("/api/refresh", status_code=202)
def refresh():
    started, run_id = signals.start_refresh()
    if not started:
        return JSONResponse(status_code=409, content={"started": False, "run_id": run_id,
                                                      "detail": "A refresh is already running."})
    return {"started": True, "run_id": run_id}


@app.get("/api/refresh/status")
def refresh_status():
    """Polling alternative to the SSE stream."""
    return signals.progress.snapshot()


@app.get("/api/refresh/stream")
def refresh_stream():
    def gen():
        last_version, last_beat = -1, time.time()
        while True:
            snap = signals.progress.snapshot()
            if snap["version"] != last_version:
                last_version = snap["version"]
                yield f"data: {json.dumps(snap)}\n\n"
                if not snap["running"]:
                    return
            elif time.time() - last_beat > 15:
                last_beat = time.time()
                yield ": keep-alive\n\n"
            time.sleep(0.3)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/changes")
def changes(limit: int = 100):
    """PS&E stock-change history (was_available -> is_available) per refresh."""
    return db.recent_changes(limit)


# Serve the built frontend (npm run build) if present, so one process serves everything.
DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(DIST, "assets")), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        candidate = os.path.join(DIST, path)
        if path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(DIST, "index.html"))
