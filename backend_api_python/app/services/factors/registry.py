"""Built-in technical and point-in-time fundamental factors."""

from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Mapping, Optional

import numpy as np
import pandas as pd


class FactorError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class FactorDefinition:
    factor_id: str
    version: str
    name_i18n_key: str
    description_i18n_key: str
    category: str
    factor_type: str
    required_fields: tuple[str, ...]
    default_params: dict[str, Any] = field(default_factory=dict)
    parameter_schema: dict[str, dict[str, Any]] = field(default_factory=dict)
    direction_hint: str = "neutral"
    supported_contexts: tuple[str, ...] = ("portfolio",)
    default_warmup_bars: int = 0
    compute: Callable[[pd.DataFrame, Mapping[str, Any]], float] = field(repr=False, compare=False, default=None)

    def metadata(self) -> dict:
        value = asdict(self)
        value.pop("compute", None)
        return value


def _technical_warmup(factor_id: str, params: Mapping[str, Any]) -> int:
    period = int(params.get("period") or 1)
    if factor_id in {"momentum", "roc", "rsi", "downside_volatility"}:
        return period + 1
    if factor_id == "ema_slope":
        return period + int(params.get("slope_period") or 1)
    if factor_id == "macd":
        return int(params.get("slow_period") or 26) + int(params.get("signal_period") or 9)
    if factor_id == "stochastic":
        return period + int(params.get("smooth_k") or 1) + int(params.get("smooth_d") or 1) - 2
    if factor_id == "trix":
        return period * 3 + 1
    if factor_id == "dema":
        return period * 2
    if factor_id == "tema":
        return period * 3
    if factor_id == "hma":
        return period + int(math.sqrt(period))
    if factor_id in {"cmo", "efficiency_ratio", "kama", "ulcer_index", "choppiness", "vortex"}:
        return period + 1
    if factor_id in {"ppo", "awesome_oscillator"}:
        return int(params.get("slow_period") or period)
    if factor_id == "ultimate_oscillator":
        return int(params.get("slow_period") or 28) + 1
    if factor_id == "tsi":
        return int(params.get("slow_period") or 25) + int(params.get("fast_period") or 13) + 1
    if factor_id == "adx":
        return period * 2
    if factor_id == "chaikin_oscillator":
        return int(params.get("slow_period") or 10)
    if factor_id in {"obv", "ad_line"}:
        return period + 1
    if factor_id == "smc_ifvg":
        # No pivots involved: a gap needs three bars and the inversion needs
        # somewhere to happen, so the scan window is the whole requirement.
        return max(4, int(params.get("lookback") or 60)) + 3
    if factor_id in {"smc_structure", "smc_fvg", "smc_sweep", "smc_ob", "smc_ote"}:
        # A pivot needs swing_length bars on each side, plus a bar for the
        # break to land on. Below this the structure is not yet defined.
        return int(params.get("swing_length") or 10) * 2 + 2
    return max(1, period)


def _technical(
    factor_id: str,
    category: str,
    fields: tuple[str, ...],
    params: dict,
    direction: str,
    compute: Callable,
) -> FactorDefinition:
    return FactorDefinition(
        factor_id=factor_id,
        version="1.0.0",
        name_i18n_key=f"factor.{factor_id}.name",
        description_i18n_key=f"factor.{factor_id}.description",
        category=category,
        factor_type="technical",
        required_fields=fields,
        default_params=params,
        parameter_schema=_parameter_schema(factor_id, params),
        direction_hint=direction,
        supported_contexts=("cta", "portfolio"),
        default_warmup_bars=_technical_warmup(factor_id, params),
        compute=compute,
    )


_OUTPUT_OPTIONS = {
    "ad_line": ("value", "slope"),
    "adx": ("adx", "plus_di", "minus_di"),
    "aroon": ("up", "down", "oscillator"),
    "bollinger_bands": ("upper", "middle", "lower", "bandwidth", "position"),
    "donchian_channels": ("upper", "middle", "lower", "position"),
    "elder_ray": ("bull", "bear"),
    "kdj": ("k", "d", "j"),
    "keltner_channels": ("upper", "middle", "lower", "position"),
    "macd": ("line", "signal", "histogram"),
    "obv": ("value", "slope"),
    "smc_fvg": ("side", "top", "bottom", "distance", "stop", "age"),
    "smc_ifvg": ("side", "top", "bottom", "stop", "distance", "age"),
    "smc_ob": ("side", "top", "bottom", "stop", "distance", "age"),
    "smc_ote": ("position", "retrace", "in_ote", "discount", "premium",
                "ote_near", "ote_far", "leg_low", "leg_high"),
    "smc_structure": ("trend", "bos", "choch", "swing_high", "swing_low",
                      "distance_high", "distance_low"),
    "smc_sweep": ("side", "level", "extreme", "age"),
    "stochastic": ("k", "d"),
    "supertrend": ("direction", "line"),
    "vwap": ("value", "distance"),
    "vortex": ("plus", "minus", "oscillator"),
}


