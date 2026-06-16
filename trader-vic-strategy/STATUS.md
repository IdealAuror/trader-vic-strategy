# 项目状态记录 — 2026-06-16

## 目标
将《专业投机原理（珍藏版）》Trader Vic 的完整知识体系转化为 Python 量化策略。

## 当前阶段：设计迭代中（未开始编码）

### 已完成
- [x] 精读 trader-vic-principles 技能的 SKILL.md、patterns.md、cheatsheet.md、glossary.md
- [x] 精读 skill 中的章节摘要：ch09(经济学)、ch10(繁荣衰退)、ch19(经济预测)、ch20(货币信用)、ch21(政治周期)、ch23(美元)、ch24(波动率)、ch25(领先指标)、ch26(风险回报)、ch29(期权)
- [x] 调研 GitHub：SwingTrend(状态机架构)、smc-toolkit(向量化)、backtrader 最佳实践
- [x] 从 EPUB 提取原书全文 (333K chars) 到 trader_vic_full.txt
- [x] 设计迭代 V1（纯技术分析）→ 被否
- [x] 设计迭代 V2（资金管理核心）→ 被否
- [x] 设计迭代 V3（+概率/EV/凯利）→ 被否（缺宏观）
- [x] 设计迭代 V4（宏观层+战术层双层架构）→ 待确认

### 当前设计（V4）核心结构
```
宏观层 (macro/):
  credit_cycle.py   — 8项信用指标评分 (自由准备/利率/货币供给/收益率曲线等)
  economic_phase.py — 经济四阶段定位 (膨胀/繁荣末期/崩解/复苏)
  political_cycle.py — 选举周期乘数
  macro_regime.py   — 综合引擎 → 方向偏好+风险乘数+资产偏好

战术层 (core/):
  probability.py — 信号概率表/EV/凯利
  capital.py     — 三原则金字塔资金管理
  trend.py       — SwingDetector 趋势状态机
  signals.py     — 1-2-3/2B/四天/三天回调
  consensus.py   — 多信号加权共识+蓝图检测
  risk.py        — RRR过滤+止损+时间止损

融合: 宏观方向→过滤信号 | 宏观风险乘数→调整仓位 | 宏观同向→加成概率
```

### 未完成
- [ ] 用户尚未确认 V4 方案
- [ ] 从原书提取 ch03(资金管理)、ch11(风险)、ch18(三原则展开) 等关键章节内容与原文本对比
- [ ] 用户多次建议"再多看看技能内容/原书"，说明设计仍有遗漏
- [ ] 没有开始写任何代码
- [ ] 没有数据源/测试数据

### 已知问题
1. 原书 EPUB 提取的文本有编码问题（UTF-8 下部分中文字符乱码）
2. 可能需要安装 Python 库（ebooklib/BeautifulSoup）来正确解析
3. 用户的最终确认尚未获得

### 下一步建议
- 用 Python 库正确解析原书关键章节（ch03、ch11、ch18、ch19）
- 与 skill 摘要对比，找出遗漏内容
- 补充后再次提交给用户确认
