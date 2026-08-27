# SMC — Smart Money Concepts for QuantDinger v5

The full SMC vocabulary — swing highs/lows, BOS & CHoCH, fair value gaps, order
blocks, liquidity pools, previous period high/low, sessions and retracements —
drawn against the v5 indicator contract with **no repaint**.

## Why this is written from scratch

The obvious move is `pip install smartmoneyconcepts` (joshyattridge, MIT,
★1,959). Two measured reasons not to:

**It cannot run in the v5 sandbox.** Indicator and strategy code share
`app/utils/safe_exec.py`, whose `SAFE_IMPORT_MODULES` allows 13 modules.
Whitelisting the package and installing it into the image gets `import` and
attribute access to pass, but *calling* any function still fails
(`TypeError: unhashable type: 'list'`) — the read-only module proxy breaks the
package's `inputvalidator` decorator. The same code runs fine outside the
sandbox, so this is the sandbox, not the package. The isolation is deliberate:
`safe_exec_isolated` starts the worker with `python -I` and no parent
environment.

**Its signals are all retroactive.** Recomputing on expanding windows and
diffing against the final pass:

| swing_length | signals | visible on their own bar | mean lag | max lag |
|---|---|---|---|---|
| 5  | 59 | **0** | 17.2 bars | 40 |
| 10 | 35 | **0** | 28.6 bars | 72 |
| 20 | 15 | **0** | 57.5 bars | 156 |

Not a bug — a BOS is defined against a swing pivot, and a pivot needs N bars on
each side. `MitigatedIndex` / `BrokenIndex` / `Swept` are future indices by
definition. Charting that misleads; backtesting it is look-ahead bias.

## What this draws differently

Reference SMC charts stamp a BOS on the **pivot** bar. This stamps it on the
**break** bar, because that is when it became knowable. Everything derived from
a pivot — BOS, CHoCH, order blocks, liquidity — inherits the `swing_length`
confirmation delay, and pivots inside the last `swing_length` bars are never
marked at all.

Verified by re-running on 350 / 400 / 450 / 500 bars of the same series with the
display cap lifted (`max_items=999`): annotations in the first 300 bars are
identical every time, **+0 / −0**.

## Components

All eight render through `output['layers']`. Counts below are from a 400-bar
BTC/USDT 4H sample at `swing_length=8`, `max_items=10`.

| Component | Drawn as | Sample count |
|---|---|---|
| Swing highs / lows | `label` — PH / PL | 30 |
| BOS & CHoCH | `line` + text, CHoCH dashed | 11 |
| Fair value gap | `zone` | 10 |
| Order block | `zone` + volume share | 10 |
| Liquidity | dashed `line` — BSL / SSL | 6 |
| Previous high / low | dashed `line` — PDH / PDL | 20 |
| Sessions | background `zone` — Asia / London / NY | 9 |
| Retracements | `label` — `C:x% D:y%` | 10 |

Sessions self-disable on daily bars (every bar sits at 00:00, so the bands carry
no information).

## Files

| File | Purpose |
|---|---|
| `chart_indicator.py` | Indicator source (sandbox DSL). Chart-only. |
| `validate.py` | Runs the code through QuantDinger's own validation pipeline. |
| `strategy_example.py` | Script strategy consuming the factors. Backtestable. |

## Parameters

`swing_length` (3–30) and `max_items` (2–30) plus one toggle per component:
`show_swings`, `show_structure`, `show_fvg`, `show_ob`, `show_liquidity`,
`show_prev_hl`, `show_sessions`, `show_retracement`.

`show_sessions` defaults to off — with everything on the chart gets crowded fast.

## Installing

Requires no fork changes — paste `chart_indicator.py` into the indicator editor
in the web UI and save.

It is already seeded into this local stack as `qd_indicator_codes` id 2, named
`SMC Full`. To reseed after a database reset:

```bash
docker cp smc/chart_indicator.py quantdinger-db:/tmp/smc.py
docker exec quantdinger-db psql -U quantdinger -d quantdinger -c "\set code \`cat /tmp/smc.py\`
INSERT INTO qd_indicator_codes (user_id, name, code, asset_type, createtime, updatetime)
VALUES (1, 'SMC Full', :'code', 'indicator',
        extract(epoch from now())::bigint, extract(epoch from now())::bigint);"
```

## Verifying a change

```bash
docker run --rm -v "$PWD/smc":/w -w /app quantdinger-backend:local \
  python /w/validate.py /w/chart_indicator.py
```

