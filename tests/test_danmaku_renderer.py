# -*- coding: utf-8 -*-
"""DanmakuRenderer 测试 — 过滤链 / 精灵缓存 / 添加与生命周期（需要 Qt）。"""

import time

from danmaku_renderer import (
    DanmakuDataFilter,
    DanmakuFilterResult,
    DanmakuImageCache,
    DanmakuRenderer,
    EmptyTextFilter,
)


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
        renderer.setDataFilters([CountingFilter(), CountingFilter()])
        renderer.addDanmaku("x", kind="scroll")
        assert len(calls) == 1


class TestImageCache:
    def test_same_key_returns_same_sprite(self, qapp):
        from danmaku_renderer import DanmakuStyle

        cache = DanmakuImageCache(max_items=32)
        style = DanmakuStyle()
        s1 = cache.get_or_create("测试", "#FFFFFF", style)
        s2 = cache.get_or_create("测试", "#FFFFFF", style)
        assert s1 is s2  # 同一对象（缓存命中）

    def test_different_text_different_sprite(self, qapp):
        from danmaku_renderer import DanmakuStyle

        cache = DanmakuImageCache(max_items=32)
        style = DanmakuStyle()
        s1 = cache.get_or_create("甲", "#FFFFFF", style)
        s2 = cache.get_or_create("乙", "#FFFFFF", style)
        assert s1 is not s2

    def test_lru_eviction(self, qapp):
        from danmaku_renderer import DanmakuStyle

        cache = DanmakuImageCache(max_items=3)
        style = DanmakuStyle()
        a = cache.get_or_create("a", "#FFFFFF", style)
        b = cache.get_or_create("b", "#FFFFFF", style)
        c = cache.get_or_create("c", "#FFFFFF", style)
        # 访问 a 使其成为最近使用
        cache.get_or_create("a", "#FFFFFF", style)
        d = cache.get_or_create("d", "#FFFFFF", style)  # 淘汰最久未用的 b
        assert len(cache._cache) == 3
        assert cache.get_or_create("b", "#FFFFFF", style) is not b  # b 已被淘汰，重新创建


class TestRendererLifecycle:
    def test_add_scroll_danmaku(self, qapp):
        renderer = DanmakuRenderer()
        renderer.setViewportSize(800, 600)
        renderer.addDanmaku("滚动弹幕", color="#FF0000", kind="scroll")
        assert renderer.activeCount() == 1
        assert renderer.hasActiveDanmaku()

    def test_add_top_danmaku(self, qapp):
        renderer = DanmakuRenderer()
        renderer.setViewportSize(800, 600)
        renderer.addDanmaku("顶部", kind="top")
        assert renderer.activeCount() == 1

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

    def test_stop_clears(self, qapp):
        renderer = DanmakuRenderer()
        renderer.setViewportSize(800, 600)
        for i in range(5):
            renderer.addDanmaku(f"弹幕{i}", kind="scroll")
        assert renderer.activeCount() == 5
        renderer.stop()
        assert renderer.activeCount() == 0

    def test_fixed_kind_limit(self, qapp):
        """顶部弹幕每类最多 _MAX_FIXED_PER_KIND 条"""
        renderer = DanmakuRenderer()
        renderer.setViewportSize(800, 600)
        limit = renderer._MAX_FIXED_PER_KIND
        for i in range(limit + 10):
            renderer.addDanmaku(f"t{i}", kind="top")
        assert renderer.activeCount() == limit

    def test_purge_expired(self, qapp):
        renderer = DanmakuRenderer()
        renderer.setViewportSize(800, 600)
        renderer.addDanmaku("临时", kind="scroll")
        assert renderer.activeCount() == 1
        # 模拟时间流逝：手动把弹幕的 expire_time 改为过去
        now = time.monotonic()
        for bullet in renderer._active:
            bullet.expire_time = now - 1.0
            bullet.start_time = now - 100.0  # 滚动弹幕早已滚出屏幕
        renderer._purge(now)
        assert renderer.activeCount() == 0
