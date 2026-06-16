# Trader Vic 量化策略 — 概率化交易引擎

## 核心理念：从"找信号"到"算概率"

> 斯波朗迪全书最精华的一句话：
> **"赌博是盲目承担风险，投机是在掌握有利胜算时承担风险。"**

这和普通的量化策略有本质区别：

```
普通量化:  如果 指标A > 阈值B → 买入固定数量
           （规则是死的，不随环境变化）

Trader Vic: 如果 信号X 触发 → 
              查表得 P(成功) = 67% (四天准则)
              计算 R = 当前止损距离 → 目标距离 ≥ 1:3
              仓位 = f(概率, RRR, 当前资本层级, 信号置信度)
           （每次下注都是概率计算的结果）
```

---

## 第一层：概率统计引擎（书中硬数据的量化）

### 1.1 信号可靠度概率表（来自 cheatsheet 信号矩阵）

这是策略的**第一手输入**——每个信号不是简单的"做多/做空"，而是携带一个先验概率：

| 信号类型 | 先验概率 P(win) | 来源依据 | 数据可靠性 |
|---------|----------------|---------|-----------|
| 1-2-3 三步全满足 | ~67% | 最高可靠度评级 | **设计者估计**（从序数评级映射） |
| 2B（中期3-5天） | ~50% | 高可靠度，盈亏比≥1:5 | **设计者估计** |
| 四天准则 | 75%在24天内反转 | ch27 1926-1985道指统计 | **书中硬数据** ✅ |
| 三天回调买入（多头趋势中） | 94.4% | cheatsheet 统计 | **书中硬数据** ✅ |
| 窄幅盘整突破 | ~65% | 中高可靠度评级 | **设计者估计** |
| ABC C点顺势建仓 | ~60% | 高可靠度（顺势） | **设计者估计** |
| 缺口穿越趋势线+确认 | ~55% | 中高可靠度 | **设计者估计** |
| 趋势跟踪基础胜率 | ~33% | ch18 表18-2 暗示 | **书中数据** ✅ |
| 单一步骤2（无步骤3） | <30% | 低——不可单独使用 | **设计者估计** |

> **注意**：书中对多数信号只有序数评级（最高/高/中高/中/低），无精确概率。
> 标注为"设计者估计"的数值是根据评级映射的合理近似，回测时可用范围 [P-0.1, P+0.1] 做敏感性分析。
> 唯一有书中硬数据支撑的是：四天准则(75%)、三天回调(94.4%)、趋势跟踪基础(33%)。

**量化实现**：

```python
SIGNAL_PROBABILITIES = {
    "123_FULL": 0.67,
    "123_CONFIRMING": 0.50,   # 仅 步骤1+2
    "2B_MEDIUM": 0.50,
    "2B_LONG": 0.55,
    "FOUR_DAY_RULE": 0.75,
    "THREE_DAY_PULLBACK": 0.944,
    "NARROW_RANGE_BREAKOUT": 0.65,
    "ABC_C_POINT": 0.60,
    "GAP_WITH_TRENDLINE": 0.55,
    "STEP2_ONLY": 0.25,
}
```

### 1.2 期望值（EV）计算引擎

**每笔交易的核心计算：**

```python
def calculate_ev(signal_type, entry, stop, target):
    p_win = SIGNAL_PROBABILITIES[signal_type]
    risk = abs(entry - stop)    # R
    reward = abs(target - entry)
    rr_ratio = reward / risk    # 实际 RRR
    
    # 核心公式
    ev = p_win * reward - (1 - p_win) * risk
    
    # 归一化到 R 单位
    ev_per_r = ev / risk  # p_win × rr_ratio - (1-p_win)
    
    return ev, ev_per_r

# 例：2B信号，P=50%，RRR=1:3
# EV = 0.50 × 3 - 0.50 × 1 = +1.0R
# 每赌1元风险，期望拿回1元利润

# 例：1-2-3全确认，P=67%，RRR=1:3
# EV = 0.67 × 3 - 0.33 × 1 = +1.68R
# 比2B信号好68%

# 例：纯趋势跟踪，P=33%，RRR=1:3
# EV = 0.33 × 3 - 0.67 × 1 = +0.32R
# 斯波朗迪说的"最低可接受水平"
```

