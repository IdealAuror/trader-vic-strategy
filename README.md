# Trader Vic 量化策略 — 概率化交易引擎

基于 Victor Sperandeo《专业投机原理》（*Trader Vic: Methods of a Wall Street Master*）核心框架的 A 股量化交易策略实现。

**核心理念不是"找信号"，而是"算概率"** — 每次下注都是概率、赔率、仓位、市场环境的综合计算。

## 项目结构

```
├── trader-vic-strategy/         # 量化策略代码
│   ├── trader_vic/              # 核心库
│   │   ├── core/                #   引擎模块
│   │   │   ├── trend.py         #     多时间框架趋势检测 (SwingDetector)
│   │   │   ├── signals.py       #     信号识别 (1-2-3/2B/FourDay/ThreeDayPullback)
│   │   │   ├── probability.py   #     概率统计引擎
│   │   │   ├── risk.py          #     风险管理 (凯利/止损/ATR)
│   │   │   ├── capital.py       #     资本层级管理 (三层资金管理)
│   │   │   ├── consensus.py     #     技术共识投票 (log-odds)
│   │   │   ├── market_env.py    #     市场环境分类 (7-condition)
│   │   │   └── fundamental_regime.py  # 宏观基本面体制
│   │   ├── data/providers.py    #   数据获取 (akshare)
│   │   ├── portfolio/mgr.py     #   投资组合管理
│   │   └── strategies/vic_strategy.py  # 完整策略主流程
│   ├── data/                    # 沪深300成分股日线数据 (CSV)
│   ├── output/                  # 回测结果输出
│   ├── reports/                 # 报告生成脚本
│   ├── tests/                   # 单元测试
│   ├── backtest.py              # 回测入口
│   ├── fetch.py                 # 数据下载
│   └── daily_report.py          # 日报生成
├── trader-vic-principles/       # 《专业投机原理》中文知识库
│   ├── chapters/                #   32 章完整中文翻译
│   ├── SKILL.md                 #   Claude Code 技能定义
│   ├── cheatsheet.md            #   交易速查表
│   ├── glossary.md              #   术语表
│   └── patterns.md              #   模式库
├── ch03_original.txt            # 第三章英文原文
└── trader_vic_full.txt          # 全书英文原文 (参考用)
```

## 策略架构 (每根 K 线流程)

```
Step 0:   宏观体制更新 (M2/PMI/Shibor, 滞后1月)
Step 1:   组合估值 + 风控核算
Step 1.3: 多时间框架趋势 (CSI300 周线)
Step 1.5: 市场环境分类 (7种条件)
Step 1.8: 个股多时间框架趋势
Step 2:   检查持仓 → 退出条件
Step 3:   扫描 watchlist → 入场条件
  ├── 信号检测 (1-2-3/2B/四天/三天回调)
  ├── Layer 1: 技术共识投票 (log-odds)
  ├── Layer 2: 基本面过滤 (FILTER/REDUCE/IGNORE)
  ├── Layer 3: 市场环境适配 (CRISIS 跳过全部)
  ├── Layer 4: 道氏确认 (CSI300 vs 上证)
  └── EV > 0 + RRR >= min_rrr → 标记可入场
```

## 安装

```bash
# Python >= 3.10
pip install -r trader-vic-strategy/requirements.txt
```

依赖: `pandas`, `numpy`, `scipy`, `akshare`, `matplotlib`, `jinja2`

## 使用

```bash
# 下载数据
cd trader-vic-strategy && python fetch.py

# 运行回测
python backtest.py

# 生成日报
python daily_report.py
```

## 回测结果

当前回测覆盖沪深 300 成分股，输出包含:
- 收益曲线与基准对比
- 胜率 / 盈亏比 / 最大回撤
- 月度 / 年度收益统计

## 来源

- 《专业投机原理》Victor Sperandeo — 书中 1926-1985 道指统计数据作为信号概率核心输入
- 行情数据来源: [akshare](https://github.com/akfamily/akshare)
- 中文译本: 32 章完整翻译见 `trader-vic-principles/chapters/`

## 许可

MIT
