#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
M2 端入口: 启动云台控制（PCA9685 直驱）

用法:
    cd demo-servo-gimbal-control
    python3 -m venv .venv            # 在工程目录内创建隔离环境
    .venv/bin/pip install -r requirements.txt
    python3 run_gimbal.py            # 启动程序
"""
import glob
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# GNOME Wayland (SSH 场景): 自动补 DISPLAY / Xwayland 授权,
# 否则 Qt 报 "Authorization required ... could not connect to display :0"
os.environ.setdefault("DISPLAY", ":0")
if not os.environ.get("XAUTHORITY"):
    auth = glob.glob(f"/run/user/{os.getuid()}/.mutter-Xwaylandauth.*")
    if auth:
        os.environ["XAUTHORITY"] = auth[0]

# 优先使用工程目录内创建的隔离环境
venv_python = None
for venv_name in (".venv", "venv"):
    candidate = ROOT / venv_name / "bin" / "python3"
    if candidate.exists():
        venv_python = candidate
        break

if venv_python is None:
    sys.stderr.write(
        "未找到隔离环境, 请先在工程目录内执行:\n"
        f"  cd {ROOT}\n"
        "  python3 -m venv .venv\n"
        "  .venv/bin/pip install -r requirements.txt\n"
    )
    sys.exit(1)

os.chdir(ROOT)
os.execv(str(venv_python), [str(venv_python), str(ROOT / "src" / "main.py")])