### 1.3 凯利公式变体 —— 根据信号概率动态分配（⚠️ 外部扩展）

> **重要声明**：凯利公式**不是斯波朗迪原书内容**。Sperandeo 的头寸规模公式是固定比例法：
> `仓位 = (资本 × 固定风险%) ÷ |入场 - 止损|`（风险%固定为 2-3%）。
>
> 凯利公式是本设计者从 ch11 存活率公式 `存活率 = (1-风险比例)^交易次数` 外推的外部扩展，
> 用于实现动态概率调仓。安全系数层级（0.25/0.50/0.75）也是设计者判断，无书中依据。

```python
def optimal_fraction(p_win, rr_ratio):
    """凯利公式计算最优下注比例"""
    # f* = (p × (R+1) - 1) / R
    # 其中 R = reward/risk
    return (p_win * (rr_ratio + 1) - 1) / rr_ratio

def vic_position_fraction(p_win, rr_ratio, capital_level):
    """Trader Vic 改进版：凯利 × 安全系数 × 资本层级"""
    kelly_f = optimal_fraction(p_win, rr_ratio)
    
    # 安全系数：斯波朗迪强调不要满仓凯利
    safety = {1: 0.25, 2: 0.50, 3: 0.75}[capital_level]
    
    # = 最终风险比例
    return max(0, kelly_f * safety)

# 例：2B信号，P=50%，RRR=1:3
# kelly = (0.5 × 4 - 1) / 3 = 0.33
# Level 1 实际风险 = 33% × 25% = 8.25%  ← 但被2%上限截断
  
# 所以实际用的是: min(2%, 8.25%) = 2%
# 即 Level 1 时2%上限起到了硬约束作用
```

**关键洞察**：Level 1 的 2% 上限实际是凯利约束的安全截断！Level 2 允许更高的分数，Level 3 最高。

---

## 第二层：三原则金字塔资金管理（反馈闭环）

这不是一个静态的规则，而是一个**随账户状态自动调整的反馈系统**：

```
                    ┌──────────────────────┐
                    │     CapitalManager    │
                    │  (每笔交易后更新)       │
                    └──────────┬───────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
     ┌─────────────────┐ ┌──────────┐ ┌──────────────┐
     │   Level 1: 保本  │ │Level 2:   │ │ Level 3: 卓越 │
     │                 │ │一致性获利  │ │              │
     │ 风险=min(1%,    │ │风险=动态  │ │风险=银行利润 │
     │    凯利×0.25)   │ │ 2%~3%    │ │ × 10~20%     │
     │ 上限2%          │ │50%利润锁定│ │              │
     └────────┬────────┘ └─────┬────┘ └───────┬──────┘
              │                │                │
              └────────────────┼────────────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │   实际头寸 =           │
                    │   (资本 × 风险比例)    │
                    │   ÷ |入场 - 止损|     │
                    └──────────────────────┘
```

**层级切换逻辑（自动）：**

```python
def determine_level(self, peak_capital, current_capital, bank_profit):
    drawdown = (peak_capital - current_capital) / peak_capital
    
    if bank_profit >= self.initial_capital * 2:
        return 3  # 银行利润已翻倍，解锁第三层
    
    if drawdown > 0.20:
        return 1  # 回撤超20%退回保本层
    
    if current_capital > self.initial_capital * 1.1:
        return 2  # 盈利10%以上进入一致性获利层
    
    return 1  # 默认在保本层
```

**50%利润锁定 + 动态缩放的数学：**

