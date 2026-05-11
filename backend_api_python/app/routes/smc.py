"""
Smart Money Concepts analysis endpoint.

Computes FVG / Order Block / BOS / CHoCH / Swings from K-line data using the
`smartmoneyconcepts` library and returns a JSON payload the frontend can render
as klinecharts overlays (rectangles, polylines, text).

  GET /api/smc/analyze
      ?market=Crypto
      &symbol=BTC/USDT
      &timeframe=4H
      &limit=500
      &swing_length=10            (optional, default 10)
      &features=fvg,ob,bos,swings (optional; default = all)

Each shape carries unix-second timestamps (`start_time` / `end_time`) so the
frontend can map them onto chart bars without re-deriving indices.
"""

from __future__ import annotations

import traceback
from typing import Any, Dict, List, Optional

import pandas as pd
from flask import Blueprint, jsonify, request

from app.services.kline import KlineService
from app.utils.logger import get_logger

logger = get_logger(__name__)

smc_bp = Blueprint("smc", __name__)
_kline_service = KlineService()

_ALL_FEATURES = ("fvg", "ob", "bos", "swings", "liquidity")


def _klines_to_ohlc(klines: List[Dict[str, Any]]) -> pd.DataFrame:
    """Convert KlineService output → OHLC DataFrame indexed by datetime.

    `smartmoneyconcepts` expects: open / high / low / close / volume columns
    and a DatetimeIndex.  We keep the original unix `time` (seconds) on the
    side as the `_ts` column so we can stamp shapes back to timestamps.
    """
    df = pd.DataFrame(klines)
    if df.empty:
        return df
    df["_ts"] = df["time"].astype(int)
    df["datetime"] = pd.to_datetime(df["_ts"], unit="s", utc=True)
    df = df.set_index("datetime")
    return df[["open", "high", "low", "close", "volume", "_ts"]].astype(
        {"open": float, "high": float, "low": float, "close": float, "volume": float}
    )


def _ts_at(df: pd.DataFrame, idx: int) -> Optional[int]:
    """Safe index → unix-second lookup; returns None if idx is out of range/NaN."""
    if idx is None:
        return None
    try:
        i = int(idx)
    except (TypeError, ValueError):
        return None
    if i < 0 or i >= len(df):
        return None
    return int(df["_ts"].iloc[i])


def _shape_fvg(df: pd.DataFrame, fvg_df: pd.DataFrame) -> List[Dict[str, Any]]:
    """smc.fvg() → [{top, bottom, type, start_time, end_time, mitigated}, ...]

    Library columns: FVG (1=bull, -1=bear, NaN=none), Top, Bottom, MitigatedIndex.
    The FVG forms across the 3-bar pattern ending at row i; we treat row i as
    the start.  end_time = mitigated bar timestamp, or None (extend to live).
    """
    out: List[Dict[str, Any]] = []
    last_ts = int(df["_ts"].iloc[-1])
    for i, row in fvg_df.iterrows():
        direction = row.get("FVG")
        if pd.isna(direction):
            continue
        try:
            bar_idx = int(i)
        except (TypeError, ValueError):
            continue
        if bar_idx < 0 or bar_idx >= len(df):
            continue
        mitigated_ts = _ts_at(df, row.get("MitigatedIndex"))
        out.append({
            "type": "bullish" if direction > 0 else "bearish",
            "top": float(row["Top"]),
            "bottom": float(row["Bottom"]),
            "start_time": int(df["_ts"].iloc[bar_idx]),
            "end_time": mitigated_ts if mitigated_ts else last_ts,
            "mitigated": mitigated_ts is not None,
        })
    return out


