# -*- coding: utf-8 -*-
"""弹幕布局器测试 — 轨道分配 / 碰撞检测 / 过期清理 / 密集模式（纯逻辑，无 Qt）。"""

import time

from app.danmaku.layout import BottomLayout, RollLayout, TopLayout


class TestRollLayout:
    def _layout(self, width=800, height=600, font_size=36):
        layout = RollLayout()
        layout.configure(width, height, font_size=font_size)
        return layout

    def test_first_allocation_at_top(self):
        layout = self._layout()
        now = time.monotonic()
        placement = layout.allocate(now, 200, 40, 10.0)
        assert placement is not None
        assert placement.start_x == 800.0
        assert placement.duration > 0
        assert len(layout._tracks) == 1

    def test_second_allocation_new_track(self):
        """第二条弹幕应分配不同轨道（y 递增），不重叠"""
        layout = self._layout()
        now = time.monotonic()
        p1 = layout.allocate(now, 200, 40, 10.0)
        p2 = layout.allocate(now, 200, 40, 10.0)
        assert p1.y != p2.y
        assert p2.y > p1.y

    def test_lane_gap_respected(self):
        layout = self._layout()
        now = time.monotonic()
        p1 = layout.allocate(now, 200, 40, 10.0)
        p2 = layout.allocate(now, 200, 40, 10.0)
        assert p2.y - p1.y >= 40  # 高度 + lane_gap

    def test_track_full_returns_none(self):
        """轨道占满后无法再分配（无密集模式时返回 None）"""
        layout = self._layout(height=200, font_size=36)
        now = time.monotonic()
        allocated = 0
        while layout.allocate(now, 200, 40, 10.0) is not None:
            allocated += 1
            assert allocated < 50  # 防死循环
        assert allocated >= 1  # 至少能分配一些
        # 轨道满后应为 None

    def test_release_expired(self):
        layout = self._layout()
        now = time.monotonic()
        layout.allocate(now, 200, 40, 5.0)
        assert len(layout._tracks) == 1
        layout.release_expired(now + 100.0)  # 远未来 → 全部过期
        assert len(layout._tracks) == 0

    def test_allocate_after_expire_reuses_track(self):
        """轨道过期释放后，新弹幕可重新使用"""
        layout = self._layout()
        now = time.monotonic()
        p1 = layout.allocate(now, 200, 40, 5.0)
        layout.release_expired(now + 100.0)
        p2 = layout.allocate(now + 100.0, 200, 40, 5.0)
        assert p2 is not None
        assert p2.y == p1.y  # 复用首个轨道

    def test_dense_level_reuses_track(self):
        """密集模式 2：轨道满时仍可分配（复用追赶空隙）"""
        layout = self._layout(height=120, font_size=36)
        layout.setDenseLevel(2)
        now = time.monotonic()
        allocated = 0
        for _ in range(30):
            if layout.allocate(now, 200, 40, 10.0) is not None:
                allocated += 1
        assert allocated >= 10  # 密集模式下显著提升吞吐

    def test_speed_factor(self):
        layout = self._layout()
        now = time.monotonic()
        layout.setSpeedFactor(1.5)
        fast = layout.allocate(now, 200, 40, 10.0)
        layout2 = self._layout()
        slow = layout2.allocate(now, 200, 40, 10.0)
        assert fast.speed > slow.speed

    def test_configure_reset(self):
        layout = self._layout()
        now = time.monotonic()
        layout.allocate(now, 200, 40, 10.0)
        layout.reset()
        assert len(layout._tracks) == 0


class TestFixedLayouts:
    def test_top_layout_allocates_top(self):
        layout = TopLayout()
        layout.configure(800, 600, font_size=36)
        now = time.monotonic()
        p = layout.allocate(now, 200, 40, 5.0)
        assert p is not None
        assert p.x == (800 - 200) / 2.0  # 水平居中
        assert p.y == 3  # top_padding = round(36*0.08) = 3

    def test_bottom_layout_allocates_bottom(self):
        layout = BottomLayout()
        layout.configure(800, 600, font_size=36)
        now = time.monotonic()
        p = layout.allocate(now, 200, 40, 5.0)
        assert p is not None
        # display_ratio 默认 0.55: usable=600*0.55-3=327, bottom_guard=54
        # 首条 y = 3 + 327 - 54 - 40 = 236（贴近可用区域底部）
        assert p.y == 236

    def test_fixed_tracks_do_not_overlap(self):
        layout = TopLayout()
        layout.configure(800, 600, font_size=36)
        now = time.monotonic()
        placements = []
        for _ in range(5):
            p = layout.allocate(now, 200, 40, 5.0)
            if p is None:
                break
            placements.append(p)
        # 轨道之间应有 lane_gap 间隔
        ys = sorted(p.y for p in placements)
        for a, b in zip(ys, ys[1:]):
            assert b - a >= 40

    def test_max_tracks_limit(self):
        layout = TopLayout()
        layout.configure(800, 600, font_size=36)
        layout.setMaxTracks(3)
        now = time.monotonic()
        allocated = 0
        for _ in range(10):
            if layout.allocate(now, 200, 40, 5.0) is not None:
                allocated += 1
        assert allocated <= 3

    def test_expired_track_reusable(self):
        layout = TopLayout()
        layout.configure(800, 600, font_size=36)
        now = time.monotonic()
        p1 = layout.allocate(now, 200, 40, 5.0)
        assert p1 is not None
        layout.release_expired(now + 100.0)
        p2 = layout.allocate(now + 100.0, 200, 40, 5.0)
        assert p2 is not None