```python
# 盈利后：
locked_profit = trade_profit * 0.50        # 一半存入银行
available_boost = trade_profit * 0.50      # 另一半放大后续头寸
next_risk_base = current_capital + available_boost  # 放大可用资本

# 亏损后：
next_risk_base = current_capital - loss_amount  # 自动缩小
# 注意：不需要主动"缩小头寸"，因为 (资本-亏损)×2%/|入场-止损| 自动缩小了
# 这就是斯波朗迪"亏损时头寸自动缩小"的数学原理
```

---

## 第三层：统计趋势定位（用历史分布判断当前位置）

### 3.1 趋势寿命/幅度统计定位 (ch11, ch24)

斯波朗迪用 1896 年以来的历史正态分布来回答"这个趋势还有多少空间"：

```python
from scipy.stats import norm

BULL_MARKET_STATS = {
    "avg_duration_years": 2.33,
    "avg_gain_pct": 77.5,
    "duration_std_years": 1.1,      # 估算，ch04 正态分布图反推
}

BEAR_MARKET_STATS = {
    "avg_duration_years": 1.1,
    "avg_loss_pct": 29.4,
    "duration_std_years": 0.6,
}

def trend_age_percentile(trend_start_date, trend_direction):
    """计算当前趋势在历史分布中的位置（z-score → 正态 CDF）"""
    stats = BULL_MARKET_STATS if trend_direction == UP else BEAR_MARKET_STATS
    elapsed = (today - trend_start_date).days / 365
    z = (elapsed - stats["avg_duration_years"]) / stats["duration_std_years"]
    percentile = norm.cdf(z)  # 0~1，50% = 平均值
    
    # > 0.50 = 趋势已超过历史平均寿命
    # > 0.84 = 趋势处于历史尾部（1个标准差以上），提高警惕
    # 用于风险乘数调整：趋势越老，风险乘数越低
```

### 3.2 次级折返定位 (道氏定理五)

```
折返幅度 = 前一波段的 1/3 ~ 2/3
折返持续 = 3周 ~ 3个月

量化过滤:
  - 如果当前回调幅度 < 前一波段 × 33% → 可能还不是折返末端
  - 如果 > 66% → 可能不是折返而是反转
  - 在 33%~66% 之间 + 出现 1-2-3/2B → 高胜率入场
```

---

## 第四层：信号过滤器与综合决策

### 4.1 多信号权重共识系统

当多个信号同时出现时，做概率加权：

```python
def consensus_signal(active_signals):
    """多个信号加权投票"""
    total_weight = 0
    weighted_direction = 0
    
    for sig in active_signals:
        # 权重 = log(P/(1-P)) 即证据权重
        odds = sig.probability / (1 - sig.probability)
        weight = math.log(odds) if odds > 0 else 0
        
        weighted_direction += sig.direction * weight
        total_weight += weight
    
    if total_weight == 0:
        return Signal.NONE
    
    avg_direction = weighted_direction / total_weight
    confidence = abs(avg_direction)  # 0~1
    
    if confidence > 0.3:
        return Signal(direction=1 if avg_direction > 0 else -1, 
                     confidence=confidence)
    return Signal.NONE
```

### 4.2 蓝图预测法 —— "该发生的没发生"反向机制

这是斯波朗迪独特的逆向信号：

```python
def blueprint_violation(expected_direction, actual_price_action):
    """
    当市场应该朝某个方向走但没走 → 反向信号
    
    例: 经济数据利好，但价格不涨反跌
        利好不涨 = 利空，做空信号
    """
    # 实现方式：追踪重大事件后的价格行为
    # 实际偏离预期 → 反向权重累加
```

### 4.3 道氏指数相互确认

```python
def dow_confirmation(index1_trend, index2_trend):
    """两个指数必须同向才确认"""
    if index1_trend == index2_trend:
        return index1_trend  # 确认
    return None  # 无确认，不交易
```

---

## 完整交易流程（整合版）