Checks `@param` parsing, sandbox execution, and output structure.

## Sandbox constraints worth knowing

Learned by probing 21 operations, not from docs:

- **ndarray *method* reductions are blocked.** `arr.max()`, `arr.min()`,
  `arr.sum()` lazily import `numpy._core._methods`, which the sandbox rejects as
  an internal numpy submodule. The function forms — `np.max(arr)`,
  `np.sum(arr)`, `np.argmax(arr)` — are fine, as is every pandas reduction
  (`Series.max()`, `.rolling().max()`, `.expanding().max()`).
- Banned method names on any receiver include `format`, `eval`, `query`,
  `save`, `load`, `stack`, and all `read_*` / `to_*`.
- `type()` is not in the builtins whitelist. `DatetimeIndex` access is fine —
  `.hour`, `.normalize()`, `.dayofweek`, `.astype('int64')`.
- Every entry in `plots` and `signals` must have `len(data) == len(df)`.
  `layers` entries carry their own indices and are exempt.
- Source limit is 512 KiB.

## The layers contract

Not obvious from the backend alone — the renderer is
`QuantDinger-Vue/src/views/indicator-analysis/components/KlineChart.vue`
(`renderIndicatorLayers`). Integer `startIndex` / `endIndex` / `index` are
resolved against the visible frame, so bar indices can be used directly.

```python
{'type': 'zone',  'startIndex': int, 'endIndex': int,
 'top': float, 'bottom': float, 'text': str,
 'fillColor': '#RRGGBB', 'borderColor': '#RRGGBB', 'opacity': 0.15}

{'type': 'line',  'startIndex': int, 'endIndex': int,
 'price': float, 'text': str, 'color': '#RRGGBB', 'dashed': bool}

{'type': 'label', 'index': int, 'price': float,
 'text': str, 'color': '#RRGGBB', 'textColor': '#FFFFFF'}
```

For sloped lines the renderer reads `price1` / `price2` (or `y1` / `y2`). The
backend docstring mentions `startPrice` / `endPrice`; those are **not** read by
the renderer.

## Backtesting — the factor lane

Indicators in v5 are chart-only and cannot place orders, so the same logic is
also registered as two factors in `app/services/factors/registry.py`. This is
the only upstream file the SMC work touches.

| Factor | Outputs |
|---|---|
| `smc_structure` | `trend`, `bos`, `choch`, `swing_high`, `swing_low`, `distance_high`, `distance_low` |
| `smc_fvg` | `side`, `top`, `bottom`, `distance` |

Call them from a script strategy:

```python
trend = indicator("smc_structure", "USStock:SPY", swing_length=10, output="trend")
choch = indicator("smc_structure", "USStock:SPY", swing_length=10, output="choch")
```

**The runtime handles look-ahead, not the strategy.** `runtime.py` evaluates
factors on expanding windows (`visible = frame.iloc[:index + 1]`), asking each
bar what is true right now. Combined with confirmation-delayed pivots, a break
that took 28 bars to become knowable arrives 28 bars late in the backtest too.
No manual signal lag is needed — and adding one would double-count the delay.

Warmup is `swing_length * 2 + 2`; below that the factor raises
`factor.insufficientHistory` rather than returning a misleading number.

Verified against the chart indicator on the same 300-bar series: both find the
same 7 BOS/CHoCH events, at the same bars. The two lanes agree.

### Cost

The factor contract is `compute(frame, params) -> float` re-evaluated per bar,
so the protocol is O(n²) — inherent to the registry, not to this factor
(`_supertrend` has the same shape).

| bars | `smc_structure` | `smc_fvg` | per bar |
|---|---|---|---|
| 250 | 0.18s | 0.05s | 1.05 ms |
| 500 | 0.53s | 0.11s | 1.36 ms |
| 1000 | 1.91s | 0.22s | 2.19 ms |

Fine for a single backtest; painful for parameter sweeps or wide universes.

### After editing registry.py

The backend image bakes the source in at build time, so a change is not live
until the services that share the image are rebuilt:

```bash
docker compose up -d --build backend trading-worker scheduler-worker celery-worker celery-beat
```

## Before trusting a backtest result

The structure signal has not been shown to have edge — only to be computed
honestly. Read any result against buy-and-hold on the same instrument and
period, and against a random-entry control with a matched trade count. A signal
that beats neither is a signal that costs fees.
