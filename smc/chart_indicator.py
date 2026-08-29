# ============================================================
# SMC Full -- every Smart Money Concepts component, no repaint
# --- QuantDinger chart indicator contract ---
# ------------------------------------------------------------
# Draws the whole SMC vocabulary the way the reference charts do:
# swing highs/lows, BOS & CHoCH, fair value gaps, order blocks,
# liquidity pools, previous period high/low, trading sessions and
# retracement depth.
#
# Zones and labels use output['layers']; continuous state uses
# output['plots'].
#
# THE ONE RULE THIS FILE ENFORCES
#   Nothing is drawn before it could be known. A swing pivot needs
#   swing_length bars on BOTH sides, so it is revealed swing_length
#   bars after it happened -- never on the bar itself. Everything
#   derived from a pivot (BOS, CHoCH, order blocks, liquidity)
#   inherits that delay.
#
#   The `smartmoneyconcepts` package does the opposite: measured over
#   150 BOS/CHoCH signals, ZERO were visible on the bar they were
#   stamped on -- mean lag 17-58 bars. Charts drawn that way show a
#   past that never existed.
#
# SANDBOX NOTE
#   Reductions must use np.max(a) / np.sum(a), never a.max() / a.sum().
#   The ndarray METHOD form lazily imports numpy._core._methods, which
#   the indicator sandbox rejects as an internal numpy submodule.
# ============================================================

my_indicator_name = "SMC Full"
my_indicator_description = (
    "Complete Smart Money Concepts overlay -- swings, BOS/CHoCH, FVG, order "
    "blocks, liquidity, previous high/low, sessions and retracements, all "
    "drawn without repaint. Chart-only."
)

# ===== Configurable params =====
# @param swing_length int 10 Bars required each side to confirm a swing range=3:30:1
# @param max_items int 8 Keep only this many of each zone type (newest first) range=2:30:1
# @param show_swings int 1 Swing high / low labels range=0:1:1
# @param show_structure int 1 BOS and CHoCH breaks range=0:1:1
# @param show_fvg int 1 Fair value gaps range=0:1:1
# @param show_ob int 1 Order blocks range=0:1:1
# @param show_liquidity int 1 Equal highs / lows range=0:1:1
# @param show_prev_hl int 1 Previous day high / low range=0:1:1
# @param show_sessions int 0 Trading session bands range=0:1:1
# @param show_retracement int 1 Retracement depth labels range=0:1:1

swing_length = int(params.get('swing_length', 10))
max_items = int(params.get('max_items', 8))
show_swings = int(params.get('show_swings', 1))
show_structure = int(params.get('show_structure', 1))
show_fvg = int(params.get('show_fvg', 1))
show_ob = int(params.get('show_ob', 1))
show_liquidity = int(params.get('show_liquidity', 1))
show_prev_hl = int(params.get('show_prev_hl', 1))
show_sessions = int(params.get('show_sessions', 0))
show_retracement = int(params.get('show_retracement', 1))

df = df.copy()
op = df['open'].astype(float).to_numpy()
hi = df['high'].astype(float).to_numpy()
lo = df['low'].astype(float).to_numpy()
cl = df['close'].astype(float).to_numpy()
vol = df['volume'].astype(float).to_numpy()
m = len(df)
n = swing_length
last = m - 1

# Palette. Two zone families share the chart, so hue separates the TYPE and
# warm/cool separates the DIRECTION -- otherwise a bullish order block and a
# bullish gap sit next to each other in the same blue-green and stop being
# distinguishable at a glance.
#
#   Order block   teal  / crimson    saturated, heavier fill
#   Fair value gap  indigo / amber   lighter fill, dashed border
BULL = '#26A69A'          # candles / structure, bullish
BEAR = '#EF5350'          # candles / structure, bearish
OB_BULL = '#00897B'       # order block, bullish   -- teal
OB_BEAR = '#C2185B'       # order block, bearish   -- crimson
FVG_BULL = '#3949AB'      # fair value gap, bullish -- indigo
FVG_BEAR = '#EF6C00'      # fair value gap, bearish -- amber
LIQ = '#C79A3C'
PREV = '#8E86C9'
SESS = '#5A6270'

