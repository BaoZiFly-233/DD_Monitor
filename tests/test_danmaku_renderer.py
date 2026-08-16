# -*- coding: utf-8 -*-
"""DanmakuRenderer 测试 — 过滤链 / 精灵缓存 / 添加与生命周期（需要 Qt）。"""

import time

from app.danmaku.events import DanmakuEvent
from app.danmaku.renderer import (
    DanmakuDataFilter,
    DanmakuFilterResult,
    DanmakuImageCache,
    DanmakuRenderer,
    EmptyTextFilter,
)


def _wait_until(qapp, predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    qapp.processEvents()
    assert predicate()


class TestFilters:
    def test_empty_text_filter(self):
        f = EmptyTextFilter()
        result = f.filter(type("I", (), {"text": "   "})(), None)
        assert result.filtered is True
        assert result.reason == "empty_text"

    def test_non_empty_text_passes(self):
        f = EmptyTextFilter()
        result = f.filter(type("I", (), {"text": "hello"})(), None)
        assert result.filtered is False

    def test_custom_filter_chain(self, qapp):
        class BlockAll(DanmakuDataFilter):
            def filter(self, item, renderer):
                return DanmakuFilterResult(True, "block_all")

        renderer = DanmakuRenderer()
        renderer.setViewportSize(800, 600)
        renderer.setDataFilters([EmptyTextFilter(), BlockAll()])
        renderer.addDanmaku("visible", kind="scroll")
        assert renderer.activeCount() == 0

    def test_filter_chain_stops_at_first_block(self, qapp):
        """第一个拒绝的过滤器短路，后续不执行"""
        calls = []

        class CountingFilter(DanmakuDataFilter):
            def filter(self, item, renderer):
                calls.append(1)
                return DanmakuFilterResult(True, "stop")

        renderer = DanmakuRenderer()
        renderer.setViewportSize(800, 600)
        renderer.setDataFilters([CountingFilter(), CountingFilter()])
        renderer.addDanmaku("x", kind="scroll")
        assert len(calls) == 1


class TestImageCache:
    def test_same_key_returns_same_sprite(self, qapp):
        from app.danmaku.renderer import DanmakuStyle

        cache = DanmakuImageCache(max_items=32)
        style = DanmakuStyle()
        s1 = cache.get_or_create("测试", "#FFFFFF", style)
        s2 = cache.get_or_create("测试", "#FFFFFF", style)
        assert s1 is s2  # 同一对象（缓存命中）

    def test_different_text_different_sprite(self, qapp):
        from app.danmaku.renderer import DanmakuStyle

        cache = DanmakuImageCache(max_items=32)
        style = DanmakuStyle()
        s1 = cache.get_or_create("甲", "#FFFFFF", style)
        s2 = cache.get_or_create("乙", "#FFFFFF", style)
        assert s1 is not s2

    def test_async_miss_queue_is_bounded(self, qapp):
        from app.danmaku.renderer import DanmakuStyle

        cache = DanmakuImageCache(max_items=32, max_pending=4)
        style = DanmakuStyle()
        for index in range(10):
            cache.get_or_request(f"pending-{index}", "#FFFFFF", style, lambda sprite: None)

        assert cache.pending_count == 4
        cache.cancel_pending()
        assert cache.pending_count == 0

    def test_lru_eviction(self, qapp):
        from app.danmaku.renderer import DanmakuStyle

        # 构造器有最小容量钳制（max(32, max_items)），用 32 触发淘汰
        cache = DanmakuImageCache(max_items=32)
        style = DanmakuStyle()
        for i in range(32):
            cache.get_or_create(f"s{i}", "#FFFFFF", style)
        oldest = cache.get_or_create("s0", "#FFFFFF", style)
        # 再访问 s0 使其成为最近使用，然后插入新条目
        cache.get_or_create("s0", "#FFFFFF", style)
        new_sprite = cache.get_or_create("new", "#FFFFFF", style)
        assert len(cache._cache) == 32
        # 最久未使用的 s1 已被淘汰，重新创建后不是旧对象
        assert cache.get_or_create("s1", "#FFFFFF", style) is not oldest
        # 被访问过的 s0 保留（仍是缓存中的同一对象）
        assert cache.get_or_create("s0", "#FFFFFF", style) is oldest
        assert new_sprite is cache.get_or_create("new", "#FFFFFF", style)


class TestRendererLifecycle:
    def test_add_structured_event(self, qapp):
        renderer = DanmakuRenderer()
        renderer.setViewportSize(800, 600)
        renderer.addEvent(
            DanmakuEvent(
                connection_id=1,
                room_id="100",
                kind="danmaku",
                text="结构化弹幕",
                position="top",
            )
        )
        _wait_until(qapp, lambda: renderer.activeCount() == 1)

    def test_non_overlay_event_is_ignored(self, qapp):
        renderer = DanmakuRenderer()
        renderer.setViewportSize(800, 600)
        renderer.addEvent(
            DanmakuEvent(
                connection_id=1,
                room_id="100",
                kind="gift",
                text="礼物",
            )
        )
        assert renderer.activeCount() == 0
        assert renderer._image_cache.pending_count == 0

    def test_add_scroll_danmaku(self, qapp):
        renderer = DanmakuRenderer()
        renderer.setViewportSize(800, 600)
        renderer.addDanmaku("滚动弹幕", color="#FF0000", kind="scroll")
        assert renderer.activeCount() == 0
        assert renderer._image_cache.pending_count == 1
        _wait_until(qapp, lambda: renderer.activeCount() == 1)
        assert renderer.hasActiveDanmaku()

    def test_overlay_text_is_trimmed_and_bounded(self, qapp):
        captured = []

        class CaptureCache:
            def get_or_request(self, text, color, style, callback):
                captured.append(text)
                return None

        renderer = DanmakuRenderer()
        renderer.setViewportSize(800, 600)
        renderer._image_cache = CaptureCache()
        renderer.addDanmaku("  " + "x" * 240 + "  ", kind="scroll")

        assert len(captured) == 1
        assert len(captured[0]) == 200
        assert captured[0].endswith("...")

    def test_add_top_danmaku(self, qapp):
        renderer = DanmakuRenderer()
        renderer.setViewportSize(800, 600)
        renderer.addDanmaku("顶部", kind="top")
        _wait_until(qapp, lambda: renderer.activeCount() == 1)

    def test_top_disabled_rejects(self, qapp):
        renderer = DanmakuRenderer()
        renderer.setViewportSize(800, 600)
        renderer.setTopEnabled(False)
        renderer.addDanmaku("顶部", kind="top")
        assert renderer.activeCount() == 0

    def test_disabled_rejects_all(self, qapp):
        renderer = DanmakuRenderer()
        renderer.setViewportSize(800, 600)
        renderer.setEnabled(False)
        renderer.addDanmaku("任何", kind="scroll")
        assert renderer.activeCount() == 0

    def test_no_viewport_rejects(self, qapp):
        renderer = DanmakuRenderer()
        renderer.addDanmaku("无视口", kind="scroll")
        assert renderer.activeCount() == 0

    def test_stop_clears_and_invalidates_pending_renders(self, qapp):
        renderer = DanmakuRenderer()
        renderer.setViewportSize(800, 600)
        for i in range(5):
            renderer.addDanmaku(f"弹幕{i}", kind="scroll")
        renderer.stop()
        assert renderer.activeCount() == 0
        assert renderer._image_cache.pending_count == 0
        for _ in range(20):
            qapp.processEvents()
            time.sleep(0.005)
        assert renderer.activeCount() == 0

    def test_fixed_kind_limit(self, qapp):
        """顶部弹幕每类最多 _MAX_FIXED_PER_KIND 条"""
        renderer = DanmakuRenderer()
        # 高视口保证轨道数 >= 上限，让布局先于数量限制被触发
        renderer.setViewportSize(800, 4000)
        limit = renderer._MAX_FIXED_PER_KIND
        for i in range(limit + 10):
            renderer.addDanmaku(f"t{i}", kind="top")
        _wait_until(qapp, lambda: renderer._image_cache.pending_count == 0)
        assert renderer.activeCount() == limit

    def test_purge_expired(self, qapp):
        renderer = DanmakuRenderer()
        renderer.setViewportSize(800, 600)
        renderer.addDanmaku("临时", kind="scroll")
        _wait_until(qapp, lambda: renderer.activeCount() == 1)
        # 模拟时间流逝：手动把弹幕的 expire_time 改为过去
        now = time.monotonic()
        for bullet in renderer._active:
            bullet.expire_time = now - 1.0
            bullet.start_time = now - 100.0  # 滚动弹幕早已滚出屏幕
        renderer._purge(now)
        assert renderer.activeCount() == 0
