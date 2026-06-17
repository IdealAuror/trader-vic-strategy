"""每日盘面 HTML 报告生成（Jinja2 模板）"""

import os
from datetime import datetime
from typing import Optional

from trader_vic.config import WATCHLIST


def generate_daily_report(
    strategy,
    market_env: str,
    env_adapt: dict,
    regime: str,
    output_path: str = "output/daily_report.html",
) -> str:
    """生成每日盘面 HTML 报告

    Args:
        strategy: TraderVicStrategy 实例（含组合状态）
        market_env: 当前市场环境
        env_adapt: 环境适配参数
        regime: 基本面方向
        output_path: HTML 文件输出路径

    Returns:
        HTML 文件路径
    """
    today = datetime.now().strftime("%Y-%m-%d")
    summary = strategy.get_summary()
    positions = strategy.pm.positions
    trades = strategy.pm.trades

    # 持仓行
    pos_rows = ""
    for ticker, pos in positions.items():
        pos_rows += f"""
        <tr>
            <td>{ticker}</td>
            <td>{pos.shares}</td>
            <td>{pos.entry_price:.2f}</td>
            <td>{pos.stop:.2f}</td>
            <td>{pos.target:.2f}</td>
            <td>{pos.bars_held}</td>
        </tr>"""

    pos_rows = pos_rows or "<tr><td colspan='6'>无持仓</td></tr>"

    # 最近交易
    trade_rows = ""
    for t in trades[-20:]:
        direction = "买入" if getattr(t, 'direction', 1) > 0 else "卖出"
        trade_rows += f"""
        <tr>
            <td>{getattr(t, 'ticker', '')}</td>
            <td>{direction}</td>
            <td>{getattr(t, 'entry_price', 0):.2f}</td>
            <td>{getattr(t, 'exit_price', 0):.2f}</td>
            <td>{getattr(t, 'pnl', 0):+.0f}</td>
            <td>{getattr(t, 'exit_reason', '')}</td>
        </tr>"""

    # 环境适配参数
    env_params = "<br>".join(
        f"{k}: {v}" for k, v in env_adapt.items()
    )

    html = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<title>Trader Vic 每日报告 - {today}</title>
<style>
body {{ font-family: 'Microsoft YaHei', sans-serif; margin: 20px; background: #f8f9fa; }}
h1 {{ color: #2c3e50; font-size: 1.5em; }}
.section {{ background: white; border-radius: 8px; padding: 15px; margin: 10px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.9em; }}
th {{ background: #2c3e50; color: white; padding: 8px; text-align: left; }}
td {{ padding: 6px 8px; border-bottom: 1px solid #eee; }}
.bull {{ color: #e74c3c; }}
.bear {{ color: #27ae60; }}
.neutral {{ color: #f39c12; }}
.badge {{ display: inline-block; padding: 3px 8px; border-radius: 4px; font-size: 0.85em; }}
.badge-bull {{ background: #fde8e8; color: #e74c3c; }}
.badge-bear {{ background: #e8f8e8; color: #27ae60; }}
.badge-neutral {{ background: #fef3e2; color: #f39c12; }}
</style></head><body>
<h1>Trader Vic 每日盘面指导报告</h1>
<p>📅 {today}</p>

<div class="section">
<h2>市场概览</h2>
<table>
<tr><td>市场环境</td><td><strong>{market_env}</strong></td></tr>
<tr><td>基本面方向</td><td><span class="badge badge-{regime.lower()}">{regime}</span></td></tr>
<tr><td>组合市值</td><td>{summary.get('cash', 0):,.0f}</td></tr>
<tr><td>持仓数量</td><td>{summary.get('positions', 0)}</td></tr>
<tr><td>资本层级</td><td>Level {summary.get('capital_level', 1)}</td></tr>
<tr><td>总交易数</td><td>{summary.get('trades_total', 0)}</td></tr>
</table>
</div>

<div class="section">
<h2>环境适配参数</h2>
<pre>{env_params}</pre>
</div>

<div class="section">
<h2>当前持仓</h2>
<table><tr><th>股票</th><th>股数</th><th>入场价</th><th>止损</th><th>目标</th><th>持有天数</th></tr>
{pos_rows}
</table>
</div>

<div class="section">
<h2>最近交易</h2>
<table><tr><th>股票</th><th>方向</th><th>入场</th><th>出场</th><th>盈亏</th><th>原因</th></tr>
{trade_rows}
</table>
</div>

<div class="section">
<h2>候选池</h2>
<p>共 {len(set(WATCHLIST))} 只候选股</p>
</div>

<div class="section">
<h2>风险提醒</h2>
<table>
<tr><td>连续亏损</td><td>{getattr(strategy.loss_pause, 'loss_streak', 0)} 笔</td></tr>
<tr><td>可用现金</td><td>{strategy.pm.cash:,.0f}</td></tr>
<tr><td>风险占用</td><td>{strategy.pm.risk_used():,.0f}</td></tr>
</table>
</div>

<p style="color: #999; font-size: 0.8em; margin-top: 20px;">
报告生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
</p>
</body></html>"""

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path
