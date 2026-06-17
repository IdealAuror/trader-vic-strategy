"""Trader Vic 量化策略 — 全局配置

所有可调参数集中管理。修改策略行为只需改此文件。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ============================================================================
# 风险参数
# ============================================================================

# 单笔最大风险 = 可用资本 × RISK_PCT（ch03=1~2%, ch18=3%，可配置）
# A股波动大，1.5% 比美股 2% 更合适
RISK_PCT = 0.015

# 总风险敞口上限 = 资本 × TOTAL_RISK_BUDGET × position_cap
TOTAL_RISK_BUDGET = 0.15

# 连续亏损 N 笔后暂停交易（ch12）
CONSECUTIVE_LOSS_PAUSE = 5
CONSECUTIVE_LOSS_BAR = 20  # 暂停 N 根 K 线

# ============================================================================
# 资金管理
# ============================================================================

CAPITAL_LEVEL2_THRESHOLD = 1.10    # 盈利 10% 进入第 2 层（一致性获利）
CAPITAL_LEVEL3_THRESHOLD = 2.00    # 银行利润翻倍进入第 3 层（卓越报酬）
MAX_DRAWDOWN_LEVEL1 = 0.20         # 回撤 20% 退回第 1 层（保障资本）

# 层级对应的安全系数（凯利乘数）
KELLY_SAFETY = {1: 0.25, 2: 0.50, 3: 0.75}

# ============================================================================
# 交易成本（A 股）
# ============================================================================

COMMISSION_RATE = 0.0003    # 佣金 万三，双边
STAMP_TAX_RATE = 0.001      # 印花税 千一，仅卖出
MIN_COMMISSION = 5.0        # 最低佣金 5 元
SLIPPAGE = 0.001            # 滑点 0.1%

# ============================================================================
# 数据参数
# ============================================================================

DATA_ADJUST = "qfq"          # 前复权
MIN_DATA_BARS = 252          # 最少 1 年数据
MAX_NAN_RATIO = 0.05         # 最大允许 NaN 比例
SUSPEND_THRESHOLD = 20       # 连续 N 日价格不变 = 停牌

# ============================================================================
# 宏观-战术冲突处理
# ============================================================================

MACRO_CONFLICT_MODE = "FILTER"   # FILTER | REDUCE | IGNORE
MACRO_CONSENSUS = "MAJORITY"     # UNANIMOUS | MAJORITY | WEIGHTED_AVERAGE

# A 股普通账户只能做多，融券受限
SHORT_ALLOWED = False

# ============================================================================
# 多维基本面评分参数
# ============================================================================
# 四维度权重（月度更新），综合输出风险预算

FUNDAMENTAL_DIMENSIONS = {
    "liquidity": 0.35,       # 宏观流动性：M2/PMI/Shibor
    "leverage": 0.25,        # 市场杠杆：融资余额趋势
    "valuation": 0.25,       # 估值分位：沪深300 PE分位
    "volume_trend": 0.15,    # 量能确认：市场成交量趋势
}

# 风险预算映射：综合得分 → 仓位系数
FUNDAMENTAL_RISK_BUDGET_MAP = [
    (0.40, 1.00),    # 积极：满仓运行
    (0.00, 0.75),    # 中性偏多
    (-0.40, 0.50),   # 中性偏空
    (-2.00, 0.30),   # 防御：大幅降仓
]

# 量能确认阈值（日频，在 market_env 中计算）
VOLUME_SURGE_THRESHOLD = 1.20     # 20日均量 / 60日均量 > 1.2 = 放量
VOLUME_SHRINK_THRESHOLD = 0.80    # 20日均量 / 60日均量 < 0.8 = 缩量

# ============================================================================
# A 股牛熊统计参数（替代美股默认值）
# ============================================================================
# 沪深300: 牛市均值 14 个月（vs 道指 28 个月），熊市均值 7 个月（vs 13 个月）

CN_BULL_MEAN_MONTHS = 14
CN_BULL_STD_MONTHS = 8
CN_BEAR_MEAN_MONTHS = 7
CN_BEAR_STD_MONTHS = 4

# ============================================================================
# 信号可靠度概率表
# ============================================================================
# 来源：cheatsheet.md 信号矩阵 + ch27 统计数据
# 只有 四天准则(75%)、三天回调(94.4%)、趋势跟踪基础(33%) 有书中硬数据
# 其余为设计者从序数评级映射的估计值

SIGNAL_PROBABILITIES = {
    "123_FULL": 0.67,               # 1-2-3 三步全确认（最高可靠度评级）
    "123_CONFIRMING": 0.50,         # 仅步骤 1+2
    "2B_MEDIUM": 0.50,              # 2B 中期 3-5 天
    "2B_LONG": 0.55,                # 2B 长期
    "FOUR_DAY_RULE": 0.75,          # 四天准则 — 书中硬数据 ✅
    "THREE_DAY_PULLBACK": 0.944,    # 三天回调买入 — 书中硬数据 ✅
    "THREE_DAY_HL": 0.55,           # 三天高低价规则（ch27）
    "NARROW_RANGE_BREAKOUT": 0.65,  # 窄幅盘整突破
    "ABC_C_POINT": 0.60,            # ABC C 点顺势建仓
    "GAP_WITH_TRENDLINE": 0.55,     # 缺口穿越趋势线 + 确认
    "TREND_FOLLOWING_BASE": 0.33,   # 趋势跟踪基础胜率 — 书中数据 ✅
    "STEP2_ONLY": 0.25,             # 单一步骤 2（不可单独使用）
}

# 信号置信度区间（用于敏感性分析）
SIGNAL_CONFIDENCE_RANGE = 0.1  # ±10%

# ============================================================================
# 市场环境 → 策略适配表
# ============================================================================

ENV_ADAPTATION = {
    "TRENDING_BULL": {
        "signal_boost": 1.2,
        "kelly_mult": 1.0,
        "min_rrr": 2.5,
        "position_cap": 1.0,
        "preferred_signals": ["123_FULL", "123_CONFIRMING", "2B_MEDIUM", "THREE_DAY_PULLBACK"],
        "mean_reversion": False,
    },
    "AGING_BULL": {
        "signal_boost": 1.0,
        "kelly_mult": 0.7,
        "min_rrr": 3.0,
        "position_cap": 0.8,
        "preferred_signals": ["2B_MEDIUM", "FOUR_DAY_RULE"],
        "mean_reversion": True,
        "tight_stop": True,
    },
    "TRENDING_BEAR": {
        "signal_boost": 0.3,
        "kelly_mult": 0.3,
        "min_rrr": 5.0,
        "position_cap": 0.3,
        "preferred_signals": [],
        "short_allowed": True,
        "cash_bias": True,
        "cash_ratio": 0.80,
    },
    "RANGE_BOUND": {
        "signal_boost": 0.4,
        "kelly_mult": 0.3,
        "min_rrr": 4.0,
        "position_cap": 0.3,
        "preferred_signals": ["NARROW_RANGE_BREAKOUT", "THREE_DAY_PULLBACK"],
        "mean_reversion": True,
        "skip_trend_signals": True,
        "cash_ratio": 0.60,
    },
    "HIGH_VOL": {
        "signal_boost": 0.5,
        "kelly_mult": 0.4,
        "min_rrr": 4.0,
        "position_cap": 0.4,
        "preferred_signals": ["2B_MEDIUM", "FOUR_DAY_RULE"],
    },
    "LOW_VOL": {
        "signal_boost": 0.8,
        "kelly_mult": 0.7,
        "min_rrr": 3.0,
        "position_cap": 0.7,
        "preferred_signals": ["123_FULL", "123_CONFIRMING", "THREE_DAY_PULLBACK"],
    },
    "CRISIS": {
        "signal_boost": 0.0,
        "kelly_mult": 0.0,
        "min_rrr": 999,
        "position_cap": 0.0,
        "preferred_signals": [],
        "force_cash": True,
    },
}

# ============================================================================
# 候选池（50 只沪深 300 成分股，去重后 ~48 只）
# ============================================================================
# 覆盖：金融、消费、医药、制造、能源、科技板块

WATCHLIST = [
    "000001", "000002", "000333", "000568", "000651",  # 平安/万科/美的/泸州老窖/格力
    "000858", "002415", "300750", "600036", "600276",  # 五粮液/海康/宁德/招商/恒瑞
    "600309", "600519", "600585", "600690", "600887",  # 万华/茅台/海螺/海尔/伊利
    "600900", "601012", "601166", "601318", "601398",  # 长江/隆基/兴业/平安/工行
    "601857", "601888", "603259", "000725", "002304",  # 中石油/中免/药明/京东方/洋河
    "600028", "600030", "600104", "600196", "600547",  # 中石化/中信/上汽/复星/山东黄金
    "600570", "600809", "601088", "601288", "601628",  # 恒生/汾酒/神华/农行/人寿
    "601668", "601766", "601939", "603288", "000538",  # 建筑/中车/建行/海天/云南白药
    "000596", "002007", "002142", "300124", "600438",  # 古井/华兰/宁波/汇川/通威
    "601211", "603993",                                 # 国泰/洛钼
]

# ============================================================================
# 回测参数
# ============================================================================

BACKTEST_START = "2010-01-01"
BACKTEST_END = None  # None = 截至最新数据
INITIAL_CAPITAL = 1_000_000  # 初始资本 100 万

# ============================================================================
# 信号检测参数
# ============================================================================

# 1-2-3 准则
TRENDLINE_TOUCH_TOLERANCE = 0.02    # 趋势线接触容差 2%

# 2B 准则
TWOB_RETRACE_THRESHOLD = 0.01       # 折返阈值 1%

# 四天准则
FOUR_DAY_LOOKBACK = 24              # 24 天内 75% 反转（ch27 统计）
FOUR_DAY_REVERSAL_THRESHOLD = 0.03  # 反转幅度阈值 3%

# 三天回调
THREE_DAY_PULLBACK_MIN = 0.02      # 最小回调幅度 2%
THREE_DAY_PULLBACK_MAX = 0.10      # 最大回调幅度 10%（超出的可能是反转）

# 时间止损
TIME_STOP_MAX_BARS = 10            # 入场后最多 10 根 K 线

# 止盈
TAKE_PROFIT_RATIO = 0.50           # 达目标平 50%
TRAILING_STOP_ACTIVATE = 0.30      # 盈利达 RRR 的 30% 时移止损保本（A股反弹短，比美股50%更紧）

# A股专项参数
A_SHARE_BEAR_CASH_RATIO = 0.70     # 熊市保留 70% 现金
A_SHARE_MIN_VOL_RATIO = 0.6        # 当日成交量 < 5日均量×0.6 则跳过入场
A_SHARE_DUAL_TF_REQUIRED = True    # 周线+日线必须同向
ANTI_CHASE_MAX_INTRADAY = 0.03     # 当日涨幅 >3% 不追
ANTI_CHASE_MAX_GAP = 0.05          # 跳空高开 >5% 不追
LIMIT_UP_DOWN_PROXIMITY = 0.09     # 距涨跌停 <9% 不交易
VOL_SURGE_MULTIPLIER = 1.5          # 成交量放大倍数阈值
VOL_SURGE_LOOKBACK = 20             # 成交量均线周期
VOL_SURGE_CONFIDENCE_BOOST = 1.3    # 放量信号置信度加成

# ============================================================================
# K 线 OHLCV 列名
# ============================================================================

OHLCV = ["open", "high", "low", "close", "volume"]

# ============================================================================
# 技术指标参数
# ============================================================================

# ── 窄幅盘整参数 ──
NARROW_RANGE_LOOKBACK = 15
NARROW_RANGE_MAX_PCT = 0.08
NARROW_RANGE_VOL_MULT = 1.3

# ── ABC 修正参数 ──
ABC_MIN_LOOKBACK = 40
ABC_B_RETRACE_MIN = 0.30
ABC_B_RETRACE_MAX = 0.70
