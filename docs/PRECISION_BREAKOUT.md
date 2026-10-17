# 全池20日突破的复现与精度

本次扩展保持原5DR研究结果，在同一个原始股份引擎中增加全池状态型突破策略。评价区间2025-01-02至2026-09-30；2024仅选型。已看过此前结果，本研究是回顾性时间隔离，不是真实前瞻预注册。

## 本机查看

```bash
python web_server.py --data-dir /你的路径/feathers
```

打开`http://127.0.0.1:8765/breakout`；`/5dr`保留反转研究，`/`保留最初的个股实验。无行情数据也可打开`results/breakout_review/report.html`阅读离线报告。

## 重跑

先按`PRECISION_5DR.md`安装`requirements-research.txt`并下载逐日辅助状态。下面命令在仓库目录运行，`work/`为临时发现目录：

```bash
python research_breakout.py --data-dir /你的路径/feathers --register-only
python research_breakout.py --data-dir /你的路径/feathers --output work/breakout_discovery --provisional
python tools/fetch_actions.py --requests work/breakout_discovery/needed_actions.json
```

再次运行发现模式，检查`needed_actions.json`和`event_discrepancies.json`。前者为空、后者无未解释差异后再正式运行；发现模式允许合成数量，仅用于定位缺资料，收益不能当正式结果。若已下载事件仍不匹配，应核对公告或数据，不能把正式缺失检查关闭。

```bash
python research_breakout.py --data-dir /你的路径/feathers
python validate_5dr.py --results results/breakout_review
python -m unittest discover -s tests -v > results/breakout_review/unit_tests.txt 2>&1
python make_breakout_report.py
```

`protocol.json`先记录5个候选；正式运行重新检查候选定义没有变化。`selection.json`只使用2024成绩，`control_protocol.json`记录试跑后追加的固定半仓归因诊断，它不进入选型。本次包含5训练、5评价、基础与冻结方案各2个压力情景、1个半仓诊断，共15组账户。若复现时选出的方案变成基础版，压力情景会去重，应以实际运行清单为准。

研究脚本通过`on_close(context)`公共接口执行策略，使用实际持仓和持续退出状态。没有改变原`PrecisionEngine`、旧5DR候选或已保存结果。`backtest/breakout_pool.py`可作为实现自定义状态型策略的例子。

## 精度和来源

撮合、T+1、原始现金与股份、分红应收、股份锁定、板块数量、历史限价重建、缺价减记与费用沿用`PRECISION_5DR.md`，所有局限同样适用。这里的ATR退出只在收盘判断，下一交易日执行，不假设按盘中止损价成交。

`reference/breakout_corporate_reference_overrides.json`新增3笔公告摘要，均为回购专户不分配造成实际到账比例与摊薄除权参考比例不同。账户用实际到账比例，参考价检查用公告参考比例；数据修复不改变选股参数。

源码、输入文件和辅助缓存哈希存于`source_manifest.json`。第三方服务可能修订历史，复现时先核对哈希。课程源包是否覆盖完整历史A股、ST公告具体时点、开盘盘口成交、完整个税与特殊重整仍未解决，不将它们藏在“测试通过”之后。
