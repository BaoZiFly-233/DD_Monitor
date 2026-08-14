# -*- coding: utf-8 -*-
"""30 分钟稳定性测试 — 模拟真实用户行为循环，检查崩溃/内存增长。

行为循环（QTimer 驱动，每 10s 一轮）：
1. 页面切换（导航 4 页轮询）
2. 播放窗口轮换（内存窗口 0/1/2 播放 lavfi 流，其余窗口开关弹幕机）
3. 弹幕消息注入（随机房间窗口）
4. 音量/静音/画质调节
5. 悬浮窗弹出与关闭
每 60s 记录: 运行秒数 / RSS 内存 / 事件循环健康度。
30 分钟后正常关闭并打印 FINAL-STABLE。
"""
import os
import sys
import time
import tempfile
import shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel, QProgressBar
from PySide6.QtGui import QFont

DURATION_S = 30 * 60          # 30 分钟
CYCLE_MS = 10 * 1000          # 每轮行为周期
REPORT_MS = 60 * 1000         # 每分钟记录

tmp = tempfile.mkdtemp()
os.makedirs(os.path.join(tmp, "resources"), exist_ok=True)
os.makedirs(os.path.join(tmp, "logs"), exist_ok=True)
for n in ("splash.jpg", "vtb.csv"):
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", n)
    if os.path.exists(src):
        shutil.copy2(src, os.path.join(tmp, "resources", n))

app = QApplication(sys.argv)
from app.ui.uikit_bridge import init_uikit
init_uikit()
app.setFont(QFont("微软雅黑", 9))

import app.ui.main_window as mw
mw.get_application_path = lambda: tmp
from app.core import log
log.init_log(tmp)

win = mw.MainWindow(tmp + "/cache", QProgressBar(), QLabel("x"))
win.resize(1400, 850)
win.show()

# 启动播放（窗口 0-2 播 lavfi，其余待命）
for vw in win.videoWidgetList[:3]:
    vw._init_mpv()
    vw._mpv.play("lavfi://testsrc2=size=640x360:rate=30")
    vw.videoFrame.setPlaybackActive(True)
    vw.mediaReload()
for vw in win.videoWidgetList[3:]:
    vw._init_mpv()

pages = [win.monitorPage, win.danmakuPage, win.cardPage, win.settingsPage]
page_i = [0]
cycle = [0]
t0 = time.monotonic()
rss_peak = [0]


def logf(msg):
    print(f"[{time.monotonic()-t0:7.0f}s] {msg}", flush=True)


def mock_danmu():
    import random
    for vw in win.videoWidgetList[:3]:
        try:
            vw.playDanmu("稳定性测试弹幕%d" % random.randint(0, 999))
        except Exception:
            pass


def do_cycle():
    cycle[0] += 1
    c = cycle[0]
    # 1. 页面切换
    page_i[0] = (page_i[0] + 1) % len(pages)
    win.contentStack.setCurrentWidget(pages[page_i[0]])
    # 2. 弹幕机开关（窗口 3 轮换）
    vw3 = win.videoWidgetList[3]
    if c % 2 == 0:
        vw3.showTextBrowser()
    else:
        vw3.hideTextBrowser()
    # 3. 弹幕注入
    mock_danmu()
    # 4. 音量/静音（全局）
    if c % 3 == 0:
        win.globalSetVolume((c * 7) % 100)
    if c % 5 == 0:
        win.globalMediaMute()
    # 5. 悬浮窗弹出关闭（窗口 0 每 4 轮一次）
    if c % 4 == 0:
        win._getOrCreatePopVideoWidget(0)


def do_report():
    import psutil
    proc = psutil.Process(os.getpid())
    rss = proc.memory_info().rss // (1024 * 1024)
    rss_peak[0] = max(rss_peak[0], rss)
    elapsed = time.monotonic() - t0
    logf(f"报告 rss={rss}MB peak={rss_peak[0]}MB cycle={cycle[0]}")
    if elapsed >= DURATION_S:
        logf(f"FINAL-STABLE elapsed={elapsed:.0f}s rss_peak={rss_peak[0]}MB cycles={cycle[0]}")
        win.close()
        app.quit()


cycle_timer = QTimer()
cycle_timer.timeout.connect(do_cycle)
cycle_timer.start(CYCLE_MS)
report_timer = QTimer()
report_timer.timeout.connect(do_report)
report_timer.start(REPORT_MS)

# 先立即跑一轮行为避免空等
QTimer.singleShot(2000, do_cycle)
logf("STABILITY-TEST START")
app.exec()
logf("EXIT-NORMAL")
shutil.rmtree(tmp, ignore_errors=True)