"""Perform a single monitored external refresh in CI, then export a static snapshot.

Failures are preserved as source status; if all external sources are blocked the static site
honestly shows that the collection has not succeeded.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import db
import signals
from export_static import snapshot_payload, write_snapshot

def main():
    db.init_db()
    run_id = db.start_run()
    signals._run(run_id)
    payload = snapshot_payload()
    write_snapshot(payload, [ROOT / "frontend/public/snapshot.json", ROOT / "site/snapshot.json"])
    run = payload['overview']['last_run'] or {}
    print(f"run={run.get('status')} data_available={payload['data_available']}")
    if not payload['data_available']:
        print('Warning: no external research collected. Site will show honest empty states.')

if __name__ == '__main__':
    main()
