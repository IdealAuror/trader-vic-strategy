"""回测引擎 — 逐 K 线回测 + 绩效指标 + 多图表报告（仿 all-weather-portfolio 风格）"""

import os
import calendar
from datetime import datetime
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

from trader_vic.config import INITIAL_CAPITAL, MIN_DATA_BARS
from trader_vic.strategies.vic_strategy import TraderVicStrategy
from trader_vic.core.stock_pool import StockPool

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Microsoft YaHei", "SimHei", "Noto Sans SC"],
    "axes.unicode_minus": False,
    "figure.dpi": 150,
    "savefig.dpi": 150,
    "savefig.bbox": "tight",
    "savefig.facecolor": "white",
})

NAV_COLOR = "#2ecc71"
BENCH_COLOR = "#d35400"
TRADE_WIN = "#e74c3c"
TRADE_LOSS = "#3498db"


class BacktestResult:
    """回测结果"""

    def __init__(self):
        self.equity_curve: list[dict] = []
        self.trades: list = []
        self.metrics: dict = {}
        self.environment_returns: dict[str, list[float]] = {}
        self._chart_dir = ""
        self._html_path = ""

    def compute_metrics(self) -> dict:
        if not self.equity_curve:
            return {}
        df = pd.DataFrame(self.equity_curve)
        if "value" not in df.columns:
            return {}
        values = df["value"].values.astype(float)
        values = values[np.isfinite(values)]
        if len(values) == 0:
            return {}
        init_val = values[0] if len(values) > 0 else INITIAL_CAPITAL
        final_val = values[-1] if len(values) > 0 else init_val
        total_return = (final_val - init_val) / init_val if init_val != 0 else 0
        years = len(values) / 252 if len(values) > 0 else 1
        annual_return = (1 + total_return) ** (1 / years) - 1 if years > 0 and total_return > -1 else 0
        peak = np.maximum.accumulate(values)
        with np.errstate(divide="ignore", invalid="ignore"):
            drawdowns = (values - peak) / peak
            drawdowns = drawdowns[np.isfinite(drawdowns)]
        max_drawdown = abs(float(np.min(drawdowns))) if len(drawdowns) > 0 else 0
        if len(values) > 1:
            with np.errstate(divide="ignore", invalid="ignore"):
                rets = np.diff(values) / values[:-1]
                rets = rets[np.isfinite(rets)]
            sharpe = float(np.mean(rets) / np.std(rets) * np.sqrt(252)) if len(rets) > 0 and np.std(rets) > 0 else 0
        else:
            sharpe = 0
        win_trades = sum(1 for t in self.trades if getattr(t, 'pnl', None) is not None and t.pnl > 0)
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

    def _nav_series(self) -> pd.Series:
        df = pd.DataFrame(self.equity_curve)
        if df.empty:
            return pd.Series(dtype=float)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            return df.set_index("date")["value"]
        return pd.Series(df["value"].values, dtype=float)

    def plot_all(self, output_html: str, benchmark: Optional[pd.Series] = None):
        """生成全部图表 PNG 到 charts/ 目录 + HTML 报告"""
        output_dir = os.path.dirname(output_html)
        os.makedirs(output_dir, exist_ok=True)
        self._chart_dir = os.path.join(output_dir, "charts")
        os.makedirs(self._chart_dir, exist_ok=True)
        self._html_path = output_html
        nv = self._nav_series()
        if nv.empty:
            return None

        imgs = []
        imgs.append(("净值曲线与回撤", self._plot_nav_drawdown(nv, benchmark)))
        imgs.append(("月度收益热力图", self._plot_monthly_heatmap(nv)))
        imgs.append(("分年收益", self._plot_yearly_bar(nv)))
        imgs.append(("滚动一年收益", self._plot_rolling_returns(nv)))
        if self.trades:
            imgs.append(("交易盈亏分布", self._plot_trade_pnl(self.trades)))

        html = self._build_html(imgs, nv)
        with open(output_html, "w", encoding="utf-8") as f:
            f.write(html)
        return output_html

    # ──  Chart 1: NAV + Drawdown ──
    def _plot_nav_drawdown(self, nv: pd.Series, benchmark: Optional[pd.Series] = None) -> str:
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 9),
                                        sharex=True,
                                        gridspec_kw={"height_ratios": [3, 2], "hspace": 0.05})
        nv0 = nv.iloc[0]
        if nv0 == 0:
            return ""
        nav_norm = nv / nv0

        ax1.plot(nav_norm.index, nav_norm.values, color=NAV_COLOR, lw=1.2, label="Trader Vic")
        if benchmark is not None:
            bm0 = benchmark.iloc[0]
            if bm0 == 0:
                bm = benchmark
            else:
                bm = benchmark / bm0
            bm = bm.reindex(nav_norm.index, method="ffill")
            ax1.plot(bm.index, bm.values, color=BENCH_COLOR, ls="--", lw=0.9, alpha=0.7, label="沪深300")
        ax1.set_ylabel("净值")
        ax1.set_title("净值曲线与回撤", fontsize=13, fontweight="bold")
        ax1.legend(loc="upper left", frameon=False, fontsize=9)
        ax1.yaxis.set_major_formatter(mticker.StrMethodFormatter("{x:.1f}"))
        ax1.grid(True, alpha=0.3)

        dd = nv / nv.cummax() - 1
        ax2.fill_between(dd.index, 0, dd.values * 100, color="#e74c3c", alpha=0.15)
        ax2.plot(dd.index, dd.values * 100, color="#e74c3c", lw=0.8)
        ax2.set_ylabel("回撤 (%)")
        ax2.yaxis.set_major_formatter(mticker.StrMethodFormatter("{x:.1f}%"))
        ax2.grid(True, alpha=0.3)
        ax2.axhline(0, color="black", lw=0.5)

        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        ax2.tick_params(axis="x", labelsize=9)

        path = os.path.join(self._chart_dir, "nav_drawdown.png")
        fig.savefig(path)
        plt.close(fig)
        return path

    # ──  Chart 2: Monthly return heatmap ──
    def _plot_monthly_heatmap(self, nv: pd.Series) -> str:
        monthly = nv.resample("ME").apply(lambda x: x.iloc[-1] / x.iloc[0] - 1 if len(x) > 0 and x.iloc[0] != 0 else np.nan)
        monthly = monthly.replace([np.inf, -np.inf], np.nan).dropna()
        table = {}
        yearly_sum = {}
        for d, r in monthly.items():
            table.setdefault(d.year, {})[d.month] = r * 100
            yearly_sum[d.year] = (1 + yearly_sum.get(d.year, 0.0)) * (1 + r) - 1

        years = sorted(table.keys())
        months = list(range(1, 13))
        data = np.full((len(years), len(months)), np.nan)
        for i, y in enumerate(years):
            for j, m in enumerate(months):
                data[i, j] = table[y].get(m, np.nan)

        fig, ax = plt.subplots(figsize=(14, max(7, len(years) * 0.45)))
        v = max(abs(np.nanpercentile(data, 2)), abs(np.nanpercentile(data, 98)), 3)
        im = ax.imshow(data, cmap="RdYlGn", aspect="auto", vmin=-v, vmax=v)

        for i in range(len(years)):
            for j in range(len(months)):
                val = data[i, j]
                if not np.isnan(val):
                    ax.text(j, i, f"{val:.1f}", ha="center", va="center",
                            fontsize=7, color="black" if abs(val) < v * 0.65 else "white")

        ax.set_xticks(range(len(months)))
        ax.set_xticklabels([calendar.month_abbr[m] for m in months], fontsize=8)
        ax.set_yticks(range(len(years)))
        ylabels = [f"{y}  {yearly_sum.get(y, 0):+.1f}%" for y in years]
        ax.set_yticklabels(ylabels, fontsize=8, fontfamily="monospace")
        ax.set_title("月度收益热力图", fontsize=13, fontweight="bold")
        cbar = fig.colorbar(im, ax=ax, shrink=0.85, pad=0.01)
        cbar.set_label("%", fontsize=9)

        path = os.path.join(self._chart_dir, "heatmap.png")
        fig.savefig(path)
        plt.close(fig)
        return path

    # ──  Chart 3: Yearly bar ──
    def _plot_yearly_bar(self, nv: pd.Series) -> str:
        yearly = nv.resample("YE").apply(lambda x: x.iloc[-1] / x.iloc[0] - 1 if len(x) > 0 and x.iloc[0] != 0 else np.nan).dropna() * 100
        years = [d.year for d in yearly.index]

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8),
                                        gridspec_kw={"height_ratios": [2, 3], "hspace": 0.15})
        colors = [TRADE_WIN if v > 0 else TRADE_LOSS for v in yearly.values]
        ax1.bar(years, yearly.values, color=colors, alpha=0.8, edgecolor="white", lw=0.5)
        ax1.axhline(0, color="black", lw=0.5)
        ax1.set_ylabel("年收益 (%)")
        ax1.set_title("分年收益", fontsize=13, fontweight="bold")
        ax1.grid(True, alpha=0.3, axis="y")

        nav_norm = nv / nv.iloc[0]
        ax2.plot(nav_norm.index, nav_norm.values, color=NAV_COLOR, lw=1.2)
        ax2.set_ylabel("累计净值")
        ax2.grid(True, alpha=0.3)
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        ax2.tick_params(axis="x", labelsize=9)

        path = os.path.join(self._chart_dir, "yearly.png")
        fig.savefig(path)
        plt.close(fig)
        return path

    # ──  Chart 4: Rolling 1-year ──
    def _plot_rolling_returns(self, nv: pd.Series) -> str:
        daily_ret = nv.pct_change().dropna()
        rolling_ann = daily_ret.rolling(252).apply(
            lambda x: (1 + x).prod() ** (252 / len(x)) - 1 if len(x) > 0 else 0
        ) * 100
        rolling_dd = nv / nv.rolling(252, min_periods=252).max() - 1

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True,
                                        gridspec_kw={"height_ratios": [3, 2], "hspace": 0.05})
        ax1.plot(rolling_ann.index, rolling_ann.values, color="#3498db", lw=0.8)
        ax1.axhline(0, color="black", lw=0.5)
        ax1.set_ylabel("年化收益 (%)")
        ax1.set_title("滚动 1 年收益与回撤", fontsize=13, fontweight="bold")
        ax1.grid(True, alpha=0.3)

        ax2.fill_between(rolling_dd.index, 0, rolling_dd.values * 100, color="#e74c3c", alpha=0.15)
        ax2.plot(rolling_dd.index, rolling_dd.values * 100, color="#e74c3c", lw=0.8)
        ax2.set_ylabel("滚动回撤 (%)")
        ax2.grid(True, alpha=0.3)
        ax2.axhline(0, color="black", lw=0.5)

        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        ax2.tick_params(axis="x", labelsize=9)

        path = os.path.join(self._chart_dir, "rolling.png")
        fig.savefig(path)
        plt.close(fig)
        return path

    # ──  Chart 5: Trade PnL distribution ──
    def _plot_trade_pnl(self, trades: list) -> str:
        pnls = np.array([t.pnl for t in trades if getattr(t, 'pnl', None) is not None and t.pnl != 0], dtype=float)
        if len(pnls) == 0:
            return ""
        wins = pnls[pnls > 0]
        losses = pnls[pnls < 0]
        win_rate = len(wins) / len(pnls) * 100

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
        bins = 40
        ax1.hist(losses / 1000, bins=bins, color=TRADE_LOSS, alpha=0.7, label=f"亏损 ({len(losses)})")
        ax1.hist(wins / 1000, bins=bins, color=TRADE_WIN, alpha=0.7, label=f"盈利 ({len(wins)})")
        ax1.axvline(0, color="black", lw=0.5)
        ax1.set_xlabel("盈亏 (千元)")
        ax1.set_ylabel("次数")
        ax1.set_title(f"交易盈亏分布 (胜率 {win_rate:.1f}%)", fontsize=12, fontweight="bold")
        ax1.legend(fontsize=9)
        ax1.grid(True, alpha=0.3)

        cum = np.cumsum(pnls) / 1000
        ax2.plot(cum, color="#2c3e50", lw=1.0)
        ax2.fill_between(range(len(cum)), 0, cum, alpha=0.15, color="#2c3e50")
        ax2.axhline(0, color="black", lw=0.5)
        ax2.set_xlabel("交易序号")
        ax2.set_ylabel("累计盈亏 (千元)")
        ax2.set_title("累计盈亏曲线", fontsize=12, fontweight="bold")
        ax2.grid(True, alpha=0.3)

        path = os.path.join(self._chart_dir, "trades.png")
        fig.savefig(path)
        plt.close(fig)
        return path

    def _build_html(self, imgs: list[tuple[str, str]], nv: pd.Series) -> str:
        m = self.metrics

        def fmt(v, pct=False):
            if isinstance(v, float):
                return f"{v:.2%}" if pct else f"{v:.4f}"
            return str(v)

        img_tags = "\n".join(
            f'<div class="chart"><h3>{title}</h3><img src="charts/{Path(p).name}" alt="{title}"></div>'
            for title, p in imgs if p
        )

        trade_rows = ""
        if self.trades:
            for t in self.trades[-30:]:
                pnl_val = getattr(t, 'pnl', 0) or 0
                cls = "win" if pnl_val > 0 else "loss"
                trade_rows += (
                    f"<tr class='{cls}'><td>{getattr(t, 'ticker', '')}</td>"
                    f"<td>{'多' if getattr(t, 'direction', 1) > 0 else '空'}</td>"
                    f"<td>{getattr(t, 'entry_price', 0):.2f}</td>"
                    f"<td>{getattr(t, 'exit_price', 0):.2f}</td>"
                    f"<td>{getattr(t, 'pnl', 0):+.0f}</td>"
                    f"<td>{getattr(t, 'exit_reason', '')}</td></tr>\n"
                )

        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Trader Vic 回测报告</title>
