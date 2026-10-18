# 网页研究报告：阅读、打包与发布

## 两种网页各做什么

| 入口 | 功能 | 是否需要课程行情或Python |
| --- | --- | --- |
| `report_site/index.html`及GitHub Pages | 阅读已保存的5DR、20日突破和完整报告，含图表、表格、机制与股票子集分析 | 不需要 |
| `python web_server.py`启动的`127.0.0.1` | 本机研究工作台、参数修改、策略运行、查看与导出结果 | 重新回测需要依赖和行情；全池研究另见精度指南 |

老师不能通过自己的电脑打开你电脑上的`127.0.0.1`。GitHub仓库文件页通常展示HTML源文件；使用Pages才能把静态报告按网页提供。Pages托管不运行Python，因此不能代替本机回测服务。

现在下载仓库后，双击`report_site/index.html`即可离线阅读并在报告间切换。页面使用相对导航、内嵌CSS与SVG，无需第三方字体、CDN、数据接口或本机文件路径。

macOS也可双击仓库根目录的`OpenReports.command`，由默认浏览器打开离线首页。无需Python，也不依赖`127.0.0.1`预览服务；临时预览服务停止后，这个入口仍可使用。

## 重新打包

在仓库根目录运行，Python标准库即可：

```bash
python3 build_report_site.py
python3 build_report_site.py --check
```

打包来源为已保存的5DR、突破、机制研究HTML与`REVIEW_LECTURE4.md`。`full.html`包含总览和两份报告的全部内容，突破全文已包含机制与股票子集分析；单独的`analysis.html`方便直接跳转。此过程不运行回测，不改变策略和指标，不读取原始Feather或辅助行情缓存。

`manifest.json`保存源文件SHA-256。打包过程保留研究假设、精度边界、图表与数值，只调整阅读导航和页面展示。

本地HTTP预览（也可直接双击HTML）：

```bash
python3 -m http.server 8768 --bind 127.0.0.1 --directory report_site
```

然后打开 http://127.0.0.1:8768/ 。

## 发布流程

代码推送、网页部署与课程评论分别执行。

1. 在保存待发布版本的分支运行`bash push_to_github.sh --publish-reviewed`，把当前HEAD推送至远程`main`。脚本不切换本地分支、不强制覆盖远程；普通运行只显示说明，不发布。
2. 在仓库 **Settings → Pages → Build and deployment → Source** 选择 **GitHub Actions**。
3. 在 **Actions → Publish read-only research reports → Run workflow**，选择`main`并手动运行。工作流只上传`report_site/`，不会发布课程数据、辅助缓存或完整仓库。
4. 等待部署成功，分别验证下列线上地址和评论内的截图链接。确认成功后，将README的在线访问说明更新为实际状态，再发布课程评论。未部署的地址不能当作已可访问的网页。

| 报告 | 预定地址 |
| --- | --- |
| 首页 | https://chuboxiao.github.io/stoneflow-quant/ |
| 5DR | https://chuboxiao.github.io/stoneflow-quant/5dr.html |
| 20日突破 | https://chuboxiao.github.io/stoneflow-quant/breakout.html |
| 完整报告 | https://chuboxiao.github.io/stoneflow-quant/full.html |
| 机制与股票子集 | https://chuboxiao.github.io/stoneflow-quant/analysis.html |

工作流只有手动触发器；普通push和PR不会自动发布。部署任务限制为`main`分支，工作流的Pages权限只赋予发布任务。

GitHub官方说明：[自定义Pages工作流](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)、[配置发布来源](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)。
