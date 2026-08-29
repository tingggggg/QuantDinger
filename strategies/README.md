# Strategies

General-purpose Strategy API V2 sources. SMC-specific work lives in
[`../smc/`](../smc/).

## Loading them into the web UI

**Strategies live in the database, not on disk.** The UI reads
`qd_script_sources`; editing a file here changes nothing until it is loaded:

```bash
./strategies/seed.sh
```

Safe to re-run — it updates in place. Re-run it after editing any strategy, or
after resetting the database.

Getting that right took a few tries, and the reasons are worth knowing before
writing a similar script:

- **Match on more than one key.** `name` is rewritten to the code's docstring
  title on save, so matching by name misses on the second run and creates a
  duplicate. `seed_key` in metadata has also been seen to disappear, replaced by
  a row carrying `script_template_params` — a key that appears nowhere in the
  backend source. The script matches on either.
- **Go through `ScriptSourceService`, not raw SQL.** `create_source` writes the
  version table too; a direct INSERT leaves version history broken.
- **Duplicates are reported, never deleted.** A row matching by name could be
  something hand-written in the UI.

## `buy_and_hold.py` — the benchmark arm

Three ways of simply owning an instrument, selected with `mode`:

| mode | Behaviour | Parameters it reads |
|---|---|---|
| 0 | Buy `weight` on the first bar, then stop | `weight` |
| 1 | Hold `weight`, correcting drift once a month | `weight` |
| 2 | Buy every `dca_interval_days`, sized to finish on the end date | `dca_interval_days` |

Each parameter belongs to specific modes; the others are ignored.

### Parameters

**`weight`** (modes 0 and 1) — share of the portfolio to hold, 0.05 to 1.0.
Set it to a timing strategy's measured exposure to build the comparison arm.

**`dca_interval_days`** (mode 2) — days between buys. That is the only DCA knob;
the amount follows from it and the run itself:

```
instalment = starting_cash / (backtest_window_days / dca_interval_days)
```

Both inputs are read from the runtime — `context.portfolio.starting_cash` and
`context.backtest_start` / `backtest_end` — so capital is fully deployed by the
end date whatever window is picked, and the two can never drift apart. Nothing
is restated by hand.

Mode 1 rebalances on the 1st of each month. That day is **not** configurable:
the schedule is registered in `initialize`, where `context.params` is
unavailable (the validator raises `strategyV2.initializeParamsUnavailable`), so
it has to be a literal in the source.

### The interval is a request, not a guarantee

Fractional shares are **rejected** by this engine — not partially filled,
rejected. Verified: `order(SPY, 0.5)`, `order_value(SPY, 100)` and
`order_value(SPY, 37.5)` all came back `rejected` with SPY near 470.

So an instalment worth less than one share cannot buy on schedule. Unspent cash
carries to the next interval, and fills land further apart than asked. This is
arithmetic, not a setting: 10,000 spread over 8 years buys about 25 shares of a
400 instrument, so 25 purchases is the ceiling however fine the interval.

The run logs the effective spacing when it happens:

```
DCA: instalment 204.08 is below one share at 477.71 -- buys will land
roughly every 3 intervals (~90 days), not every 30. Raise
dca_interval_days to about 90, or raise initial capital.
```

Measured, 2022-2025 on SPY:

| Capital | `dca_interval_days` | Fills | Actual spacing |
|---|---|---|---|
| 10,000 | 30 | 20 | **72 days** — warned |
| 10,000 | 120 | 12 | 120 days |
| 50,000 | 30 | 48 | 30 days |
| 100,000 | 30 | 48 | 30 days |

The backtest form defaults to 50,000 for this reason.

### Use mode 1, not mode 0, to judge a timing strategy

Comparing a timing strategy only against 100% buy-and-hold conflates two
different things: **holding less** and **holding at better moments**. A strategy
in the market 70% of the time will usually lose to 100% buy-and-hold in a bull
run no matter how good its timing is.