def _shape_ob(df: pd.DataFrame, ob_df: pd.DataFrame) -> List[Dict[str, Any]]:
    """smc.ob() → list of order blocks.

    Library columns: OB (1/-1), Top, Bottom, OBVolume, MitigatedIndex, Percentage.
    """
    out: List[Dict[str, Any]] = []
    last_ts = int(df["_ts"].iloc[-1])
    for i, row in ob_df.iterrows():
        direction = row.get("OB")
        if pd.isna(direction):
            continue
        try:
            bar_idx = int(i)
        except (TypeError, ValueError):
            continue
        if bar_idx < 0 or bar_idx >= len(df):
            continue
        mitigated_ts = _ts_at(df, row.get("MitigatedIndex"))
        out.append({
            "type": "bullish" if direction > 0 else "bearish",
            "top": float(row["Top"]),
            "bottom": float(row["Bottom"]),
            "start_time": int(df["_ts"].iloc[bar_idx]),
            "end_time": mitigated_ts if mitigated_ts else last_ts,
            "volume": float(row.get("OBVolume") or 0.0),
            "percentage": float(row.get("Percentage") or 0.0),
            "mitigated": mitigated_ts is not None,
        })
    return out


def _shape_bos_choch(df: pd.DataFrame, bc_df: pd.DataFrame) -> List[Dict[str, Any]]:
    """smc.bos_choch() → list of BOS/CHoCH events.

    Library columns: BOS (1/-1/NaN), CHOCH (1/-1/NaN), Level, BrokenIndex.
    The structure forms at row i (where the swing pivot was); the break
    happens at BrokenIndex.  For drawing: horizontal line from i → BrokenIndex
    at price = Level.
    """
    out: List[Dict[str, Any]] = []
    for i, row in bc_df.iterrows():
        bos_dir = row.get("BOS")
        choch_dir = row.get("CHOCH")
        kind = None
        direction = None
        if not pd.isna(bos_dir) and bos_dir != 0:
            kind, direction = "BOS", bos_dir
        elif not pd.isna(choch_dir) and choch_dir != 0:
            kind, direction = "CHoCH", choch_dir
        if kind is None:
            continue
        try:
            bar_idx = int(i)
        except (TypeError, ValueError):
            continue
        if bar_idx < 0 or bar_idx >= len(df):
            continue
        broken_ts = _ts_at(df, row.get("BrokenIndex"))
        if broken_ts is None:
            continue
        out.append({
            "kind": kind,
            "direction": "bullish" if direction > 0 else "bearish",
            "level": float(row["Level"]),
            "start_time": int(df["_ts"].iloc[bar_idx]),
            "break_time": broken_ts,
        })
    return out


def _shape_swings(df: pd.DataFrame, swing_df: pd.DataFrame) -> List[Dict[str, Any]]:
    """smc.swing_highs_lows() → list of pivots.

    Library columns: HighLow (1=high, -1=low, NaN=none), Level.
    """
    out: List[Dict[str, Any]] = []
    for i, row in swing_df.iterrows():
        hl = row.get("HighLow")
        if pd.isna(hl) or hl == 0:
            continue
        try:
            bar_idx = int(i)
        except (TypeError, ValueError):
            continue
        if bar_idx < 0 or bar_idx >= len(df):
            continue
        out.append({
            "type": "high" if hl > 0 else "low",
            "price": float(row["Level"]),
            "time": int(df["_ts"].iloc[bar_idx]),
        })
    return out


def _shape_liquidity(df: pd.DataFrame, liq_df: pd.DataFrame) -> List[Dict[str, Any]]:
    """smc.liquidity() → list of liquidity zones.

    Library columns: Liquidity (1/-1), Level, End, Swept.
    Drawn as horizontal segments between the originating swing and the sweep.
    """
    out: List[Dict[str, Any]] = []
    last_ts = int(df["_ts"].iloc[-1])
    for i, row in liq_df.iterrows():
        side = row.get("Liquidity")
        if pd.isna(side) or side == 0:
            continue
        try:
            bar_idx = int(i)
        except (TypeError, ValueError):
            continue
        if bar_idx < 0 or bar_idx >= len(df):
            continue
        end_ts = _ts_at(df, row.get("End"))
        swept_ts = _ts_at(df, row.get("Swept"))
        out.append({
            "side": "buy_side" if side > 0 else "sell_side",
            "level": float(row["Level"]),
            "start_time": int(df["_ts"].iloc[bar_idx]),
            "end_time": end_ts or last_ts,
            "swept": swept_ts is not None,
            "swept_time": swept_ts,
        })
    return out


