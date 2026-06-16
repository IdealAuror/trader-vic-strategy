"""回测引擎 — 逐 K 线回测 + 绩效指标计算 + matplotlib 图表"""

import os
from datetime import datetime
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from trader_vic.config import INITIAL_CAPITAL, BACKTEST_START, COMMISSION_RATE, STAMP_TAX_RATE, SLIPPAGE
from trader_vic.strategies.vic_strategy import TraderVicStrategy


class BacktestResult:
    """回测结果"""

    def __init__(self):
        self.equity_curve: list[dict] = []
        self.trades: list = []
        self.metrics: dict = {}
        self.environment_returns: dict[str, list[float]] = {}

    def compute_metrics(self) -> dict:
        """计算绩效指标"""
        if not self.equity_curve:
            return {}

        df = pd.DataFrame(self.equity_curve)
        if "value" not in df.columns:
            return {}

        values = df["value"].values
        init_val = values[0] if len(values) > 0 else INITIAL_CAPITAL
        final_val = values[-1] if len(values) > 0 else init_val

        total_return = (final_val - init_val) / init_val

        # 年化收益
        years = len(values) / 252 if len(values) > 0 else 1
        annual_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0

        # 最大回撤
        peak = np.maximum.accumulate(values)
        drawdowns = (values - peak) / peak
        max_drawdown = abs(float(np.min(drawdowns))) if len(drawdowns) > 0 else 0

        # 夏普比
        returns = np.diff(values) / values[:-1] if len(values) > 1 else np.array([0])
        sharpe = float(np.mean(returns) / np.std(returns) * np.sqrt(252)) if np.std(returns) > 0 else 0

        # 胜率
        win_trades = sum(1 for t in self.trades if t.pnl > 0)
        total_trades = len(self.trades)
        win_rate = win_trades / total_trades if total_trades > 0 else 0

        self.metrics = {
            "total_return": total_return,
            "annual_return": annual_return,
            "max_drawdown": max_drawdown,
            "sharpe_ratio": sharpe,
            "win_rate": win_rate,
            "total_trades": total_trades,
            "years": years,
            "final_value": final_val,
        }
        return self.metrics

    def plot_equity_curve(self, output_path: str, benchmark: Optional[pd.Series] = None) -> str:
        """绘制净值曲线

        Returns:
            HTML 文件路径
        """
        df = pd.DataFrame(self.equity_curve)
        if df.empty:
            return ""

        fig, axes = plt.subplots(2, 1, figsize=(12, 8), gridspec_kw={"height_ratios": [3, 1]})

        # 净值曲线
        ax1 = axes[0]
        ax1.plot(df.index, df["value"] / df["value"].iloc[0], label="Trader Vic", color="blue", linewidth=2)
        if benchmark is not None:
            bench = benchmark / benchmark.iloc[0]
            bench = bench.reindex(df.index, method="ffill")
            ax1.plot(bench.index, bench.values, label="CSI 300", color="gray", linewidth=1, alpha=0.7)
        ax1.set_title("Equity Curve", fontsize=14)
        ax1.set_ylabel("Cumulative Return")
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        # 回撤曲线
        ax2 = axes[1]
        values = df["value"].values
        peak = np.maximum.accumulate(values)
        drawdowns = (values - peak) / peak * 100
        ax2.fill_between(df.index, 0, drawdowns, color="red", alpha=0.3)
        ax2.set_ylabel("Drawdown %")
        ax2.set_xlabel("Bar")
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        plt.savefig(output_path.replace(".html", ".png"), dpi=100)
        plt.close()

        # 生成 HTML
        html = self._to_html(output_path)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
        return output_path

    def _to_html(self, image_path: str) -> str:
        """生成 HTML 报告"""
        img_src = os.path.basename(image_path).replace(".html", ".png")

        metrics_rows = ""
        for key, val in self.metrics.items():
            if isinstance(val, float):
                if "return" in key or "drawdown" in key or "rate" in key:
                    metrics_rows += f"<tr><td>{key}</td><td>{val:.2%}</td></tr>\n"
                else:
                    metrics_rows += f"<tr><td>{key}</td><td>{val:.4f}</td></tr>\n"
            else:
                metrics_rows += f"<tr><td>{key}</td><td>{val}</td></tr>\n"

        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Trader Vic 回测报告</title>
