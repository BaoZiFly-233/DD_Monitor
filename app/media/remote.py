# -*- coding: utf-8 -*-
"""Bilibili live event receiver backed by blivedm."""

from __future__ import annotations

import asyncio
import hashlib
import http.cookies
import logging
import threading
import uuid
from typing import Optional

import aiohttp
from PySide6.QtCore import QThread, Signal

import blivedm
import blivedm.models.web as web_models
from app.danmaku.events import DanmakuEvent, normalize_timestamp_ms


class _BlivedmNoiseFilter(logging.Filter):
    """Suppress protocol churn that blivedm reports as large warning blobs."""

    def filter(self, record):
        msg = record.getMessage()
        return not ("unknown cmd" in msg or "is calling close()" in msg)


logging.getLogger("blivedm").addFilter(_BlivedmNoiseFilter())


def _generate_buvid3() -> str:
    return str(uuid.uuid4()) + "infoc"


def _event_id(prefix, *parts):
    payload = "\x1f".join(str(part or "") for part in parts).encode("utf-8", "replace")
    digest = hashlib.blake2s(payload, digest_size=12).hexdigest()
    return f"{prefix}:{digest}"


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return int(default)


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return float(default)


def _danmaku_position(mode):
    mode = _safe_int(mode, 1)
    if mode == 4:
        return "bottom"
    if mode == 5:
        return "top"
    return "scroll"


def _medal_fields(message):
    medal_name = str(getattr(message, "medal_name", "") or "")
    medal_level = _safe_int(getattr(message, "medal_level", 0))
    if medal_name or medal_level:
        return medal_name, medal_level

    extra = getattr(message, "extra", None)
    medal = extra.get("medal_info") if isinstance(extra, dict) else None
    if not isinstance(medal, dict):
        return "", 0
    return str(medal.get("medal_name") or ""), _safe_int(medal.get("medal_level"))


class DanmakuHandler(blivedm.BaseHandler):
    """Convert blivedm messages into immutable application events."""

    def __init__(self, message_signal, room_id="", connection_id=0):
        super().__init__()
        self._signal = message_signal
        self._room_id = str(room_id)
        self._connection_id = int(connection_id)

    def _emit(self, **values):
        values.setdefault("room_id", self._room_id)
        values.setdefault("connection_id", self._connection_id)
        self._signal.emit(DanmakuEvent(**values))

    def _on_heartbeat(self, client: blivedm.BLiveClient, message: web_models.HeartbeatMessage):
        pass

    def _on_danmaku(self, client: blivedm.BLiveClient, message: web_models.DanmakuMessage):
        if getattr(message, "is_mirror", False):
            return
        timestamp = normalize_timestamp_ms(getattr(message, "timestamp", 0))
        user_id = str(getattr(message, "uid", "") or "")
        medal_name, medal_level = _medal_fields(message)
        self._emit(
            event_id=_event_id(
                "dm",
                self._room_id,
                getattr(message, "rnd", ""),
                timestamp,
                user_id,
                message.msg,
            ),
            kind="danmaku",
            text=message.msg,
            uname=str(getattr(message, "uname", "") or ""),
            user_id=user_id,
            user_avatar=str(getattr(message, "face", "") or ""),
            color=getattr(message, "color", 0xFFFFFF),
            position=_danmaku_position(getattr(message, "mode", 1)),
            timestamp_ms=timestamp,
            medal_name=medal_name,
            medal_level=medal_level,
        )

    def _on_gift(self, client: blivedm.BLiveClient, message: web_models.GiftMessage):
        if message.coin_type != "gold":
            return
        timestamp = normalize_timestamp_ms(getattr(message, "timestamp", 0))
        total_coin = _safe_float(getattr(message, "total_coin", 0))
        self._emit(
            event_id=_event_id(
                "gift",
                self._room_id,
                getattr(message, "rnd", ""),
                getattr(message, "uid", ""),
                timestamp,
                message.gift_name,
            ),
            kind="gift",
            text=f"赠送 {message.gift_name} × {message.num}",
            uname=str(getattr(message, "uname", "") or ""),
            user_id=str(getattr(message, "uid", "") or ""),
            user_avatar=str(getattr(message, "face", "") or ""),
            timestamp_ms=timestamp,
            price=total_coin / 1000.0,
            quantity=message.num,
            gift_name=message.gift_name,
        )

    def _on_buy_guard(self, client: blivedm.BLiveClient, message: web_models.GuardBuyMessage):
        timestamp = normalize_timestamp_ms(getattr(message, "start_time", 0))
        self._emit(
            event_id=_event_id(
                "guard",
                self._room_id,
                getattr(message, "uid", ""),
                timestamp,
                message.gift_name,
            ),
            kind="guard",
            text=f"开通 {message.gift_name} × {message.num}",
            uname=message.username,
            user_id=str(getattr(message, "uid", "") or ""),
            timestamp_ms=timestamp,
            price=_safe_float(getattr(message, "price", 0)) / 1000.0,
            quantity=message.num,
            gift_name=message.gift_name,
            guard_level=_safe_int(getattr(message, "guard_level", 0)),
        )

    def _on_super_chat(self, client: blivedm.BLiveClient, message: web_models.SuperChatMessage):
        timestamp = normalize_timestamp_ms(getattr(message, "start_time", 0))
        self._emit(
            event_id=_event_id("sc", self._room_id, message.id, getattr(message, "uid", "")),
            kind="super_chat",
            text=message.message,
            uname=message.uname,
            user_id=str(getattr(message, "uid", "") or ""),
            user_avatar=str(getattr(message, "face", "") or ""),
            timestamp_ms=timestamp,
            price=_safe_float(message.price),
        )

    def _on_interact_word_v2(self, client: blivedm.BLiveClient, message: web_models.InteractWordV2Message):
        interaction = {
            1: ("enter", "进入直播间"),
            2: ("follow", "关注了直播间"),
            3: ("share", "分享了直播间"),
            4: ("follow", "特别关注了直播间"),
            5: ("follow", "与主播互粉"),
            6: ("like", "为主播点赞"),
        }.get(_safe_int(message.msg_type))
        if interaction is None:
            return
        kind, action = interaction
        timestamp = normalize_timestamp_ms(message.timestamp)
        self._emit(
            event_id=_event_id(kind, self._room_id, message.uid, timestamp, message.msg_type),
            kind=kind,
            text=action,
            uname=message.username,
            user_id=str(message.uid or ""),
            user_avatar=str(getattr(message, "face", "") or ""),
            timestamp_ms=timestamp,
        )