<style>
* {{ box-sizing: border-box; }}
body {{ font-family: 'Microsoft YaHei', sans-serif; margin: 0; background: #f5f6fa; color: #2c3e50; }}
.header {{ background: linear-gradient(135deg, #2c3e50, #3498db); color: white; padding: 30px 40px; }}
.header h1 {{ margin: 0; font-size: 24px; }}
.header p {{ margin: 5px 0 0; opacity: 0.85; font-size: 14px; }}
.container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
.section {{ background: white; border-radius: 8px; padding: 20px; margin: 16px 0; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }}
.section h2 {{ margin: 0 0 12px; font-size: 18px; border-left: 4px solid #3498db; padding-left: 10px; }}
.metrics {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px; }}
.metric {{ background: #f8f9fa; border-radius: 6px; padding: 12px; text-align: center; }}
.metric .label {{ font-size: 12px; color: #7f8c8d; }}
.metric .value {{ font-size: 20px; font-weight: bold; }}
.metric .value.green {{ color: #27ae60; }}
.metric .value.red {{ color: #e74c3c; }}
img {{ max-width: 100%; height: auto; border-radius: 4px; }}
.chart {{ margin: 16px 0; }}
.chart h3 {{ font-size: 14px; color: #555; margin: 0 0 6px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th {{ background: #2c3e50; color: white; padding: 8px 10px; text-align: left; font-weight: 500; }}
td {{ padding: 6px 10px; border-bottom: 1px solid #eee; }}
tr.win td:nth-child(5) {{ color: #e74c3c; }}
tr.loss td:nth-child(5) {{ color: #3498db; }}
tr:hover td {{ background: #f8f9fa; }}
.footer {{ text-align: center; padding: 20px; color: #95a5a6; font-size: 12px; }}
</style></head><body>
<div class="header"><h1>Trader Vic 回测报告</h1>
<p>期间: {nv.index[0].strftime('%Y-%m-%d') if hasattr(nv.index[0], 'strftime') else str(nv.index[0])} ~ {nv.index[-1].strftime('%Y-%m-%d') if hasattr(nv.index[-1], 'strftime') else str(nv.index[-1])} | 交易: {m.get('total_trades', 0)} 笔 | 初始资本: {INITIAL_CAPITAL:,.0f}</p></div>
<div class="container">
<div class="section"><h2>绩效指标</h2><div class="metrics">
<div class="metric"><div class="label">总收益率</div><div class="value {'green' if m.get('total_return',0)>0 else 'red'}">{fmt(m.get('total_return',0), True)}</div></div>
<div class="metric"><div class="label">年化收益</div><div class="value {'green' if m.get('annual_return',0)>0 else 'red'}">{fmt(m.get('annual_return',0), True)}</div></div>
<div class="metric"><div class="label">最大回撤</div><div class="value red">{fmt(m.get('max_drawdown',0), True)}</div></div>
<div class="metric"><div class="label">夏普比率</div><div class="value">{fmt(m.get('sharpe_ratio',0))}</div></div>
<div class="metric"><div class="label">胜率</div><div class="value">{fmt(m.get('win_rate',0), True)}</div></div>
<div class="metric"><div class="label">交易次数</div><div class="value">{m.get('total_trades',0)}</div></div>
<div class="metric"><div class="label">期末净值</div><div class="value">{m.get('final_value',0):,.0f}</div></div>
<div class="metric"><div class="label">回测年数</div><div class="value">{m.get('years',0):.1f}</div></div>
</div></div>
{img_tags}
<div class="section"><h2>最近交易 (30 笔)</h2>
<table><tr><th>股票</th><th>方向</th><th>入场</th><th>出场</th><th>盈亏</th><th>原因</th></tr>
{trade_rows or '<tr><td colspan="6">无交易记录</td></tr>'}
</table></div>
</div>
<div class="footer">报告生成: {datetime.now().strftime("%Y-%m-%d %H:%M")}</div>
</body></html>"""


def run_backtest(
    strategy: TraderVicStrategy,
    stock_data: dict[str, pd.DataFrame],
    index_data: pd.DataFrame,
    sh_index_data: Optional[pd.DataFrame] = None,
    output_dir: str = "output",
) -> BacktestResult:
    """运行回测"""
    os.makedirs(output_dir, exist_ok=True)
    result = BacktestResult()

    all_dates = sorted(set(index_data.index))
    if not all_dates:
        print("错误：指数数据为空")
        return result

    pool = StockPool()
    for ticker in stock_data:
        pool.register(ticker)

    print(f"回测期间: {all_dates[0].date()} ~ {all_dates[-1].date()}")
    print(f"总交易日: {len(all_dates)}")
    print(f"候选池: {len(stock_data)} 只（动态评估）")

    for i, date in enumerate(all_dates):
        if i % 500 == 0:
            s = pool.get_summary()
            print(f"  处理中: {date.date()} ({i}/{len(all_dates)}) | 活跃: {s['active']}")

        bar_data = {}
        for ticker, df in stock_data.items():
            if date not in df.index:
                continue
            status = pool.evaluate(ticker, df.loc[:date], date)
            if status == "active":
                row = df.loc[date]
                bar_data[ticker] = row

        csi300_bar = index_data.loc[date]
        csi300_history = index_data.loc[:date]

        sh_bar = sh_history = None
        if sh_index_data is not None and date in sh_index_data.index:
            sh_bar = sh_index_data.loc[date]
            sh_history = sh_index_data.loc[:date]

        strategy.next(bar_data, csi300_bar, csi300_history, sh_bar, sh_history, date)

    result.trades = list(strategy.pm.trades)
    result.equity_curve = strategy.equity_curve

    m = result.compute_metrics()
    print(f"\n回测结果:")
    print(f"  总收益率: {m.get('total_return', 0):.2%}")
    print(f"  年化收益: {m.get('annual_return', 0):.2%}")
    print(f"  最大回撤: {m.get('max_drawdown', 0):.2%}")
    print(f"  夏普比率: {m.get('sharpe_ratio', 0):.2f}")
    print(f"  胜率: {m.get('win_rate', 0):.2%}")
    print(f"  总交易: {m.get('total_trades', 0)}")

    return result
