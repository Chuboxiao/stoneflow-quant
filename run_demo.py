"""直接运行本文件：使用用户课程数据，演示保守过滤模式。"""
from pathlib import Path
import json
import sys
import os
from backtest.cli import main

if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    config = json.loads((root / "examples/demo_config.json").read_text(encoding="utf-8"))
    local = json.loads((root/"local_config.json").read_text()) if (root/"local_config.json").exists() else {}
    defaults = ["--data-dir", os.environ.get("FEATHER_DIR") or local.get("data_dir") or config["data_dir"], "--symbols", *config["symbols"],
                "--limit-mode", "conservative", "--output", str(root / "results/demo")]
    main([*defaults, *sys.argv[1:]])
