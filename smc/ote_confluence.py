"""
SMC OTE Confluence
Model 4, from Justin Bennett's published eight-step model (dailypriceaction.com
plus the video of the same name). Long-only mirror of the short setup he shows.

  1  Structure   the higher timeframe has turned up -- a CHoCH, not a pullback
  2  Discount    price is below the midpoint of the leg; he will not short in
                 discount, so the mirror is: do not buy in premium
  3  OTE         price has retraced into 62-79% of the leg, the band he states
                 verbatim: "this is a 62% to 79% of this recent move"
  4  Gap         an unmitigated bullish FVG, AND it has to sit inside the OTE --
                 he treats the two as a confluence, not alternatives
  5  Entry       on that bar
  Stop           below the leg's own low: if the leg is void the idea is void
  Target         a fixed multiple of risk, minimum 3R in the source

WHAT THIS MODEL ADDS THAT 1-3 DO NOT HAVE
  A position filter. Structure, gaps and blocks all describe *what happened*;
  OTE describes *where price is now* relative to it. A setup can be structurally
  perfect and still be a poor entry because price never retraced. That is the
  one genuinely new dimension here, and it is arithmetic rather than judgement,
  which is why it is worth testing separately.

WHAT IS MINE RATHER THAN THE MODEL'S
  The source gives no mechanical exit beyond "minimum 3R and take partials", so
  `reward_r` is a choice, as in the other three. It also stops at the lower high
  that formed before the CHoCH; this stops below the leg low instead, which is
  cruder, wider, and does not need a second structural read.

  It also describes dropping to 5m for a final confirmation. That is not
  reproduced: a 5m subscription would drive every run at 5m, and the data
  provider caps 5m at 180 days -- which would then cap every other timeframe
  too, since the range limit takes the strictest subscribed frequency.

BACKTEST RANGE ON CRYPTO
  Crypto falls back to the 1D default of 1095 days and the 120-bar warmup on
  the daily frequency costs 227 of them, leaving roughly 868 usable.
"""

# @param signal_timeframe str 4h Bars the SMC factors read values=1h,4h,1d
# @param swing_length int 10 Bars each side to confirm a swing range=4:24:1
# @param ote_from float 0.62 Shallow edge of the OTE band range=0.3:0.9:0.01
# @param ote_to float 0.79 Deep edge of the OTE band range=0.4:0.95:0.01
# @param require_fvg int 1 Require an unmitigated gap inside the OTE range=0:1:1
# @param reward_r float 3.0 Target as a multiple of risk -- source says 3R minimum range=0.5:6:0.25
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
    ote_from = float(context.params.get("ote_from", 0.62))
    ote_to = float(context.params.get("ote_to", 0.79))
    require_fvg = int(context.params.get("require_fvg", 1))
    reward_r = float(context.params.get("reward_r", 3.0))
    size_pct = float(context.params.get("size_pct", 1.0))

    position = get_position(SYMBOL)
    if position is not None and position.amount > 0:
        return

    # 1. Structure must be bullish.
    trend = factor("smc_structure", SYMBOL, frequency=tf, swing_length=swing_length, output="trend")
    if trend is None or trend <= 0:
        return

    # 2 and 3. Price has to be in discount AND inside the OTE band. Discount is
    # implied by a 62-79% retracement, but checking it explicitly keeps the
    # rule readable and survives someone widening the band.
    discount = factor("smc_ote", SYMBOL, frequency=tf, swing_length=swing_length,
                      ote_from=ote_from, ote_to=ote_to, output="discount")
    if discount is None or discount <= 0:
        return
    in_ote = factor("smc_ote", SYMBOL, frequency=tf, swing_length=swing_length,
                    ote_from=ote_from, ote_to=ote_to, output="in_ote")
    if in_ote is None or in_ote <= 0:
        return

    # 4. A gap, and it has to be inside the band rather than merely existing.
    if require_fvg == 1:
        fvg_side = factor("smc_fvg", SYMBOL, frequency=tf, output="side")
        if fvg_side is None or fvg_side <= 0:
            return
        gap_top = factor("smc_fvg", SYMBOL, frequency=tf, output="top")
        gap_bottom = factor("smc_fvg", SYMBOL, frequency=tf, output="bottom")
        near = factor("smc_ote", SYMBOL, frequency=tf, swing_length=swing_length,
                      ote_from=ote_from, ote_to=ote_to, output="ote_near")
        far = factor("smc_ote", SYMBOL, frequency=tf, swing_length=swing_length,
                     ote_from=ote_from, ote_to=ote_to, output="ote_far")
        if gap_top is None or gap_bottom is None or near is None or far is None:
            return
        # Overlap, not containment: a gap straddling the band edge still counts.
        if gap_bottom > near or gap_top < far:
            return

    stop = factor("smc_ote", SYMBOL, frequency=tf, swing_length=swing_length,
                  ote_from=ote_from, ote_to=ote_to, output="leg_low")
    if stop is None:
        return

    entry = float(data.current(SYMBOL, "close", frequency=tf))
    risk = entry - stop
    if risk <= 0 or entry <= 0:
        return
    stop_pct = risk / entry
    if stop_pct <= 0 or stop_pct >= 1:
        return

    order_target_percent(
        SYMBOL, size_pct, reason="ote_confluence",
        protection={
            "stop_loss_pct": stop_pct,
            "take_profit_pct": stop_pct * reward_r,
        },
    )