```
每根 K 线:
│
├─ 第一步：更新状态 ──────────────────────────────
│  ├─ SwingDetector.update(high, low, close) → 趋势方向
│  ├─ TrendAge.update() → 趋势在历史分布中的百分位
│  └─ CapitalManager.update(account_value) → 当前层级
│
├─ 第二步：检测信号 ──────────────────────────────
│  ├─ 每个信号独立检测（1-2-3, 2B, 4天准则, 3天回调等）
│  ├─ 每个信号携带 P(win) 和方向
│  └─ consensus_signal() → 加权共识方向和置信度
│
├─ 第三步：计算期望值 ────────────────────────────
│  ├─ 用共识 P(win) + RRR → 计算 EV
│  ├─ 如果 EV ≤ 0 → 跳过（持有现金）
│  ├─ 如果 RRR < 1:3 → 跳过
│  └─ 道氏确认 → 如果两个指数不同向 → 减半仓位
│
├─ 第四步：计算头寸 ──────────────────────────────
│  ├─ vic_position_fraction(P(win), RRR, capital_level)
│  ├─ 趋势年龄风险乘数（老趋势 → 小仓位）
│  ├─ 最终头寸 = min(2%, 凯利分数 × 安全系数 × 趋势乘数)
│  └─ **入場順序**：所有合格標的按 EV × signal_boost × 置信度 降序
│       （所有信號在同一根K線同時產生，"先到先得"無意義）
│
├─ 第五步：执行入场 ──────────────────────────────
│  ├─ 满足所有条件 → 入场
│  ├─ 止损位 = 信号定义的技术止损（摆动点/趋势线）
│  └─ 目标位 = 入场 + RRR × 止损距离（至少1:3）
│
└─ 第六步：持仓管理 ─────────────────────────────
   ├─ 止损 → 鳄鱼原则立即平仓
   ├─ 目标 → 平50% + 移止损至保本 + 剩余追踪
   ├─ RRR 降到 1:2 → 移止损至保本
   ├─ 时间止损 → 5-10根K线未朝预期方向走 → 离场
   ├─ 趋势反转信号 → 平仓（可能反手）
   └─ 蓝图违背 → 平仓
```

---

## 与普通量化策略的根本区别

| 维度 | 普通量化 | Trader Vic 量化 |
|------|---------|----------------|
| **入场逻辑** | "如果指标A > B则买入" | "如果信号X的概率P满足EV>0" |
| **头寸规模** | 固定数量或固定比例 | P(win)×凯利×资本层级×趋势乘数 |
| **风险管理** | 固定止损% | 动态: 资金管理引擎自动调节 |
| **信号处理** | 单一信号决策 | 多信号概率加权共识 |
| **账户反馈** | 无（每笔独立） | 有: 亏损缩小/盈利放大+50%锁定 |
| **统计背景** | 通常只用回测数据 | 使用书中78+年历史统计分布 |
| **现金管理** | 满仓或空仓 | 基于可用资本层级自动调节 |
| **退出机制** | 固定目标或跟踪止损 | 多条件: 时间/概率/价格/宏观 |

---

## 配置参数（config.py 新增）

```python
# 宏观-战术冲突处理
MACRO_CONFLICT_MODE = "FILTER"   # FILTER | REDUCE | IGNORE
MACRO_CONSENSUS = "MAJORITY"     # UNANIMOUS | MAJORITY | WEIGHTED_AVERAGE

# 风险参数（ch03=1~2%, ch18=3%，用户可配置）
RISK_PCT = 0.02                  # 范围: 0.01~0.05

# 资金管理
CAPITAL_LEVEL2_THRESHOLD = 1.10  # 盈利10%进入第2层
CAPITAL_LEVEL3_THRESHOLD = 2.00  # 银行利润翻倍进入第3层
MAX_DRAWDOWN_LEVEL1 = 0.20      # 回撤20%退回第1层

# 连续亏损暂停（ch12）
CONSECUTIVE_LOSS_PAUSE = 5       # 连续亏损N笔后暂停
CONSECUTIVE_LOSS_BAR = 20        # 暂停N根K线

# 波动率模式（ch24）
VOLATILITY_MEDIAN = 7            # 月均2%走势次数历史中位数
VOL_LOW_THRESHOLD = 0.8          # <80%中位数=低波动模式
VOL_HIGH_THRESHOLD = 1.2         # >120%中位数=高波动模式
```

