"""Load the repo's strategy sources into QuantDinger so the web UI can see them.

Strategies live in the database, not on disk -- the UI reads qd_script_sources.
Editing a file here changes nothing until it is loaded, which is what this does.

    docker cp strategies/seed.py quantdinger-backend:/tmp/seed.py
    docker run --rm -v "$PWD":/repo alpine true   # (no-op, keeps paths obvious)
    docker cp strategies quantdinger-backend:/repo_strategies
    docker cp smc quantdinger-backend:/repo_smc
    docker exec -e PYTHONPATH=/app quantdinger-backend python /tmp/seed.py

Or in one line from the repo root:

    ./strategies/seed.sh

Safe to re-run: it updates in place rather than adding a second copy, and warns
instead of deleting when it finds duplicates.
"""
import json
import os
import sys

sys.path.insert(0, "/app")

from run import app

# Where the repo is mounted inside the container. seed.sh copies the two source
# directories here; override if mounting somewhere else.
ROOT = os.environ.get("SEED_ROOT", "/repo")

ITEMS = [
    {
        "path": "strategies/buy_and_hold.py",
        "name": "長期買進 / DCA 基準",
        "aliases": ["長期買進 / DCA 基準", "Long-Term Buy Strategy"],
        "description": (
            "三種長期持有方式：mode 0 買進持有、mode 1 固定權重月再平衡、"
            "mode 2 定期定額。判斷擇時策略時用 mode 1 對齊該策略的實際曝險，"
            "只跟 100% 買進持有比會把「持有較少」誤算成「擇時較差」。"
        ),
    },
    {
        "path": "smc/strategy_example.py",
        "name": "SMC 結構跟隨",
        "aliases": ["SMC 結構跟隨", "SMC Structure Following"],
        "description": (
            "用 smc_structure factor 的市場結構跟隨。entry_mode 0 依結構狀態進出，"
            "1 只在 CHoCH 轉多時進場。前視偏誤由 runtime 的展開視窗處理，"
            "策略端不要再自行加 signal lag。尚未證明有超額報酬。"
        ),
    },
]

DEFAULT_RUN_CONFIG = {
    "market_category": "USStock",
    "symbol": "SPY",
    "timeframe": "1d",
    "initial_capital": 50000,
    "investment_amount": 50000,
    "trade_direction": "long",
    "leverage": 1,
}


def existing_rows(get_db_connection):
    """Every strategy row for user 1, with whatever identity it still carries.

    Matching needs both keys, because either alone has been seen to fail:
    `name` is rewritten to the code's docstring title on save, and `seed_key`
    has been observed to vanish from metadata (replaced by a row carrying
    script_template_params, a key that appears nowhere in the backend source).
    Either one matching is treated as the same strategy.
    """
    rows = []
    with get_db_connection() as db:
        cur = db.cursor()
        cur.execute("select id, name, metadata from qd_script_sources where user_id = 1")
        for row in cur.fetchall():
            vals = row if isinstance(row, dict) else {
                "id": row[0], "name": row[1], "metadata": row[2]}
            meta = vals.get("metadata") or {}
            if isinstance(meta, str):
                meta = json.loads(meta or "{}")
            rows.append({
                "id": vals.get("id"),
                "name": vals.get("name"),
                "seed_key": meta.get("seed_key"),
            })
        cur.close()
    return rows


def main() -> int:
    with app.app_context():
        from app.services.script_source import get_script_source_service
        from app.services.strategy_v2.contract import canonical_source_metadata
        from app.utils.db import get_db_connection

        service = get_script_source_service()
        rows = existing_rows(get_db_connection)
        failures = 0

        for item in ITEMS:
            source_path = os.path.join(ROOT, item["path"])
            try:
                code = open(source_path).read()
            except OSError as exc:
                print(f"  x {item['name']}: cannot read {source_path} ({exc})")
                failures += 1
                continue

            try:
                # Same call the /api/script-sources route makes, so the stored
                # manifest matches what the UI expects. A bad strategy fails
                # here rather than at backtest time.
                metadata, manifest = canonical_source_metadata(code, {
                    "description": item["description"],
                    "last_run_config": dict(DEFAULT_RUN_CONFIG),
                    "seed_key": item["path"],
                    "script_verified": True,
                    "lifecycle_verified": True,
                })
            except Exception as exc:
                print(f"  x {item['name']}: compile failed -- "
                      f"{exc.__class__.__name__}: {exc}")
                failures += 1
                continue

            hits = [r["id"] for r in rows
                    if r["seed_key"] == item["path"] or r["name"] in item["aliases"]]
            if hits:
                source_id = max(hits)
                service.update_source(source_id, 1, {
                    "name": item["name"],
                    "description": item["description"],
                    "code": code,
                    "metadata": metadata,
                })
                print(f"  ~ updated id={source_id}  {item['name']}")
                for stale in sorted(hits):
                    if stale != source_id:
                        # Never deleted automatically: a row matching by name
                        # could be something hand-written.
                        print(f"    ! id={stale} also matches -- check, then "
                              f"DELETE FROM qd_script_sources WHERE id={stale};")
            else:
                source_id = service.create_source({
                    "user_id": 1,
                    "name": item["name"],
                    "description": item["description"],
                    "code": code,
                    "asset_type": "script",
                    "metadata": metadata,
                    "status": "ready",
                    "visibility": "private",
                })
                print(f"  + created id={source_id}  {item['name']}")

            universe = manifest.get("universe", {}).get("instruments", [])
            print(f"      universe={[i.get('instrument_id') for i in universe]}"
                  f"  warmup={manifest.get('warmupBars')}"
                  f"  freq={manifest.get('frequencies')}"
                  f"  schedules={len(manifest.get('schedules') or [])}")

        print()
        print("qd_script_sources:")
        for row in existing_rows(get_db_connection):
            print(f"    id={row['id']:<4} {row['name']}")
        return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
