#!/bin/zsh
cd "${0:A:h}"
if [[ -x .venv/bin/python ]]; then
  python_bin=.venv/bin/python
else
  python_bin=python3
fi
open http://127.0.0.1:8765
"$python_bin" web_server.py --port 8765
