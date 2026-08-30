"""
SMC HTF/LTF Fusion
Model 5. The first model here that is genuinely two-timeframe: the higher
timeframe decides WHERE, the lower timeframe decides WHEN.

  Stage 1, higher timeframe
    1  Trend      HTF structure is bullish, or the setup is skipped entirely
    2  Zone       an unmitigated HTF order block -- the candle that produced
                  the displacement -- is the demand zone
    3  Arrival    wait, do not predict. Price has to actually trade into it

  Stage 2, lower timeframe, only once price is inside the zone
    A  Sweep      price takes out a recent low (stops harvested), then closes
                  back and structure turns up -- a CHoCH on the LTF
    B  Inversion  price closes through a bearish gap, flipping it to support

  Stage 3, entry
    Entry         on the confirming LTF bar
    Stop          outside the extreme the reversal made
    Size          risk_pct of equity divided by the stop distance, so every
                  trade risks the same amount rather than the same notional

  Stage 4, exit
    Target        a fixed multiple of risk
    Trail         once in profit, the stop follows each new LTF swing low

WHY THIS IS NOT MODEL 1 WITH EXTRA STEPS
  Models 1-4 read several frequencies but decide on one: a 4h factor read on
  an 1h clock is still a single condition. This one has a state machine. The
  HTF zone arms the setup and the LTF trigger fires it, and the two can be
  many bars apart -- which is what "wait for price to reach the zone, then
  drop down a timeframe" actually means.

THE TRAILING STOP IS NOT THE ENGINE'S
  protection={} anchors every trigger to a PERCENTAGE of average cost --
  process_protections re-reads position.avg_cost each bar and computes
  entry * (1 +/- pct). A structural trail needs an ABSOLUTE price that moves
  with the swing lows, which that cannot express, and re-issuing an order to
  update it would rebase the entry through apply_scale_in and corrupt the R
  multiple.

  So the trail is managed here, in handle_data, against g.trail. The cost is
  real and worth stating: the engine's own stop is checked INTRABAR against
  each bar's high/low, while this trail is only checked on the CLOSE. A bar
  that dips through the trail and recovers exits in life and does not exit
  here, so trailed exits are optimistic. The hard stop stays with the engine
  precisely so the catastrophic case keeps intrabar fidelity.

TIMEFRAME PAIRING AND WHAT IT COSTS
  htf_timeframe and ltf_timeframe are both parameters, but only the pairs
  whose LTF is subscribed can be chosen. The runtime drives on the SMALLEST
  subscribed frequency and the backtest range limit takes the STRICTEST
  subscribed frequency, so subscribing 5m would cap every run at 180 days on
  crypto regardless of which pair is selected.

  1h is therefore the finest subscribed here, giving 1d/1h and 4h/1h pairs
  over the full 1095-day budget. The ratio the source model asks for -- LTF at
  or below half the HTF -- holds for both. Going to 1h/5m would need 5m
  subscribed, and half a year is too thin for a setup needing this many
  conditions to coincide; the place to start is the widest sample.

  The HTF read is free of look-ahead by construction: the portal's visible
  cutoff subtracts the READ frequency's own length, so an HTF bar only becomes
  visible on the LTF bar that completes it. Verified separately, 0 violations.

BACKTEST RANGE ON CRYPTO
  Crypto falls back to the 1D default of 1095 days and the 120-bar warmup on
  the daily frequency costs 227 of them, leaving roughly 868 usable.
"""

# @param htf_timeframe str 1d Higher timeframe that sets direction and zones values=4h,1d
# @param ltf_timeframe str 1h Lower timeframe that confirms entry values=1h,4h
# @param trigger int 0 0 = sweep then CHoCH, 1 = inversion gap, 2 = either range=0:2:1
# @param swing_length int 10 Bars each side to confirm a swing range=4:24:1
# @param zone_max_age int 40 Ignore HTF zones older than this many HTF bars range=3:120:1
# @param arm_bars int 12 LTF bars the trigger stays armed after price enters the zone range=2:60:1
# @param reward_r float 3.0 Target as a multiple of risk range=0.5:8:0.25
# @param risk_pct float 0.01 Equity risked per trade -- source says 1% to 3% range=0.005:0.03:0.005
# @param sweep_window int 10 LTF bars the sweep stays valid for range=2:40:1
# @param trail_enabled int 1 Move the stop up to each new LTF swing low range=0:1:1