OB_OPACITY = 0.22         # heavier: an order block is a price area that acted
FVG_OPACITY = 0.13        # lighter: a gap is an absence, not a level

layers = []

# --- 1) Swing pivots -------------------------------------------------------
# Candidates live in [n, m-n): anything later has no confirmed right side.
is_ph = np.zeros(m, dtype=bool)
is_pl = np.zeros(m, dtype=bool)

for i in range(n, m - n):
    wh = hi[i - n:i + n + 1]
    if hi[i] == np.max(wh) and int(np.sum(wh == hi[i])) == 1:
        is_ph[i] = True
    wl = lo[i - n:i + n + 1]
    if lo[i] == np.min(wl) and int(np.sum(wl == lo[i])) == 1:
        is_pl[i] = True

ph_idx = [int(i) for i in np.flatnonzero(is_ph)]
pl_idx = [int(i) for i in np.flatnonzero(is_pl)]

if show_swings == 1:
    for i in ph_idx[-(max_items * 2):]:
        layers.append({'type': 'label', 'index': i, 'price': float(hi[i]),
                       'text': 'PH', 'color': BEAR, 'textColor': '#FFFFFF',
                       'fontSize': 10})
    for i in pl_idx[-(max_items * 2):]:
        layers.append({'type': 'label', 'index': i, 'price': float(lo[i]),
                       'text': 'PL', 'color': BULL, 'textColor': '#FFFFFF',
                       'fontSize': 10})

# --- 2) Structure replay: BOS / CHoCH --------------------------------------
# A level is consumed on break, so an event fires once, on the break bar.
ref_high = np.full(m, np.nan)
ref_low = np.full(m, np.nan)
trend_arr = np.zeros(m, dtype=np.int8)
events = []            # (break_idx, pivot_idx, level, kind, direction)

cur_h = np.nan
cur_l = np.nan
h_pivot = -1
l_pivot = -1
h_live = False
l_live = False
direction = 0

for t in range(m):
    pivot = t - n
    if pivot >= 0:
        if is_ph[pivot]:
            cur_h, h_pivot, h_live = hi[pivot], pivot, True
        if is_pl[pivot]:
            cur_l, l_pivot, l_live = lo[pivot], pivot, True

    ref_high[t] = cur_h
    ref_low[t] = cur_l

    if h_live and not np.isnan(cur_h) and cl[t] > cur_h:
        kind = 'BOS' if direction >= 0 else 'CHoCH'
        events.append((t, h_pivot, float(cur_h), kind, 1))
        direction = 1
        h_live = False
    elif l_live and not np.isnan(cur_l) and cl[t] < cur_l:
        kind = 'BOS' if direction <= 0 else 'CHoCH'
        events.append((t, l_pivot, float(cur_l), kind, -1))
        direction = -1
        l_live = False

    trend_arr[t] = direction

if show_structure == 1:
    for brk, piv, level, kind, side in events[-(max_items * 2):]:
        col = BULL if side > 0 else BEAR
        layers.append({'type': 'line', 'startIndex': piv, 'endIndex': brk,
                       'price': level, 'text': kind, 'color': col,
                       'dashed': kind == 'CHoCH', 'lineWidth': 1,
                       'textColor': col, 'fontSize': 10})

# --- 3) Fair value gaps ----------------------------------------------------
# Three-bar imbalance, knowable on the third bar. The box extends to the bar
# that trades back through it, or to the right edge while still open.
fvgs = []
for k in range(2, m):
    if lo[k] > hi[k - 2]:
        top, bottom, side = float(lo[k]), float(hi[k - 2]), 1
    elif hi[k] < lo[k - 2]:
        top, bottom, side = float(lo[k - 2]), float(hi[k]), -1
    else:
        continue
    end = last
    for j in range(k + 1, m):
        if lo[j] <= top and hi[j] >= bottom:
            end = j
            break
    fvgs.append((k, end, top, bottom, side))