class remoteThread(QThread):
    """Receive one immutable room generation on an asyncio worker thread."""

    message = Signal(object)

    def __init__(self, roomID, sessionData=""):
        super().__init__()
        self.roomID = str(roomID)
        self.sessionData = sessionData if sessionData else ""
        self.connectionID = 0
        self._config_lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._stop_requested = threading.Event()

    def configure(self, room_id, session_data="", connection_id=0):
        if self.isRunning():
            raise RuntimeError("cannot reconfigure a running danmaku connection")
        with self._config_lock:
            self.roomID = str(room_id)
            self.sessionData = session_data if session_data else ""
            self.connectionID = int(connection_id)
        self._stop_requested.clear()

    def stop(self):
        self._stop_requested.set()
        if self._loop and self._loop.is_running() and self._stop_event is not None:
            try:
                self._loop.call_soon_threadsafe(self._stop_event.set)
            except RuntimeError:
                pass

    def run(self):
        with self._config_lock:
            room_id = self.roomID
            session_data = self.sessionData
            connection_id = self.connectionID
        if not room_id or room_id == "0" or self._stop_requested.is_set():
            return

        try:
            seed = int(hashlib.md5(room_id.encode()).hexdigest()[:8], 16)
            delay = 0.3 + (seed % 1500) / 1000.0
        except Exception:
            delay = 0.5
        if self._stop_requested.wait(delay):
            return

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect(room_id, session_data, connection_id))
        except Exception:
            logging.exception("弹幕线程 room=%s generation=%s 异常退出", room_id, connection_id)
        finally:
            try:
                if not self._loop.is_closed():
                    self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            except Exception:
                pass
            if not self._loop.is_closed():
                self._loop.close()
            self._loop = None
            self._stop_event = None

    async def _connect(self, room_id, session_data, connection_id):
        cookies = http.cookies.SimpleCookie()
        cookies["buvid3"] = _generate_buvid3()
        cookies["buvid3"]["domain"] = "bilibili.com"
        if session_data:
            cookies["SESSDATA"] = session_data
            cookies["SESSDATA"]["domain"] = "bilibili.com"

        session = aiohttp.ClientSession()
        session.cookie_jar.update_cookies(cookies)
        try:
            client = blivedm.BLiveClient(int(room_id), session=session)
            client.set_handler(DanmakuHandler(self.message, room_id, connection_id))
            client.set_reconnect_policy(
                blivedm.utils.make_linear_retry_policy(
                    start_interval=1.0,
                    interval_step=2.0,
                    max_interval=30.0,
                )
            )
            client.start()
            logging.info("弹幕连接已启动 room=%s generation=%s", room_id, connection_id)
            try:
                self._stop_event = asyncio.Event()
                if self._stop_requested.is_set():
                    self._stop_event.set()
                await self._stop_event.wait()
            finally:
                await client.stop_and_close()
                logging.info("弹幕连接已关闭 room=%s generation=%s", room_id, connection_id)
        except Exception:
            logging.exception("弹幕连接 room=%s generation=%s 失败", room_id, connection_id)
        finally:
            await session.close()