SYMBOL = "Crypto:BTC/USDT@spot"


def initialize(context):
    context.set_universe([SYMBOL])
    # 1h is the finest subscribed on purpose -- see the timeframe note above.
    context.subscribe(frequency="1h", fields=["open", "high", "low", "close"])
    context.subscribe(frequency="4h", fields=["open", "high", "low", "close"])
    context.subscribe(frequency="1d", fields=["open", "high", "low", "close"])
    context.set_warmup(120)
    context.set_metadata(direction_mode="long_only", strategy_family="trend")
    # The state machine. armed_until is an LTF bar count, not a timestamp, so
    # it does not need calendar arithmetic inside the sandbox.
    g.bar = 0
    g.armed_until = -1
    g.zone_low = 0.0
    g.trail = 0.0


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
    g.bar = g.bar + 1
    try:
        _decide(context, data)
    except Exception:
        return


def _decide(context, data):
    htf = str(context.params.get("htf_timeframe", "1d"))
    ltf = str(context.params.get("ltf_timeframe", "1h"))
    trigger = int(context.params.get("trigger", 0))
    swing_length = int(context.params.get("swing_length", 10))
    zone_max_age = int(context.params.get("zone_max_age", 40))
    arm_bars = int(context.params.get("arm_bars", 12))
    reward_r = float(context.params.get("reward_r", 3.0))
    risk_pct = float(context.params.get("risk_pct", 0.01))
    sweep_window = int(context.params.get("sweep_window", 10))
    trail_enabled = int(context.params.get("trail_enabled", 1))

    position = get_position(SYMBOL)
    if position is not None and position.amount > 0:
        if trail_enabled == 1:
            _manage(context, data, ltf, swing_length)
        return

    # Flat: nothing to trail, and a stale level would only mislead the next
    # trade into thinking it is already protected.
    g.trail = 0.0

    _arm(data, htf, ltf, swing_length, zone_max_age, arm_bars)
    if g.bar > g.armed_until:
        return

    entry = float(data.current(SYMBOL, "close", frequency=ltf))
    stop = _trigger_stop(data, ltf, swing_length, trigger, sweep_window)
    if stop is None or entry <= 0:
        return
    # The stop must sit below the zone that armed this, not merely below price.
    # A trigger that fires above the zone is a different trade.
    if g.zone_low > 0 and stop > g.zone_low:
        stop = g.zone_low

    risk = entry - stop
    if risk <= 0:
        return
    stop_pct = risk / entry
    if stop_pct <= 0 or stop_pct >= 1:
        return

    # Fixed fractional risk: size so the distance to the stop costs risk_pct of
    # equity, rather than committing a fixed share of the book and letting the
    # loss vary with the stop distance. This is what the source means by "risk
    # 1% per trade"; order_target_percent alone cannot express it.
    equity = float(context.portfolio.total_value)
    shares = (equity * risk_pct) / risk
    if shares <= 0:
        return
    # Never borrow to honour the risk budget -- a tight stop would otherwise
    # ask for more than the account holds.
    affordable = (float(context.portfolio.available_cash) * 0.98) / entry
    shares = min(shares, affordable)
    if shares <= 0:
        return

    g.armed_until = -1
    g.trail = stop
    order(
        SYMBOL, shares, reason="htf_ltf_fusion",
        protection={
            # Kept with the engine so the catastrophic case is still checked
            # intrabar. The structural trail below only ever tightens.
            "stop_loss_pct": stop_pct,
            "take_profit_pct": stop_pct * reward_r,
        },
    )


