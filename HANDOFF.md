# Trader Vic 量化策略 — 交接文档

## 当前状态

项目已进入 Phase 1 实现阶段。~30 个 Python 文件，~3000 行代码。

### 核心架构
```
trader_vic/
  config.py          — 全局参数
  core/
    trend.py         — SwingDetector 状态机 + TrendAge + MarketPhase
    signals.py       — 1-2-3/2B/四天准则/三天回调/ABC修正/窄幅突破
    probability.py   — EV 计算 + 凯利公式
    consensus.py     — 四层确认漏斗 + 道氏确认
    risk.py          — RRR过滤/止损/时间止损/连续亏损暂停
    capital.py       — 三原则金字塔资金管理
    market_env.py    — 7环境分类器
    fundamental_regime.py — 多维基本面评分
    alpha_factors.py — Alpha因子排名
    divergence.py    — RSI背离确认
    stock_pool.py    — 候选池管理
  data/
    providers.py     — akshare 数据拉取 + CSV缓存 + 质量验证
  portfolio/
    mgr.py           — 组合管理 + 风险敞口总账
  strategies/
    vic_strategy.py  — 主策略 10步流程
```

### 关键设计决策
1. 状态机而非向量化 — 无前瞻偏差
2. 风险驱动头寸数 — 无固定 MAX_POSITIONS
3. 周线定方向，日线找入场 — 双重时间框架
4. 宏观定仓位中枢，技术调边界 — 双层融合
5. 出场优先于入场 — 鳄鱼原则
