#!/usr/bin/env python3
"""
Replay data/trades.csv with FIFO matching: each settle pairs with earliest unmatched buy
for the same ticker. Produces equity curve, drawdown, win rate, and total P/L.

Intraday technicals and stop-loss are not simulated (no per-tick price path in CSV).
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import re
from collections import defaultdict, deque
from datetime import datetime

from kelly import TRADES_FILE, _parse_settle_pnl, compute_kelly_scaler
from portfolio import STARTING_BALANCE


def _parse_ts(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_sorted_rows(path: str) -> list[dict]:
    if not os.path.isfile(path):
        return []
    rows: list[dict] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    rows.sort(key=lambda r: (_parse_ts(r.get("timestamp") or "") or datetime.min,))
    return rows


def run_fifo_backtest(path: str) -> dict:
    """
    Walk rows in time order. Buys push onto per-ticker FIFO; settles pop and apply P/L.
    """
    rows = load_sorted_rows(path)
    stacks: dict[str, deque[dict]] = defaultdict(deque)
    equity = float(STARTING_BALANCE)
    equity_curve: list[tuple[str, float]] = []
    equity_curve.append((rows[0]["timestamp"] if rows else "", equity))
    matched_pnls: list[float] = []
    orphan_settles = 0
    orphan_buys = 0

    for row in rows:
        action = (row.get("action") or "").strip().lower()
        ticker = (row.get("ticker") or "").strip()
        ts = row.get("timestamp") or ""

        if action == "buy" and ticker:
            try:
                c = int(float(row.get("contracts") or 0))
                cost = float(row.get("cost_usd") or 0)
            except (TypeError, ValueError):
                c, cost = 0, 0.0
            stacks[ticker].append({"contracts": c, "cost_usd": cost, "ts": ts})
            continue

        if action in ("settle", "stop") and ticker:
            pnl = _parse_settle_pnl(row.get("reason") or "")
            if pnl is None and action == "stop":
                m = re.search(r"P/L\s*\$?\s*([+-]?\d+(?:\.\d+)?)", row.get("reason") or "", re.I)
                if m:
                    try:
                        pnl = float(m.group(1))
                    except ValueError:
                        pnl = None
            if pnl is None:
                continue
            if not stacks[ticker]:
                orphan_settles += 1
                continue
            stacks[ticker].popleft()
            equity += pnl
            matched_pnls.append(pnl)
            equity_curve.append((ts, equity))

    for _t, dq in stacks.items():
        orphan_buys += len(dq)

    peak = equity_curve[0][1] if equity_curve else STARTING_BALANCE
    max_dd = 0.0
    for _, e in equity_curve:
        peak = max(peak, e)
        dd = (peak - e) / peak if peak else 0.0
        max_dd = max(max_dd, dd)

    wins = sum(1 for p in matched_pnls if p > 0)
    n = len(matched_pnls)
    win_rate = wins / n if n else 0.0
    total_pnl = sum(matched_pnls)

    # Sharpe on per-trade "returns" vs zero (rough)
    sharpe = 0.0
    if n > 1 and matched_pnls:
        mean = total_pnl / n
        var = sum((p - mean) ** 2 for p in matched_pnls) / (n - 1)
        std = math.sqrt(var) if var > 0 else 0.0
        if std > 0:
            sharpe = (mean / std) * math.sqrt(n)

    return {
        "path": path,
        "starting_balance": STARTING_BALANCE,
        "ending_equity": equity,
        "total_pnl": total_pnl,
        "matched_trades": n,
        "win_rate": win_rate,
        "max_drawdown_pct": max_dd * 100,
        "orphan_settles": orphan_settles,
        "unmatched_buys_remaining": orphan_buys,
        "equity_curve": equity_curve,
        "matched_pnls": matched_pnls,
        "sharpe_trades": sharpe,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="FIFO backtest from trades.csv")
    p.add_argument(
        "--trades",
        default=TRADES_FILE,
        help=f"Path to trades CSV (default: {TRADES_FILE})",
    )
    args = p.parse_args()
    path = os.path.abspath(args.trades)

    res = run_fifo_backtest(path)
    k_scaler = compute_kelly_scaler(path)

    print(f"Trades file: {res['path']}")
    print(f"Starting balance: ${res['starting_balance']:,.2f}")
    print(f"Ending equity (matched closes): ${res['ending_equity']:,.2f}")
    print(f"Total realized P/L (matched): ${res['total_pnl']:+,.2f}")
    print(f"Matched closes: {res['matched_trades']} | Win rate: {res['win_rate']*100:.1f}%")
    print(f"Max drawdown (on equity curve): {res['max_drawdown_pct']:.2f}%")
    print(f"Sharpe (per-trade, rough): {res['sharpe_trades']:.3f}")
    print(f"Orphan settles/stops (no buy): {res['orphan_settles']}")
    print(f"Unmatched buys (still open in log): {res['unmatched_buys_remaining']}")
    print(f"Current Kelly scaler (from file): {k_scaler:.4f}")
    print("---")
    print("Note: Path-dependent rules (technicals, stop) are not replayed without tick data.")


if __name__ == "__main__":
    main()