def _parameter_schema(factor_id: str, params: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    schema: dict[str, dict[str, Any]] = {}
    for key, value in params.items():
        if key == "output" and factor_id in _OUTPUT_OPTIONS:
            schema[key] = {"type": "enum", "options": list(_OUTPUT_OPTIONS[factor_id])}
        elif isinstance(value, bool):
            schema[key] = {"type": "boolean"}
        elif isinstance(value, int):
            schema[key] = {"type": "integer", "minimum": 1, "maximum": 5000, "step": 1}
        elif isinstance(value, float):
            schema[key] = {"type": "number", "minimum": 0.000001, "step": 0.1}
        else:
            schema[key] = {"type": "string"}
    return schema


def _fundamental(
    factor_id: str,
    category: str,
    fields: tuple[str, ...],
    direction: str,
    compute: Callable,
) -> FactorDefinition:
    return FactorDefinition(
        factor_id=factor_id,
        version="1.0.0",
        name_i18n_key=f"factor.{factor_id}.name",
        description_i18n_key=f"factor.{factor_id}.description",
        category=category,
        factor_type="fundamental",
        required_fields=fields,
        default_params={},
        direction_hint=direction,
        supported_contexts=("portfolio",),
        compute=compute,
    )


_FACTORS = {
    definition.factor_id: definition
    for definition in (
        _technical("sma", "trend", ("close",), {"period": 20}, "neutral", lambda f, p: _sma(f, p)),
        _technical("ema", "trend", ("close",), {"period": 20}, "neutral", lambda f, p: _ema(f, p)),
        _technical("sma_distance", "trend", ("close",), {"period": 20}, "higher_is_bullish", lambda f, p: _ma_distance(f, p, exponential=False)),
        _technical("ema_distance", "trend", ("close",), {"period": 20}, "higher_is_bullish", lambda f, p: _ma_distance(f, p, exponential=True)),
        _technical("momentum", "momentum", ("close",), {"period": 60}, "higher_is_bullish", lambda f, p: _return(f, p)),
        _technical("roc", "momentum", ("close",), {"period": 12}, "higher_is_bullish", lambda f, p: _return(f, p)),
        _technical("rsi", "momentum", ("close",), {"period": 14}, "neutral", lambda f, p: _rsi(f, p)),
        _technical("macd", "trend", ("close",), {"fast_period": 12, "slow_period": 26, "signal_period": 9, "output": "histogram"}, "higher_is_bullish", lambda f, p: _macd(f, p)),
        _technical("bollinger_bands", "volatility", ("close",), {"period": 20, "stddev": 2.0, "output": "position"}, "neutral", lambda f, p: _bollinger(f, p)),
        _technical("stochastic", "momentum", ("high", "low", "close"), {"period": 14, "smooth_k": 3, "smooth_d": 3, "output": "k"}, "neutral", lambda f, p: _stochastic(f, p)),
        _technical("kdj", "momentum", ("high", "low", "close"), {"period": 9, "k_period": 3, "d_period": 3, "output": "j"}, "neutral", lambda f, p: _kdj(f, p)),
        _technical("cci", "momentum", ("high", "low", "close"), {"period": 20}, "neutral", lambda f, p: _cci(f, p)),
        _technical("williams_r", "momentum", ("high", "low", "close"), {"period": 14}, "neutral", lambda f, p: _williams_r(f, p)),
        _technical("mfi", "volume", ("high", "low", "close", "volume"), {"period": 14}, "neutral", lambda f, p: _mfi(f, p)),
        _technical("adx", "trend", ("high", "low", "close"), {"period": 14, "output": "adx"}, "neutral", lambda f, p: _adx(f, p)),
        _technical("aroon", "trend", ("high", "low"), {"period": 25, "output": "oscillator"}, "higher_is_bullish", lambda f, p: _aroon(f, p)),
        _technical("trix", "trend", ("close",), {"period": 15}, "higher_is_bullish", lambda f, p: _trix(f, p)),
        _technical("supertrend", "trend", ("high", "low", "close"), {"period": 10, "multiplier": 3.0, "output": "direction"}, "higher_is_bullish", lambda f, p: _supertrend(f, p)),
        _technical("atr", "volatility", ("high", "low", "close"), {"period": 14}, "neutral", lambda f, p: _atr(f, p)),
        _technical("realized_volatility", "risk", ("close",), {"period": 20}, "lower_is_bullish", lambda f, p: _realized_vol(f, p)),
        _technical("ema_slope", "trend", ("close",), {"period": 20, "slope_period": 5}, "higher_is_bullish", lambda f, p: _ema_slope(f, p)),
        _technical("atr_pct", "risk", ("high", "low", "close"), {"period": 14}, "lower_is_bullish", lambda f, p: _atr_pct(f, p)),
        _technical("downside_volatility", "risk", ("close",), {"period": 20}, "lower_is_bullish", lambda f, p: _downside_volatility(f, p)),
        _technical("max_drawdown", "risk", ("close",), {"period": 60}, "higher_is_bullish", lambda f, p: _max_drawdown(f, p)),
        _technical("donchian_channels", "volatility", ("high", "low", "close"), {"period": 20, "output": "position"}, "neutral", lambda f, p: _donchian(f, p)),
        _technical("keltner_channels", "volatility", ("high", "low", "close"), {"period": 20, "atr_period": 10, "multiplier": 2.0, "output": "position"}, "neutral", lambda f, p: _keltner(f, p)),
        _technical("volume_zscore", "liquidity", ("volume",), {"period": 20}, "neutral", lambda f, p: _zscore_last(f["volume"], p)),
        _technical("volume_ratio", "liquidity", ("volume",), {"period": 20}, "higher_is_bullish", lambda f, p: _volume_ratio(f, p)),
        _technical("mean_reversion_zscore", "reversal", ("close",), {"period": 20}, "lower_is_bullish", lambda f, p: _zscore_last(f["close"], p)),
        _technical("turnover_proxy", "liquidity", ("close", "volume"), {"period": 20}, "higher_is_bullish", lambda f, p: _turnover(f, p)),
        _technical("obv", "volume", ("close", "volume"), {"period": 20, "output": "slope"}, "higher_is_bullish", lambda f, p: _obv(f, p)),
        _technical("ad_line", "volume", ("high", "low", "close", "volume"), {"period": 20, "output": "slope"}, "higher_is_bullish", lambda f, p: _ad_line(f, p)),
        _technical("chaikin_oscillator", "volume", ("high", "low", "close", "volume"), {"fast_period": 3, "slow_period": 10}, "higher_is_bullish", lambda f, p: _chaikin(f, p)),
        _technical("vwap", "volume", ("high", "low", "close", "volume"), {"period": 20, "output": "distance"}, "higher_is_bullish", lambda f, p: _vwap(f, p)),
        _technical("cmf", "volume", ("high", "low", "close", "volume"), {"period": 20}, "higher_is_bullish", lambda f, p: _cmf(f, p)),
        _technical("dema", "trend", ("close",), {"period": 20}, "neutral", lambda f, p: _dema(f, p)),
        _technical("tema", "trend", ("close",), {"period": 20}, "neutral", lambda f, p: _tema(f, p)),
        _technical("zlema", "trend", ("close",), {"period": 20}, "neutral", lambda f, p: _zlema(f, p)),
        _technical("hma", "trend", ("close",), {"period": 20}, "neutral", lambda f, p: _hma(f, p)),
        _technical("kama", "trend", ("close",), {"period": 10, "fast_period": 2, "slow_period": 30}, "neutral", lambda f, p: _kama(f, p)),
        _technical("ppo", "momentum", ("close",), {"fast_period": 12, "slow_period": 26}, "higher_is_bullish", lambda f, p: _ppo(f, p)),
        _technical("cmo", "momentum", ("close",), {"period": 14}, "neutral", lambda f, p: _cmo(f, p)),
        _technical("awesome_oscillator", "momentum", ("high", "low"), {"fast_period": 5, "slow_period": 34}, "higher_is_bullish", lambda f, p: _awesome_oscillator(f, p)),
        _technical("ultimate_oscillator", "momentum", ("high", "low", "close"), {"fast_period": 7, "medium_period": 14, "slow_period": 28}, "neutral", lambda f, p: _ultimate_oscillator(f, p)),
        _technical("tsi", "momentum", ("close",), {"slow_period": 25, "fast_period": 13}, "neutral", lambda f, p: _tsi(f, p)),
        _technical("vortex", "trend", ("high", "low", "close"), {"period": 14, "output": "oscillator"}, "higher_is_bullish", lambda f, p: _vortex(f, p)),
        _technical("choppiness", "trend", ("high", "low", "close"), {"period": 14}, "lower_is_bullish", lambda f, p: _choppiness(f, p)),
        _technical("efficiency_ratio", "trend", ("close",), {"period": 10}, "higher_is_bullish", lambda f, p: _efficiency_ratio(f, p)),
        _technical("elder_ray", "momentum", ("high", "low", "close"), {"period": 13, "output": "bull"}, "neutral", lambda f, p: _elder_ray(f, p)),
        _technical("force_index", "volume", ("close", "volume"), {"period": 13}, "higher_is_bullish", lambda f, p: _force_index(f, p)),
        _technical("ulcer_index", "risk", ("close",), {"period": 14}, "lower_is_bullish", lambda f, p: _ulcer_index(f, p)),
        _technical("parkinson_volatility", "risk", ("high", "low"), {"period": 20}, "lower_is_bullish", lambda f, p: _parkinson_volatility(f, p)),
        _technical("garman_klass_volatility", "risk", ("open", "high", "low", "close"), {"period": 20}, "lower_is_bullish", lambda f, p: _garman_klass_volatility(f, p)),
        _technical("amihud_illiquidity", "liquidity", ("close", "volume"), {"period": 20}, "lower_is_bullish", lambda f, p: _amihud_illiquidity(f, p)),
        _technical("smc_structure", "trend", ("high", "low", "close"), {"swing_length": 10, "output": "trend"}, "higher_is_bullish", lambda f, p: _smc_structure(f, p)),
        _technical("smc_fvg", "trend", ("high", "low", "close"), {"output": "side"}, "higher_is_bullish", lambda f, p: _smc_fvg(f, p)),
        _technical("smc_ifvg", "trend", ("high", "low", "close"), {"lookback": 60, "output": "side"}, "higher_is_bullish", lambda f, p: _smc_ifvg(f, p)),
        _technical("smc_sweep", "trend", ("high", "low", "close"), {"swing_length": 10, "lookback": 60, "output": "side"}, "higher_is_bullish", lambda f, p: _smc_sweep(f, p)),
        _technical("smc_ob", "trend", ("open", "high", "low", "close"), {"swing_length": 10, "search": 30, "output": "side"}, "higher_is_bullish", lambda f, p: _smc_ob(f, p)),
        _technical("smc_ote", "trend", ("high", "low", "close"), {"swing_length": 10, "ote_from": 0.62, "ote_to": 0.79, "output": "in_ote"}, "neutral", lambda f, p: _smc_ote(f, p)),
        _fundamental("market_cap", "size", ("market_cap",), "lower_is_bullish", lambda f, p: _last_value(f, "market_cap")),
        _fundamental("earnings_yield", "valuation", ("net_income", "market_cap"), "higher_is_bullish", lambda f, p: _ratio_last(f, "net_income", "market_cap")),
        _fundamental("book_to_price", "valuation", ("book_value", "market_cap"), "higher_is_bullish", lambda f, p: _ratio_last(f, "book_value", "market_cap")),
        _fundamental("return_on_equity", "quality", ("net_income", "shareholder_equity"), "higher_is_bullish", lambda f, p: _ratio_last(f, "net_income", "shareholder_equity")),
        _fundamental("revenue_growth", "growth", ("revenue",), "higher_is_bullish", lambda f, p: _growth_last(f, "revenue")),
        _fundamental("debt_to_equity", "quality", ("total_debt", "shareholder_equity"), "lower_is_bullish", lambda f, p: _ratio_last(f, "total_debt", "shareholder_equity")),
        _fundamental("free_cash_flow_yield", "cashflow", ("free_cash_flow", "market_cap"), "higher_is_bullish", lambda f, p: _ratio_last(f, "free_cash_flow", "market_cap")),
    )
}


def list_factors(*, category: str = "", factor_type: str = "") -> list[dict]:
    values = []
    for definition in _FACTORS.values():
        if category and definition.category != category:
            continue
        if factor_type and definition.factor_type != factor_type:
            continue
        values.append(definition.metadata())
    return sorted(values, key=lambda item: (item["factor_type"], item["category"], item["factor_id"]))


def get_factor(factor_id: str) -> FactorDefinition:
    definition = _FACTORS.get(str(factor_id or "").strip())
    if definition is None:
        raise FactorError("factor.notFound")
    return definition


def compute_factor(factor_id: str, frame: pd.DataFrame, params: Optional[Mapping[str, Any]] = None) -> float:
    definition = get_factor(factor_id)
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise FactorError("factor.noData")
    missing = set(definition.required_fields) - set(frame.columns)
    if missing:
        raise FactorError("factor.missingFields")
    merged = {**definition.default_params, **dict(params or {})}
    try:
        value = float(definition.compute(frame, merged))
    except FactorError:
        raise
    except Exception as exc:
        raise FactorError("factor.computeFailed") from exc
    return value if math.isfinite(value) else float("nan")


def compute_panel_factor(
    factor_id: str,
    panel: Mapping[str, pd.DataFrame],
    params: Optional[Mapping[str, Any]] = None,
) -> dict[str, float]:
    if not isinstance(panel, Mapping):
        raise FactorError("factor.panelMustBeMapping")
    output = {}
    for symbol, frame in panel.items():
        try:
            value = compute_factor(factor_id, frame, params)
        except FactorError as exc:
            if exc.code in {"factor.noData", "factor.missingFields", "factor.insufficientHistory"}:
                continue
            raise
        if math.isfinite(value):
            output[str(symbol)] = value
    return output


def _period(params: Mapping[str, Any], key: str = "period", minimum: int = 2) -> int:
    try:
        value = int(params.get(key) or minimum)
    except (TypeError, ValueError) as exc:
        raise FactorError("factor.invalidParameter") from exc
    if value < minimum or value > 5000:
        raise FactorError("factor.invalidParameter")
    return value


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()


def _return(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    values = _numeric(frame["close"])
    if len(values) <= period:
        raise FactorError("factor.insufficientHistory")
    return float(values.iloc[-1] / values.iloc[-period - 1] - 1.0)


def _realized_vol(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    returns = _numeric(frame["close"]).pct_change().dropna()
    if len(returns) < period:
        raise FactorError("factor.insufficientHistory")
    return float(returns.iloc[-period:].std(ddof=1) * math.sqrt(252))


def _ema_slope(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    slope_period = _period(params, "slope_period", minimum=1)
    values = _require(frame["close"], period + slope_period)
    ema = _ema_values(values, period)
    base = float(ema.iloc[-slope_period - 1])
    return float(ema.iloc[-1] / base - 1.0) if base else float("nan")


def _atr_pct(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    last_close = float(pd.to_numeric(frame["close"], errors="coerce").iloc[-1])
    return float(_atr(frame, params) / last_close) if last_close else float("nan")


def _zscore_last(series: pd.Series, params: Mapping[str, Any]) -> float:
    period = _period(params)
    values = _numeric(series)
    if len(values) < period:
        raise FactorError("factor.insufficientHistory")
    window = values.iloc[-period:]
    std = float(window.std(ddof=1))
    return float((window.iloc[-1] - window.mean()) / std) if std > 0 else 0.0


def _turnover(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    values = _numeric(frame["close"] * frame["volume"])
    if len(values) < period:
        raise FactorError("factor.insufficientHistory")
    return float(values.iloc[-period:].mean())


def _ratio_last(frame: pd.DataFrame, numerator: str, denominator: str) -> float:
    numerator_value = _last_value(frame, numerator)
    denominator_value = _last_value(frame, denominator)
    return numerator_value / denominator_value if denominator_value else float("nan")


def _growth_last(frame: pd.DataFrame, field: str) -> float:
    values = _numeric(frame[field])
    if len(values) < 2:
        raise FactorError("factor.insufficientHistory")
    previous = float(values.iloc[-2])
    return float(values.iloc[-1] / previous - 1.0) if previous else float("nan")


def _last_value(frame: pd.DataFrame, field: str) -> float:
    values = _numeric(frame[field])
    if values.empty:
        raise FactorError("factor.insufficientHistory")
    return float(values.iloc[-1])


def _positive_float(params: Mapping[str, Any], key: str, default: float) -> float:
    try:
        value = float(params.get(key, default))
    except (TypeError, ValueError) as exc:
        raise FactorError("factor.invalidParameter") from exc
    if not math.isfinite(value) or value <= 0:
        raise FactorError("factor.invalidParameter")
    return value


def _choice(params: Mapping[str, Any], key: str, allowed: set[str], default: str) -> str:
    value = str(params.get(key, default) or default).strip().lower()
    if value not in allowed:
        raise FactorError("factor.invalidParameter")
    return value


def _require(values: pd.Series, count: int) -> pd.Series:
    clean = _numeric(values)
    if len(clean) < count:
        raise FactorError("factor.insufficientHistory")
    return clean


def _ema_values(values: pd.Series, period: int) -> pd.Series:
    clean = _numeric(values).reset_index(drop=True)
    if len(clean) < period:
        raise FactorError("factor.insufficientHistory")
    output = pd.Series(np.nan, index=clean.index, dtype=float)
    output.iloc[period - 1] = float(clean.iloc[:period].mean())
    multiplier = 2.0 / (period + 1.0)
    for index in range(period, len(clean)):
        output.iloc[index] = (float(clean.iloc[index]) - float(output.iloc[index - 1])) * multiplier + float(output.iloc[index - 1])
    return output


def _sma(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    values = _require(frame["close"], period)
    return float(values.iloc[-period:].mean())


def _ema(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    return float(_ema_values(frame["close"], period).iloc[-1])


def _ma_distance(frame: pd.DataFrame, params: Mapping[str, Any], *, exponential: bool) -> float:
    values = _numeric(frame["close"])
    average = _ema(frame, params) if exponential else _sma(frame, params)
    latest = float(values.iloc[-1])
    return latest / average - 1.0 if average else float("nan")


def _rsi(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    values = _require(frame["close"], period + 1)
    deltas = values.diff().dropna()
    gains = deltas.clip(lower=0.0)
    losses = (-deltas.clip(upper=0.0))
    avg_gain = float(gains.iloc[:period].mean())
    avg_loss = float(losses.iloc[:period].mean())
    for index in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + float(gains.iloc[index])) / period
        avg_loss = (avg_loss * (period - 1) + float(losses.iloc[index])) / period
    if avg_loss <= 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def _macd(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    fast = _period(params, "fast_period", minimum=2)
    slow = _period(params, "slow_period", minimum=2)
    signal = _period(params, "signal_period", minimum=2)
    if fast >= slow:
        raise FactorError("factor.invalidParameter")
    values = _require(frame["close"], slow + signal - 1)
    fast_values = _ema_values(values, fast)
    slow_values = _ema_values(values, slow)
    line = (fast_values - slow_values).dropna().reset_index(drop=True)
    signal_values = _ema_values(line, signal)
    macd_value = float(line.iloc[-1])
    signal_value = float(signal_values.iloc[-1])
    output = _choice(params, "output", {"line", "signal", "histogram"}, "histogram")
    if output == "line":
        return macd_value
    if output == "signal":
        return signal_value
    return macd_value - signal_value


def _bollinger(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    multiplier = _positive_float(params, "stddev", 2.0)
    values = _require(frame["close"], period)
    window = values.iloc[-period:]
    middle = float(window.mean())
    std = float(window.std(ddof=0))
    upper = middle + multiplier * std
    lower = middle - multiplier * std
    output = _choice(params, "output", {"upper", "middle", "lower", "bandwidth", "position"}, "position")
    if output == "upper":
        return upper
    if output == "middle":
        return middle
    if output == "lower":
        return lower
    if output == "bandwidth":
        return (upper - lower) / middle if middle else float("nan")
    return (float(values.iloc[-1]) - lower) / (upper - lower) if upper > lower else 0.5


def _true_range(frame: pd.DataFrame) -> pd.Series:
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    close = pd.to_numeric(frame["close"], errors="coerce")
    return pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1).dropna().reset_index(drop=True)


def _wilder_last(values: pd.Series, period: int) -> float:
    clean = _require(values, period)
    result = float(clean.iloc[:period].mean())
    for value in clean.iloc[period:]:
        result = (result * (period - 1) + float(value)) / period
    return result


def _atr(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    return _wilder_last(_true_range(frame), _period(params))


def _stochastic(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    smooth_k = _period(params, "smooth_k", minimum=1)
    smooth_d = _period(params, "smooth_d", minimum=1)
    required = period + smooth_k + smooth_d - 2
    if len(frame) < required:
        raise FactorError("factor.insufficientHistory")
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    close = pd.to_numeric(frame["close"], errors="coerce")
    highest = high.rolling(period).max()
    lowest = low.rolling(period).min()
    raw_k = 100.0 * (close - lowest) / (highest - lowest).replace(0, np.nan)
    k = raw_k.rolling(smooth_k).mean()
    d = k.rolling(smooth_d).mean()
    output = _choice(params, "output", {"k", "d"}, "k")
    value = d.iloc[-1] if output == "d" else k.iloc[-1]
    if not math.isfinite(float(value)):
        raise FactorError("factor.insufficientHistory")
    return float(value)


def _kdj(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    k_period = _period(params, "k_period", minimum=1)
    d_period = _period(params, "d_period", minimum=1)
    if len(frame) < period:
        raise FactorError("factor.insufficientHistory")
    high = pd.to_numeric(frame["high"], errors="coerce").reset_index(drop=True)
    low = pd.to_numeric(frame["low"], errors="coerce").reset_index(drop=True)
    close = pd.to_numeric(frame["close"], errors="coerce").reset_index(drop=True)
    k_value = 50.0
    d_value = 50.0
    for index in range(period - 1, len(frame)):
        highest = float(high.iloc[index - period + 1:index + 1].max())
        lowest = float(low.iloc[index - period + 1:index + 1].min())
        rsv = 50.0 if highest <= lowest else (float(close.iloc[index]) - lowest) / (highest - lowest) * 100.0
        k_value = ((k_period - 1) * k_value + rsv) / k_period
        d_value = ((d_period - 1) * d_value + k_value) / d_period
    output = _choice(params, "output", {"k", "d", "j"}, "j")
    return {"k": k_value, "d": d_value, "j": 3.0 * k_value - 2.0 * d_value}[output]


def _cci(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    typical = (pd.to_numeric(frame["high"], errors="coerce") + pd.to_numeric(frame["low"], errors="coerce") + pd.to_numeric(frame["close"], errors="coerce")) / 3.0
    values = _require(typical, period).iloc[-period:]
    mean = float(values.mean())
    deviation = float((values - mean).abs().mean())
    return (float(values.iloc[-1]) - mean) / (0.015 * deviation) if deviation > 0 else 0.0


def _williams_r(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    if len(frame) < period:
        raise FactorError("factor.insufficientHistory")
    high = float(pd.to_numeric(frame["high"], errors="coerce").iloc[-period:].max())
    low = float(pd.to_numeric(frame["low"], errors="coerce").iloc[-period:].min())
    close = float(pd.to_numeric(frame["close"], errors="coerce").iloc[-1])
    return -50.0 if high <= low else -100.0 * (high - close) / (high - low)


def _mfi(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    if len(frame) < period + 1:
        raise FactorError("factor.insufficientHistory")
    typical = (pd.to_numeric(frame["high"], errors="coerce") + pd.to_numeric(frame["low"], errors="coerce") + pd.to_numeric(frame["close"], errors="coerce")) / 3.0
    flow = typical * pd.to_numeric(frame["volume"], errors="coerce").fillna(0.0)
    direction = typical.diff()
    positive = flow.where(direction > 0, 0.0).iloc[-period:].sum()
    negative = flow.where(direction < 0, 0.0).iloc[-period:].sum()
    if negative <= 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + float(positive / negative))


def _adx_components(frame: pd.DataFrame, period: int) -> tuple[float, float, float]:
    if len(frame) < period + 1:
        raise FactorError("factor.insufficientHistory")
    high = pd.to_numeric(frame["high"], errors="coerce").reset_index(drop=True)
    low = pd.to_numeric(frame["low"], errors="coerce").reset_index(drop=True)
    close = pd.to_numeric(frame["close"], errors="coerce").reset_index(drop=True)
    tr = []
    plus_dm = []
    minus_dm = []
    for index in range(1, len(frame)):
        tr.append(max(float(high.iloc[index] - low.iloc[index]), abs(float(high.iloc[index] - close.iloc[index - 1])), abs(float(low.iloc[index] - close.iloc[index - 1]))))
        up = float(high.iloc[index] - high.iloc[index - 1])
        down = float(low.iloc[index - 1] - low.iloc[index])
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
    if len(tr) < period:
        raise FactorError("factor.insufficientHistory")
    smooth_tr = sum(tr[:period])
    smooth_plus = sum(plus_dm[:period])
    smooth_minus = sum(minus_dm[:period])
    dx_values = []
    for index in range(period - 1, len(tr)):
        if index >= period:
            smooth_tr = smooth_tr - smooth_tr / period + tr[index]
            smooth_plus = smooth_plus - smooth_plus / period + plus_dm[index]
            smooth_minus = smooth_minus - smooth_minus / period + minus_dm[index]
        plus_di = 100.0 * smooth_plus / smooth_tr if smooth_tr else 0.0
        minus_di = 100.0 * smooth_minus / smooth_tr if smooth_tr else 0.0
        total = plus_di + minus_di
        dx_values.append(100.0 * abs(plus_di - minus_di) / total if total else 0.0)
    adx_value = dx_values[0]
    for value in dx_values[1:]:
        adx_value = (adx_value * (period - 1) + value) / period
    return adx_value, plus_di, minus_di


def _adx(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    values = _adx_components(frame, _period(params))
    output = _choice(params, "output", {"adx", "plus_di", "minus_di"}, "adx")
    return values[{"adx": 0, "plus_di": 1, "minus_di": 2}[output]]


def _aroon(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    if len(frame) < period:
        raise FactorError("factor.insufficientHistory")
    high = pd.to_numeric(frame["high"], errors="coerce").iloc[-period:].to_numpy()
    low = pd.to_numeric(frame["low"], errors="coerce").iloc[-period:].to_numpy()
    up = 100.0 * (int(np.argmax(high)) + 1) / period
    down = 100.0 * (int(np.argmin(low)) + 1) / period
    output = _choice(params, "output", {"up", "down", "oscillator"}, "oscillator")
    return {"up": up, "down": down, "oscillator": up - down}[output]


def _trix(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    values = _require(frame["close"], period * 3 + 1)
    first = _ema_values(values, period).dropna().reset_index(drop=True)
    second = _ema_values(first, period).dropna().reset_index(drop=True)
    third = _ema_values(second, period).dropna().reset_index(drop=True)
    if len(third) < 2 or float(third.iloc[-2]) == 0:
        raise FactorError("factor.insufficientHistory")
    return float(third.iloc[-1] / third.iloc[-2] - 1.0)


def _supertrend(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    multiplier = _positive_float(params, "multiplier", 3.0)
    if len(frame) < period + 1:
        raise FactorError("factor.insufficientHistory")
    high = pd.to_numeric(frame["high"], errors="coerce").reset_index(drop=True)
    low = pd.to_numeric(frame["low"], errors="coerce").reset_index(drop=True)
    close = pd.to_numeric(frame["close"], errors="coerce").reset_index(drop=True)
    tr = _true_range(frame)
    atr_values = pd.Series(np.nan, index=range(len(frame)), dtype=float)
    atr_values.iloc[period - 1] = float(tr.iloc[:period].mean())
    for index in range(period, len(frame)):
        atr_values.iloc[index] = (float(atr_values.iloc[index - 1]) * (period - 1) + float(tr.iloc[index])) / period
    direction = 1
    final_upper = final_lower = float("nan")
    line = float("nan")
    for index in range(period - 1, len(frame)):
        midpoint = (float(high.iloc[index]) + float(low.iloc[index])) / 2.0
        basic_upper = midpoint + multiplier * float(atr_values.iloc[index])
        basic_lower = midpoint - multiplier * float(atr_values.iloc[index])
        if index == period - 1:
            final_upper, final_lower = basic_upper, basic_lower
        else:
            final_upper = basic_upper if basic_upper < final_upper or float(close.iloc[index - 1]) > final_upper else final_upper
            final_lower = basic_lower if basic_lower > final_lower or float(close.iloc[index - 1]) < final_lower else final_lower
            if direction < 0 and float(close.iloc[index]) > final_upper:
                direction = 1
            elif direction > 0 and float(close.iloc[index]) < final_lower:
                direction = -1
        line = final_lower if direction > 0 else final_upper
    output = _choice(params, "output", {"direction", "line"}, "direction")
    return float(direction if output == "direction" else line)


def _downside_volatility(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    returns = _require(frame["close"], period + 1).pct_change().dropna().iloc[-period:]
    downside = returns.where(returns < 0, 0.0)
    return float(np.sqrt(np.mean(np.square(downside))) * math.sqrt(252))


def _max_drawdown(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    values = _require(frame["close"], period).iloc[-period:]
    drawdown = values / values.cummax() - 1.0
    return float(drawdown.min())


def _donchian(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    if len(frame) < period:
        raise FactorError("factor.insufficientHistory")
    upper = float(pd.to_numeric(frame["high"], errors="coerce").iloc[-period:].max())
    lower = float(pd.to_numeric(frame["low"], errors="coerce").iloc[-period:].min())
    middle = (upper + lower) / 2.0
    output = _choice(params, "output", {"upper", "middle", "lower", "position"}, "position")
    if output == "upper": return upper
    if output == "middle": return middle
    if output == "lower": return lower
    close = float(pd.to_numeric(frame["close"], errors="coerce").iloc[-1])
    return (close - lower) / (upper - lower) if upper > lower else 0.5


def _keltner(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    atr_period = _period(params, "atr_period", minimum=2)
    multiplier = _positive_float(params, "multiplier", 2.0)
    middle = _ema(frame, {"period": period})
    atr_value = _atr(frame, {"period": atr_period})
    upper = middle + multiplier * atr_value
    lower = middle - multiplier * atr_value
    output = _choice(params, "output", {"upper", "middle", "lower", "position"}, "position")
    if output == "upper": return upper
    if output == "middle": return middle
    if output == "lower": return lower
    close = float(pd.to_numeric(frame["close"], errors="coerce").iloc[-1])
    return (close - lower) / (upper - lower) if upper > lower else 0.5


def _volume_ratio(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    values = _require(frame["volume"], period)
    average = float(values.iloc[-period:].mean())
    return float(values.iloc[-1]) / average if average else float("nan")


def _normalized_slope(values: pd.Series, volumes: pd.Series, period: int) -> float:
    if len(values) <= period:
        raise FactorError("factor.insufficientHistory")
    denominator = float(_numeric(volumes).iloc[-period:].abs().sum())
    return float(values.iloc[-1] - values.iloc[-period - 1]) / denominator if denominator else 0.0


def _obv_series(frame: pd.DataFrame) -> pd.Series:
    close = pd.to_numeric(frame["close"], errors="coerce").reset_index(drop=True)
    volume = pd.to_numeric(frame["volume"], errors="coerce").fillna(0.0).reset_index(drop=True)
    direction = np.sign(close.diff().fillna(0.0))
    return (direction * volume).cumsum()


def _obv(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    values = _obv_series(frame)
    output = _choice(params, "output", {"value", "slope"}, "slope")
    return float(values.iloc[-1]) if output == "value" else _normalized_slope(values, frame["volume"], period)


def _ad_series(frame: pd.DataFrame) -> pd.Series:
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    close = pd.to_numeric(frame["close"], errors="coerce")
    volume = pd.to_numeric(frame["volume"], errors="coerce").fillna(0.0)
    spread = (high - low).replace(0, np.nan)
    multiplier = ((close - low) - (high - close)) / spread
    return (multiplier.fillna(0.0) * volume).cumsum().reset_index(drop=True)


def _ad_line(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    values = _ad_series(frame)
    output = _choice(params, "output", {"value", "slope"}, "slope")
    return float(values.iloc[-1]) if output == "value" else _normalized_slope(values, frame["volume"], period)


def _chaikin(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    fast = _period(params, "fast_period", minimum=2)
    slow = _period(params, "slow_period", minimum=2)
    if fast >= slow:
        raise FactorError("factor.invalidParameter")
    values = _ad_series(frame)
    fast_value = float(_ema_values(values, fast).iloc[-1])
    slow_value = float(_ema_values(values, slow).iloc[-1])
    scale = float(_numeric(frame["volume"]).iloc[-slow:].mean())
    return (fast_value - slow_value) / scale if scale else 0.0


def _vwap(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    if len(frame) < period:
        raise FactorError("factor.insufficientHistory")
    typical = (pd.to_numeric(frame["high"], errors="coerce") + pd.to_numeric(frame["low"], errors="coerce") + pd.to_numeric(frame["close"], errors="coerce")) / 3.0
    volume = pd.to_numeric(frame["volume"], errors="coerce").fillna(0.0)
    denominator = float(volume.iloc[-period:].sum())
    if denominator <= 0:
        return float("nan")
    value = float((typical.iloc[-period:] * volume.iloc[-period:]).sum() / denominator)
    output = _choice(params, "output", {"value", "distance"}, "distance")
    close = float(pd.to_numeric(frame["close"], errors="coerce").iloc[-1])
    return value if output == "value" else close / value - 1.0


def _cmf(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    if len(frame) < period:
        raise FactorError("factor.insufficientHistory")
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    close = pd.to_numeric(frame["close"], errors="coerce")
    volume = pd.to_numeric(frame["volume"], errors="coerce").fillna(0.0)
    spread = (high - low).replace(0, np.nan)
    money_flow_volume = (((close - low) - (high - close)) / spread).fillna(0.0) * volume
    denominator = float(volume.iloc[-period:].sum())
    return float(money_flow_volume.iloc[-period:].sum() / denominator) if denominator else 0.0


def _dema(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    first = _ema_values(frame["close"], period).dropna().reset_index(drop=True)
    second = _ema_values(first, period).dropna().reset_index(drop=True)
    return 2.0 * float(first.iloc[-1]) - float(second.iloc[-1])


def _tema(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    first = _ema_values(frame["close"], period).dropna().reset_index(drop=True)
    second = _ema_values(first, period).dropna().reset_index(drop=True)
    third = _ema_values(second, period).dropna().reset_index(drop=True)
    return 3.0 * float(first.iloc[-1]) - 3.0 * float(second.iloc[-1]) + float(third.iloc[-1])


def _zlema(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    lag = max(1, (period - 1) // 2)
    close = _require(frame["close"], period + lag)
    adjusted = close + (close - close.shift(lag))
    return float(_ema_values(adjusted.dropna(), period).iloc[-1])


def _wma_values(values: pd.Series, period: int) -> pd.Series:
    clean = _require(values, period).reset_index(drop=True)
    weights = np.arange(1, period + 1, dtype=float)
    return clean.rolling(period).apply(lambda window: float(np.dot(window, weights) / weights.sum()), raw=True)


def _hma(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    half_period = max(1, period // 2)
    root_period = max(1, int(math.sqrt(period)))
    values = _require(frame["close"], period + root_period)
    half = _wma_values(values, half_period)
    full = _wma_values(values, period)
    raw = (2.0 * half - full).dropna()
    return float(_wma_values(raw, root_period).iloc[-1])


def _kama(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    fast = _period(params, "fast_period", minimum=1)
    slow = _period(params, "slow_period", minimum=2)
    if fast >= slow:
        raise FactorError("factor.invalidParameter")
    values = _require(frame["close"], period + 1).reset_index(drop=True)
    kama = float(values.iloc[:period].mean())
    fast_constant = 2.0 / (fast + 1.0)
    slow_constant = 2.0 / (slow + 1.0)
    for index in range(period, len(values)):
        change = abs(float(values.iloc[index] - values.iloc[index - period]))
        volatility = float(values.iloc[index - period:index + 1].diff().abs().sum())
        efficiency = change / volatility if volatility else 0.0
        smoothing = (efficiency * (fast_constant - slow_constant) + slow_constant) ** 2
        kama += smoothing * (float(values.iloc[index]) - kama)
    return kama


def _ppo(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    fast = _period(params, "fast_period", minimum=2)
    slow = _period(params, "slow_period", minimum=2)
    if fast >= slow:
        raise FactorError("factor.invalidParameter")
    fast_value = float(_ema_values(frame["close"], fast).iloc[-1])
    slow_value = float(_ema_values(frame["close"], slow).iloc[-1])
    return 100.0 * (fast_value - slow_value) / slow_value if slow_value else float("nan")


def _cmo(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    changes = _require(frame["close"], period + 1).diff().dropna().iloc[-period:]
    gains = float(changes.clip(lower=0.0).sum())
    losses = float((-changes.clip(upper=0.0)).sum())
    total = gains + losses
    return 100.0 * (gains - losses) / total if total else 0.0


def _awesome_oscillator(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    fast = _period(params, "fast_period", minimum=2)
    slow = _period(params, "slow_period", minimum=2)
    if fast >= slow:
        raise FactorError("factor.invalidParameter")
    median = (pd.to_numeric(frame["high"], errors="coerce") + pd.to_numeric(frame["low"], errors="coerce")) / 2.0
    values = _require(median, slow)
    return float(values.iloc[-fast:].mean() - values.iloc[-slow:].mean())


def _ultimate_oscillator(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    fast = _period(params, "fast_period", minimum=2)
    medium = _period(params, "medium_period", minimum=2)
    slow = _period(params, "slow_period", minimum=2)
    if not fast < medium < slow:
        raise FactorError("factor.invalidParameter")
    if len(frame) < slow + 1:
        raise FactorError("factor.insufficientHistory")
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    close = pd.to_numeric(frame["close"], errors="coerce")
    previous = close.shift(1)
    buying_pressure = close - pd.concat([low, previous], axis=1).min(axis=1)
    true_range = pd.concat([high, previous], axis=1).max(axis=1) - pd.concat([low, previous], axis=1).min(axis=1)
    def average(length: int) -> float:
        denominator = float(true_range.iloc[-length:].sum())
        return float(buying_pressure.iloc[-length:].sum()) / denominator if denominator else 0.0
    return 100.0 * (4.0 * average(fast) + 2.0 * average(medium) + average(slow)) / 7.0


def _tsi(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    slow = _period(params, "slow_period", minimum=2)
    fast = _period(params, "fast_period", minimum=2)
    momentum = _require(frame["close"], slow + fast + 1).diff().dropna()
    numerator = _ema_values(_ema_values(momentum, slow).dropna(), fast).dropna()
    denominator = _ema_values(_ema_values(momentum.abs(), slow).dropna(), fast).dropna()
    scale = float(denominator.iloc[-1])
    return 100.0 * float(numerator.iloc[-1]) / scale if scale else 0.0


def _vortex(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    if len(frame) < period + 1:
        raise FactorError("factor.insufficientHistory")
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    true_range = _true_range(frame).iloc[-period:]
    denominator = float(true_range.sum())
    if denominator <= 0:
        return 0.0
    plus = float((high - low.shift(1)).abs().iloc[-period:].sum()) / denominator
    minus = float((low - high.shift(1)).abs().iloc[-period:].sum()) / denominator
    output = _choice(params, "output", {"plus", "minus", "oscillator"}, "oscillator")
    return {"plus": plus, "minus": minus, "oscillator": plus - minus}[output]


def _choppiness(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    if len(frame) < period + 1:
        raise FactorError("factor.insufficientHistory")
    high = pd.to_numeric(frame["high"], errors="coerce").iloc[-period:]
    low = pd.to_numeric(frame["low"], errors="coerce").iloc[-period:]
    price_range = float(high.max() - low.min())
    if price_range <= 0:
        return 100.0
    return 100.0 * math.log10(float(_true_range(frame).iloc[-period:].sum()) / price_range) / math.log10(period)


def _efficiency_ratio(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    values = _require(frame["close"], period + 1)
    change = abs(float(values.iloc[-1] - values.iloc[-period - 1]))
    volatility = float(values.iloc[-period - 1:].diff().abs().sum())
    return change / volatility if volatility else 0.0


def _elder_ray(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    average = float(_ema_values(frame["close"], period).iloc[-1])
    output = _choice(params, "output", {"bull", "bear"}, "bull")
    field = "high" if output == "bull" else "low"
    return float(pd.to_numeric(frame[field], errors="coerce").iloc[-1]) - average


def _force_index(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    close = pd.to_numeric(frame["close"], errors="coerce")
    volume = pd.to_numeric(frame["volume"], errors="coerce")
    raw = (close.diff() * volume).dropna()
    return float(_ema_values(raw, period).iloc[-1])


def _ulcer_index(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    values = _require(frame["close"], period).iloc[-period:]
    drawdown = 100.0 * (values / values.cummax() - 1.0)
    return float(np.sqrt(np.mean(np.square(drawdown))))


def _parkinson_volatility(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    high = _require(frame["high"], period).iloc[-period:]
    low = _require(frame["low"], period).iloc[-period:].replace(0, np.nan)
    variance = float(np.square(np.log(high / low)).mean() / (4.0 * math.log(2.0)))
    return math.sqrt(max(0.0, variance) * 252.0)


def _garman_klass_volatility(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    high = _require(frame["high"], period).iloc[-period:]
    low = _require(frame["low"], period).iloc[-period:].replace(0, np.nan)
    open_values = _require(frame["open"], period).iloc[-period:].replace(0, np.nan)
    close = _require(frame["close"], period).iloc[-period:]
    variance = 0.5 * np.square(np.log(high / low)) - (2.0 * math.log(2.0) - 1.0) * np.square(np.log(close / open_values))
    return math.sqrt(max(0.0, float(variance.mean())) * 252.0)


def _amihud_illiquidity(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    period = _period(params)
    close = _require(frame["close"], period + 1)
    volume = pd.to_numeric(frame["volume"], errors="coerce").iloc[-period:]
    returns = close.pct_change().abs().iloc[-period:]
    traded_value = (close.iloc[-period:] * volume).replace(0, np.nan)
    return float((returns.to_numpy() / traded_value.to_numpy()).mean())


# --- Smart Money Concepts --------------------------------------------------
# Market structure primitives: confirmed swings, break of structure, change of
# character, and fair value gaps.
#
# The whole design turns on WHEN a structure becomes knowable. A swing pivot
# needs `swing_length` bars on BOTH sides, so it cannot be confirmed until
# `swing_length` bars after it printed. Every derived event therefore fires on
# the bar that broke the level -- never on the pivot itself.
#
# This matters more here than in a charting context. The registry is driven by
# runtime.py's expanding-window loop (`visible = frame.iloc[:index + 1]`), which
# asks each bar "what is true right now". Answering with a pivot that needed
# future bars to identify would feed the backtest information the strategy could
# not have had.
#
# The `smartmoneyconcepts` package stamps events on the pivot bar instead.
# Measured over 150 BOS/CHoCH signals, none were visible on the bar carrying
# them; mean lag was 17-58 bars depending on swing_length. That is inherent to
# the definition, not a bug in the package -- but it is unusable as a factor.


def _smc_confirm_swings(high, low, n, is_high, is_low, first, last) -> None:
    """Mark strict swing pivots for indices in [first, last), in place.

    A pivot at i is decided by the window [i-n, i+n] alone, so its value never
    depends on how much data follows. That is what makes the incremental path
    below exact rather than approximate: any index already decided stays
    decided, and extending the frame can only decide new ones.
    """
    for index in range(first, last):
        segment = high[index - n:index + n + 1]
        if high[index] == np.max(segment) and int(np.sum(segment == high[index])) == 1:
            is_high[index] = True
        segment = low[index - n:index + n + 1]
        if low[index] == np.min(segment) and int(np.sum(segment == low[index])) == 1:
            is_low[index] = True


def _smc_bars(frame: pd.DataFrame, params: Mapping[str, Any]):
    """Shared validation and column extraction for the SMC factors."""
    swing_length = int(params.get("swing_length") or 10)
    if swing_length < 2:
        raise FactorError("factor.badParams")
    size = len(frame)
    if size < 2 * swing_length + 2:
        raise FactorError("factor.insufficientHistory")
    return (
        swing_length,
        size,
        pd.to_numeric(frame["high"], errors="coerce").to_numpy(dtype=float),
        pd.to_numeric(frame["low"], errors="coerce").to_numpy(dtype=float),
        pd.to_numeric(frame["close"], errors="coerce").to_numpy(dtype=float),
    )


# Replay state, keyed by series identity and swing length. The runtime calls
# every factor once per bar on an expanding window, so recomputing the whole
# replay each time is O(n^2) in bar count -- 400 days of 1h bars took 339s and
# 800 days did not finish. Resuming from the previous bar makes it O(n).
_SMC_REPLAY_CACHE: "OrderedDict[tuple, dict]" = OrderedDict()
_SMC_REPLAY_CACHE_MAX = 32


def _smc_series_key(high, low, close, swing_length: int) -> tuple:
    """Identity of the series being replayed, not of one particular window."""
    return (swing_length, float(high[0]), float(low[0]), float(close[0]))


def _smc_bar_mark(high, low, close, index: int) -> tuple:
    """Fingerprint of one bar, used to prove a cached prefix is still a prefix."""
    return (float(high[index]), float(low[index]), float(close[index]))


def _smc_replay(high, low, close, swing_length: int, size: int):
    """Bar-by-bar structure replay -- the single definition of BOS and CHoCH.

    Returns (events, direction, level_high, level_low, last_event) where events
    is a list of (break_index, pivot_index, level, kind, direction) with kind
    1 = BOS and 2 = CHoCH.

    Every SMC factor derives from this rather than repeating the loop, because
    a second copy would drift and the two would disagree about what the market
    structure is.

    Resumes from a cached state when the request extends a window already seen.
    Two facts make that exact rather than merely fast:

      * a pivot at i is decided by [i-n, i+n] alone, so indices already decided
        cannot change when more bars arrive;
      * the state after bar k depends only on bars up to k.

    The cache is only trusted when the bar at the cached boundary still matches
    the fingerprint recorded for it. A stale or unrelated series therefore falls
    back to a full replay rather than silently continuing from the wrong state,
    which would corrupt a backtest quietly -- the worst possible failure here.
    Cached states are never mutated in place; each extension publishes a fresh
    one, so a concurrent reader sees either the old or the new state whole.
    """
    key = _smc_series_key(high, low, close, swing_length)
    cached = _SMC_REPLAY_CACHE.get(key)

    resume_from = 0
    if (
        cached is not None
        and 0 < cached["size"] <= size
        and cached["mark"] == _smc_bar_mark(high, low, close, cached["size"] - 1)
    ):
        resume_from = cached["size"]
        is_high = np.resize(cached["is_high"], size)
        is_low = np.resize(cached["is_low"], size)
        is_high[cached["size"]:] = False
        is_low[cached["size"]:] = False
        events = list(cached["events"])
        level_high = cached["level_high"]
        level_low = cached["level_low"]
        pivot_high = cached["pivot_high"]
        pivot_low = cached["pivot_low"]
        high_live = cached["high_live"]
        low_live = cached["low_live"]
        direction = cached["direction"]
    else:
        is_high = np.zeros(size, dtype=bool)
        is_low = np.zeros(size, dtype=bool)
        events: list[tuple[int, int, float, int, int]] = []
        level_high = float("nan")
        level_low = float("nan")
        pivot_high = -1
        pivot_low = -1
        high_live = False
        low_live = False
        direction = 0

    # Decide the pivots that became decidable since the cached boundary. A
    # pivot needs swing_length bars on each side, so index i is decidable once
    # bar i + swing_length exists.
    first_undecided = max(swing_length, resume_from - swing_length)
    _smc_confirm_swings(high, low, swing_length, is_high, is_low,
                        first_undecided, max(first_undecided, size - swing_length))

    last_event = (0, 0)          # (bos, choch) on the final bar

    for index in range(resume_from, size):
        # The pivot at index - swing_length becomes knowable exactly now.
        pivot = index - swing_length
        if pivot >= 0:
            if is_high[pivot]:
                level_high, pivot_high, high_live = high[pivot], pivot, True
            if is_low[pivot]:
                level_low, pivot_low, low_live = low[pivot], pivot, True

        broke_up = 0
        broke_down = 0
        if high_live and not np.isnan(level_high) and close[index] > level_high:
            broke_up = 1 if direction >= 0 else 2      # 1 = BOS, 2 = CHoCH
            events.append((index, pivot_high, float(level_high), broke_up, 1))
            direction = 1
            high_live = False
        elif low_live and not np.isnan(level_low) and close[index] < level_low:
            broke_down = 1 if direction <= 0 else 2
            events.append((index, pivot_low, float(level_low), broke_down, -1))
            direction = -1
            low_live = False

        # Only the final bar's event is reported; earlier ones already were.
        if index == size - 1:
            last_event = (
                1 if broke_up == 1 else (-1 if broke_down == 1 else 0),
                1 if broke_up == 2 else (-1 if broke_down == 2 else 0),
            )

    _SMC_REPLAY_CACHE[key] = {
        "size": size,
        "mark": _smc_bar_mark(high, low, close, size - 1),
        "is_high": is_high,
        "is_low": is_low,
        "events": events,
        "level_high": level_high,
        "level_low": level_low,
        "pivot_high": pivot_high,
        "pivot_low": pivot_low,
        "high_live": high_live,
        "low_live": low_live,
        "direction": direction,
    }
    _SMC_REPLAY_CACHE.move_to_end(key)
    while len(_SMC_REPLAY_CACHE) > _SMC_REPLAY_CACHE_MAX:
        _SMC_REPLAY_CACHE.popitem(last=False)

    return events, direction, level_high, level_low, last_event


def _smc_state(frame: pd.DataFrame, params: Mapping[str, Any]) -> dict[str, float]:
    """Replay the visible window and report the structure as of its last bar."""
    swing_length, size, high, low, close = _smc_bars(frame, params)
    _events, direction, level_high, level_low, last_event = _smc_replay(
        high, low, close, swing_length, size)
    bos, choch = last_event

    last_close = close[-1]
    return {
        "trend": float(direction),
        "bos": float(bos),
        "choch": float(choch),
        "swing_high": float(level_high),
        "swing_low": float(level_low),
        "distance_high": float((level_high - last_close) / last_close)
        if not np.isnan(level_high) and last_close else float("nan"),
        "distance_low": float((last_close - level_low) / last_close)
        if not np.isnan(level_low) and last_close else float("nan"),
    }


def _smc_structure(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    state = _smc_state(frame, params)
    output = _choice(
        params,
        "output",
        {"trend", "bos", "choch", "swing_high", "swing_low",
         "distance_high", "distance_low"},
        "trend",
    )
    value = state[output]
    if np.isnan(value):
        raise FactorError("factor.noData")
    return float(value)


def _smc_fvg(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    """Most recent unmitigated three-bar imbalance, as of the last visible bar.

    Detected from bars k-2, k-1 and k, so it is knowable on bar k. Scans
    backwards and stops at the first gap price has not traded back through.
    """
    size = len(frame)
    if size < 3:
        raise FactorError("factor.insufficientHistory")

    high = pd.to_numeric(frame["high"], errors="coerce").to_numpy(dtype=float)
    low = pd.to_numeric(frame["low"], errors="coerce").to_numpy(dtype=float)
    close = pd.to_numeric(frame["close"], errors="coerce").to_numpy(dtype=float)
    output = _choice(
        params, "output", {"side", "top", "bottom", "distance", "stop", "age"},
        "side")

    for k in range(size - 1, 1, -1):
        if low[k] > high[k - 2]:
            top, bottom, side = low[k], high[k - 2], 1.0
            # Invalidation sits behind the displacement candle -- bar k-1, the
            # one whose move opened the gap -- not behind the gap itself. A
            # stop just under the gap edge sits inside the noise the gap was
            # created by, and gets taken out by the retest that forms the
            # entry.
            stop = min(low[k - 1], low[k - 2])
        elif high[k] < low[k - 2]:
            top, bottom, side = low[k - 2], high[k], -1.0
            stop = max(high[k - 1], high[k - 2])
        else:
            continue
        if k + 1 < size:
            # Mitigated once any later bar trades into the gap.
            if np.min(low[k + 1:]) <= bottom and np.max(high[k + 1:]) >= top:
                continue
        if output == "side":
            return float(side)
        if output == "top":
            return float(top)
        if output == "bottom":
            return float(bottom)
        if output == "stop":
            return float(stop)
        if output == "age":
            return float(size - 1 - k)
        middle = (top + bottom) / 2.0
        last_close = close[-1]
        if not middle or not last_close:
            raise FactorError("factor.noData")
        return float((last_close - middle) / middle)

    if output == "side":
        return 0.0
    raise FactorError("factor.noData")


def _smc_ifvg(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    """Most recent live inversion gap -- a fair value gap price closed through,
    so its polarity flipped.

    smc_fvg reports the most recent gap price has NOT traded back through. This
    reports exactly the set that one discards: a gap price went through
    decisively, on the reasoning that a level which failed as resistance tends
    to act as support. A bearish gap the market closes above stops being a
    ceiling and becomes a floor.

    It is the second entry trigger in the HTF/LTF model, standing for "momentum
    changed hands inside the zone". smc_fvg cannot express it -- it stops at
    the first unmitigated gap, which is the complement of this set.

    Knowable on the bar whose CLOSE completes the inversion: the gap was
    defined three bars back, and the break is this bar's own close. Both the
    inversion and its later invalidation are close-based, so nothing here
    depends on a bar that has not finished.

      side      1 = bullish inversion (was a bearish gap, now support)
               -1 = bearish inversion (was a bullish gap, now resistance)
      top       upper edge of the flipped zone
      bottom    lower edge
      stop      the extreme the formation made between the gap and the break,
                which is the level the model puts a stop outside of
      age       bars since the inversion closed
      distance  last close against the zone midpoint
    """
    size = len(frame)
    if size < 4:
        raise FactorError("factor.insufficientHistory")

    high = pd.to_numeric(frame["high"], errors="coerce").to_numpy(dtype=float)
    low = pd.to_numeric(frame["low"], errors="coerce").to_numpy(dtype=float)
    close = pd.to_numeric(frame["close"], errors="coerce").to_numpy(dtype=float)
    output = _choice(
        params, "output", {"side", "top", "bottom", "stop", "distance", "age"},
        "side")
    # Bounded so the cost per bar stays flat. An inversion this old is not the
    # "momentum just changed" the model is about, and an unbounded scan would
    # make the factor quadratic on every call.
    lookback = max(4, int(params.get("lookback") or 60))
    start = max(2, size - lookback)

    best_index = -1
    best: tuple[float, float, float, float] | None = None
    for k in range(start, size):
        previous_high, previous_low = high[k - 2], low[k - 2]
        if low[k] > previous_high:
            top, bottom, original = low[k], previous_high, 1
        elif high[k] < previous_low:
            top, bottom, original = previous_low, high[k], -1
        else:
            continue

        later = close[k + 1:]
        if later.size == 0:
            continue
        # Through the gap, against the side it was drawn on.
        broken = later < bottom if original == 1 else later > top
        if not broken.any():
            continue
        index = k + 1 + int(np.argmax(broken))
        if index < best_index:
            # An older gap cannot beat an inversion that already happened later.
            continue
        # On a tie the later gap wins: one decisive close can invert several
        # stacked gaps at once, and the freshest is the tightest zone and the
        # nearest stop. Without an explicit rule here the winner would be
        # whichever gap the scan happened to reach first, which is the oldest
        # and widest -- and it would change as older ones were invalidated.

        after = close[index + 1:]
        if after.size:
            # Still live only while price has not closed back through the far
            # side. An inversion that failed is not a level, it is history.
            failed = after < bottom if original == -1 else after > top
            if failed.any():
                continue

        extreme = (float(np.min(low[k - 2:index + 1])) if original == -1
                   else float(np.max(high[k - 2:index + 1])))
        best_index, best = index, (float(-original), top, bottom, extreme)

    if best is None:
        if output == "side":
            return 0.0
        raise FactorError("factor.noData")

    side, top, bottom, extreme = best
    if output == "side":
        return side
    if output == "top":
        return float(top)
    if output == "bottom":
        return float(bottom)
    if output == "stop":
        return extreme
    if output == "age":
        return float(size - 1 - best_index)
    middle = (top + bottom) / 2.0
    last_close = close[-1]
    if not middle or not last_close:
        raise FactorError("factor.noData")
    return float((last_close - middle) / middle)


def _smc_sweep(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    """Most recent liquidity sweep: a wick through a confirmed swing that the
    close did not hold beyond.

    This is the piece Model 1 turns on. A break of structure is defined on the
    CLOSE -- price accepted the new level -- while a sweep is the opposite: the
    wick took the stops resting past the level and the close came back. Testing
    only closes, as the structure factor does, cannot see it at all.

    Knowable on the sweep bar itself: the pivot was confirmed swing_length bars
    earlier, and the wick and close both belong to the current bar.

      side     1 = lows swept (bullish reaction expected), -1 = highs swept
      level    the swept swing level
      extreme  the wick extreme -- where a stop goes, beyond the sweep
      age      bars since the sweep
    """
    swing_length, size, high, low, close = _smc_bars(frame, params)
    lookback = max(1, int(params.get("lookback") or 60))
    output = _choice(
        params, "output", {"side", "level", "extreme", "age"}, "side")

    # Reuse the replay's pivots rather than recomputing them; it already has
    # them cached for this series and length.
    _smc_replay(high, low, close, swing_length, size)
    cached = _SMC_REPLAY_CACHE.get(_smc_series_key(high, low, close, swing_length))
    is_high, is_low = cached["is_high"], cached["is_low"]

    # Walk back from the last bar; the first sweep found is the live one.
    start = max(swing_length, size - lookback)
    for index in range(size - 1, start - 1, -1):
        # Only pivots confirmed before this bar were visible to it.
        usable = index - swing_length
        if usable < 0:
            break

        highs = [i for i in range(usable + 1) if is_high[i]]
        lows = [i for i in range(usable + 1) if is_low[i]]

        if lows:
            level = low[lows[-1]]
            if low[index] < level and close[index] > level:
                if output == "side":
                    return 1.0
                if output == "level":
                    return float(level)
                if output == "extreme":
                    return float(low[index])
                return float(size - 1 - index)

        if highs:
            level = high[highs[-1]]
            if high[index] > level and close[index] < level:
                if output == "side":
                    return -1.0
                if output == "level":
                    return float(level)
                if output == "extreme":
                    return float(high[index])
                return float(size - 1 - index)

    if output == "side":
        return 0.0
    raise FactorError("factor.noData")


def _smc_ob(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    """Most recent unmitigated order block -- the last opposing candle before
    the move that broke structure.

    This is the piece Model 2 turns on. An order block is only meaningful once
    the break it preceded has happened, so it becomes knowable at the BREAK
    bar, not at the candle itself. Reporting it earlier would hand the strategy
    a level the market had not yet justified.

      side      1 = bullish (demand), -1 = bearish (supply)
      top       the block candle's high
      bottom    the block candle's low
      stop      just beyond the block -- below it for a bullish one
      distance  close relative to the block midpoint
      age       bars since the block candle
    """
    swing_length, size, high, low, close = _smc_bars(frame, params)
    open_ = pd.to_numeric(frame["open"], errors="coerce").to_numpy(dtype=float)
    search = max(2, int(params.get("search") or 30))
    output = _choice(
        params, "output",
        {"side", "top", "bottom", "stop", "distance", "age"}, "side")

    events, _direction, _lh, _ll, _last = _smc_replay(
        high, low, close, swing_length, size)

    for break_index, _pivot, _level, _kind, side in reversed(events):
        found = -1
        floor_index = max(break_index - search, 0)
        for j in range(break_index - 1, floor_index - 1, -1):
            # The last candle against the direction of the break.
            if side > 0 and close[j] < open_[j]:
                found = j
                break
            if side < 0 and close[j] > open_[j]:
                found = j
                break
        if found < 0:
            continue

        # Mitigated once price traded back through the block.
        mitigated = False
        for j in range(found + 1, size):
            if side > 0 and low[j] <= low[found]:
                mitigated = True
                break
            if side < 0 and high[j] >= high[found]:
                mitigated = True
                break
        if mitigated:
            continue

        top = float(high[found])
        bottom = float(low[found])
        if output == "side":
            return float(side)
        if output == "top":
            return top
        if output == "bottom":
            return bottom
        if output == "stop":
            return bottom if side > 0 else top
        if output == "age":
            return float(size - 1 - found)
        middle = (top + bottom) / 2.0
        last_close = close[-1]
        if not middle or not last_close:
            raise FactorError("factor.noData")
        return float((last_close - middle) / middle)

    if output == "side":
        return 0.0
    raise FactorError("factor.noData")


def _smc_ote(frame: pd.DataFrame, params: Mapping[str, Any]) -> float:
    """Where price sits inside the most recent completed swing leg.

    Model 4's position filter, and the one thing the other three models have no
    equivalent of: structure, gaps and blocks all say *what* happened, this says
    *where price is now* relative to it. A setup can be structurally perfect and
    still be a bad entry because price has not retraced far enough.

    The leg runs between the two most recent confirmed pivots of opposite kind,
    so it inherits the swing confirmation delay and cannot look ahead.

      position   0 at the leg's origin, 1 at its extreme
      retrace    how far price has pulled back from the extreme, 0 to 1
      in_ote     1 when retrace is inside the optimal-trade-entry band
      discount   1 when price is below the midpoint of the leg
      premium    1 when above it
      ote_near   the shallower edge of the band, as a price
      ote_far    the deeper edge, as a price
      leg_low / leg_high   the anchors

    The band defaults to 0.62-0.79, the figures the source states verbatim
    ("this is a 62% to 79% of this recent move"). They are parameters because
    they are a convention, not a derivation.
    """
    swing_length, size, high, low, close = _smc_bars(frame, params)
    lower = _positive_float(params, "ote_from", 0.62)
    upper = _positive_float(params, "ote_to", 0.79)
    if not 0 < lower < upper < 1:
        raise FactorError("factor.badParams")
    output = _choice(
        params, "output",
        {"position", "retrace", "in_ote", "discount", "premium",
         "ote_near", "ote_far", "leg_low", "leg_high"},
        "in_ote",
    )

    _smc_replay(high, low, close, swing_length, size)
    cached = _SMC_REPLAY_CACHE.get(_smc_series_key(high, low, close, swing_length))
    is_high, is_low = cached["is_high"], cached["is_low"]

    # Only pivots already confirmed at the last bar may anchor the leg.
    usable = size - 1 - swing_length
    if usable < 0:
        raise FactorError("factor.insufficientHistory")
    highs = [i for i in range(usable + 1) if is_high[i]]
    lows = [i for i in range(usable + 1) if is_low[i]]
    if not highs or not lows:
        raise FactorError("factor.noData")

    high_index, low_index = highs[-1], lows[-1]
    leg_high = float(high[high_index])
    leg_low = float(low[low_index])
    span = leg_high - leg_low
    if span <= 0:
        raise FactorError("factor.noData")

    # Direction of the leg: which extreme came last.
    rising = high_index > low_index
    last_close = float(close[-1])

    position = (last_close - leg_low) / span
    # Retracement is measured back from whichever extreme completed the leg.
    retrace = (leg_high - last_close) / span if rising else (last_close - leg_low) / span

    if output == "position":
        return float(position)
    if output == "retrace":
        return float(retrace)
    if output == "in_ote":
        return 1.0 if lower <= retrace <= upper else 0.0
    if output == "discount":
        return 1.0 if position < 0.5 else 0.0
    if output == "premium":
        return 1.0 if position > 0.5 else 0.0
    if output == "leg_low":
        return leg_low
    if output == "leg_high":
        return leg_high
    # Band edges as prices, oriented so `near` is the shallower retracement.
    if rising:
        near, far = leg_high - span * lower, leg_high - span * upper
    else:
        near, far = leg_low + span * lower, leg_low + span * upper
    return float(near if output == "ote_near" else far)
