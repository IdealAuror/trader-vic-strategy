#!/usr/bin/env python3
"""每日盘面报告生成入口

Usage:
    python daily_report.py [--output output/daily_report.html] [--capital 1000000]
"""

import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd

from trader_vic.config import WATCHLIST, INITIAL_CAPITAL
from trader_vic.strategies.vic_strategy import TraderVicStrategy
from trader_vic.data.providers import fetch_index
from trader_vic.core.market_env import MarketEnvClassifier
from reports.daily_html import generate_daily_report


def main():
    parser = argparse.ArgumentParser(description="Trader Vic 每日报告")
    parser.add_argument("--output", type=str, default="output/daily_report.html")
    parser.add_argument("--capital", type=float, default=INITIAL_CAPITAL)
    parser.add_argument("--data-dir", type=str, default="data")
    args = parser.parse_args()

    print("加载数据...")
    # 从缓存加载沪深300
    csi300_path = os.path.join(args.data_dir, "sh000300.csv")
    if not os.path.exists(csi300_path):
        print("未找到缓存数据，尝试在线拉取...")
        csi300 = fetch_index("sh000300")
    else:
        csi300 = pd.read_csv(csi300_path, index_col="date", parse_dates=True)

    if csi300.empty:
        print("错误：无沪深 300 数据")
        return

    # 使用最新数据
    latest = csi300.tail(100)
    latest_bar = latest.iloc[-1]

    # 构建虚拟 bar_data（简化演示）
    bar_data = {}
    for ticker in set(WATCHLIST):
        bar_data[ticker] = latest_bar

    # 运行策略
    strategy = TraderVicStrategy(initial_capital=args.capital)
    strategy.fundamental.update()
    orders = strategy.next(bar_data, latest_bar, latest)

    # 环境分类
    env_classifier = MarketEnvClassifier()
    weekly = latest.resample("W-FRI", label="right").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()
    env = env_classifier.classify(latest, weekly)
    env_adapt = env_classifier.get_env_adapt(env)

    # 生成报告
    print(f"市场环境: {env}")
    print(f"基本面方向: {strategy.fundamental.get_regime()}")
    print(f"生成报告...")

    html_path = generate_daily_report(
        strategy, env, env_adapt, strategy.fundamental.get_regime(), args.output
    )
    print(f"报告已保存到: {html_path}")


if __name__ == "__main__":
    main()
