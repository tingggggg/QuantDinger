"""
SMC Sweep to CHoCH
Model 1: enter after liquidity is taken and structure turns, stop beyond the
sweep.

  1  Sweep   a wick takes out a confirmed swing low but the close holds above
             it -- stops taken, price rejected
  2  CHoCH   structure turns bullish within `choch_window` bars of that sweep
  3  Entry   on the CHoCH bar
  Stop       beyond the sweep extreme, which is what invalidates the read
  Target     a fixed multiple of that risk

WHY THE SWEEP NEEDS ITS OWN FACTOR
  A break of structure is defined on the CLOSE: price accepted a level. A
  sweep is the opposite -- the wick took the stops and the close came back.
  smc_structure cannot see one, because it only ever looks at closes. smc_sweep
  exists for exactly this model.

WHAT THE SOURCE MODEL LEAVES OPEN
  It says "immediately after the sweep" without saying how immediate, and
  gives no exit at all. `choch_window` and `reward_r` are both choices made
  here. The model also says to enter at the order block or gap that caused the
  CHoCH; this enters at the CHoCH bar itself, which is simpler, later, and
  worse-priced -- the honest version of "we could not see the intrabar fill".

TIMEFRAME
  `signal_timeframe` selects which bars the SMC factors read. Both 4h and 1d
  are subscribed, and the runtime drives on the SMALLEST subscribed frequency,
  so decisions are evaluated every 4h either way -- reading 1d factors on a 4h
  clock is the multi-timeframe shape the source model describes, not a bug.

  It cannot be a plain subscribe() argument: context.subscribe runs inside
  initialize, where context.params is unavailable.

  On daily bars a 800-day crypto window holds ~570 decision points; on 4h it
  holds ~4800. These models need several conditions to coincide, so the daily
  sample was too thin to conclude anything from.

BACKTEST RANGE ON CRYPTO
  Crypto falls back to the 1D default of 1095 days and the 120-bar warmup
  costs 227 of them, leaving roughly 868 usable.
"""

# @param signal_timeframe str 4h Bars the SMC factors read: 4h or 1d values=4h,1d
# @param swing_length int 10 Bars each side to confirm a swing range=4:24:1
# @param choch_window int 10 Bars allowed between the sweep and the turn range=1:40:1
# @param reward_r float 2.0 Target as a multiple of risk -- chosen here, not from the model range=0.5:6:0.25
# @param size_pct float 1.0 Portfolio share to commit per trade range=0.1:1.0:0.05

SYMBOL = "Crypto:BTC/USDT@spot"


def initialize(context):
    context.set_universe([SYMBOL])
    context.subscribe(frequency="4h", fields=["open", "high", "low", "close"])
    context.subscribe(frequency="1d", fields=["open", "high", "low", "close"])
    context.set_warmup(120)
    context.set_metadata(direction_mode="long_only", strategy_family="trend")


def handle_data(context, data):
    tf = str(context.params.get("signal_timeframe", "4h"))
    swing_length = int(context.params.get("swing_length", 10))
    choch_window = int(context.params.get("choch_window", 10))
    reward_r = float(context.params.get("reward_r", 2.0))
    size_pct = float(context.params.get("size_pct", 1.0))

    position = get_position(SYMBOL)
    if position is not None and position.amount > 0:
        # Exits ride on the protection attached at entry.
        return

    # The turn has to happen on this bar. A CHoCH read several bars late is a
    # different trade from the one the model describes.
    choch = factor("smc_structure", SYMBOL, frequency=tf,
                   swing_length=swing_length, output="choch")
    if choch is None or choch <= 0:
        return

    # ... and it has to follow a sweep of the lows, recently.
    sweep_side = factor("smc_sweep", SYMBOL, frequency=tf,
                        swing_length=swing_length, output="side")
    if sweep_side is None or sweep_side <= 0:
        return
    sweep_age = factor("smc_sweep", SYMBOL, frequency=tf,
                       swing_length=swing_length, output="age")
    if sweep_age is None or sweep_age > choch_window:
        return

    stop = factor("smc_sweep", SYMBOL, frequency=tf,
                  swing_length=swing_length, output="extreme")
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
        SYMBOL, size_pct, reason="sweep_choch",
        protection={
            "stop_loss_pct": stop_pct,
            "take_profit_pct": stop_pct * reward_r,
        },
    )
