# 启动与页面导航

[实验室总览](../README.md) · [回测系统](../README_BACKTEST.md) · [策略研究](../README_RESEARCH.md) · [因子评价](../README_FACTORS.md)

## 在macOS中双击哪里

1. 打开 **Finder（访达）**，找到本项目的`stoneflow-quant`文件夹。
2. 进入能看到`README.md`、`web_server.py`和`Start.command`的这一层。
3. **双击文件`Start.command`**。这里双击的是电脑上的文件。
4. 启动窗口会显示本机地址，并在默认浏览器打开实验室。如果服务已在运行，会直接打开现有页面。

当终端窗口显示“穿石 Stoneflow 已启动”时，可将该窗口最小化并继续使用浏览器。保留负责运行服务的窗口；退出服务可在该窗口按`Control+C`。服务关闭后，本机网址停止响应，保存的离线报告仍可阅读。

## 打开以后去哪里

| 页面 | 地址 | 用途 |
| --- | --- | --- |
| 策略回测 | http://127.0.0.1:8765/ | 修改配置、运行回测、检查账户与交易记录 |
| 因子观测台 | http://127.0.0.1:8765/factors | 选择因子、股票池与期限，重跑评价或导入CSV |
| 5DR策略研究 | http://127.0.0.1:8765/5dr | 阅读已保存的全池5DR策略比较 |
| 20日突破研究 | http://127.0.0.1:8765/breakout | 阅读已保存的全池突破策略比较 |
| 本机报告首页 | http://127.0.0.1:8765/reports/index.html | 浏览独立研究报告 |

顶部模块导航可以在回测、因子评价与报告间切换。`127.0.0.1`指打开浏览器的这台电脑，其他设备阅读共享研究时使用静态报告。

## 首次配置环境

Python 3.10+，推荐3.12。在项目目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python web_server.py --data-dir /你的路径/feathers --open-browser
```

`feathers`目录应包含`open`、`high`、`low`、`close`、`amt`、`num_trades`、`cumadj`七个`.feather`文件。课程数据来源见[研究背景](../README_RESEARCH.md#研究背景与课程要求)。

也可将数据放到项目的`data/feathers/`，或在被忽略的`local_config.json`中保存配置：

```json
{
  "data_dir": "/你的路径/feathers",
  "reference_dir": "/你的路径/baostock-20230901-20260930",
  "action_dir": "/你的路径/actions"
}
```

已有配置时按需修改字段，保留其他本机运行设置。`data_dir`供课程行情读取；因子网页重跑需要`reference_dir`中的历史ST和交易状态。原始股份净交易研究的命令行还需通过`--action-dir`指定公司行为资料；具体复现命令见各模块文档。

双击启动优先使用项目`.venv`；已配置的本机运行路径也可由启动文件读取。缺少依赖或数据时，启动窗口会给出相应信息。

## 只阅读报告

双击项目根目录的[OpenReports.command](../OpenReports.command)，或打开[离线首页](../report_site/index.html)。独立因子报告为[report_site/factors.html](../report_site/factors.html)，可切换保存的结果并导出明细。

离线报告无需启动Python，也不读取原始行情。GitHub Pages提供同类只读报告；发布状态与操作见[报告站点说明](REPORT_SITE.md)。
