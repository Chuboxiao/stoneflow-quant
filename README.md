# 穿石 Stoneflow 回测实验室

**沿时间回放交易，让每一笔决策都有据可查。**

穿石是一个面向A股日频研究的本机实验室，包含回测系统、策略研究与因子评价。它把行情、信号、模拟成交和账户核对串联起来，让预测能力、交易表现与研究结论各有依据。

## 从这里开始

| 你想做什么 | 入口 |
| --- | --- |
| 启动实验室 | 在Finder打开项目文件夹，双击与本README同级的 [Start.command](Start.command)；[详细启动步骤](docs/START.md) |
| 运行策略回测 | [本机回测工作台](http://127.0.0.1:8765/) |
| 评价因子 | [本机因子观测台](http://127.0.0.1:8765/factors) |
| 改进因子 / 第六讲作业 | [模块与实验说明](README_EVOLUTION.md) · [本机因子改进](http://127.0.0.1:8765/factors/improve) |
| 阅读保存的研究 | [已发布报告](https://chuboxiao.github.io/stoneflow-quant/) · [离线报告首页](report_site/index.html) |

本机网址需要服务运行；保存的报告可以独立阅读。macOS也可双击 [OpenReports.command](OpenReports.command) 打开离线报告。

## 三个模块，三份说明

| 模块 | 解决的问题 | 独立文档 |
| --- | --- | --- |
| 回测系统 | 给定策略和交易规则，账户会怎样变化？ | [回测系统 README](README_BACKTEST.md) |
| 策略研究 | 哪些假设值得检验，如何比较和解释实验结果？ | [策略研究 README](README_RESEARCH.md) |
| 因子评价 | 因子分数能否区分未来表现，跨期是否稳定？ | [因子评价 README](README_FACTORS.md) |

因子评价与交易回测分别计量：IC衡量预测关系，交易账户计入成交限制和成本。研究结果标明区间、模型及累计／年化口径。

<a id="homework"></a>
<a id="classroom"></a>

## 研究入口

- **策略研究**：[全池5DR](REVIEW_5DR.md)、[全池20日突破](REVIEW_BREAKOUT.md)、[收益来源与适用股票](ANALYSIS_STRATEGIES.md)、[长源东谷与科大讯飞对照](REPORT.md)。收益核算与课程要求对应见[策略研究说明](README_RESEARCH.md)。
- **因子评价**：以5DR为完整演示，支持五个内置因子、Python因子与CSV导入；见[因子评价说明](README_FACTORS.md)及[独立交互报告](report_site/factors.html)。

公开站点提供已发布的只读研究快照；本机实验室可运行回测、重跑因子评价及导入新因子。研究保留盈利和亏损结果，历史实验属于回顾性研究。

<a id="strategy-api"></a>

## 设计与扩展

系统按 **数据 → 信号 → 策略 → 执行与记账 → 结果** 组织；网页负责操作和展示，各模块共用明确的时点与结果口径。

| 位置 | 职责 |
| --- | --- |
| `backtest/` | 行情、时钟、策略接口、成交限制与账户模型 |
| `factorlab/` | 因子定义、预测统计、组合适配器与报告生成 |
| `web_server.py`、`web/dist/` | 本机任务接口与网页工作台 |
| `results/` | 保存参数、指标、逐笔记录、来源与验证结果 |
| `report_site/` | 可独立阅读的研究快照 |
| `tests/` | 合成数据测试，覆盖回测、因果性、因子与网页任务 |

新增功能遵循[设计与扩展约定](docs/DESIGN.md)：因子加入因子接口，策略加入策略接口，交易规则进入执行层，研究结果写入独立目录。具体接口见[扩展策略](README_BACKTEST.md#strategy-api)与[扩展因子](docs/FACTORS.md#新增因子)。

当前支持日频、多头、目标仓位研究；实盘券商接入、盘中订单生命周期与保证金尚未实现。两种历史账户模型的适用范围见[回测系统说明](README_BACKTEST.md#账户模型与成交边界)。

## 数据与验证

课程数据为7个Feather矩阵；原始行情、辅助缓存、本机配置与运行环境按Git忽略规则单独管理，仓库保存源码、派生结果和复现说明。数据准备与依赖安装见[启动指南](docs/START.md)。

当前环境104项单元测试通过，包含10项因子改进模块测试；原94项基础测试另已在pandas 2与3验证。回测与因子各自保留账户核对和来源记录，验证入口分别见[回测复现](README_BACKTEST.md#复现与验证)、[因子验证](README_FACTORS.md#结果与验证)与[因子改进](README_EVOLUTION.md)。
