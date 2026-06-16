# Trader Vic 量化策略 — 交接文档

## 当前状态

### 已完成
- 精读 `trader-vic-principles` 全部核心框架（SKILL.md + patterns.md + cheatsheet.md + glossary.md + 关键章节 ch09/ch10/ch19/ch20/ch21/ch25）
- 调研 GitHub 现有实现：SwingTrend（最佳参考状态机架构）、smc-toolkit（向量化/有前瞻偏差）、backtrader 最佳实践
- 完成 4 轮设计方案迭代：
  - V1：纯技术分析（被否——"偏技术分析"）
  - V2：以资金管理为核心（被否——"再细看技能"）
  - V3：加入概率/EV/凯利引擎（被否——"缺宏观/美联储"）
  - **V4（当前）：宏观层 + 战术层双层架构（待确认）**

### 未完成
- 用户尚未确认 V4 方案
- 未开始写代码（目录结构已规划，文件未创建）
- 没有数据源或测试数据

## 设计方案的最终版位置

`C:\Users\MOSS\.claude\plans\abstract-mapping-sky.md` — 完整计划

## 架构核心思路

策略分为两层，宏观层决定方向与风险，战术层决定时机与仓位，两层融合：

```
宏观层（新增 ~400行）:
  ├─ credit_cycle.py   — 8项信用指标评分 → CREDIT_SCORE (-16~+16)
  ├─ economic_phase.py — 经济四阶段定位（膨胀/繁荣末期/崩解/复苏）
  ├─ political_cycle.py — 政治选举周期乘数
  └─ macro_regime.py   — 综合引擎 → 方向偏好 + 风险乘数 + 资产偏好

战术层（~1000行）:
  ├─ probability.py — 信号概率/EV/凯利引擎
  ├─ capital.py     — 三原则金字塔资金管理
  ├─ trend.py       — SwingDetector 趋势状态机
  ├─ signals.py     — 1-2-3/2B/四天准则/三天回调
  ├─ consensus.py   — 多信号加权共识
  └─ risk.py        — RRR过滤/止损/时间止损

融合: 宏观方向过滤信号 → 宏观风险乘数调整仓位 → 宏观同向加成概率
```

完整设计细节见计划文件。

## 关键设计决策（最重要的判断）

1. **宏观层参数化**：所有指标阈值、权重、阶段映射进 config.py，非硬编码
2. **宏观层可独立开关**：无数据源时默认中性（risk_multiplier=1.0），纯技术模式可独立运行
3. **状态机而非向量化**：SwingDetector 逐K线处理，无前瞻偏差
4. **资金管理是核心，技术是触发器**：不是找信号的策略，是管风险的系统
5. **凯利 + 安全系数 + 2%硬上限**：三层保护

## 待用户确认的问题

- V4 方案是否涵盖了所有精华？（宏观 + 信用周期 + 政治周期 + 美联储 + 技术 + 资金管理）
- 用什么宏观数据源？（FRED API？CSV导入？）
- 回测标的和时间范围？
- Python 依赖：backtrader + pandas + numpy + matplotlib
- 子代理分工：需要创建目录结构、写所有模块代码

## 参考文件

- 设计计划: `C:\Users\MOSS\.claude\plans\abstract-mapping-sky.md`
- 详细规格: `C:\Users\MOSS\Desktop\book-to-skill\trader-vic-strategy\SPEC.md`
- 技能内容: `$HOME/.claude/skills/trader-vic-principles/`
- 目标目录: `C:\Users\MOSS\Desktop\book-to-skill\trader-vic-strategy/`