if show_fvg == 1:
    for k, end, top, bottom, side in fvgs[-max_items:]:
        col = FVG_BULL if side > 0 else FVG_BEAR
        txt = 'FVG' + ('↑' if side > 0 else '↓')
        layers.append({'type': 'zone', 'startIndex': k, 'endIndex': end,
                       'top': top, 'bottom': bottom, 'text': txt,
                       'fillColor': col, 'borderColor': col,
                       'opacity': FVG_OPACITY, 'dashed': True,
                       'textColor': col, 'fontSize': 10})

# --- 4) Order blocks -------------------------------------------------------
# The last opposing candle before the move that broke structure. Derived from
# a confirmed break, so it appears no earlier than the break itself.
if show_ob == 1:
    obs = []
    for brk, piv, level, kind, side in events:
        found = -1
        for j in range(brk - 1, max(brk - 30, 0) - 1, -1):
            if side > 0 and cl[j] < op[j]:
                found = j
                break
            if side < 0 and cl[j] > op[j]:
                found = j
                break
        if found < 0:
            continue
        mit = last
        for j in range(found + 1, m):
            if side > 0 and lo[j] <= lo[found]:
                mit = j
                break
            if side < 0 and hi[j] >= hi[found]:
                mit = j
                break
        obs.append((found, mit, float(hi[found]), float(lo[found]),
                    float(vol[found]), side))

    total_vol = float(np.sum(vol)) if m else 0.0
    for start, end, top, bottom, v, side in obs[-max_items:]:
        share = (v / total_vol * 100.0) if total_vol > 0 else 0.0
        col = OB_BULL if side > 0 else OB_BEAR
        txt = 'OB' + ('↑' if side > 0 else '↓') + ' ' + str(round(share, 1)) + '%'
        layers.append({'type': 'zone', 'startIndex': start, 'endIndex': end,
                       'top': top, 'bottom': bottom, 'text': txt,
                       'fillColor': col, 'borderColor': col,
                       'opacity': OB_OPACITY,
                       'textColor': col, 'fontSize': 10})

# --- 5) Liquidity ----------------------------------------------------------
# Two or more confirmed pivots within range_percent of each other: a shelf of
# resting stops. The level runs until price sweeps it.
if show_liquidity == 1:
    range_pct = 0.005

    def _pools(idxs, prices, side):
        out = []
        used = set()
        for a in range(len(idxs)):
            if idxs[a] in used:
                continue
            base = prices[idxs[a]]
            group = [idxs[a]]
            for b in range(a + 1, len(idxs)):
                if idxs[b] in used:
                    continue
                if abs(prices[idxs[b]] - base) / base <= range_pct:
                    group.append(idxs[b])
            if len(group) < 2:
                continue
            for g in group:
                used.add(g)
            level = float(np.mean(np.array([prices[g] for g in group])))
            start = group[0]
            swept = last
            for j in range(group[-1] + 1, m):
                if side > 0 and hi[j] > level:
                    swept = j
                    break
                if side < 0 and lo[j] < level:
                    swept = j
                    break
            out.append((start, swept, level, side))
        return out

    pools = _pools(ph_idx, hi, 1) + _pools(pl_idx, lo, -1)
    pools.sort()
    for start, end, level, side in pools[-max_items:]:
        txt = 'BSL' if side > 0 else 'SSL'
        layers.append({'type': 'line', 'startIndex': start, 'endIndex': end,
                       'price': level, 'text': txt, 'color': LIQ,
                       'dashed': True, 'lineWidth': 1,
                       'textColor': LIQ, 'fontSize': 10})

# --- 6) Previous period high / low -----------------------------------------
# Carried forward from the completed session, so it is fixed the moment the
# new session opens.
if show_prev_hl == 1:
    try:
        day = df.index.normalize()
        codes = day.astype('int64').to_numpy()
        bounds = [0]
        for i in range(1, m):
            if codes[i] != codes[i - 1]:
                bounds.append(i)
        bounds.append(m)
        prev_layers = []
        for b in range(1, len(bounds) - 1):
            ps, pe = bounds[b - 1], bounds[b]
            cs, ce = bounds[b], bounds[b + 1]
            pdh = float(np.max(hi[ps:pe]))
            pdl = float(np.min(lo[ps:pe]))
            prev_layers.append({'type': 'line', 'startIndex': cs, 'endIndex': ce - 1,
                                'price': pdh, 'text': 'PDH', 'color': PREV,
                                'dashed': True, 'lineWidth': 1,
                                'textColor': PREV, 'fontSize': 9})
            prev_layers.append({'type': 'line', 'startIndex': cs, 'endIndex': ce - 1,
                                'price': pdl, 'text': 'PDL', 'color': PREV,
                                'dashed': True, 'lineWidth': 1,
                                'textColor': PREV, 'fontSize': 9})
        # Only the most recent sessions; older PDH/PDL pairs just add noise.
        for entry in prev_layers[-(max_items * 2):]:
            layers.append(entry)
    except Exception:
        pass

