# -*- coding: utf-8 -*-
"""
弹幕接收线程 - 基于 blivedm 库的 WebSocket 连接
使用 Qt Signal 推送替代轮询，显著降低 CPU 开销
"""
import asyncio
import http.cookies
import logging
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
    kind: str = 'danmaku'
    text: str = ''
    uname: str = ''
    color: str = '#FFFFFF'
    price: float = 0.0
    position: str = 'scroll'


def _generate_buvid3() -> str:
    """生成 buvid3 cookie 值，绕过 B 站 data.bilibili.com 403 风控"""
    return str(uuid.uuid4()) + 'infoc'


class DanmakuHandler(blivedm.BaseHandler):
    """弹幕事件处理器 - 通过 Qt Signal 直接推送消息到主线程"""

    def __init__(self, message_signal):
        super().__init__()
        self._signal = message_signal

    def _on_heartbeat(self, client: blivedm.BLiveClient, message: web_models.HeartbeatMessage):
        pass

    def _on_danmaku(self, client: blivedm.BLiveClient, message: web_models.DanmakuMessage):
        # 跳过镜像弹幕（DANMU_MSG_MIRROR），避免同一条弹幕出现两次
        if getattr(message, 'is_mirror', False):
            return
        self._signal.emit(message.msg)

    def _on_gift(self, client: blivedm.BLiveClient, message: web_models.GiftMessage):
        if message.coin_type == 'gold':
            self._signal.emit(
                f"** {message.uname} 赠送了 {message.num} 个 {message.gift_name}"
            )

    def _on_buy_guard(self, client: blivedm.BLiveClient, message: web_models.GuardBuyMessage):
        self._signal.emit(
            f"** {message.username} 购买了 {message.gift_name}"
        )

    def _on_super_chat(self, client: blivedm.BLiveClient, message: web_models.SuperChatMessage):
        self._signal.emit(
            f"【SC(￥{message.price}) {message.uname}: {message.message}】"
        )


class remoteThread(QThread):
    """弹幕接收线程

    在独立线程中运行 asyncio 事件循环，通过 blivedm WebSocket 接收弹幕，
    使用 Qt Signal 推送消息到主线程，消除原有 20ms QTimer 轮询。
    """
    message = Signal(str)

    def __init__(self, roomID, sessionData=''):
        super(remoteThread, self).__init__()
        self.roomID = str(roomID)
        self.sessionData = sessionData if sessionData else ''
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event: Optional[asyncio.Event] = None

    def setRoomID(self, roomID):
        self.roomID = str(roomID)

    def setSessionData(self, sessionData):
        self.sessionData = sessionData if sessionData else ''

    def stop(self):
        """安全停止弹幕线程 — 通过 asyncio.Event 通知协程优雅退出"""
        self._running = False
        if self._loop and self._loop.is_running() and self._stop_event is not None:
            self._loop.call_soon_threadsafe(self._stop_event.set)

    def run(self):
        if not self.roomID or self.roomID == '0':
            return

        self._running = True
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect())
        except RuntimeError:
            logging.exception(f'弹幕线程 room={self.roomID} 异常退出')
        except Exception:
            logging.exception(f'弹幕线程 room={self.roomID} 异常退出')
        finally:
            try:
                if not self._loop.is_closed():
                    self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            except Exception:
                pass
            if not self._loop.is_closed():
                self._loop.close()
            self._loop = None

    async def _connect(self):
        """建立弹幕 WebSocket 连接"""
        cookies = http.cookies.SimpleCookie()
        # 预设 buvid3，绕过 data.bilibili.com 403 风控
        cookies['buvid3'] = _generate_buvid3()
        cookies['buvid3']['domain'] = 'bilibili.com'
        if self.sessionData:
            cookies['SESSDATA'] = self.sessionData
            cookies['SESSDATA']['domain'] = 'bilibili.com'

        session = aiohttp.ClientSession()
        session.cookie_jar.update_cookies(cookies)

        try:
            room_id = int(self.roomID)
            client = blivedm.BLiveClient(room_id, session=session)
            client.set_handler(DanmakuHandler(self.message))
            # 线性退避重连策略，避免 32 个窗口同时重连造成风暴
            client.set_reconnect_policy(
                blivedm.utils.make_linear_retry_policy(
                    start_interval=1.0, interval_step=2.0, max_interval=30.0
                )
            )
            client.start()
            logging.info(f'弹幕连接已启动 room={self.roomID}')
            try:
                self._stop_event = asyncio.Event()
                await self._stop_event.wait()  # 阻塞直到 stop() 设置 event
            finally:
                await client.stop_and_close()
                logging.info(f'弹幕连接已关闭 room={self.roomID}')
        except Exception:
            logging.exception(f'弹幕连接 room={self.roomID} 失败')
        finally:
            await session.close()
