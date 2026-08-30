"""
SMC Order Block Continuation
Model 2: trade with the trend, buying the pullback into the block that caused
the break.

  1  Trend    market structure is bullish
  2  Block    an unmitigated bullish order block exists -- the last down
              candle before the move that broke structure
  3  Entry    price pulls back and taps the block
  Stop        behind the block
  Target      a fixed multiple of that risk

  Optionally require a fair value gap alongside the block (`require_fvg`),
  which the source names as evidence the move had real displacement behind it
  rather than a drift.

WHY THE ORDER BLOCK ONLY APPEARS AT THE BREAK
  A down candle is not an order block until the move after it breaks
  structure. smc_ob therefore derives blocks from confirmed breaks, so one
  becomes visible on the BREAK bar, never on the candle itself. Marking it
  earlier would hand this strategy a level the market had not yet justified --
  the same mistake that makes the published SMC package unusable as a factor.

WHAT THE SOURCE MODEL LEAVES OPEN
  No exit rule, so `reward_r` is a choice made here. "Ideally has an FVG next
  to it" is a preference, not a threshold, so it is a switch rather than a
  hard rule. Neither is from the model.

TIMEFRAME
  `signal_timeframe` selects which bars the SMC factors read. 1h, 4h and 1d are
  all subscribed, and the runtime drives on the SMALLEST subscribed frequency,
  so decisions are evaluated every 1h whichever is chosen -- reading 4h or 1d
  factors on a 1h clock is the multi-timeframe shape the source models
  describe, not a bug.

  It cannot be a plain subscribe() argument: context.subscribe runs inside
  initialize, where context.params is unavailable.

  1h, 4h and 1d are offered. Anything finer is capped by the data provider
  (30m allows 365 days, 5m only 180) and 1w is not offered because a 120-bar
  weekly warmup costs 960 calendar days of the 1095-day crypto budget, leaving
  135 days to actually test in -- and the range limit takes the strictest
  subscribed frequency, so adding it would shrink every run's window.

  1h was impossible until the replay was made incremental. The runtime drives
  on the SMALLEST subscribed frequency, so 1h drives every run at 1h whichever
  timeframe the signals are read at; on the old O(n^2) replay 800 days did not
  finish inside ten minutes. It now takes about a minute.

  On daily bars a 800-day crypto window holds ~570 decision points; on 4h it
  holds ~4800. These models need several conditions to coincide, so the daily
  sample was too thin to conclude anything from.

BACKTEST RANGE ON CRYPTO
  Crypto falls back to the 1D default of 1095 days and the 120-bar warmup
  costs 227 of them, leaving roughly 868 usable.
"""

# @param signal_timeframe str 4h Bars the SMC factors read values=1h,4h,1d
# @param swing_length int 10 Bars each side to confirm a swing range=4:24:1
# @param reward_r float 2.0 Target as a multiple of risk -- chosen here, not from the model range=0.5:6:0.25
# @param require_fvg int 0 Require a live fair value gap alongside the block range=0:1:1
# @param max_age int 40 Ignore blocks older than this many bars range=3:120:1
# @param size_pct float 1.0 Portfolio share to commit per trade range=0.1:1.0:0.05

SYMBOL = "Crypto:BTC/USDT@spot"


def initialize(context):
    context.set_universe([SYMBOL])
    context.subscribe(frequency="1h", fields=["open", "high", "low", "close"])
    context.subscribe(frequency="4h", fields=["open", "high", "low", "close"])
    context.subscribe(frequency="1d", fields=["open", "high", "low", "close"])
    context.set_warmup(120)
    context.set_metadata(direction_mode="long_only", strategy_family="trend")


def handle_data(context, data):
    # A factor with nothing to say yet -- during warmup, or before any pivot is
    # confirmed -- raises, and the runtime re-raises it, which kills the whole
    # run on one early bar. That means "no trade", not "abort".
    #
    # The decision lives in its own function rather than behind a read() helper
    # so the factor names stay literal: the manifest's factorDependencies come
    # from an AST scan for factor("name"), and hiding the names behind a
    # variable empties it -- which in turn stops the review chart from knowing
    # this is an SMC run.
    try:
        _decide(context, data)
    except Exception:
        return


def _decide(context, data):
    tf = str(context.params.get("signal_timeframe", "4h"))
    swing_length = int(context.params.get("swing_length", 10))
    reward_r = float(context.params.get("reward_r", 2.0))
    require_fvg = int(context.params.get("require_fvg", 0))
    max_age = int(context.params.get("max_age", 40))
    size_pct = float(context.params.get("size_pct", 1.0))

    position = get_position(SYMBOL)
    if position is not None and position.amount > 0:
        return

    trend = factor("smc_structure", SYMBOL, frequency=tf, swing_length=swing_length, output="trend")
    if trend is None or trend <= 0:
        return

    side = factor("smc_ob", SYMBOL, frequency=tf, swing_length=swing_length, output="side")
    if side is None or side <= 0:
        return

    age = factor("smc_ob", SYMBOL, frequency=tf, swing_length=swing_length, output="age")
    if age is None or age > max_age:
        return

    if require_fvg == 1:
        # The source calls a gap beside the block evidence of displacement.
        # Any live gap is a loose reading of "directly next to it", but a
        # stricter one would need a proximity threshold this model never gives.
        fvg_side = factor("smc_fvg", SYMBOL, frequency=tf, output="side")
        if fvg_side is None or fvg_side <= 0:
            return

    top = factor("smc_ob", SYMBOL, frequency=tf, swing_length=swing_length, output="top")
    stop = factor("smc_ob", SYMBOL, frequency=tf, swing_length=swing_length, output="stop")
    if top is None or stop is None:
        return

    # The pullback has to have reached the block. Testing the low rather than
    # the close makes this a limit order in spirit -- but the fill is still
    # assumed at the next bar's open, which is a known optimism.
    low = float(data.current(SYMBOL, "low", frequency=tf))
    close = float(data.current(SYMBOL, "close", frequency=tf))
    if low > top:
        return
    if close <= stop:
        # Traded through the block instead of respecting it.
        return

    entry = close
    risk = entry - stop
    if risk <= 0 or entry <= 0:
        return
    stop_pct = risk / entry
    if stop_pct <= 0 or stop_pct >= 1:
        return

    order_target_percent(
        SYMBOL, size_pct, reason="ob_continuation",
        protection={
            "stop_loss_pct": stop_pct,
            "take_profit_pct": stop_pct * reward_r,
        },
    )
