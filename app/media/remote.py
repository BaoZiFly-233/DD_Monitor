# -*- coding: utf-8 -*-
"""
弹幕接收线程 - 基于 blivedm 库的 WebSocket 连接
使用 Qt Signal 推送替代轮询，显著降低 CPU 开销
"""

import asyncio
import http.cookies
import logging
import threading
import uuid
from dataclasses import dataclass
from typing import Optional

import aiohttp
from PySide6.QtCore import QThread, Signal

import blivedm
import blivedm.models.web as web_models


@dataclass
class DanmakuEvent:
    """统一弹幕事件 — 标准化来自不同来源的弹幕数据"""

    kind: str = "danmaku"
    text: str = ""
    uname: str = ""
    color: str = "#FFFFFF"
    price: float = 0.0
    position: str = "scroll"


def _generate_buvid3() -> str:
    """生成 buvid3 cookie 值，绕过 B 站 data.bilibili.com 403 风控"""
    return str(uuid.uuid4()) + "infoc"


class DanmakuHandler(blivedm.BaseHandler):
    """弹幕事件处理器 - 通过 Qt Signal 直接推送消息到主线程"""

    def __init__(self, message_signal):
        super().__init__()
        self._signal = message_signal

    def _on_heartbeat(self, client: blivedm.BLiveClient, message: web_models.HeartbeatMessage):
        pass

    def _on_danmaku(self, client: blivedm.BLiveClient, message: web_models.DanmakuMessage):
        # 跳过镜像弹幕（DANMU_MSG_MIRROR），避免同一条弹幕出现两次
        if getattr(message, "is_mirror", False):
            return
        self._signal.emit(message.msg)

    def _on_gift(self, client: blivedm.BLiveClient, message: web_models.GiftMessage):
        if message.coin_type == "gold":
            self._signal.emit(f"** {message.uname} 赠送了 {message.num} 个 {message.gift_name}")

    def _on_buy_guard(self, client: blivedm.BLiveClient, message: web_models.GuardBuyMessage):
        self._signal.emit(f"** {message.username} 购买了 {message.gift_name}")

    def _on_super_chat(self, client: blivedm.BLiveClient, message: web_models.SuperChatMessage):
        self._signal.emit(f"【SC(￥{message.price}) {message.uname}: {message.message}】")


class remoteThread(QThread):
    """弹幕接收线程

    在独立线程中运行 asyncio 事件循环，通过 blivedm WebSocket 接收弹幕，
    使用 Qt Signal 推送消息到主线程，消除原有 20ms QTimer 轮询。
    """

    message = Signal(str)

    def __init__(self, roomID, sessionData=""):
        super(remoteThread, self).__init__()
        self.roomID = str(roomID)
        self.sessionData = sessionData if sessionData else ""
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event: Optional[asyncio.Event] = None
        # 停止请求标记（threading.Event 保证跨线程可见性）
        # 修复竞态：stop() 若在 _stop_event 创建前被调用，_connect() 创建后需能感知
        self._stop_requested = threading.Event()
        # 是否进入过 run()（用于区分"stop 先于启动"与"stop 来自上一轮运行"）
        self._has_run = False

    def setRoomID(self, roomID):
        self.roomID = str(roomID)

    def setSessionData(self, sessionData):
        self.sessionData = sessionData if sessionData else ""

    def stop(self):
        """安全停止弹幕线程 — 通过 asyncio.Event 通知协程优雅退出

        竞态修复：即使 stop() 早于 _connect() 创建 _stop_event，
        _stop_requested 标记也会被 _connect() 检查到并立即退出，
        避免线程永久阻塞在 await self._stop_event.wait()。
        """
        self._running = False
        self._stop_requested.set()
        if self._loop and self._loop.is_running() and self._stop_event is not None:
            self._loop.call_soon_threadsafe(self._stop_event.set)

    def run(self):
        if not self.roomID or self.roomID == "0":
            return

        self._running = True
        # 上一轮运行遗留的停止标记在此清除（stop→start 是合法的重启流程）；
        # 但 stop() 若发生在 run() 之前（从未运行过），标记必须保留给 _connect 消费
        if self._has_run:
            self._stop_requested.clear()
        self._has_run = True
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect())
        except Exception:
            logging.exception(f"弹幕线程 room={self.roomID} 异常退出")
        finally:
            try:
                if not self._loop.is_closed():
                    self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            except Exception:
                pass
            if not self._loop.is_closed():
                self._loop.close()
            self._loop = None
            self._running = False

    async def _connect(self):
        """建立弹幕 WebSocket 连接"""
        cookies = http.cookies.SimpleCookie()
        # 预设 buvid3，绕过 data.bilibili.com 403 风控
        cookies["buvid3"] = _generate_buvid3()
        cookies["buvid3"]["domain"] = "bilibili.com"
        if self.sessionData:
            cookies["SESSDATA"] = self.sessionData
            cookies["SESSDATA"]["domain"] = "bilibili.com"

        session = aiohttp.ClientSession()
        session.cookie_jar.update_cookies(cookies)

        try:
            room_id = int(self.roomID)
            client = blivedm.BLiveClient(room_id, session=session)
            client.set_handler(DanmakuHandler(self.message))
            # 线性退避重连策略，避免 32 个窗口同时重连造成风暴
            client.set_reconnect_policy(
                blivedm.utils.make_linear_retry_policy(start_interval=1.0, interval_step=2.0, max_interval=30.0)
            )
            client.start()
            logging.info(f"弹幕连接已启动 room={self.roomID}")
            try:
                self._stop_event = asyncio.Event()
                # 竞态修复：stop() 若在 _stop_event 创建前被调用（_stop_requested 已置位），
                # 立即置位 event，避免 await 永久阻塞导致 QThread 运行中被析构崩溃
                if self._stop_requested.is_set():
                    self._stop_requested.clear()
                    self._stop_event.set()
                await self._stop_event.wait()  # 阻塞直到 stop() 设置 event
            finally:
                await client.stop_and_close()
                logging.info(f"弹幕连接已关闭 room={self.roomID}")
        except Exception:
            logging.exception(f"弹幕连接 room={self.roomID} 失败")
        finally:
            await session.close()