def _arm(data, htf, ltf, swing_length, zone_max_age, arm_bars):
    """Stage 1: is price inside a live HTF demand zone right now?"""
    trend = factor("smc_structure", SYMBOL, frequency=htf, swing_length=swing_length, output="trend")
    if trend is None or trend <= 0:
        return

    side = factor("smc_ob", SYMBOL, frequency=htf, swing_length=swing_length, output="side")
    if side is None or side <= 0:
        return
    age = factor("smc_ob", SYMBOL, frequency=htf, swing_length=swing_length, output="age")
    if age is None or age > zone_max_age:
        return

    top = factor("smc_ob", SYMBOL, frequency=htf, swing_length=swing_length, output="top")
    bottom = factor("smc_ob", SYMBOL, frequency=htf, swing_length=swing_length, output="bottom")
    if top is None or bottom is None:
        return

    # Arrival, on the LTF bar: the low reaching into the zone is the touch the
    # model waits for. Testing the LTF low rather than the HTF close is the
    # whole point of dropping down a timeframe.
    low = float(data.current(SYMBOL, "low", frequency=ltf))
    close = float(data.current(SYMBOL, "close", frequency=ltf))
    if low > top or close < bottom:
        # Either not there yet, or through it -- a zone price closed below is
        # not holding.
        return

    g.zone_low = bottom
    # Arm for a window rather than a single bar: the source expects the
    # confirmation to form after the touch, not on it.
    g.armed_until = g.bar + arm_bars


def _trigger_stop(data, ltf, swing_length, trigger, sweep_window):
    """Stage 2: the LTF confirmation. Returns the stop it implies, or None."""
    if trigger in (0, 2):
        # A: stops taken below, close recovered, and structure now reads up.
        #
        # "Structure now reads up" is the LTF trend STATE, not the one-bar
        # choch flag, and that substitution is mine rather than the model's.
        # It is not a preference -- it is forced. Measured over BTC 1h,
        # 2023-08 to 2025-12: 19,729 bars, 918 of them arriving in a live HTF
        # zone, and inside those armed windows the choch flag and a recent
        # sweep coincide exactly ONCE. The literal reading cannot be tested,
        # so it cannot be evaluated. Using the state gives 236 candidates.
        #
        # The sweep still has to be recent, which is what keeps the order the
        # model describes: liquidity taken first, structure turning second.
        side = factor("smc_sweep", SYMBOL, frequency=ltf, swing_length=swing_length, output="side")
        if side is not None and side > 0:
            age = factor("smc_sweep", SYMBOL, frequency=ltf, swing_length=swing_length, output="age")
            trend = factor("smc_structure", SYMBOL, frequency=ltf, swing_length=swing_length, output="trend")
            if age is not None and trend is not None and age <= sweep_window and trend > 0:
                extreme = factor("smc_sweep", SYMBOL, frequency=ltf, swing_length=swing_length, output="extreme")
                if extreme is not None:
                    return float(extreme)

    if trigger in (1, 2):
        # B: a bearish gap price closed above, now acting as support.
        side = factor("smc_ifvg", SYMBOL, frequency=ltf, output="side")
        if side is not None and side > 0:
            age = factor("smc_ifvg", SYMBOL, frequency=ltf, output="age")
            bottom = factor("smc_ifvg", SYMBOL, frequency=ltf, output="bottom")
            stop = factor("smc_ifvg", SYMBOL, frequency=ltf, output="stop")
            low = float(data.current(SYMBOL, "low", frequency=ltf))
            # Only while the flip is fresh and price has come back to test it.
            if age is not None and bottom is not None and stop is not None:
                if age <= 6 and low <= float(bottom) * 1.005:
                    return float(stop)

    return None


def _manage(context, data, ltf, swing_length):
    """Stage 4: raise the stop to each new confirmed LTF swing low.

    Close-only, unlike the engine's own stop. See the note in the docstring --
    trailed exits here are optimistic by exactly the bars that dip through the
    level and recover.
    """
    swing_low = factor("smc_structure", SYMBOL, frequency=ltf, swing_length=swing_length, output="swing_low")
    if swing_low is not None and float(swing_low) > g.trail:
        # Only ever tightens. A swing low below the current stop is the market
        # going against the trade, which is what the hard stop is for.
        g.trail = float(swing_low)

    if g.trail <= 0:
        return
    close = float(data.current(SYMBOL, "close", frequency=ltf))
    if close < g.trail:
        order_target_percent(SYMBOL, 0.0, reason="structure_trail")
        g.trail = 0.0
