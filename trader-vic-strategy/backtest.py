#!/usr/bin/env python3
"""回测入口

Usage:
    python backtest.py [--output output/backtest_result.html] [--capital 1000000]
"""

import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd

from trader_vic.config import WATCHLIST, INITIAL_CAPITAL
from trader_vic.strategies.vic_strategy import TraderVicStrategy
from reports.backtest import run_backtest


def load_csv_data(cache_dir: str = "data") -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    """从 CSV 加载数据"""
    stock_data = {}
    for ticker in set(WATCHLIST):
        path = os.path.join(cache_dir, f"{ticker}.csv")
        if os.path.exists(path):
            df = pd.read_csv(path, index_col="date", parse_dates=True)
            if len(df) >= 252:
                stock_data[ticker] = df

    # 沪深 300
    csi300 = None
    csi300_path = os.path.join(cache_dir, "sh000300.csv")
    if os.path.exists(csi300_path):
        csi300 = pd.read_csv(csi300_path, index_col="date", parse_dates=True)

    # 上证指数
    sh = None
    sh_path = os.path.join(cache_dir, "sh000001.csv")
    if os.path.exists(sh_path):
        sh = pd.read_csv(sh_path, index_col="date", parse_dates=True)

    return stock_data, csi300, sh


def main():
    parser = argparse.ArgumentParser(description="Trader Vic 回测")
    parser.add_argument("--output", type=str, default="output/backtest_result.html")
    parser.add_argument("--capital", type=float, default=INITIAL_CAPITAL)
    parser.add_argument("--data-dir", type=str, default="data")
    args = parser.parse_args()

    print("加载数据...")
    stock_data, csi300, sh_index = load_csv_data(args.data_dir)

    if not stock_data:
        print("错误：未找到数据。请先运行 python fetch.py")
        return

    if csi300 is None:
        print("错误：未找到沪深 300 数据")
        return

    print(f"  股票: {len(stock_data)} 只")
    print(f"  沪深 300: {len(csi300)} 行")

    strategy = TraderVicStrategy(initial_capital=args.capital)
    strategy._stock_data = stock_data

    print("\n开始回测...")
    result = run_backtest(strategy, stock_data, csi300, sh_index, output_dir=os.path.dirname(args.output))

    # 生成报告
    print(f"\n生成报告: {args.output}")
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    html_path = result.plot_equity_curve(args.output)
    print(f"完成！报告已保存到: {html_path}")


if __name__ == "__main__":
    main()