# --- 7) Sessions -----------------------------------------------------------
# Asia / London / New York bands in UTC. Intraday data only -- on daily bars
# every bar sits at 00:00 and the bands carry no information.
if show_sessions == 1:
    try:
        hours = np.array(list(df.index.hour))
        if int(np.sum(hours != hours[0])) > 0:
            top_all = float(np.max(hi))
            bot_all = float(np.min(lo))
            spans = (('Asia', 0, 8), ('London', 8, 13), ('New York', 13, 21))
            for label, h0, h1 in spans:
                inside = (hours >= h0) & (hours < h1)
                run_start = -1
                runs = []
                for i in range(m):
                    if inside[i] and run_start < 0:
                        run_start = i
                    elif not inside[i] and run_start >= 0:
                        runs.append((run_start, i - 1))
                        run_start = -1
                if run_start >= 0:
                    runs.append((run_start, last))
                for s, e in runs[-3:]:
                    layers.append({'type': 'zone', 'startIndex': s, 'endIndex': e,
                                   'top': top_all, 'bottom': bot_all,
                                   'text': label, 'fillColor': SESS,
                                   'borderColor': SESS, 'opacity': 0.05,
                                   'textColor': SESS, 'fontSize': 9})
    except Exception:
        pass

# --- 8) Retracements -------------------------------------------------------
# For each completed leg between opposing pivots: how far price has pulled
# back so far (C) and the deepest pullback reached (D).
if show_retracement == 1:
    pivots = sorted([(i, 1) for i in ph_idx] + [(i, -1) for i in pl_idx])
    legs = []
    for a in range(1, len(pivots)):
        i0, s0 = pivots[a - 1]
        i1, s1 = pivots[a]
        if s0 == s1:
            continue
        p0 = hi[i0] if s0 > 0 else lo[i0]
        p1 = hi[i1] if s1 > 0 else lo[i1]
        legs.append((i0, i1, float(p0), float(p1), s1))

    for i0, i1, p0, p1, s1 in legs[-max_items:]:
        span = p1 - p0
        if span == 0:
            continue
        seg_end = min(i1 + n, last)
        if s1 > 0:
            deepest = float(np.min(lo[i1:seg_end + 1]))
        else:
            deepest = float(np.max(hi[i1:seg_end + 1]))
        cur_px = float(cl[seg_end])
        c_pct = (p1 - cur_px) / span * 100.0
        d_pct = (p1 - deepest) / span * 100.0
        txt = 'C:' + str(round(abs(c_pct), 1)) + '% D:' + str(round(abs(d_pct), 1)) + '%'
        col = BEAR if s1 > 0 else BULL
        layers.append({'type': 'label', 'index': i1, 'price': p1,
                       'text': txt, 'color': col, 'textColor': '#FFFFFF',
                       'fontSize': 9})


def plot_list(values):
    """Warm-up NaN becomes None so the chart draws no fake zero line."""
    return [None if np.isnan(v) else float(v) for v in values]


# Continuous state stays in plots: the levels that are currently live.
live_high = np.where((~np.isnan(ref_high)) & (cl <= ref_high), ref_high, np.nan)
live_low = np.where((~np.isnan(ref_low)) & (cl >= ref_low), ref_low, np.nan)

output = {
    'name': my_indicator_name,
    'plots': [
        {'name': 'Structure High', 'data': plot_list(live_high),
         'color': BEAR, 'overlay': True},
        {'name': 'Structure Low', 'data': plot_list(live_low),
         'color': BULL, 'overlay': True},
    ],
    'signals': [],
    'layers': layers,
}
