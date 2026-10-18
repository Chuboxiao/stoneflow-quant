第四讲作业更新：**穿石 Stoneflow — 全股票池5DR与趋势突破研究**

仓库：https://github.com/Chuboxiao/stoneflow-quant

提交账号：**Chuboxiao**

> 审核说明（正式发布前移除）：以下Pages链接是预定地址，尚未部署。须在更新推送、Pages部署成功且逐页验证后，再发布本评论；Markdown入口也须在推送后复核。

**报告入口（网页版可直接查看图表、表格和全文，无需安装Python或下载课程行情）：**

- **[5DR报告 · 网页版](https://chuboxiao.github.io/stoneflow-quant/5dr.html)** ｜ [GitHub文字全文](https://github.com/Chuboxiao/stoneflow-quant/blob/main/REVIEW_5DR.md)
- **[20日突破报告 · 网页版](https://chuboxiao.github.io/stoneflow-quant/breakout.html)** ｜ [GitHub文字全文](https://github.com/Chuboxiao/stoneflow-quant/blob/main/REVIEW_BREAKOUT.md)
- **[完整报告 · 网页版](https://chuboxiao.github.io/stoneflow-quant/full.html)**（总览＋5DR全文＋突破全文，含机制与适用股票研究）｜ [GitHub总览](https://github.com/Chuboxiao/stoneflow-quant/blob/main/REVIEW_LECTURE4.md)

[网页报告首页](https://chuboxiao.github.io/stoneflow-quant/)；网页版为已保存结果的只读报告，可修改参数并重新运行的回测系统及代码在仓库中提供。

**课堂任务保留：** 可编程回测系统、模拟时钟与券商，以及长源东谷、科大讯飞的普通突破、成交额确认突破、买入持有实验，均保留在同一仓库和README中。[课堂实验完整报告](https://github.com/Chuboxiao/stoneflow-quant/blob/main/REPORT.md)的区间为2020-07-01至2026-10-16；它采用原版教学账户，与本次课后作业分别说明，不拼接绩效。

**本次课后作业：**

按照指定区间 **2025-01-02至2026-09-30（424日）**，对课程5,451列证券动态筛选，排除历史ST／*ST和未知状态新买入。cumadj统一信号口径，收盘固定股数、次日执行，涨停拒买、跌停拒卖；原始股份、现金、分红应收、送转锁股分别记账。

5DR比较基础与4个改进，仅用2024选出流动性版：评价期收益37.55%、最大回撤-47.17%；基础版2.76%、-56.50%。冻结方案2026年前三季度亏损20.71%，双倍税费滑点后全期仅0.73%。

延续20日突破，比较成交额确认、流动性、趋势与ATR控制。2024冻结的**趋势 + ATR仓位与退出**评价期收益-11.71%、回撤-22.75%；普通突破为-23.19%、-43.87%。同时提供固定半仓参照，避免把减仓效果误认为选股优势；保留全部候选、分年与压力结果。

新增收益来源与适用股票研究：用2024资料固定7个股票组，较高波动组普通突破全期收益19.38%、最大回撤-31.06%，双倍成本后15.43%；匹配全组为-10.76%。仅用2025选组后，2026重新建账仅0.36%、回撤-30.23%。共同股票池信号检验也未证明5DR有稳定正超额，不能把样本盈利等同普遍有效。所有新增分析均明确为回顾性解释。

71项单元测试通过，主研究39组与新增研究17组分别完成独立账本重放。研究属于回顾性的时间隔离，日线成交、ST生效时点、个税与特殊公司行为有明确限制，不声称精确实盘复现。课程和辅助源数据不上传。

[机制与股票子集研究 · 网页专页](https://chuboxiao.github.io/stoneflow-quant/analysis.html) · [GitHub文字全文](https://github.com/Chuboxiao/stoneflow-quant/blob/main/ANALYSIS_STRATEGIES.md)

![穿石全池突破研究工作台](https://raw.githubusercontent.com/Chuboxiao/stoneflow-quant/main/docs/stoneflow-breakout-review.jpg)

![收益来源与适用股票研究](https://raw.githubusercontent.com/Chuboxiao/stoneflow-quant/main/docs/stoneflow-strategy-analysis.jpg)
