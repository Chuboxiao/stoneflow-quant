#!/bin/zsh
cd "${0:A:h}"
if python3 - <<'PY'
import json, sys, urllib.request
try:
    request = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    state = json.load(request.open('http://127.0.0.1:8765/api/bootstrap', timeout=1))
    sys.exit(0 if state.get('english_name') == 'STONEFLOW' else 1)
except Exception:
    sys.exit(1)
PY
then
  open http://127.0.0.1:8765
  echo '已打开正在运行的穿石实验室。'
  exit 0
fi
if [[ -x .venv/bin/python ]]; then
  python_bin=.venv/bin/python
else
  python_bin="$(python3 -c 'import json,pathlib; p=pathlib.Path("local_config.json"); print(json.loads(p.read_text()).get("runtime_python","python3") if p.exists() else "python3")')"
  extra_packages="$(python3 -c 'import json,pathlib; p=pathlib.Path("local_config.json"); print(json.loads(p.read_text()).get("runtime_pythonpath","") if p.exists() else "")')"
  if [[ -n "$extra_packages" ]]; then
    export PYTHONPATH="$extra_packages${PYTHONPATH:+:$PYTHONPATH}"
  fi
fi
if ! "$python_bin" -c 'import pandas, numpy, pyarrow' 2>/dev/null; then
  echo '请先按README安装依赖；当前Python缺少pandas、numpy或pyarrow。'
  read '?按回车关闭。'
  exit 1
fi
"$python_bin" web_server.py --port 8765 --open-browser