Measure the strategy's exposure first, then run mode 1 at that weight. The gap
is what the timing was actually worth.

SPY 2018-2025, SMC structure following at 71.4% exposure:

| | Return | Read |
|---|---|---|
| SMC | 96.5% | — |
| Buy and hold 100% | 155.0% | −58.5 pts, but mostly just "held less" |
| **Fixed weight 71.4%** | **110.7%** | **−14.2 pts — the honest number** |

## Measured on SPY

5 bps commission, 5 bps slippage, 100,000 initial capital. Mode 2 deploys the
full account inside each window, so the arms are directly comparable.

| Window | Lump sum | DCA 7d | DCA 14d | DCA 30d | DCA 90d |
|---|---|---|---|---|---|
| 8 years, 2018-2025 | 155.00% | 78.81% | 79.43% | 78.30% | 83.15% |
| 3 years, 2023-2025 | 78.90% | 33.08% | 33.41% | 34.31% | 36.41% |
| 1 year, 2025 | 16.81% | 11.34% | 11.52% | 12.80% | 14.07% |

Two things worth noticing:

**Interval barely matters; the window does.** Within a row the spread is 1-5
points with no direction to it. What moves the number is how long entry is
spread out — which is the backtest range, not a parameter.

**DCA buys risk reduction, not return.** Over 8 years it gave up 76 points
against lump sum, but cut max drawdown from −34.07% to −17.79%. Over 2025 alone
the drawdown went from −19.00% to −4.44% and Sharpe rose from 0.908 to 1.498.
That is the actual trade, and it is worth seeing before treating DCA as free
prudence.

Mode 1 is worth its own note: at 71.4% it returned **100.55%** against
**110.71%** for simply buying 71.4% and leaving it alone, across 80 rebalances.
Holding a constant weight in a rising market means repeatedly selling the thing
that is going up. Drift is not automatically an error.

`totalTrades` counts **closed round trips**, so a position that is bought and
never sold reports 0 — read `totalExecutions` for order count.

## Running one programmatically

The HTTP API needs auth; the service layer does not. `persist=False` keeps the
run out of the database.

```python
import sys; sys.path.insert(0, "/app")
from datetime import datetime
from run import app

with app.app_context():
    from app.services.strategy_v2.service import StrategyV2BacktestService
    svc = StrategyV2BacktestService()
    _, result = svc.run(
        user_id=1,
        code=open("buy_and_hold.py").read(),
        start_date=datetime(2018, 1, 1),
        end_date=datetime(2025, 12, 31),
        initial_capital=100000.0,
        commission=0.0005,
        slippage=0.0005,
        params={"mode": 1, "weight": 0.714},
        persist=False,
    )
    print(result["totalReturn"], result["sharpeRatio"])
```

```bash
docker cp strategies/buy_and_hold.py quantdinger-backend:/w/
docker exec -e PYTHONPATH=/app quantdinger-backend python /tmp/your_runner.py
```

## Notes on the Strategy API that cost time to find

- **`factor()` returns a float, `indicator()` returns a Series.** A decision
  needs the scalar. Comparing the Series with `>` raises *"The truth value of a
  Series is ambiguous"* at runtime, and the contract validator does not catch
  it at compile time.
- **`context.params` is unavailable inside `initialize`** — the validator
  rejects it outright (`strategyV2.initializeParamsUnavailable`), so the
  universe cannot be parameterised. Generate one source per symbol instead.
- **Schedules do fire in backtests.** `run_daily` / `run_weekly` / `run_monthly`
  are bound to no-op lambdas in `_bind_runtime_api`, which looks like they are
  stubs — but that binding is only for compile-time discovery. The runner reads
  the recorded schedule from the manifest and invokes the callback by name.
- **Backtest range is capped per market and timeframe.** US stock daily allows
  10 years; everything else, crypto included, falls back to 1095 days. Warmup
  counts against the window: 120 daily bars costs 227 calendar days, so the
  usable crypto window is about 868 days.
