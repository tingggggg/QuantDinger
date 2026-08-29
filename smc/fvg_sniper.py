"""
SMC FVG Sniper
Model 3 from the SMC entry-model literature: buy the retest of a fair value gap
in a strong trend, stop behind the candle that opened it.

  Entry   price trades back into an unmitigated bullish FVG, at the level set
          by entry_pct across the gap (0.5 = the 50% mark the model names,
          1.0 = the far edge, 0.0 = the near edge)
  Stop    behind the displacement candle that created the gap
  Target  a fixed multiple of the risk taken

WHAT THE SOURCE MODEL DOES NOT SPECIFY
  It gives an entry and a stop and no exit. That is not a strategy -- without
  an exit there is no return to measure. `reward_r` is therefore a choice made
  here, not a rule taken from the model, and it is the single largest degree of
  freedom in the whole thing. Sweep it and you will find a flattering value;
  that finding would be about the sweep, not about the model.

  Two other words in the source are doing quiet work: "massive displacement"
  and "highly trending environment". Both are subjective. `trend_filter` is one
  concrete reading of the second (structure must be bullish); there is no
  filter for the first, so every gap qualifies regardless of size. Read the
  result knowing that.

LONG ONLY
  The mirrored short side is deliberately absent. Adding it would mix two
  different questions into one number.

TIMEFRAME
  `signal_timeframe` selects which bars the SMC factors read. Both 4h and 1d
  are subscribed, and the runtime drives on the SMALLEST subscribed frequency,
  so decisions are evaluated every 4h either way -- reading 1d factors on a 4h
  clock is the multi-timeframe shape the source model describes, not a bug.

  It cannot be a plain subscribe() argument: context.subscribe runs inside
  initialize, where context.params is unavailable.

  Only 4h and 1d are offered. The runtime drives on the SMALLEST subscribed
  frequency, so subscribing to 1h would make every run 1h-driven -- including
  the ones reading daily signals. Measured on this factor set, which is O(n^2)
  in bar count: 200 days at 1h took 101s, 400 days took 339s, and 800 days did
  not finish inside ten minutes. A 1h option would cost every other run 24x
  for the benefit of one.

  On daily bars a 800-day crypto window holds ~570 decision points; on 4h it
  holds ~4800. These models need several conditions to coincide, so the daily
  sample was too thin to conclude anything from.

BACKTEST RANGE ON CRYPTO
  Crypto has no market-specific range policy, so it falls back to the 1D
  default of 1095 days. The 120-bar warmup costs 227 calendar days of that,
  leaving roughly 868 usable. Ask for more and the run fails with
  strategyV2.backtestRangeLimit before it starts.
"""

# @param signal_timeframe str 4h Bars the SMC factors read values=4h,1d
# @param entry_pct float 0.5 Where in the gap to buy: 0 = near edge, 1 = far edge range=0:1:0.05
# @param reward_r float 2.0 Target as a multiple of risk -- chosen here, not from the model range=0.5:6:0.25
# @param trend_filter int 1 Require bullish market structure before entering range=0:1:1
# @param max_age int 30 Ignore gaps older than this many bars range=3:120:1
# @param swing_length int 10 Bars each side to confirm a swing, for the trend filter range=4:24:1
# @param size_pct float 1.0 Portfolio share to commit per trade range=0.1:1.0:0.05

SYMBOL = "Crypto:BTC/USDT@spot"


def initialize(context):
    context.set_universe([SYMBOL])
    context.subscribe(frequency="4h", fields=["open", "high", "low", "close"])
    context.subscribe(frequency="1d", fields=["open", "high", "low", "close"])
    # smc_structure needs swing_length * 2 + 2; ask for enough history that a
    # few completed legs sit behind the first decision.
    context.set_warmup(120)
    context.set_metadata(direction_mode="long_only", strategy_family="trend")


def handle_data(context, data):
    tf = str(context.params.get("signal_timeframe", "4h"))
    entry_pct = float(context.params.get("entry_pct", 0.5))
    reward_r = float(context.params.get("reward_r", 2.0))
    trend_filter = int(context.params.get("trend_filter", 1))
    max_age = int(context.params.get("max_age", 30))
    swing_length = int(context.params.get("swing_length", 10))
    size_pct = float(context.params.get("size_pct", 1.0))

    position = get_position(SYMBOL)
    if position is not None and position.amount > 0:
        # Exits are handled by the protection attached at entry, so a held
        # position needs no decision here. Re-entering while long would also
        # average the stop distance into something the model never described.
        return

    side = factor("smc_fvg", SYMBOL, frequency=tf, output="side")
    if side is None or side <= 0:
        return

    age = factor("smc_fvg", SYMBOL, frequency=tf, output="age")
    if age is None or age > max_age:
        # A gap price has ignored for months is not the "highly trending
        # environment" the model is about.
        return

    if trend_filter == 1:
        trend = factor("smc_structure", SYMBOL, frequency=tf,
                       swing_length=swing_length, output="trend")
        if trend is None or trend <= 0:
            return

    top = factor("smc_fvg", SYMBOL, frequency=tf, output="top")
    bottom = factor("smc_fvg", SYMBOL, frequency=tf, output="bottom")
    stop = factor("smc_fvg", SYMBOL, frequency=tf, output="stop")
    if top is None or bottom is None or stop is None:
        return

    # entry_pct measures from the near edge (bottom, where a retest arrives)
    # toward the far edge.
    entry = bottom + (top - bottom) * entry_pct
    close = float(data.current(SYMBOL, "close", frequency=tf))
    low = float(data.current(SYMBOL, "low", frequency=tf))

    # The retest has to have happened: price must have traded down to the entry
    # level. Testing the low rather than the close is what makes this a limit
    # order rather than a close-only signal -- but it also means the fill is
    # assumed at the next bar's open, not at `entry`. Slippage covers part of
    # that gap; the rest is a known optimism in this backtest.
    if low > entry:
        return
    if close <= stop:
        # Already invalidated. Entering here buys a broken setup.
        return

    risk = entry - stop
    if risk <= 0 or entry <= 0:
        return

    stop_pct = risk / entry
    if stop_pct <= 0 or stop_pct >= 1:
        return

    order_target_percent(
        SYMBOL, size_pct, reason="fvg_sniper",
        protection={
            "stop_loss_pct": stop_pct,
            "take_profit_pct": stop_pct * reward_r,
        },
    )
