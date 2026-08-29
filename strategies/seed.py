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
        "run_config": "US",
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
        "run_config": "BTC",
        "name": "SMC 結構跟隨",
        "aliases": ["SMC 結構跟隨", "SMC Structure Following"],
        "description": (
            "用 smc_structure factor 的市場結構跟隨。entry_mode 0 依結構狀態進出，"
            "1 只在 CHoCH 轉多時進場。前視偏誤由 runtime 的展開視窗處理，"
            "策略端不要再自行加 signal lag。尚未證明有超額報酬。"
        ),
    },
    {
        "path": "smc/fvg_sniper.py",
        "run_config": "BTC",
        "name": "SMC FVG 狙擊進場",
        "aliases": ["SMC FVG 狙擊進場", "SMC FVG Sniper"],
        "description": (
            "SMC Model 3：回測未緩解的公允價值缺口，停損放在造成缺口的位移 K 棒後方，"
            "停利用固定 R 倍數。注意 reward_r 是實作時選的，原始模型只給進場與停損、"
            "沒有出場規則。BTC 800 天實測：4h 週期 61 筆、PF 0.97，1d 只有 10 筆。"
            "signal_timeframe 可切 4h/1d。幣圈回測區間上限約 868 天。"
        ),
    },
    {
        "path": "smc/sweep_choch.py",
        "run_config": "BTC",
        "name": "SMC 掃蕩→CHoCH",
        "aliases": ["SMC 掃蕩→CHoCH", "SMC Sweep to CHoCH"],
        "description": (
            "SMC Model 1：影線掃掉前低但收盤守住，隨後結構轉多才進場，停損放在掃蕩極值外。"
            "smc_sweep factor 專為此模型而生 —— BOS 定義在收盤，掃蕩正好相反，"
            "只看收盤的 smc_structure 看不到它。choch_window 與 reward_r 是實作時選的。"
        ),
    },
    {
        "path": "smc/ob_continuation.py",
        "run_config": "BTC",
        "name": "SMC 訂單塊順勢",
        "aliases": ["SMC 訂單塊順勢", "SMC Order Block Continuation"],
        "description": (
            "SMC Model 2：結構偏多時，等價格回測造成突破的未緩解訂單塊。"
            "訂單塊只在其造成的突破確認後才浮現，不是在該 K 棒當下。"
            "BTC 800 天 4h 實測 29 筆、PF 1.19，1d 只有 5 筆、PF 0.34。"
        ),
    },
]

def run_config(market: str, symbol: str) -> dict:
    """Prefill for the backtest form. Must match the strategy's own universe --
    the form does not read it to pick instruments, but a mismatch is confusing.
    """
    return {
        "market_category": market,
        "symbol": symbol,
        "timeframe": "1d",
        "initial_capital": 50000,
        "investment_amount": 50000,
        "trade_direction": "long",
        "leverage": 1,
    }


US = run_config("USStock", "SPY")
# Crypto falls back to the default 1D range policy of 1095 days, and a 120-bar
# warmup eats 227 of them -- so a crypto strategy has about 868 usable days.
BTC = run_config("Crypto", "BTC/USDT")


def build_param_schema(code: str) -> dict:
    """Turn the source's `# @param` lines into the shape the backtest form reads.

    Nothing else populates this. The route does not derive it on save and the
    frontend only ever reads it, so a source stored without one shows an empty
    parameter panel -- which is why every run in this install recorded
    `params={}` and every parameter had to be varied by editing the code.
    Seeding it makes the declared parameters adjustable in the UI, and makes
    the values land in the run history where they can be compared.
    """
    import re

    from app.services.indicator_params import IndicatorParamsParser

    # IndicatorParamsParser only reads `values=` for numeric parameters -- its
    # sweep grammar is documented as numeric-only -- so a string parameter such
    # as a timeframe loses its choices and the form falls back to a number
    # input it can never accept. Pick the list off the raw @param line instead.
    choices: dict[str, list[str]] = {}
    for name, raw in re.findall(r"^#\s*@param\s+(\w+)\s+\S+\s+\S+\s*(.*)$", code, re.M):
        found = re.search(r"values\s*=\s*(\S+)", raw, re.I)
        if found:
            values = [v.strip() for v in found.group(1).split(",") if v.strip()]
            if values:
                choices[name] = values

    params = []
    for item in IndicatorParamsParser.parse_params(code):
        kind = str(item.get("type") or "").lower()
        values = item.get("values") or []
        entry = {
            "name": item.get("name"),
            "type": "boolean" if kind == "bool" else ("string" if kind in ("str", "string") else "number"),
            "default": item.get("default"),
            "description": item.get("description") or "",
        }
        # The form renders a number input, so give it the bounds the @param
        # range already declares rather than leaving it unbounded.
        declared = choices.get(str(item.get("name")))
        if declared:
            entry["options"] = declared
        else:
            numeric = [v for v in values if isinstance(v, (int, float))]
            if numeric:
                entry["min"] = min(numeric)
                entry["max"] = max(numeric)
                if len(numeric) > 1:
                    entry["step"] = abs(numeric[1] - numeric[0]) or 1
        params.append(entry)
    return {"params": params}


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
                    "last_run_config": dict(US if item.get("run_config") == "US" else BTC),
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
                    "param_schema": build_param_schema(code),
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
                    "param_schema": build_param_schema(code),
                    "status": "ready",
                    "visibility": "private",
                })
                print(f"  + created id={source_id}  {item['name']}")

            universe = manifest.get("universe", {}).get("instruments", [])
            print(f"      universe={[i.get('instrument_id') for i in universe]}"
                  f"  warmup={manifest.get('warmupBars')}"
                  f"  freq={manifest.get('frequencies')}"
                  f"  schedules={len(manifest.get('schedules') or [])}"
                  f"  params={len(build_param_schema(code)['params'])}")

        print()
        print("qd_script_sources:")
        for row in existing_rows(get_db_connection):
            print(f"    id={row['id']:<4} {row['name']}")
        return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
