"""
Long-Term Buy Strategy
Three ways of simply owning an instrument, selected with `mode`:

    0  Buy and hold   buy `weight` of the portfolio on the first bar, then stop
    1  Fixed weight   hold `weight`, correcting drift once a month
    2  DCA            buy every `dca_interval_days`, sized to finish in `dca_years`

This is the benchmark arm, not an idea. Any timing strategy has to beat the
version of this that matches its own average exposure, otherwise the timing
added nothing and the trading costs were paid for nothing.

WHY MODE 1 MATTERS MORE THAN MODE 0
  Comparing a timing strategy only against 100% buy-and-hold conflates two
  different things: holding less, and holding at better moments. A strategy in
  the market 70% of the time will usually lose to 100% buy-and-hold in a bull
  run regardless of how good its timing is. Measure its exposure first, then
  run mode 1 at that weight -- the gap is what the timing was actually worth.

  On SPY 2018-2025, SMC structure following sat at 71.4% exposure and returned
  96.5%. Buy-and-hold returned 155.0%, but fixed weight at 71.4% returned
  110.7%. The honest number is -14.2 points, not -58.5.

MODE 2 TAKES ONE PARAMETER
  Interval is the only thing to decide. The horizon is the backtest window,
  which the run already knows, so the instalment falls out of it:

      instalment = starting_cash / (window_days / interval_days)

  Capital is therefore fully deployed by the end date whatever window is
  chosen, and DCA stays directly comparable with lump sum over the same range.
  Both numbers are read from the runtime -- context.portfolio.starting_cash and
  context.backtest_start / backtest_end -- so nothing has to be restated by
  hand and the two can never drift apart.

  Interval is a request, not a guarantee. Fractional shares are rejected by
  this engine, so an instalment worth less than one share cannot buy on
  schedule; unspent cash carries to the next interval and fills land further
  apart than asked. The run logs the effective spacing when that happens.
  The ceiling is capital / share_price purchases, whatever interval says.
"""

# @param mode int 0 0 = buy and hold, 1 = fixed weight, 2 = DCA range=0:2:1
# @param weight float 1.0 Modes 0 and 1 only: share of the portfolio to hold range=0.05:1.0:0.05
# @param dca_interval_days int 30 Mode 2 only: days between buys; widens automatically if capital cannot cover a share range=1:365:1

SYMBOL = "USStock:SPY"

DAYS_PER_YEAR = 365.0


def initialize(context):
    context.set_universe([SYMBOL])
    context.subscribe(frequency="1d", fields=["close"])
    # Nothing is computed from history, but a warmup keeps the start date
    # aligned with strategies being compared against this one.
    context.set_warmup(120)
    context.set_metadata(direction_mode="long_only", strategy_family="trend")
    g.entered = False
    g.last_buy_day = 0
    g.instalment = 0.0
    g.pending = 0.0
    # Mode 1 rebalances monthly. The schedule day is fixed at the 1st and
    # cannot be a parameter: run_monthly is called here, and context.params is
    # unavailable inside initialize (the validator raises
    # initializeParamsUnavailable), so it has to be a literal.
    run_monthly(monthly_rebalance, monthday=1)


def monthly_rebalance(context, data):
    if int(context.params.get("mode", 0)) != 1:
        return
    # order_target_percent is a no-op in months where the weight has not moved,
    # so this costs nothing when nothing drifted.
    order_target_percent(SYMBOL, float(context.params.get("weight", 1.0)),
                         reason="rebalance")


def handle_data(context, data):
    mode = int(context.params.get("mode", 0))

    if mode != 2:
        if not bool(g.entered):
            # Modes 0 and 1 both open on the first bar; mode 1's monthly
            # callback only corrects drift from there.
            order_target_percent(SYMBOL, float(context.params.get("weight", 1.0)),
                                 reason="initial_entry")
            g.entered = True
        return

    # --- DCA -------------------------------------------------------------
    interval = max(1, int(context.params.get("dca_interval_days", 30)))
    today = int(context.current_dt.toordinal())

    if not bool(g.entered):
        # Size the instalment once, from the run's own capital and window, so
        # the schedule finishes flat on the end date whatever the account size
        # and whatever range was picked in the backtest form.
        window = 0
        try:
            window = int(context.backtest_end.toordinal()
                         - context.backtest_start.toordinal())
        except Exception:
            # Live trading has no end date. Fall back to a one-year schedule so
            # the strategy still runs rather than dividing by nothing.
            window = int(DAYS_PER_YEAR)
        buys = max(1, int(round(float(max(window, interval)) / interval)))
        g.instalment = float(context.portfolio.starting_cash) / buys
        g.entered = True
        g.last_buy_day = today - interval      # buy on the first bar

        # US stocks do not fill fractional quantities here -- an order for less
        # than one share is rejected outright, not partially filled. So when
        # the instalment is worth less than a share, buying cannot happen every
        # interval no matter what interval says, and the real spacing stretches
        # to however many intervals it takes to afford one. That is arithmetic,
        # not a setting: 10,000 spread over 8 years buys about 25 shares of a
        # 400 instrument, so 25 purchases is the ceiling however fine the
        # interval. Say so, rather than letting the fills look mysteriously
        # sparse.
        first_price = float(data.current(SYMBOL, "close"))
        if first_price > 0 and g.instalment < first_price:
            every = int(first_price / g.instalment) + 1
            log("DCA: instalment " + str(round(g.instalment, 2))
                + " is below one share at " + str(round(first_price, 2))
                + " -- buys will land roughly every " + str(every)
                + " intervals (~" + str(every * interval) + " days), not every "
                + str(interval) + ". Raise dca_interval_days to about "
                + str(every * interval) + ", or raise initial capital.")

    if today - int(g.last_buy_day) < interval:
        return

    g.last_buy_day = today

    # Carry unspent cash forward instead of sending it. Orders fill in whole
    # shares, so an instalment worth less than one share fills nothing at all
    # -- silently, with no error and no position. At a 7-day interval over 8
    # years each instalment is about 240, while SPY opened the period near 268,
    # so every single buy would have been dropped and the run would report a
    # flat 0.00%. Accumulating until the bucket covers a share is also what
    # real fixed-sum investing does with the remainder.
    g.pending = float(g.pending) + float(g.instalment)
    price = float(data.current(SYMBOL, "close"))
    if price <= 0:
        return

    # Orders fill in whole shares at the NEXT bar's open, not at the close read
    # here. Sending a cash amount worth exactly one share therefore buys
    # nothing whenever price ticked up overnight -- and it fails silently, with
    # no error and no fill, while this bucket has already been debited. At a
    # 7-day interval that lost 146 of 258 instalments before the buffer below
    # was added. Ordering an explicit share count makes the fill deterministic,
    # and the 2% headroom keeps a normal overnight move from breaking it.
    if float(g.pending) < price * 1.02:
        return

    shares = int(float(g.pending) // (price * 1.02))
    if shares < 1:
        return
    g.pending = float(g.pending) - shares * price
    order(SYMBOL, shares, reason="dca_instalment")
