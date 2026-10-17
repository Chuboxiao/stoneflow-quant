"""Stoneflow 本机网页服务：只绑定 loopback，调用真实回测引擎。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
import json
import math
import mimetypes
from pathlib import Path
import threading
import time
import uuid
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urlparse

import pandas as pd
import pyarrow as pa
from backtest import BacktestConfig, BacktestEngine, FeeModel, MarketData, PeriodicEqualWeight
from backtest.limits import LimitPolicy
from backtest.report import export_result, json_safe

ROOT = Path(__file__).resolve().parent
NAMES = {"603950.SH":"长源东谷", "002230.SZ":"科大讯飞", "688508.SH":"芯朋微",
         "000001.SZ":"平安银行", "000002.SZ":"万科A", "600519.SH":"贵州茅台",
         "600036.SH":"招商银行", "300750.SZ":"宁德时代", "601318.SH":"中国平安"}
DOWNLOADS = {"equity.csv", "orders.csv", "positions.csv", "signals.csv", "metrics.json", "metadata.json", "report.html"}


def records(frame):
    return json_safe(frame.where(pd.notna(frame),None).to_dict("records"))


class Application:
    def __init__(self, data_dir, results_dir=None):
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.results_dir = Path(results_dir or ROOT/"results/web").resolve()
        self.results_dir.mkdir(parents=True,exist_ok=True)
        self.pool = ThreadPoolExecutor(max_workers=1,thread_name_prefix="stoneflow")
        self.jobs, self.lock = {}, threading.Lock()
        self.catalog, self.dates = [], []
        self.data_error = None
        try:
            with pa.memory_map(str(self.data_dir/"close.feather"),"r") as source:
                columns = pa.ipc.open_file(source).schema.names
            self.catalog = [c for c in columns if c != "date"]
            self.dates = pd.read_feather(self.data_dir/"close.feather",columns=["date"])["date"].dt.strftime("%Y-%m-%d").tolist()
            missing = [f for f in ("open","high","low","close","amt","num_trades","cumadj")
                       if not (self.data_dir/f"{f}.feather").is_file()]
            if missing: raise ValueError("缺少数据文件："+", ".join(missing))
        except Exception as exc:
            self.data_error = str(exc)

    def run_directory(self, run_id):
        if run_id == "research": return ROOT/"results/research"
        if run_id == "demo":
            return ROOT/"results/demo"
        if not (len(run_id)==12 and all(c in "0123456789abcdef" for c in run_id)):
            raise ValueError("无效运行编号")
        return self.results_dir/run_id

    def list_runs(self):
        directories = [("research",ROOT/"results/research"),("demo",ROOT/"results/demo")]
        directories += [(p.name,p) for p in self.results_dir.iterdir() if p.is_dir()]
        result = []
        for run_id,directory in directories:
            if not (directory/"metrics.json").exists(): continue
            try:
                metrics = json.loads((directory/"metrics.json").read_text())
                metadata = json.loads((directory/"metadata.json").read_text())
                result.append({"id":run_id,"created_at":metadata.get("created_at","预置演示"),
                               "metrics":metrics,"symbols":metadata["data_audit"]["symbols"],
                               "limit_mode":metadata["limit_mode"],
                               "strategy_parameters":metadata.get("strategy_parameters",{})})
            except (ValueError,KeyError,OSError): continue
        return sorted(result,key=lambda r: (r["id"]!="demo",r["created_at"]),reverse=True)

    def bootstrap(self):
        runs = self.list_runs()
        return {"name":"穿石","english_name":"STONEFLOW","version":"1.0",
                "data_connected":self.data_error is None,"data_error":self.data_error,
                "dataset":{"rows":len(self.dates),"securities":len(self.catalog),
                           "first_date":self.dates[0] if self.dates else None,
                           "last_date":self.dates[-1] if self.dates else None,"files":7},
                "catalog":[{"symbol":s,"name":NAMES.get(s,"")} for s in self.catalog],
                "defaults":{"symbols":["603950.SH","002230.SZ"],"start":"2020-07-01",
                            "end":self.dates[-1] if self.dates else "2026-10-16",
                            "cash":1000000,"rebalance_every":20,"invested_weight":0.98,
                            "commission":0.0003,"min_commission":5,"slippage_bps":5,
                            "limit_mode":"conservative"},"runs":runs}

    def read_run(self, run_id):
        directory = self.run_directory(run_id)
        if not (directory/"metrics.json").is_file(): raise FileNotFoundError("未找到回测结果")
        result = {"id":run_id}
        for name in ("metrics","metadata"):
            result[name] = json.loads((directory/f"{name}.json").read_text(encoding="utf-8"))
        for name in ("equity","orders","positions","signals"):
            result[name] = records(pd.read_csv(directory/f"{name}.csv"))
        return result

    def validate(self, request):
        if self.data_error: raise ValueError("课程数据未连接："+self.data_error)
        allowed = {"strategy_id","symbols","start","end","cash","rebalance_every","invested_weight",
                   "commission","min_commission","slippage_bps","limit_mode","limits_csv_text"}
        if not isinstance(request,dict) or set(request)-allowed: raise ValueError("请求包含未知参数")
        symbols = request.get("symbols",[])
        if (not isinstance(symbols,list) or not 1 <= len(symbols) <= 5 or
                any(not isinstance(s,str) for s in symbols) or len(set(symbols))!=len(symbols)
                or not set(symbols).issubset(self.catalog)):
            raise ValueError("请选择 1 至 5 个不重复、数据包内存在的证券代码")
        clean = {"symbols":list(symbols)}
        clean["strategy_id"] = request.get("strategy_id","research")
        if clean["strategy_id"] not in ("research","equal_weight"): raise ValueError("未知策略模块")
        if clean["strategy_id"]=="research" and len(symbols)!=2: raise ValueError("研究比较须选择两只股票")
        for key in ("start","end"):
            value = request.get(key)
            try:
                date = pd.Timestamp(value)
                if not isinstance(value,str) or len(value)!=10 or pd.isna(date) or date.tz is not None:
                    raise ValueError()
                clean[key] = date.strftime("%Y-%m-%d")
            except Exception as exc: raise ValueError("日期格式必须为 YYYY-MM-DD") from exc
        if not self.dates[0] <= clean["start"] < clean["end"] <= self.dates[-1]:
            raise ValueError("请在数据范围内选择有效的起止日期，结束日期须晚于开始日期")
        for key,default,lo,hi in [("cash",1000000,1,1e12),("invested_weight",0.98,0.01,1),
                                  ("commission",0.0003,0,0.02),("min_commission",5,0,10000),
                                  ("slippage_bps",5,0,1000)]:
            try:
                value = float(request.get(key,default))
            except (ValueError,TypeError) as exc: raise ValueError(f"{key} 必须是数字") from exc
            if not math.isfinite(value) or not lo <= value <= hi: raise ValueError(f"{key} 超出允许范围")
            clean[key] = value
        every = request.get("rebalance_every",20)
        if isinstance(every,bool) or not isinstance(every,int) or not 1 <= every <= 252:
            raise ValueError("调仓间隔必须为 1 至 252 的整数")
        clean["rebalance_every"] = every
        mode = request.get("limit_mode","strict")
        if mode not in ("strict","conservative"): raise ValueError("成交模式无效")
        clean["limit_mode"] = mode
        text = request.get("limits_csv_text","")
        if not isinstance(text,str) or len(text)>1_500_000: raise ValueError("涨跌停文件过大或格式无效")
        if text.strip(): LimitPolicy(mode,pd.read_csv(StringIO(text),dtype={"symbol":str}))
        clean["limits_csv_text"] = text
        return clean

    def submit(self, payload):
        clean = self.validate(payload)
        with self.lock:
            if any(job["status"] in ("queued","running") for job in self.jobs.values()):
                raise RuntimeError("已有回测正在运行，请等待完成")
            run_id = uuid.uuid4().hex[:12]
            self.jobs[run_id] = {"id":run_id,"status":"queued","stage":"等待开始"}
        self.pool.submit(self.execute,run_id,clean)
        return {"job_id":run_id}

    def update(self, job_key, **fields):
        with self.lock: self.jobs[job_key].update(fields)

    def execute(self, run_id, params):
        directory = self.results_dir/run_id
        try:
            self.update(run_id,status="running",stage="读取所选股票的 7 个行情矩阵")
            market = MarketData.from_feather(self.data_dir,params["symbols"])
            config = BacktestConfig(params["cash"],100,params["limit_mode"])
            fees = FeeModel(params["commission"],params["min_commission"],params["slippage_bps"])
            text = params["limits_csv_text"]
            policy = LimitPolicy(params["limit_mode"],pd.read_csv(StringIO(text),dtype={"symbol":str}) if text.strip() else None)
            self.update(run_id,stage="按交易日回放行情、撮合订单并更新账户")
            if params["strategy_id"]=="research":
                from research import run_research
                result=run_research(self.data_dir,params["symbols"],params["start"],params["end"],
                                    params["cash"],params["limit_mode"],fees,policy,directory)
            else:
                result = BacktestEngine(market,config,fees,policy).run(
                    PeriodicEqualWeight(params["rebalance_every"],params["invested_weight"]),params["start"],params["end"])
            result.metadata["created_at"] = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
            result.metadata["strategy_parameters"] = {"rebalance_every":params["rebalance_every"],"invested_weight":params["invested_weight"]}
            result.metadata["web_parameters"] = {k:v for k,v in params.items() if k!="limits_csv_text"}
            self.update(run_id,stage="保存交易记录和结果报告")
            export_result(result,directory)
            if text.strip(): (directory/"supplied_limits.csv").write_text(text,encoding="utf-8")
            self.update(run_id,status="completed",stage="回测完成",run_id=run_id)
        except Exception as exc:
            self.update(run_id,status="failed",stage="回测未完成",error=str(exc))


def make_handler(application):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Stoneflow/1.0"

        def json_response(self, obj, code=200):
            body = json.dumps(json_safe(obj),ensure_ascii=False,allow_nan=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type","application/json; charset=utf-8")
            self.send_header("Content-Length",str(len(body)))
            self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            route = urlparse(self.path).path
            try:
                if route == "/api/5dr-review":
                    directory=ROOT/"results/5dr_review"
                    status=json.loads((directory/"run_status.json").read_text())
                    if status.get("status")!="COMPLETE":raise ValueError("正式研究尚未完成："+status.get("status","UNKNOWN"))
                    summary=json.loads((directory/"summary.json").read_text())
                    series={}
                    for item in summary["comparison"]:
                        key=item["key"]
                        frame=pd.read_csv(directory/"evaluation"/key/"equity.csv")
                        series[key]=records(frame)
                    orders=pd.read_csv(directory/"evaluation"/summary["selected_key"]/"orders.csv")
                    positions=pd.read_csv(directory/"evaluation"/summary["selected_key"]/"positions.csv")
                    final_date=summary["performance_end"]
                    audit_path=directory/"validation.json"
                    return self.json_response({"summary":summary,"equity":series,
                        "orders":records(orders.tail(100)),"positions":records(positions[positions.date==final_date]),
                        "validation":json.loads(audit_path.read_text()) if audit_path.exists() else None})
                if route.startswith("/review-files/"):
                    name=route.rsplit("/",1)[-1]
                    if name not in {"report.html","comparison.csv","summary.json","validation.json","protocol.json","data_audit.json","precision_audit.json"}:
                        raise FileNotFoundError("文件不存在")
                    return self.send_file(ROOT/"results/5dr_review"/name,attachment=name!="report.html")
                if route == "/api/bootstrap": return self.json_response(application.bootstrap())
                if route == "/api/runs": return self.json_response(application.list_runs())
                if route.startswith("/api/jobs/"):
                    run_id = route.rsplit("/",1)[-1]
                    with application.lock: job = application.jobs.get(run_id,{}).copy()
                    if not job: raise FileNotFoundError("未找到任务")
                    return self.json_response(job)
                if route.startswith("/api/runs/"):
                    return self.json_response(application.read_run(route.rsplit("/",1)[-1]))
                if route.startswith("/files/"):
                    parts = route.split("/")
                    if len(parts)!=4 or parts[3] not in DOWNLOADS: raise FileNotFoundError("文件不存在")
                    path = application.run_directory(parts[2])/parts[3]
                    if not path.is_file(): raise FileNotFoundError("文件不存在")
                    return self.send_file(path,attachment=parts[3]!="report.html")
                assets = {"/":"index.html","/index.html":"index.html","/style.css":"style.css","/art.css":"art.css","/app.js":"app.js",
                          "/5dr":"5dr.html","/5dr.css":"5dr.css","/5dr.js":"5dr.js"}
                if route not in assets: raise FileNotFoundError("页面不存在")
                return self.send_file(ROOT/"web/dist"/assets[route])
            except FileNotFoundError as exc: self.json_response({"error":str(exc)},404)
            except ValueError as exc: self.json_response({"error":str(exc)},400)
            except Exception as exc: self.json_response({"error":f"读取失败：{exc}"},500)

        def send_file(self,path,attachment=False):
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type",(mimetypes.guess_type(path.name)[0] or "application/octet-stream") + ("; charset=utf-8" if path.suffix in (".html",".js",".css") else ""))
            self.send_header("Content-Length",str(len(body)))
            self.send_header("Cache-Control","no-cache")
            self.send_header("X-Content-Type-Options","nosniff")
            if attachment: self.send_header("Content-Disposition",f'attachment; filename="stoneflow_{path.name}"')
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            try:
                port = self.server.server_address[1]
                allowed_origins = {f"http://127.0.0.1:{port}",f"http://localhost:{port}"}
                host = self.headers.get("Host","")
                if host not in {f"127.0.0.1:{port}",f"localhost:{port}"}: return self.json_response({"error":"拒绝非本机请求"},403)
                origin = self.headers.get("Origin")
                if origin and origin not in allowed_origins: return self.json_response({"error":"拒绝跨站请求"},403)
                if urlparse(self.path).path != "/api/runs": raise FileNotFoundError("接口不存在")
                if self.headers.get("Content-Type","").split(";")[0] != "application/json":
                    return self.json_response({"error":"需要 application/json"},415)
                length = int(self.headers.get("Content-Length","0"))
                if not 0 < length <= 2_000_000: raise ValueError("请求为空或过大")
                payload = json.loads(self.rfile.read(length))
                return self.json_response(application.submit(payload),202)
            except FileNotFoundError as exc: self.json_response({"error":str(exc)},404)
            except RuntimeError as exc: self.json_response({"error":str(exc)},409)
            except (ValueError,TypeError) as exc: self.json_response({"error":str(exc)},400)

        def log_message(self,fmt,*args):
            if "/api/jobs/" not in str(args): super().log_message(fmt,*args)
    return Handler


def main():
    parser = argparse.ArgumentParser(description="穿石 Stoneflow 本地回测工作台")
    parser.add_argument("--data-dir",type=Path)
    parser.add_argument("--port",type=int,default=8765)
    args = parser.parse_args()
    default = json.loads((ROOT/"examples/demo_config.json").read_text(encoding="utf-8"))
    local_path=ROOT/"local_config.json"
    local=json.loads(local_path.read_text()) if local_path.exists() else {}
    app = Application(args.data_dir or os.environ.get("FEATHER_DIR") or local.get("data_dir") or default["data_dir"])
    server = ThreadingHTTPServer(("127.0.0.1",args.port),make_handler(app))
    print(f"穿石 Stoneflow 已启动：http://127.0.0.1:{args.port}",flush=True)
    print("仅在本机运行。按 Ctrl+C 停止。",flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        server.server_close()
        app.pool.shutdown(wait=True)


if __name__ == "__main__": main()