## 数据层（data/providers.py 新增）

```python
# 宏观数据源
MACRO_DATA_MODE = "CSV"          # FRED | CSV | DISABLED
# CSV 回退模式需提供 sample_data/ 目录下的历史数据文件
# FRED 模式需要 API key，缺失时自动降级为 CSV/DISABLED
# DISABLED 模式 = risk_multiplier=1.0，纯技术模式

# 个股数据
DATA_ADJUST = "qfq"              # 前复权，保持当前价格真实
MIN_DATA_BARS = 252              # 最少 1 年数据
MAX_NAN_RATIO = 0.05             # 最大允许 NaN 比例
SUSPEND_THRESHOLD = 20           # 连续 N 日价格不变 = 停牌

# 交易成本（A股）
COMMISSION_RATE = 0.0003         # 佣金 万三，双边
STAMP_TAX_RATE = 0.001           # 印花税 千一，仅卖出
MIN_COMMISSION = 5.0             # 最低佣金 5 元
SLIPPAGE = 0.001                 # 滑点 0.1%
```

## 数据质量过滤器

```python
def validate_stock_data(df: pd.DataFrame) -> pd.DataFrame:
    """数据质量检查，不合格则抛异常"""
    if len(df) < MIN_DATA_BARS:
        raise DataQualityError(f"数据不足 {MIN_DATA_BARS} 根K线")
    nan_ratio = df[OHLCV].isna().sum().sum() / (len(df) * 5)
    if nan_ratio > MAX_NAN_RATIO:
        raise DataQualityError(f"NaN比例 {nan_ratio:.1%}")
    # 停牌检测：连续 N 日 OHLC 完全不变
    # 前复权异常：单日涨跌幅 > 20%（A股涨跌停限制 ±10%，复权可能偶尔突破）
    return df.ffill().dropna(subset=OHLCV)
```

## 新增缺失项（审查后补充）

| # | 项目 | 来源 | 模块 |
|---|------|------|------|
| 49 | A/D线背离 | ch27 | consensus.py |
| 50 | 10/30周均线交叉 | ch08 | indicators/ |
| 51 | 震荡指标背离RSI | ch08 | indicators/ |
| 52 | 三天高低价规则 | ch27 | signals.py |
| 53 | 七项评估系统7/7→90% | ch30 | consensus.py |

## 所需文件清单

| 文件 | 核心类/内容 | 重点 |
|------|------------|------|
| `core/probability.py` | SignalProbability, EVCalculator, KellyFraction | **新**概率/EV引擎，这是核心 |
| `core/capital.py` | CapitalManager, TieredPositionSizer | 三原则金字塔资金管理 |
| `core/trend.py` | SwingDetector, TrendAge(正态CDF), RetracementLocator | 趋势检测+统计定位 |
| `core/signals.py` | Criterion123, Criterion2B, FourDayRule, ThreeDayPullback, ThreeDayHL | 所有信号，每个带P(win) |
| `core/consensus.py` | ConsensusEngine, BlueprintDetector, DowConfirmation, **ADDivergence, SevenItemEval** | 多信号加权+逆向检测 |
| `core/risk.py` | RiskRewardFilter, StopManager, TimeStop, **ConsecutiveLossPause** | 风险过滤器 |
| `indicators/vic_indicators.py` | bt.Indicator 子类, **MA10_30, RSIDivergence** | backtrader封装 |
| `strategies/vic_strategy.py` | TraderVicStrategy | 主策略流程 + 波动率模式接入 |
| `data/providers.py` | akshare 数据拉取 + CSV 缓存 + 数据质量验证 | 前复权 + 数据过滤器 |
| `config.py` | 所有参数 + 概率表 + 交易成本 + 数据参数 | 阈值+可配置风险%+佣金+印花税+滑点+复权 |

---

怎么样，这次把统计概率、EV引擎、资本层级反馈闭环都放进去了？
