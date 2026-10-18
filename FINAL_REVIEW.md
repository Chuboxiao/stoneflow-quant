# 穿石 Stoneflow：提交前最终审核

**状态：待你审核。本次更新仅保存在本机；未推送、未部署Pages、未向课程issue发布新评论。**

仓库：`Chuboxiao/stoneflow-quant`。拟在[第四讲issue #8](https://github.com/aslan9/pku_quantllm/issues/8)新增一条作业更新评论，原课堂任务提交保留。本次评论以[`SUBMISSION_LECTURE4_DRAFT.md`](SUBMISSION_LECTURE4_DRAFT.md)为准；`SUBMISSION_COMMENT.md`和`SUBMISSION_5DR_DRAFT.md`是此前阶段的材料，不用于这次提交。

## 请先审核这三项

1. **[README](README.md)**：以“穿石 Stoneflow 回测实验室”的项目介绍、系统能力与策略研究结果为主线。系统建设、个股研究、全池研究及课程要求对应完整保留；审核清单、评论草稿和提交状态不进入README的展示框架。
2. **[课程评论草稿](SUBMISSION_LECTURE4_DRAFT.md)**：包含5DR、突破、完整作业报告三个网页入口、Markdown备用入口、课堂实验链接及两张研究截图。开头的审核说明会在正式发布前移除。
3. **[离线报告首页](report_site/index.html)**：下载后用浏览器打开，或在macOS双击[`OpenReports.command`](OpenReports.command)。不依赖预览服务、Python或原始行情。Pages地址现在仍是待部署地址。

## 两部分都包含哪些内容

| 部分 | 范围 | 入口 |
| --- | --- | --- |
| 课堂任务一：回测系统 | 模拟时钟、可编程状态型策略、券商与成交限制、订单／持仓／现金账、本机网页 | [README系统接口](README.md#strategy-api) · [记账说明](docs/ENGINE.md) · `backtest/`、`web_server.py`、`web/dist/` |
| 课堂任务二：两股趋势研究 | 长源东谷603950.SH、科大讯飞002230.SZ；2020-07-01至2026-10-16；普通突破、成交额确认、买入持有；六个独立子账户 | [课堂实验完整报告](REPORT.md) · `results/research/` |
| 课后作业：5DR | 2025-01-02至2026-09-30，共424日；课程5,451列证券逐日筛选，排除ST／*ST和未知状态的新买入；基础版＋4个改进 | [网页全文](report_site/5dr.html) · [Markdown全文](REVIEW_5DR.md) · [复现与精度](docs/PRECISION_5DR.md) |
| 课后作业：20日突破 | 同一评价期与账户；普通突破、成交额确认、流动性、趋势、ATR方案，以及固定半仓诊断 | [网页全文](report_site/breakout.html) · [Markdown全文](REVIEW_BREAKOUT.md) · [复现与精度](docs/PRECISION_BREAKOUT.md) |
| 收益来源与适用股票 | 真实账户损益归因、共同股票池的后续报价、2024固定7个股票组、2025选组后2026重新建账 | [网页专页](report_site/analysis.html) · [Markdown全文](ANALYSIS_STRATEGIES.md) |
| 完整作业报告 | 总览＋5DR全文＋突破全文，突破全文已包含收益来源与适用股票分析 | [完整网页](report_site/full.html) · [Markdown总览](REVIEW_LECTURE4.md) |

课堂实验沿用原版复权单位教学账户；课后作业采用原始股份、现金、应收股利和送转锁股账户。二者区间与执行模型不同，各自报告完整保留，不直接拼接绩效。

## 主要结论是否表达准确

- 5DR流动性版全期收益37.55%，但最大回撤47.17%；2026年前三季度亏损20.71%，双倍费用滑点后全期仅0.73%。不能把本样本盈利写成稳定有效。
- 普通20日突破全期收益-23.19%。2024冻结的趋势＋ATR版为-11.71%，仍然亏损；固定半仓参照反而取得3.14%收益，不能把减仓效果当作已证明的ATR优势。
- 2024固定的较高波动股票组，普通突破全期收益19.38%、回撤31.06%；只用2025选组、2026重新建账后仅0.36%、回撤30.23%。这是回顾性特征分组，不能推荐事后盈利股票名单，也不属于真正前瞻盲测。
- cumadj统一信号口径，收盘固定订单股数、次日执行，涨停拒买、跌停拒卖；保留日线成交、ST公告时点、个税及特殊公司行为的精度边界。账本对账成功不代表已精确复现实盘成交。

## 检查与交付记录

本次交付同时包含源代码、课堂实验结果、三组作业研究的派生结果及逐笔账本、HTML／Markdown报告、截图和复现说明。课程Feather、辅助历史缓存、本机配置与虚拟环境不进入交付包。

- **71项单元测试通过**：[最终测试日志](results/final_review/unit_tests.txt)。
- **56组精度账户通过3,056,824次检查，另有9组课堂／演示账户通过重放**：[账本重放与源码哈希核对](results/final_review/ledger_replay.json)。
- [文档、网页导航与发布脚本检查](results/final_review/delivery_checks.json)。

推送脚本已改为推送**当前审核提交HEAD到远程main**，不再推送旧的本地main；普通运行只显示说明，明确传入`--publish-reviewed`才会执行发布。脚本不自动部署Pages、不发布评论，也不强制覆盖远程历史。

## 审核通过后的发布顺序

1. 确认拟发布内容与本次审核版本一致，工作区干净，账号为Chuboxiao。
2. 运行`bash push_to_github.sh --publish-reviewed`，将当前审核提交推送到已有仓库的main；如远程有新提交，先合并并检查，不强制覆盖。
3. 按[网页发布说明](docs/REPORT_SITE.md)启用Pages的GitHub Actions来源，并手动运行报告发布工作流。只发布`report_site/`，不公开原始行情或本机服务。
4. 验证首页及5DR、突破、完整报告和截图的公开链接，再把README的待发布说明更新为实际状态、移除评论草稿的审核说明。
5. 向issue #8发布审核通过的作业更新评论，返回仓库、网页和评论的最终链接。

以上外部操作尚未执行。当前可审核本机网页和全部交付文件，无需先授权发布。
