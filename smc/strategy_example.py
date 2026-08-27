"""
SMC Structure Following
Holds while market structure is bullish, flat otherwise. Optionally waits for a
CHoCH to confirm the turn instead of acting on trend state alone.

This is a deliberately plain use of the smc_structure factor -- one instrument,
one decision per bar, no stacking of conditions. The point is to measure whether
the structure signal carries anything, not to build a good strategy on the first
try. Read the result against buy-and-hold on the same instrument and period, and
against a random-entry control with the same trade count, before concluding
anything.

Look-ahead is handled by the runtime, not by this file. The factor is evaluated
on expanding windows (`visible = frame.iloc[:index + 1]`), and its pivots are
only confirmed swing_length bars after they print, so a break that took 28 bars
to become knowable arrives 28 bars late here too.
"""

# @param swing_length int 10 Bars each side required to confirm a swing range=4:24:1
# @param target_pct float 0.5 Target portfolio weight while long range=0.1:1.0:0.05
# @param entry_mode int 0 0 = follow trend state, 1 = require a CHoCH to enter range=0:1:1

SYMBOL = "USStock:SPY"


def initialize(context):
    context.set_universe([SYMBOL])
    context.subscribe(frequency="1d", fields=["high", "low", "close"])
    # smc_structure needs swing_length * 2 + 2 bars before it returns anything;
    # ask for more so the structure has a few completed legs behind it.
    context.set_warmup(120)
    context.set_metadata(direction_mode="long_only", strategy_family="trend")


def handle_data(context, data):
    swing_length = int(context.params.get("swing_length", 10))
    target_pct = float(context.params.get("target_pct", 0.5))
    entry_mode = int(context.params.get("entry_mode", 0))

    trend = indicator("smc_structure", SYMBOL,
                      swing_length=swing_length, output="trend")
    if trend is None:
        return

    if entry_mode == 0:
        # Plain state following: long while structure is bullish.
        target = target_pct if trend > 0 else 0.0
        reason = "structure_bullish" if trend > 0 else "structure_not_bullish"
    else:
        # Event driven: enter only on the bar a CHoCH turns structure up, exit
        # whenever structure is no longer bullish. A CHoCH is the first break
        # against the prevailing direction, i.e. the turn rather than the
        # continuation.
        choch = indicator("smc_structure", SYMBOL,
                          swing_length=swing_length, output="choch")
        position = get_position(SYMBOL)
        holding = position is not None and position.amount > 0

        if choch is not None and choch > 0:
            target, reason = target_pct, "choch_bullish"
        elif trend <= 0:
            target, reason = 0.0, "structure_lost"
        elif holding:
            return
        else:
            return

    order_target_percent(SYMBOL, target, reason=reason)
