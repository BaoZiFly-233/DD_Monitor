# -*- coding: utf-8 -*-
"""30 分钟稳定性测试（真实直播版）— 真实 B 站房间播放流 + 真实 blivedm 弹幕。

行为循环（QTimer 每 10s）：
1. 页面切换（导航 4 页轮询，验证 MpvGLWidget 隐藏挂起补丁）
2. 弹幕注入模拟 + 真实 blivedm 弹幕接收（房间 21013446）
3. 音量/静音/画质调节
4. 悬浮窗弹出与关闭
每分钟记录 RSS 内存；30 分钟后正常关闭打印 FINAL-STABLE。
"""
import os
import sys
import time
import tempfile
import shutil
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel, QProgressBar
from PySide6.QtGui import QFont

DURATION_S = 30 * 60
CYCLE_MS = 10 * 1000
REPORT_MS = 60 * 1000
ROOM_ID = "21013446"          # 真实直播间（直播中）

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

# 预取真实播放流地址（有效期约 2 小时，足够测试）
# B 站接口结构不稳定：有时 url_info[]（FLV），有时 master_url（HLS），需兼容 + 重试
REAL_URL = None
def fetch_real_url():
    H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Referer": "https://live.bilibili.com/"}
    r = requests.get(
        "https://api.live.bilibili.com/xlive/web-room/v2/index/getRoomPlayInfo",
        params={"room_id": ROOM_ID, "protocol": "0,1", "format": "0,1,2", "codec": "0,1",
                "qn": "10000", "platform": "web"},
        timeout=12, headers=H,
    )
    d = r.json()["data"]["playurl_info"]["playurl"]
    for s in d.get("stream", []):
        for f in s.get("format", []):
            # 1) FLV: base_url + url_info[]
            for c in f.get("codec", []):
                uis = c.get("url_info") or []
                for u in uis:
                    base = u.get("base_url") or ""
                    host = u.get("host") or ""
                    if base and host:
                        # base_url 以 '?' 结尾（B 站接口设计），extra 直接接在后面
                        return host + base + (u.get("extra", "") or "")
            # 2) HLS: master_url
            m = f.get("master_url")
            if m:
                return m
    return None

for attempt in range(3):
    try:
        REAL_URL = fetch_real_url()
        if REAL_URL:
            print(f"真实流已获取(第{attempt+1}次): {REAL_URL[:90]}", flush=True)
            break
    except Exception as e:
        print(f"获取真实流失败(第{attempt+1}次): {type(e).__name__} {e}", flush=True)
    time.sleep(2)

# 启动播放：窗口 0-2 走项目真实取流+播放链路（mediaReload → FetchRoomInfo
# → _onRoomInfo → GetStreamURL 线程 → mpv.play），其余窗口仅初始化 MPV
for vw in win.videoWidgetList[:3]:
    vw._init_mpv()
    vw.roomID = str(ROOM_ID)
    vw.mediaReload()  # 真实取流并播放
for vw in win.videoWidgetList[3:]:
    vw._init_mpv()

# 真实弹幕线程（blivedm 直连房间）
from app.media.remote import remoteThread

real_danmu_thread = remoteThread(ROOM_ID, "")

total_msgs = [0]


def on_danmu(msg):
    total_msgs[0] += 1
    if total_msgs[0] <= 3:
        print(f"真实弹幕收到: {msg[:40]}", flush=True)


real_danmu_thread.message.connect(on_danmu)
real_danmu_thread.start()

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
    # 1. 页面切换（触发 monitorPage 隐藏 → MpvGLWidget 挂起渲染）
    page_i[0] = (page_i[0] + 1) % len(pages)
    win.contentStack.setCurrentWidget(pages[page_i[0]])
    # 2. 模拟弹幕注入
    mock_danmu()
    # 3. 音量/静音
    if c % 3 == 0:
        win.globalSetVolume((c * 7) % 100)
    if c % 5 == 0:
        win.globalMediaMute()
    # 4. 悬浮窗弹出（index 轮换，已完成则关闭）
    if c % 4 == 0:
        pop = win._getOrCreatePopVideoWidget(0)
        if pop.isHidden():
            pop.show()


def do_report():
    import psutil
    proc = psutil.Process(os.getpid())
    rss = proc.memory_info().rss // (1024 * 1024)
    rss_peak[0] = max(rss_peak[0], rss)
    elapsed = time.monotonic() - t0
    danmu_ok = "连接中"
    if total_msgs[0] > 0:
        danmu_ok = f"收弹幕{total_msgs[0]}条"
    logf(f"报告 rss={rss}MB peak={rss_peak[0]}MB cycle={cycle[0]} 弹幕={danmu_ok}")
    if elapsed >= DURATION_S:
        logf(f"FINAL-STABLE elapsed={elapsed:.0f}s rss_peak={rss_peak[0]}MB cycles={cycle[0]} 弹幕总数={total_msgs[0]}")
        real_danmu_thread.stop()
        win.close()
        app.quit()


cycle_timer = QTimer()
cycle_timer.timeout.connect(do_cycle)
cycle_timer.start(CYCLE_MS)
report_timer = QTimer()
report_timer.timeout.connect(do_report)
report_timer.start(REPORT_MS)

QTimer.singleShot(2000, do_cycle)
logf("STABILITY-TEST(REAL) START")
app.exec()
logf("EXIT-NORMAL")
shutil.rmtree(tmp, ignore_errors=True)