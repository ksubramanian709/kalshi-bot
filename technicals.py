"""
RSI (Wilder 14), MACD (12,26,9), Bollinger (20, 2σ) on implied YES probability series.
NumPy only. Persists snapshots under data/technicals/.
"""
from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import numpy as np

_PKG_ROOT = os.path.dirname(os.path.abspath(__file__))
TECH_DIR = os.path.join(_PKG_ROOT, "data", "technicals")
TECH_LOG = os.path.join(TECH_DIR, "technical_log.csv")

RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
BB_PERIOD = 20
BB_NUM_STD = 2.0

# Need enough points for slow EMA and BB
MIN_BARS = 40


@dataclass
class TechnicalSnapshot:
    rsi: float
    macd_line: float
    macd_signal: float
    macd_hist: float
    bb_mid: float
    bb_upper: float
    bb_lower: float
    rsi_label: Literal["oversold", "neutral", "overbought"]
    macd_label: Literal["bull", "bear"]
    bb_label: Literal["below_lower", "inside", "above_upper"]


def _ema_series(x: np.ndarray, span: int) -> np.ndarray:
    alpha = 2.0 / (span + 1)
    out = np.empty_like(x, dtype=np.float64)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = alpha * x[i] + (1.0 - alpha) * out[i - 1]
    return out


def _rsi_wilder_last(close: np.ndarray, period: int = RSI_PERIOD) -> float:
    """Last RSI using Wilder smoothing (matches common TA libraries)."""
    if len(close) < period + 1:
        return float("nan")
    delta = np.diff(close)
    n = len(delta)
    gain = np.maximum(delta, 0.0)
    loss = np.maximum(-delta, 0.0)
    avg_gain = np.zeros(n, dtype=np.float64)
    avg_loss = np.zeros(n, dtype=np.float64)
    avg_gain[period - 1] = float(np.mean(gain[:period]))
    avg_loss[period - 1] = float(np.mean(loss[:period]))
    for i in range(period, n):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gain[i]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + loss[i]) / period
    rs = avg_gain / np.maximum(avg_loss, 1e-12)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return float(rsi[-1])


def _rolling_mean_std(x: np.ndarray, window: int) -> tuple[float, float]:
    if len(x) < window:
        return float("nan"), float("nan")
    w = x[-window:]
    return float(np.mean(w)), float(np.std(w, ddof=0))


def compute_technicals(prices: np.ndarray) -> TechnicalSnapshot | None:
    """
    prices: implied YES in [0,1] (same units as momentum deque).
    Returns None if series too short.
    """
    x = np.asarray(prices, dtype=np.float64).ravel()
    if x.size < MIN_BARS:
        return None

    rsi_val = _rsi_wilder_last(x, RSI_PERIOD)
    ema_f = _ema_series(x, MACD_FAST)
    ema_s = _ema_series(x, MACD_SLOW)
    macd_line = ema_f - ema_s
    sig = _ema_series(macd_line, MACD_SIGNAL)
    macd_hist = macd_line - sig

    m, s = _rolling_mean_std(x, BB_PERIOD)
    upper = m + BB_NUM_STD * s
    lower = m - BB_NUM_STD * s
    last = float(x[-1])

    if np.isnan(rsi_val):
        return None

    if rsi_val < 30:
        rl: Literal["oversold", "neutral", "overbought"] = "oversold"
    elif rsi_val > 70:
        rl = "overbought"
    else:
        rl = "neutral"

    ml = float(macd_line[-1])
    sl = float(sig[-1])
    mh = float(macd_hist[-1])
    md: Literal["bull", "bear"] = "bull" if mh >= 0 else "bear"

    if last > upper:
        bl: Literal["below_lower", "inside", "above_upper"] = "above_upper"
    elif last < lower:
        bl = "below_lower"
    else:
        bl = "inside"

    return TechnicalSnapshot(
        rsi=rsi_val,
        macd_line=ml,
        macd_signal=sl,
        macd_hist=mh,
        bb_mid=m,
        bb_upper=upper,
        bb_lower=lower,
        rsi_label=rl,
        macd_label=md,
        bb_label=bl,
    )


def technicals_allow_buy(prices: np.ndarray | None) -> tuple[bool, str]:
    """
    Gate buys: not RSI overbought, MACD histogram not bearish, price not above upper band.
    Short history: no veto (align with momentum).
    """
    if prices is None:
        return True, "technicals: no history (no veto)"
    snap = compute_technicals(prices)
    if snap is None:
        return True, "technicals: short history (no veto)"

    if snap.rsi > 70:
        return False, f"technicals: RSI overbought ({snap.rsi:.1f})"
    if snap.macd_hist < 0:
        return False, f"technicals: MACD bearish (hist {snap.macd_hist:.5f})"
    if snap.bb_label == "above_upper":
        return False, "technicals: price above upper Bollinger"
    return True, (
        f"technicals: ok RSI={snap.rsi:.1f} MACD_hist={snap.macd_hist:.5f} BB={snap.bb_label}"
    )


def record_technicals_if_ready(ticker: str) -> None:
    """Append one technical snapshot row when history is long enough."""
    from momentum import get_price_samples

    arr = get_price_samples(ticker)
    snap = compute_technicals(arr) if arr is not None else None
    if snap is not None:
        append_technical_log(ticker, snap)


def append_technical_log(ticker: str, snap: TechnicalSnapshot) -> None:
    os.makedirs(TECH_DIR, exist_ok=True)
    write_header = not os.path.isfile(TECH_LOG)
    ts = datetime.utcnow().isoformat() + "Z"
    row = [
        ts,
        ticker,
        f"{snap.rsi:.4f}",
        f"{snap.macd_line:.6f}",
        f"{snap.macd_signal:.6f}",
        f"{snap.macd_hist:.6f}",
        f"{snap.bb_mid:.6f}",
        f"{snap.bb_upper:.6f}",
        f"{snap.bb_lower:.6f}",
        snap.rsi_label,
        snap.macd_label,
        snap.bb_label,
    ]
    with open(TECH_LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(
                [
                    "timestamp",
                    "ticker",
                    "rsi",
                    "macd_line",
                    "macd_signal",
                    "macd_hist",
                    "bb_mid",
                    "bb_upper",
                    "bb_lower",
                    "rsi_signal",
                    "macd_signal_label",
                    "bb_signal",
                ]
            )
        w.writerow(row)
