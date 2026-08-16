# -*- coding: utf-8 -*-
"""Tests for typed live events and receiver lifecycle."""

import re
from dataclasses import FrozenInstanceError

import pytest

from app.media.remote import DanmakuEvent, _generate_buvid3


class TestGenerateBuvid3:
    def test_format(self):
        buvid = _generate_buvid3()
        assert re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}infoc",
            buvid,
        )

    def test_unique(self):
        assert _generate_buvid3() != _generate_buvid3()


class TestDanmakuEvent:
    def test_defaults(self):
        event = DanmakuEvent()
        assert event.kind == "danmaku"
        assert event.text == ""
        assert event.uname == ""
        assert event.color == "#FFFFFF"
        assert event.position == "scroll"

    def test_custom(self):
        event = DanmakuEvent(
            kind="gift",
            text="赠送 辣条 × 10",
            uname="用户A",
            price=10.0,
            position="top",
        )
        assert event.price == 10.0
        assert event.position == "top"
        assert event.category == "interaction"

    def test_is_immutable(self):
        event = DanmakuEvent()
        with pytest.raises(FrozenInstanceError):
            event.text = "新弹幕"


class TestRemoteThreadStopRace:
    def test_stop_before_start(self):
        from app.media.remote import remoteThread

        thread = remoteThread("1", "")
        thread.stop()
        thread.run()
        assert thread._stop_requested.is_set()
        assert not thread.isRunning()

    def test_configure_clears_old_stop_request(self):
        from app.media.remote import remoteThread

        thread = remoteThread("1", "")
        thread.stop()
        thread.configure("2", "session", connection_id=7)
        assert thread.roomID == "2"
        assert thread.connectionID == 7
        assert not thread._stop_requested.is_set()


class TestDanmakuHandlerSignals:
    @staticmethod
    def _receiver():
        from PySide6.QtCore import QObject, Signal

        class Receiver(QObject):
            received = Signal(object)

        receiver = Receiver()
        received = []
        receiver.received.connect(received.append)
        return receiver, received

    def test_handler_emits_typed_danmaku(self, qapp):
        from app.media.remote import DanmakuHandler

        receiver, got = self._receiver()

        class FakeMessage:
            msg = "测试弹幕"
            uname = "测试用户"
            uid = 42
            color = 0x12ABEF
            mode = 5
            dm_type = 1
            timestamp = 1_700_000_000
            rnd = 99
            face = "https://example.com/avatar.jpg"
            medal_name = "测试牌"
            medal_level = 12
            is_mirror = False

        handler = DanmakuHandler(receiver.received, room_id="100", connection_id=8)
        handler._on_danmaku(None, FakeMessage())

        assert len(got) == 1
        event = got[0]
        assert isinstance(event, DanmakuEvent)
        assert event.room_id == "100"
        assert event.connection_id == 8
        assert event.text == "测试弹幕"
        assert event.uname == "测试用户"
        assert event.user_id == "42"
        assert event.color == "#12ABEF"
        assert event.position == "top"
        assert event.user_avatar == "https://example.com/avatar.jpg"
        assert event.medal_name == "测试牌"
        assert event.medal_level == 12

    def test_handler_skips_mirror(self, qapp):
        from app.media.remote import DanmakuHandler

        receiver, got = self._receiver()

        class FakeMessage:
            msg = "镜像弹幕"
            is_mirror = True

        DanmakuHandler(receiver.received)._on_danmaku(None, FakeMessage())
        assert got == []

    def test_handler_gift_gold_only(self, qapp):
        from app.media.remote import DanmakuHandler

        receiver, got = self._receiver()

        class GoldGift:
            coin_type = "gold"
            uname = "老板"
            uid = 7
            num = 5
            gift_name = "辣条"
            total_coin = 5000
            timestamp = 1_700_000_000
            rnd = "gift-1"

        class SilverGift:
            coin_type = "silver"
            uname = "路人"
            num = 1
            gift_name = "小心心"

        handler = DanmakuHandler(receiver.received, room_id="100", connection_id=3)
        handler._on_gift(None, GoldGift())
        handler._on_gift(None, SilverGift())

        assert len(got) == 1
        event = got[0]
        assert event.kind == "gift"
        assert event.uname == "老板"
        assert event.text == "赠送 辣条 × 5"
        assert event.price == 5.0
        assert event.quantity == 5
        assert event.gift_name == "辣条"
        assert event.connection_id == 3

    def test_handler_preserves_interaction_type_and_avatar(self, qapp):
        from app.media.remote import DanmakuHandler

        receiver, got = self._receiver()

        class LikeMessage:
            msg_type = 6
            timestamp = 1_700_000_000
            uid = 88
            username = "点赞用户"
            face = "https://example.com/like.jpg"

        DanmakuHandler(receiver.received, room_id="100", connection_id=4)._on_interact_word_v2(
            None, LikeMessage()
        )

        assert len(got) == 1
        assert got[0].kind == "like"
        assert got[0].text == "为主播点赞"
        assert got[0].user_avatar == "https://example.com/like.jpg"