@smc_bp.route("/analyze", methods=["GET"])
def analyze():
    """Compute SMC structures for a symbol/timeframe and return drawable shapes."""
    market = request.args.get("market", "Crypto")
    symbol = request.args.get("symbol", "")
    timeframe = request.args.get("timeframe", "4H")
    try:
        limit = max(50, min(int(request.args.get("limit", 500)), 1500))
    except (TypeError, ValueError):
        limit = 500
    try:
        swing_length = max(2, min(int(request.args.get("swing_length", 10)), 50))
    except (TypeError, ValueError):
        swing_length = 10

    raw_features = (request.args.get("features") or "").strip().lower()
    if raw_features:
        features = tuple(f for f in raw_features.split(",") if f in _ALL_FEATURES)
    else:
        features = _ALL_FEATURES

    if not symbol:
        return jsonify({"code": 0, "msg": "Missing symbol parameter", "data": None}), 400

    try:
        from smartmoneyconcepts import smc
    except ImportError as e:
        logger.error("smartmoneyconcepts not installed: %s", e)
        return jsonify({
            "code": 0,
            "msg": "smartmoneyconcepts library not installed. Run: pip install smartmoneyconcepts",
            "data": None,
        }), 500

    try:
        klines = _kline_service.get_kline(market=market, symbol=symbol,
                                          timeframe=timeframe, limit=limit)
        if not klines:
            return jsonify({"code": 0, "msg": "No K-line data", "data": None}), 200

        df = _klines_to_ohlc(klines)
        if len(df) < swing_length * 3:
            return jsonify({
                "code": 0,
                "msg": f"Need at least {swing_length * 3} bars; got {len(df)}",
                "data": None,
            }), 200

        ohlc = df[["open", "high", "low", "close", "volume"]]

        # `swing_highs_lows` is a prerequisite for ob / bos_choch / liquidity.
        swing_df = smc.swing_highs_lows(ohlc, swing_length=swing_length)

        data: Dict[str, Any] = {
            "klines_count": len(df),
            "swing_length": swing_length,
            "first_time": int(df["_ts"].iloc[0]),
            "last_time": int(df["_ts"].iloc[-1]),
        }

        if "fvg" in features:
            try:
                data["fvgs"] = _shape_fvg(df, smc.fvg(ohlc, join_consecutive=False))
            except Exception as e:
                logger.warning("smc.fvg failed: %s", e)
                data["fvgs"] = []

        if "ob" in features:
            try:
                data["order_blocks"] = _shape_ob(
                    df, smc.ob(ohlc, swing_df, close_mitigation=False)
                )
            except Exception as e:
                logger.warning("smc.ob failed: %s", e)
                data["order_blocks"] = []

        if "bos" in features:
            try:
                data["bos"] = _shape_bos_choch(
                    df, smc.bos_choch(ohlc, swing_df, close_break=True)
                )
            except Exception as e:
                logger.warning("smc.bos_choch failed: %s", e)
                data["bos"] = []

        if "swings" in features:
            data["swings"] = _shape_swings(df, swing_df)

        if "liquidity" in features:
            try:
                data["liquidity"] = _shape_liquidity(
                    df, smc.liquidity(ohlc, swing_df, range_percent=0.01)
                )
            except Exception as e:
                logger.warning("smc.liquidity failed: %s", e)
                data["liquidity"] = []

        return jsonify({"code": 1, "msg": "success", "data": data})

    except Exception as e:
        logger.error("SMC analyze failed: %s", e)
        logger.error(traceback.format_exc())
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500
