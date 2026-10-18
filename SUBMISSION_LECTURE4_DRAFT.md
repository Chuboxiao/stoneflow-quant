**穿石 Stoneflow 回测实验室｜5DR与趋势突破研究**

仓库：[Chuboxiao/stoneflow-quant](https://github.com/Chuboxiao/stoneflow-quant)

报告入口：

- **[5DR报告](https://chuboxiao.github.io/stoneflow-quant/5dr.html)** · [文字版](https://github.com/Chuboxiao/stoneflow-quant/blob/main/REVIEW_5DR.md)
- **[20日突破报告](https://chuboxiao.github.io/stoneflow-quant/breakout.html)** · [文字版](https://github.com/Chuboxiao/stoneflow-quant/blob/main/REVIEW_BREAKOUT.md)
- **[完整报告](https://chuboxiao.github.io/stoneflow-quant/full.html)**（含收益来源与适用股票分析）· [文字总览](https://github.com/Chuboxiao/stoneflow-quant/blob/main/REVIEW_LECTURE4.md)

按照指定区间 **2025-01-02至2026-09-30（424日）**，在课程5,451列证券中动态构池，排除ST／*ST及未知状态的新买入。系统支持自定义Python策略；使用cumadj、收盘固定股数、次日执行、涨停拒买与跌停拒卖，分别记录原始股份、现金及公司行为。原有[长源东谷与科大讯飞的趋势实验](https://github.com/Chuboxiao/stoneflow-quant/blob/main/REPORT.md)也完整保留。

5DR与突破各自仅用2024年选型，冻结后在上述区间比较：

| 方案 | 累计收益 | 最大回撤 |
| --- | --- | --- |
| 基础5DR | 2.76% | -56.50% |
| 5DR＋流动性【2024冻结】 | 37.55% | -47.17% |
| 普通20日突破 | -23.19% | -43.87% |
| 趋势＋ATR仓位与退出【2024冻结】 | -11.71% | -22.75% |

5DR流动性版2026年前三季度亏损20.71%，双倍税费滑点后全期仅0.73%。突破改进仍亏损；固定半仓参照反而取得3.14%收益、-19.02%回撤，不能把减仓效果当作ATR优势。

进一步[研究收益来源与适用股票](https://chuboxiao.github.io/stoneflow-quant/analysis.html)：按2024资料固定7组，较高波动组普通突破全期收益19.38%、回撤-31.06%；仅用2025选组、2026重新建账后仅0.36%、回撤-30.23%。样本盈利不等于稳定有效，也不据此推荐事后盈利股票名单。

71项单元测试与56组精度账户的独立账本重放通过。研究属于回顾性分析，日线成交、ST时点及公司行为仍有精度边界，不等同精确实盘复现。网页报告可直接阅读，本机系统支持重跑；原始行情与辅助缓存不上传。

![穿石全池突破研究工作台](https://raw.githubusercontent.com/Chuboxiao/stoneflow-quant/main/docs/stoneflow-breakout-review.jpg)

![收益来源与适用股票研究](https://raw.githubusercontent.com/Chuboxiao/stoneflow-quant/main/docs/stoneflow-strategy-analysis.jpg)
