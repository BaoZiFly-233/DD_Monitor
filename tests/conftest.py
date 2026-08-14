# -*- coding: utf-8 -*-
"""pytest 公共配置 — 无头 GUI 环境。"""

import asyncio
import os
import sys

import pytest

# 确保项目根目录可导入
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Qt 无头模式（CI / 无显示器环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    """全局 QApplication（会话级，避免重复创建）"""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def pytest_sessionfinish():
    """为 bilibili_api 的 atexit 清理保留可用事件循环。"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = None
    if loop is None or loop.is_closed():
        asyncio.set_event_loop(asyncio.new_event_loop())
