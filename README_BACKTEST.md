# 回测系统 · 穿石 Stoneflow

[实验室总览](README.md) · [策略研究](README_RESEARCH.md) · [因子评价](README_FACTORS.md) · [启动指南](docs/START.md)

回测系统负责按时间回放行情、调用策略、尝试成交并记录账户。策略研究负责设计和解释具体实验；因子评价负责检查信号的预测能力。三者共用数据与成交约束，各自维护说明和结果。

## 实验室能力

| 模块 | 能力 |
| --- | --- |
| 模拟时钟与数据 | 逐日回放行情，历史窗口截至当前时点；使用cumadj统一价格信号口径 |
| 可编程策略 | Python状态型策略接口，支持自定义条件、内部状态和目标持仓 |
| 模拟券商 | 次日执行、涨跌停限制、T+1、资金检查、费用和滑点，记录成交与拒单 |
| 账户与对账 | 保存现金、持仓、订单、信号和每日权益，标记缺价与旧估值；精度账户分别记录原始股份、股利应收与送转锁股，支持独立账本重放 |
| 研究工作台 | 本机网页、参数调整、分股比较、净值与回撤、运行历史和报告导出 |
| 研究验证 | 同口径对照、训练期选型、分年分析、成本压力检验、股票分组与损益归因 |

当前支持日频、多头、目标仓位策略。个股趋势实验使用原版复权单位账户；全股票池研究使用原始股份精度账户。两类实验的区间和执行模型不同，分别报告结果，收益不直接拼接。

## 启动和使用

完整步骤见[统一启动指南](docs/START.md)。Python 3.10+，推荐3.12。在仓库目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python web_server.py --data-dir /你的路径/feathers
```

打开 http://127.0.0.1:8765 。只绑定本机，不上传行情、不连接券商，也不发送真实订单。

`/`为可运行的策略回测工作台，`/factors`为可运行的因子观测台，`/5dr`与`/breakout`展示已保存的全池反转与突破研究，`/reports/index.html`是本机报告总览。原始Feather及辅助历史数据缓存不随仓库分发；全池研究的完整复现需按各自指南准备辅助数据。因子评价的启动条件和接口独立说明于[因子评价README](README_FACTORS.md)。

课程数据从[第四讲issue](https://github.com/aslan9/pku_quantllm/issues/8)下载。也可以将七个文件放入`data/feathers/`，再直接`python web_server.py`。本机已有的`local_config.json`可记录数据路径，此文件及原始Feather不进入Git。完成依赖安装后，macOS也可双击`Start.command`启动。

网页可选择三组研究或等权流程演示、调整区间/资金/费用/滑点、导入精确涨跌停CSV、切换成交模式、查看净值/回撤、分股比较、成交/拒单/持仓、运行历史并导出报告。

## 复现与验证

```bash
python research.py --data-dir /你的路径/feathers
python run_demo.py --data-dir /你的路径/feathers
python -m unittest discover -s tests -v
python validate_results.py
```

上述命令重跑个股突破实验，共同区间2020-07-01至2026-10-16，共1526个交易日；此前行情仅用于指标预热。输出为`results/research/`；六个独立子账户保存在其`subaccounts/`内。`validate_results.py`检查已保存账本，因此运行前保留或重建演示与严格模式结果。全池5DR、突破与股票分组实验见各自复现指南。

原主研究39组与补充研究17组精度账户保留[独立账本重放记录](results/final_review/ledger_replay.json)，另有9组个股、演示及严格模式账户完成重放。历史[pandas兼容性验证](results/final_review/ci_compatibility.json)与对应测试日志保留在`results/final_review/`；当前测试范围见[项目总览](README.md#数据与验证)，新增因子验证见[因子评价README](README_FACTORS.md#结果与验证)。这些检查验证实现与账本一致性，策略表现仍需结合样本、数据和成交假设解读。



<a id="strategy-api"></a>

## 扩展策略

引擎接收独立Python对象的`on_close(context)`。策略可以保存内部状态、结合多个行情字段、检查真实模拟持仓、实现任意条件和返回目标仓位；不需要改动引擎。突破策略在持仓时只判断退出条件，未触发时保持原持仓，不每日重置权重；订单失败后按照实际持仓继续判断。

```python
class MyStrategy:
    def on_close(self, context):
        history = context.history('close', lookback=21, adjusted=True)
        # 在这里编写状态、组合条件或自己的模型。
        return None   # 保持原持仓
        # return {}   # 下一次开盘尝试清仓
        # return {'603950.SH': 0.5}  # 下一次开盘尝试达到目标权重
```

`None`表示不下新指令；权重映射表示新目标，省略的证券目标为0。历史接口只返回截至当前日期的副本。当前通用范围是日频目标仓位策略；没有盘中事件、限价单撤改、做空、保证金或完整实盘订单生命周期。复杂策略逻辑可扩展，不等于已实现全部交易机制。

## 账户模型与成交边界

个股趋势实验使用 `BacktestEngine`，结果位于`results/research/`；全池5DR与突破研究使用 `PrecisionEngine`。后者按原始股份、现金、股利应收和送转锁股分别记账，并加入历史ST、参考前收、数量单位及滞后成交额容量检查，详见[5DR精度说明](docs/PRECISION_5DR.md)和[突破精度说明](docs/PRECISION_BREAKOUT.md)。日线盘口、ST公告时点、个税与特殊公司行为仍有精度边界。

以下说明原版个股实验的执行口径：

**复权单位账户。** 价格比较使用原价×cumadj/固定基准因子，成交检查保留原价。累计因子无法还原每次现金分红、送股、配股与到账日，所以持仓输出为复权单位和模型等价股数，不能当作券商登记股数；没有虚构现金分红账本。

**涨跌停资料不足。** `strict`模式需要外部精确涨跌停资料；缺资料拒单。资料齐全时涨停拒买、跌停拒卖。`conservative`模式按因子近似还原参考前收，以向内一分钱的5%边界保守保护，可能过度拒单，也不能证明识别所有历史涨停。个股实验的网页与报告持续标明代理，其绩效为代理下的教学结果，不能宣称精确成交复现。

另外，全天成交额非正或缺失的日期，会**事后否决成交**。全天零成交额是执行不可行性的证明，属于日线执行检查，不作为盘前可获知的选股信息；未使用当日高低收盘价回头决定开盘成交。严格的逐事件实盘验证仍需盘前停牌资料与更细粒度数据。

费用：佣金万三、最低5元、滑点5bps；卖方印花税在2023-08-28前后分别千分之一/万分之五。暂未覆盖全部过户等收费。每个子账户98%目标投资比例；期末不强制清仓。

## 相关文件

| 职责 | 实现 |
| --- | --- |
| 通用数据、时钟、策略与交易账户 | `backtest/` |
| 原始股份精度账户 | `backtest/precision.py` |
| 本机接口与网页 | `web_server.py`、`web/dist/` |
| 个股研究运行 | `research.py`、`run_demo.py` |
| 历史全池策略研究 | `research_5dr.py`、`research_breakout.py` |
| 独立账本检查 | `validate_results.py`、`validate_5dr.py` |

[记账说明](docs/ENGINE.md) · [全池5DR精度](docs/PRECISION_5DR.md) · [突破精度](docs/PRECISION_BREAKOUT.md) · [设计与扩展](docs/DESIGN.md)。
