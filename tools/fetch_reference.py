"""Download public historical trading states; raw cache stays outside Git.

Each process owns its BaoStock socket. No credentials or paid API are required.
Restarting resumes existing successful files. Unknown dates stay unknown.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import socket
import time


def fetch_batch(args):
    symbols, destination, start, end = args
    import baostock as bs
    socket.setdefaulttimeout(20)
    root = Path(destination)
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"BaoStock login: {login.error_code} {login.error_msg}")
    failures = []
    for symbol in symbols:
        path = root / f"{symbol}.csv.gz"
        if path.exists():
            continue
        code, exchange = symbol.split(".")
        for attempt in range(3):
            try:
                response = bs.query_history_k_data_plus(
                    f"{exchange.lower()}.{code}",
                    "date,code,close,preclose,tradestatus,isST", start, end, "d", "3")
                if response.error_code != "0":
                    raise RuntimeError(f"{response.error_code}: {response.error_msg}")
                # Avoid deprecated DataFrame.append in the provider's pagination helper.
                rows = []
                while response.error_code == "0" and response.next():
                    rows.append(response.get_row_data())
                if response.error_code != "0":
                    raise RuntimeError(response.error_msg)
                import pandas as pd
                frame = pd.DataFrame(rows, columns=response.fields)
                if not set(("date", "isST", "preclose", "tradestatus", "close")).issubset(frame):
                    raise RuntimeError("Missing response fields")
                temporary = path.with_suffix(".part.gz")
                frame.to_csv(temporary, index=False, compression="gzip")
                temporary.replace(path)
                break
            except Exception as exc:
                if attempt == 2:
                    failures.append({"symbol": symbol, "error": str(exc)})
                else:
                    time.sleep(1)
                    bs.login()
    # Anonymous logouts can invalidate another worker's requests. Socket close
    # on process exit is sufficient; do not send a shared-user logout here.
    return failures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--output", default="data/reference/baostock-20230901-20260930")
    parser.add_argument("--start", default="2023-09-01")
    parser.add_argument("--end", default="2026-09-30")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.workers <= 4:
        parser.error("Use 1–4 workers")
    import pyarrow as pa
    with pa.memory_map(str(Path(args.data_dir)/"close.feather"), "r") as source:
        symbols = [x for x in pa.ipc.open_file(source).schema.names if x != "date"]
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    missing = [x for x in symbols if not (root/f"{x}.csv.gz").exists()]
    print(f"Cached {len(symbols)-len(missing)}/{len(symbols)}; downloading {len(missing)}", flush=True)
    failures = []
    # Small batches make progress observable and avoid interleaving protocol messages.
    batches = [missing[i:i+40] for i in range(0, len(missing), 40)]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        jobs = [pool.submit(fetch_batch, (batch, str(root), args.start, args.end)) for batch in batches]
        for count, job in enumerate(as_completed(jobs), 1):
            failures.extend(job.result())
            print(f"Batches {count}/{len(batches)}; files {len(list(root.glob('*.csv.gz')))}/{len(symbols)}", flush=True)
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.glob("*.csv.gz"))}
    manifest = {"provider": "BaoStock", "package_version": "0.9.4", "start": args.start,
                "end": args.end, "fields": "date,code,close,preclose,tradestatus,isST",
                "adjustflag": 3, "symbols_requested": len(symbols), "files": files,
                "failures": failures, "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "source": "https://www.baostock.com/"}
    (root/"manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps({"files": len(files), "failures": len(failures)}), flush=True)


if __name__ == "__main__":
    main()
