# -*- coding: utf-8 -*-
"""remote.py 测试 — buvid3 生成 / 事件数据类 / 线程停止竞态。"""

import re

from app.media.remote import DanmakuEvent, _generate_buvid3


class TestGenerateBuvid3:
    def test_format(self):
        buvid = _generate_buvid3()
        # buvid3 格式: uuid4（36字符带连字符） + "infoc"
        assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}infoc", buvid)

    def test_unique(self):
        assert _generate_buvid3() != _generate_buvid3()


class TestDanmakuEvent:
    def test_defaults(self):
        ev = DanmakuEvent()
        assert ev.kind == "danmaku"
        assert ev.text == ""
        assert ev.uname == ""
        assert ev.color == "#FFFFFF"
        assert ev.position == "scroll"

    def test_custom(self):
        ev = DanmakuEvent(kind="gift", text="10个辣条", uname="用户A", price=10.0, position="top")
        assert ev.price == 10.0
        assert ev.position == "top"

    def test_mutation(self):
        ev = DanmakuEvent()
        ev.text = "新弹幕"
        assert ev.text == "新弹幕"


class TestRemoteThreadStopRace:
    """stop() 早于线程 _stop_event 创建时的竞态——线程必须能感知停止请求并退出"""

    def test_stop_before_start(self):
        from app.media.remote import remoteThread

        thread = remoteThread("1", "")
        # 先 stop（模拟在 _stop_event 创建前停止）
        thread.stop()
        # run() 中 _connect() 会检查 _stop_requested 并立即退出
        thread.run()
        assert thread._running is False


class TestDanmakuHandlerSignals:
    def test_handler_emits_danmaku(self, qapp):
        """DanmakuHandler 收到弹幕消息后通过 Qt Signal 推送（消息以字符串形式）"""
        from PySide6.QtCore import QObject, Signal

        from app.media.remote import DanmakuHandler

        class Receiver(QObject):
            received = Signal(str)

        receiver = Receiver()
        got = []
        receiver.received.connect(got.append)

        class FakeMessage:
            msg = "测试弹幕"
            is_mirror = False

        handler = DanmakuHandler(receiver.received)
        handler._on_danmaku(None, FakeMessage())
        assert got == ["测试弹幕"]

    def test_handler_skips_mirror(self, qapp):
        from PySide6.QtCore import QObject, Signal

        from app.media.remote import DanmakuHandler

        class Receiver(QObject):
            received = Signal(str)

        receiver = Receiver()
        got = []
        receiver.received.connect(got.append)

        class FakeMessage:
            msg = "镜像弹幕"
            is_mirror = True

        handler = DanmakuHandler(receiver.received)
        handler._on_danmaku(None, FakeMessage())
        assert got == []

    def test_handler_gift_gold_only(self, qapp):
        from PySide6.QtCore import QObject, Signal

        from app.media.remote import DanmakuHandler

        class Receiver(QObject):
            received = Signal(str)

        receiver = Receiver()
        got = []
        receiver.received.connect(got.append)

        class GoldGift:
            coin_type = "gold"
            uname = "老板"
            num = 5
            gift_name = "辣条"

        class SilverGift:
            coin_type = "silver"
            uname = "路人"
            num = 1
            gift_name = "小心心"

        handler = DanmakuHandler(receiver.received)
        handler._on_gift(None, GoldGift())
        handler._on_gift(None, SilverGift())
        assert len(got) == 1
        assert "老板" in got[0]
