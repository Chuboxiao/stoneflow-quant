# 因子观测台：评价方法与扩展接口

[因子评价README](../README_FACTORS.md)维护模块使用与5DR演示；本页集中说明公式、数据要求和扩展接口。[启动指南](START.md) · [设计与扩展](DESIGN.md)。

穿石的因子研究与交易回测共用行情和历史股票状态，分别计量。因子评价回答“分数能否对应未来表现”，交易账户回答“按规则实际尝试交易后表现怎样”。原有个股和全池回测接口保留。

## 打开和复现

启动 `python web_server.py --data-dir /你的路径/feathers`，打开 http://127.0.0.1:8765/factors 。`local_config.json`中的`reference_dir`指向第四讲已准备的历史状态缓存；`data_dir`指向课程7个Feather。原始数据和本机路径配置不上传。网页可重跑内置因子与导入CSV；重复运行保存在被忽略的`results/factor_runs/`，不覆盖正式快照。

不启动服务也可打开`report_site/factors.html`，交互切换已保存的因子、股票池、预测期限并下载明细。这是只读结果，不会在读者电脑上执行Python或读取你的本机数据。公开站点通过推送后的独立Pages部署更新，见[报告发布流程](REPORT_SITE.md#发布流程)。

默认完整演示命令（替换路径）：

```bash
python -m factorlab.runner \
  --data-dir /你的路径/feathers \
  --reference-dir /你的路径/baostock-20230901-20260930 \
  --action-dir /你的路径/actions \
  --trade-factors reversal5 \
  --output results/factors
python build_report_site.py
```

默认计算5DR、20日动量、20日突破幅度、成交额放大、20日低波动；5DR保留基础池与流动性池对照，其余默认基础池，避免把不同股票池当成不同因子混比。`--pool liquid`可显式评价其他因子的流动性池。`--factors reversal5`仅运行5DR。`--trade-factors reversal5`只为5DR重跑标准与双倍成本的净账户；`--trade`为本次所有因子运行净账户，需要完整公司行为资料。缺资料时停止，不以报价收益替代精确成交。

## 时点和股票池

- 信号为t日收盘信息；5DR分数为`−(close[t]*cumadj[t] / (close[t−5]*cumadj[t−5]) − 1)`，高分代表过去跌得多。因子方向预设，不按IC翻转。
- 基础池与原5DR的资格条件一致：信号日明确非ST、交易状态正常，累计至少60个有效报价日、连续20日有效价格，当日成交额与笔数为正，20日成交额均值有效。流动性池再要求20日均额≥2000万元、原始收盘价≥3元。
- 没有历史状态的证券排除，不按今日名称回填历史ST，也不根据未来停牌/ST提前排除。
- 信号区间默认为2025-01-02至2026-09-30；七个矩阵的原始2026年10月数据不进入本次标签。

## 标签、覆盖和分组

未来h日标签为`adjusted_open[t+1+h] / adjusted_open[t+1] − 1`；h为交易日。1日标签至少隔夜，符合次日买入后再下一日退出的时序。这里是报价诊断，不判断队列是否成交。

先对信号日全部可用因子值分组，再检查未来报价。不存在有效入场/退出价、成交额非正或交易状态异常的标签保持缺失；不填零、不后移寻找可用退出价。所有组都输出入选数和可观察数。期末h+1个信号日没有完整观察窗口，单独统计删失数；这与中途缺价分开。缺价可能非随机，99%以上覆盖也不能证明没有退市或停牌偏差。

仅用当日1%和99%分位缩尾；不按全样本统计量标准化，不按未来收益去极值。IC为Pearson，Rank IC为平均秩Spearman；不足30个配对、常数因子或常数未来收益时不计算相关系数，不能填成0。

五分组按平均秩划分，同分不按代码强拆；不足5个不同取值时不硬分组。Q5高分，Q1低分。分组均值按日期等权汇总。Q5约为股票池的20%，与净交易账户的Top20不是同一个组合；分组图不应与原5DR净值直接核对。

## 指标与解释

| 指标 | 定义和边界 |
| --- | --- |
| IC / Rank IC均值 | 每个信号日横截面相关性的时间均值；保留正负方向 |
| ICIR | 日度IC均值／日度IC样本标准差，明确未年化；零标准差显示不可计算 |
| 正IC日占比 | 有效IC中大于0的日期比例，不把缺失日当负值或零值 |
| HAC t | Bartlett/Newey-West均值诊断，lag=max(h−1,5)；保留缺失日期间隔，非多重检验校正后显著性结论 |
| Q5−Q1 | 高分组减低分组的平均未来h日报价收益；不能把每日重叠的多日收益累乘成净值 |
| 单调性 | 每日组号与组平均未来收益的Rank相关，再跨日平均；只是描述 |
| 分组曲线 | 只将1日分组平均报价收益复合，报价区间不重叠；不扣费、不拒涨停、不保证买到，不是可做空账户 |
| 预测衰减 | 并列比较未来1、5、10、20日，未按结果选择最优持有期 |
| 稳定性 | 分月、分年保留正负IC。按信号日分桶，跨年标签可能落在次年，不能未经purge用于训练选型 |
| 名单退出比例 | `1−(相邻日Q5交集人数/前日Q5人数)`，与金额换手不同 |
| 因子排名自相关 | 相邻日共同有效证券的分数Rank相关，观察信号变化速度 |
| 因子间相关性 | 共同基础池内逐日Rank相关的时间均值；不能替代中性化或独立增量收益检验 |

当前没有完整历史行业、市值及退市账本，因此不宣称已完成行业/市值中性化、风险模型归因或消除存活偏差。IC、分组、成本与跨期证据并列展示，不合成一个未经论证的“因子质量总分”。研究为看到历史后开展的回顾性分析，不是真正的前瞻盲测。

## 与旧评分结合

原评分`年化收益 / (|最大回撤|+0.05)`保留在策略层；它是自定义收益回撤评分，不是IC、标准Calmar或因子固有属性。新评价模块对非正年化收益显示“不参与评分”，避免相同亏损时大回撤反而获得较高的负分。既有第四讲选型记录不改写。

年化统一按`(期末权益/初始资金)^(252/区间交易日数)−1`；年化不是实际年历收益率。2024选型期为242个交易日，5DR流动性版累计29.0448%、年化30.4117%、回撤−32.2850%，评分0.8156557。评价期424日累计37.5464%、年化20.8609%、回撤−47.1694%。两段数据不混用。

新适配器`FactorPortfolio`把因子送入现有`PrecisionEngine`，每天选最高分20只、总目标95%，收盘固定股数、次日执行；涨停拒买、跌停拒卖、税费、容量和公司行为沿用原模型。5DR四个账户（基础/流动性×标准/双倍成本）与原结果逐项比对；保留逐笔账本以供重放。

## 新增因子

### Python时点builder

```python
from factorlab import FactorSpec

def signal(context):
    close = context.history('close', lookback=11, adjusted=True)
    return -(close.iloc[-1] / close.iloc[0] - 1)

FACTOR = FactorSpec('reversal10', '10日反转', '预设低收益高分', 11, signal)
```

返回以证券代码为索引的Series；允许缺失值，不允许重复代码或股票池外代码。`history`只给截至当前收盘的副本；成交额和笔数不能乘cumadj。接口提供因果性约束，不是恶意Python代码沙箱，用户插件应来自可信本机文件。

```bash
python -m factorlab.runner --data-dir /行情目录 --reference-dir /状态目录 \
  --factors '' --plugin examples/custom_factor.py --output results/my_factor
```

### 导入因子值

CSV仅三列`date,symbol,value`，每个日期证券键唯一。分数必须在当日收盘时已经可知；不能使用未来收益当因子。未知代码、非交易日、重复键或非有限数值会拒绝，缺失日期不填充。`examples/factor_values_TEMPLATE.csv`仅说明格式，其两行虚构数值不构成可评价样本；至少30个有效配对才输出IC。

```bash
python -m factorlab.runner --data-dir /行情目录 --reference-dir /状态目录 \
  --factors '' --factor-csv /你的因子.csv --direction 1 --output results/my_factor
```

网页支持相同的CSV接口，上限10MB；大矩阵使用命令行。导入数据只能核查格式，无法自动证明发布时间与因果性，报告持续显示这一限制。

输出包括`summary.json`、`daily.csv`、`groups.csv`、`coverage.csv`、`manifest.json`、独立HTML与Markdown报告；净交易另有`accounts/`完整账本。manifest记录参数、源码、课程文件与历史状态清单哈希，不发布原始行情或缓存。

方法参考：[Alphalens原始文档](https://quantopian.github.io/alphalens/alphalens.html)、[因子评价实现](https://github.com/quantopian/alphalens/blob/master/alphalens/performance.py)。穿石为本项目自有实现，不要求安装旧版Alphalens。
