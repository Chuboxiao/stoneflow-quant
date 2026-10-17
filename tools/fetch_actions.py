"""Fetch only the symbol-years required by held corporate-action events."""
from __future__ import annotations
import argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
import json
from pathlib import Path
import socket
import time


def batch(job):
    pairs,destination=job
    import baostock as bs
    socket.setdefaulttimeout(20)
    bs.login()
    failed=[]
    for symbol,year in pairs:
        path=Path(destination)/f"{symbol}-{year}.json"
        if path.exists() and json.loads(path.read_text()).get("error") is None:continue
        code,ex=symbol.split(".")
        result={"symbol":symbol,"year":year,"events":[],"source":"BaoStock query_dividend_data(yearType=operate)","retrieved_at":time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        for attempt in range(3):
            try:
                response=bs.query_dividend_data(f"{ex.lower()}.{code}",str(year),"operate")
                if response.error_code!="0":raise ValueError(response.error_msg)
                rows=[]
                while response.error_code=="0" and response.next():rows.append(dict(zip(response.fields,response.get_row_data())))
                if response.error_code!="0":raise ValueError(response.error_msg)
                result["events"]=rows
                result["error"]=None
                break
            except Exception as exc:
                result["error"]=str(exc)
                if attempt<2:
                    time.sleep(.5);bs.login()
        if result.get("error"):failed.append([symbol,year,result["error"]])
        path.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return failed


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--requests",required=True)
    parser.add_argument("--output",default="data/reference/actions")
    parser.add_argument("--workers",type=int,default=1)
    args=parser.parse_args()
    pairs=json.loads(Path(args.requests).read_text())
    root=Path(args.output).resolve();root.mkdir(parents=True,exist_ok=True)
    pairs=[v for v in pairs if not (root/f"{v[0]}-{v[1]}.json").exists()
           or json.loads((root/f"{v[0]}-{v[1]}.json").read_text()).get("error")]
    jobs=[pairs[i:i+20] for i in range(0,len(pairs),20)]
    failures=[]
    if not 1<=args.workers<=4:parser.error("Use 1–4 workers")
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for i,result in enumerate(as_completed([pool.submit(batch,(job,str(root))) for job in jobs]),1):
            failures.extend(result.result());print(f"Action batches {i}/{len(jobs)}",flush=True)
    print(json.dumps({"requests":len(pairs),"failures":failures},ensure_ascii=False),flush=True)


if __name__=="__main__":main()
