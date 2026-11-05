# -*- coding: utf-8 -*-
"""程序入口：点阵连线求解器"""
import os
import sys

# 开发环境：PySide6 安装在独立短路径，避免长路径限制；打包后由 PyInstaller 收集，此段无效
for _p in (r"C:\pylibs", os.path.join(os.path.dirname(os.path.abspath(__file__)), "libs")):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flowlink.app import main

if __name__ == "__main__":
    main()
