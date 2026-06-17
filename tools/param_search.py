#!/usr/bin/env python3
"""Walk-Forward 参数优化

对信号检测和风险管理参数做滚动窗口随机搜索。
每个窗口：in-sample 搜索最优参数 → out-of-sample 验证。

用法：
    python tools/param_search.py --mode random --samples 30 --window 3 --step 1
"""

import argparse
import os
import random
import sys
import time
from contextlib import redirect_stdout
from itertools import product

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import numpy as np
import pandas as pd

import trader_vic.config as config


def load_data(data_dir: str = "data"):
    stock_data = {}
    for ticker in set(config.WATCHLIST):
        path = os.path.join(data_dir, f"{ticker}.csv")
        if os.path.exists(path):
            df = pd.read_csv(path, index_col="date", parse_dates=True)
            if len(df) >= 252:
                stock_data[ticker] = df

    csi300 = None
    p = os.path.join(data_dir, "sh000300.csv")
    if os.path.exists(p):
        csi300 = pd.read_csv(p, index_col="date", parse_dates=True)

    sh = None
    p2 = os.path.join(data_dir, "sh000001.csv")
    if os.path.exists(p2):
        sh = pd.read_csv(p2, index_col="date", parse_dates=True)

    return stock_data, csi300, sh


def apply_params(params: dict):
    """直接修改 config 模块属性，信号检测和风控模块在运行时读取。"""
    for key, value in params.items():
        setattr(config, key, value)


def run_single_backtest(stock_data, csi300, sh_index, capital: float = 1_000_000, quiet: bool = True):
    from trader_vic.strategies.vic_strategy import TraderVicStrategy
    from reports.backtest import run_backtest

    strategy = TraderVicStrategy(initial_capital=capital)
    strategy._stock_data = stock_data

    if quiet:
        with open(os.devnull, 'w') as f, redirect_stdout(f):
            result = run_backtest(strategy, stock_data, csi300, sh_index)
    else:
        result = run_backtest(strategy, stock_data, csi300, sh_index)

    metrics = result.compute_metrics()

    return {
        "total_return": metrics.get("total_return", -1.0),
        "annual_return": metrics.get("annual_return", -1.0),
        "max_drawdown": metrics.get("max_drawdown", -1.0),
        "win_rate": metrics.get("win_rate", 0.0),
        "sharpe": metrics.get("sharpe_ratio", -10.0),
        "num_trades": metrics.get("total_trades", 0),
        "profit_factor": metrics.get("profit_factor", 0.0),
    }


def score(m: dict) -> float:
    s = min(max(m["sharpe"], -2), 3) / 3
    w = min(m["win_rate"], 0.6)
    r = min(max(m["annual_return"], -0.3), 0.3) / 0.3
    t = min(m["num_trades"] / 100, 1.0)
    return s * 0.4 + w * 0.3 + r * 0.2 + t * 0.1


PARAM_GRID = {
    "TRENDLINE_TOUCH_TOLERANCE": [0.02, 0.03, 0.04],
    "TWOB_RETRACE_THRESHOLD": [0.005, 0.01, 0.02],
    "FOUR_DAY_REVERSAL_THRESHOLD": [0.02, 0.04],
    "THREE_DAY_PULLBACK_MIN": [0.01, 0.03],
    "THREE_DAY_PULLBACK_MAX": [0.08, 0.12],
    "RISK_PCT": [0.01, 0.02],
    "TIME_STOP_MAX_BARS": [8, 12],
}

ALL_COMBOS = list(dict(zip(PARAM_GRID.keys(), combo)) for combo in product(*PARAM_GRID.values()))


def sample_combos(n: int) -> list[dict]:
    if n >= len(ALL_COMBOS):
        return ALL_COMBOS
    return random.sample(ALL_COMBOS, n)