<style>
body {{ font-family: sans-serif; margin: 20px; }}
h1 {{ color: #333; }}
table {{ border-collapse: collapse; margin: 10px 0; }}
th, td {{ border: 1px solid #ccc; padding: 8px 12px; text-align: right; }}
th {{ background: #f5f5f5; }}
img {{ max-width: 100%; height: auto; }}
</style></head><body>
<h1>Trader Vic 回测报告</h1>
<h2>绩效指标</h2>
<table><tr><th>Metric</th><th>Value</th></tr>
{metrics_rows}
</table>
<h2>净值曲线</h2>
<img src="{img_src}" alt="Equity Curve">
<h2>交易明细</h2>
<table><tr><th>Ticker</th><th>方向</th><th>入场</th><th>出场</th><th>盈亏</th><th>原因</th></tr>
{"".join(
    f"<tr><td>{t.ticker}</td><td>{'多' if t.direction>0 else '空'}</td>"
    f"<td>{t.entry_price:.2f}</td><td>{t.exit_price:.2f}</td>"
    f"<td>{t.pnl:.0f}</td><td>{t.exit_reason}</td></tr>"
    for t in self.trades[-50:]  # 最近 50 笔
)}
</table>
</body></html>"""


def run_backtest(
    strategy: TraderVicStrategy,
    stock_data: dict[str, pd.DataFrame],
    index_data: pd.DataFrame,
    sh_index_data: Optional[pd.DataFrame] = None,
    output_dir: str = "output",
) -> BacktestResult:
    """运行回测

    Args:
        strategy: 策略实例
        stock_data: {ticker: OHLCV DataFrame}
        index_data: 沪深 300 DataFrame
        sh_index_data: 上证指数 DataFrame（可选）
        output_dir: 输出目录

    Returns:
        BacktestResult
    """
    os.makedirs(output_dir, exist_ok=True)
    result = BacktestResult()

    # 对齐日期
    all_dates = None
    for df in stock_data.values():
        dates = set(df.index)
        if all_dates is None:
            all_dates = dates
        else:
            all_dates &= dates
    all_dates &= set(index_data.index)

    if not all_dates:
        print("错误：无共同交易日")
        return result

    all_dates = sorted(all_dates)
    print(f"回测期间: {all_dates[0].date()} ~ {all_dates[-1].date()}")
    print(f"总交易日: {len(all_dates)}")

    for i, date in enumerate(all_dates):
        if i % 500 == 0:
            print(f"  处理中: {date.date()} ({i}/{len(all_dates)})")

        # 构建当日 bar_data
        bar_data = {}
        for ticker, df in stock_data.items():
            if date in df.index:
                row = df.loc[date]
                bar_data[ticker] = row

        csi300_bar = index_data.loc[date]
        csi300_history = index_data.loc[:date]

        sh_bar = None
        sh_history = None
        if sh_index_data is not None and date in sh_index_data.index:
            sh_bar = sh_index_data.loc[date]
            sh_history = sh_index_data.loc[:date]

        # 策略决策
        orders = strategy.next(bar_data, csi300_bar, csi300_history, sh_bar, sh_history, date)

        # 记录
        result.trades.extend(strategy.pm.trades_today)

    # 收集净值曲线
    result.equity_curve = strategy.equity_curve

    # 计算指标
    m = result.compute_metrics()
    print(f"\n回测结果:")
    print(f"  总收益率: {m.get('total_return', 0):.2%}")
    print(f"  年化收益: {m.get('annual_return', 0):.2%}")
    print(f"  最大回撤: {m.get('max_drawdown', 0):.2%}")
    print(f"  夏普比率: {m.get('sharpe_ratio', 0):.2f}")
    print(f"  胜率: {m.get('win_rate', 0):.2%}")
    print(f"  总交易: {m.get('total_trades', 0)}")

    return result