def walk_forward_search(
    stock_data, csi300, sh_index, window_years: int = 3, step_years: int = 1,
    mode: str = "random", samples: int = 30, quiet: bool = True,
):
    all_dates = sorted(csi300.index)
    if not isinstance(all_dates, pd.DatetimeIndex):
        all_dates = pd.DatetimeIndex(all_dates)

    start_date = all_dates[0]
    end_date = all_dates[-1]

    from datetime import timedelta
    from dateutil.relativedelta import relativedelta

    print(f"Data: {start_date.date()} ~ {end_date.date()}")
    print(f"Window: {window_years}yr IS + 1yr OOS, step={step_years}yr, samples={samples}")
    print(f"Params: {list(PARAM_GRID.keys())}\n")

    results = []
    is_start_date = start_date
    window_idx = 0

    while True:
        is_end_date = is_start_date + relativedelta(years=window_years) - timedelta(days=1)
        oos_start_date = is_start_date + relativedelta(years=window_years)
        oos_end_date = min(oos_start_date + relativedelta(years=2) - timedelta(days=1), end_date)

        if oos_start_date > end_date:
            break

        is_mask = (all_dates >= is_start_date) & (all_dates <= is_end_date)
        is_data = csi300.loc[all_dates[is_mask]]
        if len(is_data) < 400:
            is_start_date = is_start_date + relativedelta(years=step_years)
            continue

        combos = sample_combos(samples) if mode == "random" else ALL_COMBOS

        best_score = -999
        best_params = None
        best_metrics = None

        for params in combos:
            apply_params(params)
            m = run_single_backtest(stock_data, is_data, sh_index, quiet=quiet)
            s = score(m) if m["num_trades"] >= 5 else -999

            if s > best_score:
                best_score = s
                best_params = params
                best_metrics = m

        if best_params is None or best_metrics["num_trades"] < 5:
            is_start_date = is_start_date + relativedelta(years=step_years)
            continue

        oos_mask = (all_dates >= oos_start_date) & (all_dates <= oos_end_date)
        oos_data = csi300.loc[all_dates[oos_mask]]

        oos_m = None
        if len(oos_data) >= 100:
            apply_params(best_params)
            oos_m = run_single_backtest(stock_data, oos_data, sh_index, quiet=quiet)

        row = {
            "window": window_idx + 1,
            "is_start": str(is_start_date.date()), "is_end": str(is_end_date.date()),
            "oos_start": str(oos_start_date.date()), "oos_end": str(oos_end_date.date()),
            "is_score": best_score,
            "is_return": best_metrics["annual_return"],
            "is_win_rate": best_metrics["win_rate"],
            "is_sharpe": best_metrics["sharpe"],
            "is_trades": best_metrics["num_trades"],
            "oos_return": oos_m["annual_return"] if oos_m else None,
            "oos_win_rate": oos_m["win_rate"] if oos_m else None,
            "oos_sharpe": oos_m["sharpe"] if oos_m else None,
            "oos_trades": oos_m["num_trades"] if oos_m else None,
        }
        row.update(best_params)
        results.append(row)

        print(f"W{window_idx+1}: IS={is_start_date.date()}~{is_end_date.date()}")
        print(f"     IS: ret={best_metrics['annual_return']:.1%} wr={best_metrics['win_rate']:.1%} sh={best_metrics['sharpe']:.2f} tr={best_metrics['num_trades']}")
        if oos_m:
            print(f"     OOS: ret={oos_m['annual_return']:.1%} wr={oos_m['win_rate']:.1%} sh={oos_m['sharpe']:.2f} tr={oos_m['num_trades']}")
        print(f"     params: {best_params}\n")

        is_start_date = is_start_date + relativedelta(years=step_years)
        window_idx += 1

    return results


def main():
    parser = argparse.ArgumentParser(description="Walk-Forward 参数优化")
    parser.add_argument("--data-dir", type=str, default="data")
    parser.add_argument("--output", type=str, default="tools/param_results.csv")
    parser.add_argument("--mode", type=str, default="random", choices=["random", "exhaustive"])
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--window", type=int, default=3)
    parser.add_argument("--step", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)

    print("Loading data...")
    stock_data, csi300, sh_index = load_data(args.data_dir)
    if not stock_data:
        print("Error: no data found")
        return

    t0 = time.time()
    results = walk_forward_search(
        stock_data, csi300, sh_index,
        window_years=args.window, step_years=args.step,
        mode=args.mode, samples=args.samples, quiet=True,
    )

    if results:
        df = pd.DataFrame(results)
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        df.to_csv(args.output, index=False)
        print(f"\nSaved to: {args.output} ({len(df)} windows)")

        oos_cols = ["oos_return", "oos_win_rate", "oos_sharpe"]
        oos_df = df[oos_cols].dropna()
        if len(oos_df) > 0:
            print(f"\nOOS Avg (N={len(oos_df)}):")
            print(f"  Return: {oos_df['oos_return'].mean():.1%}")
            print(f"  WinRate: {oos_df['oos_win_rate'].mean():.1%}")
            print(f"  Sharpe: {oos_df['oos_sharpe'].mean():.2f}")

            param_cols = [c for c in df.columns if c in PARAM_GRID]
            print("\nBest Params (median OOS Sharpe):")
            for col in param_cols:
                best_val = df.groupby(col)["oos_sharpe"].median().idxmax()
                print(f"  {col}: {best_val}")

    t = time.time() - t0
    print(f"\nTime: {t/60:.1f} min")


if __name__ == "__main__":
    main()
