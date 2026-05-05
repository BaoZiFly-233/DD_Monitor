# -*- coding: utf-8 -*-
"""弹幕渲染器。"""

from collections import OrderedDict
from dataclasses import dataclass, field, replace
from hashlib import sha1
import time

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPainterPath, QPen

from danmaku_layout import BottomLayout, RollLayout, TopLayout


@dataclass(frozen=True)
class DanmakuStyle:
    font_family: str = 'Microsoft YaHei'
    font_size: int = 36
    bold: bool = True
    stroke_width: float = 3.0
    stroke_color: str = '#000000'
    opacity: float = 0.85
    display_ratio: float = 0.55
    shadow_enabled: bool = False
    shadow_strength: int = 35


@dataclass
class CachedSprite:
    key: str
    image: QImage
    width: int
    height: int
    layout_height: int


@dataclass
class ActiveDanmaku:
    sprite: CachedSprite
    kind: str
    y: float
    width: int
    height: int
    start_time: float
    start_x: float
    speed: float
    expire_time: float = 0.0


@dataclass(frozen=True)
class DanmakuItemData:
    text: str
    color: str = '#FFFFFF'
    kind: str = 'scroll'
    uname: str = ''
    created_at: float = field(default_factory=time.monotonic)


@dataclass(frozen=True)
class DanmakuFilterResult:
    filtered: bool = False
    reason: str = ''


class DanmakuDataFilter:
    def filter(self, item: DanmakuItemData, renderer):
        return DanmakuFilterResult()


class DanmakuLayoutFilter:
    def filter(self, item: DanmakuItemData, placement, renderer):
        return DanmakuFilterResult()


class EmptyTextFilter(DanmakuDataFilter):
    def filter(self, item: DanmakuItemData, renderer):
        if not item.text.strip():
            return DanmakuFilterResult(True, 'empty_text')
        return DanmakuFilterResult()


class DanmakuImageCache:
    """弹幕精灵缓存 — 每个 DanmakuRenderer 实例独立持有。

    相同文字+样式的弹幕只渲染一次，缓存 QImage 精灵。
    LRU 淘汰策略，超过上限时移除最久未使用的条目。
    """

    def __init__(self, max_items=128):
        self._cache = OrderedDict()
        self._max_items = max(32, int(max_items))
        self._cache = OrderedDict()

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_or_create(self, text, color, style: DanmakuStyle):
        key = self._build_key(text, color, style)
        sprite = self._cache.get(key)
        if sprite is not None:
            self._cache.move_to_end(key)
            return sprite

        sprite = self._render_sprite(key, text, color, style)
        self._cache[key] = sprite
        self._cache.move_to_end(key)
        while len(self._cache) > self._max_items:
            self._cache.popitem(last=False)
        return sprite

    def get_cached(self, key):
        sprite = self._cache.get(key)
        if sprite is not None:
            self._cache.move_to_end(key)
        return sprite

    @staticmethod
    def _build_key(text, color, style: DanmakuStyle):
        raw = '|'.join([
            text,
            color,
            style.font_family,
            str(style.font_size),
            str(style.bold),
            str(style.stroke_width),
            style.stroke_color,
            str(style.shadow_enabled),
            str(style.shadow_strength),
        ])
        return sha1(raw.encode('utf-8')).hexdigest()

    @staticmethod
    def _render_sprite(key, text, color, style: DanmakuStyle):
        font = QFont(style.font_family, style.font_size)
        font.setBold(style.bold)

        path = QPainterPath()
        path.addText(0, 0, font, text)
        bounds = path.boundingRect()
        metrics = QFontMetrics(font)
        shadow_offset = max(0.0, style.shadow_strength / 20.0) if style.shadow_enabled else 0.0
        padding = int(style.stroke_width * 4 + 8 + shadow_offset * 2)
        width = max(1, int(bounds.width()) + padding * 2)
        height = max(1, int(bounds.height()) + padding * 2 + shadow_offset)
        layout_height = min(
            height,
            max(
                metrics.height() + int(round(style.stroke_width * 2 + shadow_offset * 0.5)),
                int(round(style.font_size * 1.05)),
            ),
        )

        image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)

        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        painter.translate(padding - bounds.left(), padding - bounds.top())
        if style.shadow_enabled and style.shadow_strength > 0:
            shadow_alpha = min(180, 30 + int(style.shadow_strength * 1.2))
            shadow_color = QColor(0, 0, 0, shadow_alpha)
            painter.fillPath(path.translated(shadow_offset, shadow_offset), shadow_color)
        pen = QPen(QColor(style.stroke_color), style.stroke_width)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(path)
        painter.fillPath(path, QColor(color))
        painter.end()
        return CachedSprite(
            key=key,
            image=image,
            width=image.width(),
            height=image.height(),
            layout_height=layout_height,
        )


class DanmakuRenderer:
    ROLL_KIND = 'scroll'
    TOP_KIND = 'top'
    BOTTOM_KIND = 'bottom'
    _FIXED_DURATION = 5.0
    _MAX_FIXED_PER_KIND = 20

    def __init__(self):
        self._style = DanmakuStyle()
        self._roll_layout = RollLayout()
        self._top_layout = TopLayout()
        self._bottom_layout = BottomLayout()
        self._image_cache = DanmakuImageCache(max_items=128)
        self._active = []
        self._enabled = True
        self._roll_duration = 12.0
        self._viewport_width = 0
        self._viewport_height = 0
        self._update_callback = None
        self._data_filters = [EmptyTextFilter()]
        self._layout_filters = []
        self._top_enabled = True
        self._bottom_enabled = True

    def initialize_gl(self):
        return

    def cleanup_gl(self):
        return

    def cleanup_file(self):
        return

    def setUpdateCallback(self, callback):
        self._update_callback = callback

    def setDataFilters(self, filters):
        self._data_filters = list(filters or [EmptyTextFilter()])
        if not self._data_filters:
            self._data_filters = [EmptyTextFilter()]

    def setLayoutFilters(self, filters):
        self._layout_filters = list(filters or [])

    def _run_data_filters(self, item):
        for danmaku_filter in self._data_filters:
            result = danmaku_filter.filter(item, self)
            if result.filtered:
                return result
        return DanmakuFilterResult()

    def _run_layout_filters(self, item, placement):
        for danmaku_filter in self._layout_filters:
            result = danmaku_filter.filter(item, placement, self)
            if result.filtered:
                return result
        return DanmakuFilterResult()

    def hasActiveDanmaku(self):
        return bool(self._active)

    def _request_update(self):
        if self._update_callback is not None:
            self._update_callback()

    def _update_style(self, *, reset=False, request_update=True, **changes):
        next_style = replace(self._style, **changes)
        if next_style == self._style:
            return
        self._style = next_style
        if reset:
            self.reset()
            return
        if request_update:
            self._request_update()

    @staticmethod
    def _normalize_kind(kind):
        normalized = str(kind or DanmakuRenderer.ROLL_KIND).strip().lower()
        if normalized in {DanmakuRenderer.TOP_KIND, DanmakuRenderer.BOTTOM_KIND, DanmakuRenderer.ROLL_KIND}:
            return normalized
        return DanmakuRenderer.ROLL_KIND

    def setEnabled(self, enabled):
        self._enabled = bool(enabled)
        if not self._enabled:
            self.reset()
        else:
            self._request_update()

    def setFontFamily(self, family):
        family = str(family).strip() or self._style.font_family
        self._update_style(font_family=family, reset=True)

    def setFontSize(self, size):
        size = max(20, int(size))
        if size == self._style.font_size:
            return
        self._update_style(font_size=size, reset=True, request_update=False)
        self._configure_layouts()

    def setDuration(self, seconds):
        self._roll_duration = max(5.0, min(float(seconds), 20.0))

    def setOpacity(self, value):
        if value > 1.0:
            value = value / 100.0
        value = min(max(float(value), 0.07), 1.0)
        self._update_style(opacity=value)

    def setDisplayArea(self, ratio):
        ratio = min(max(float(ratio), 0.1), 1.0)
        self._update_style(display_ratio=ratio, request_update=False)
        self._configure_layouts()
        self._request_update()

    def setStrokeWidth(self, width):
        width = min(max(float(width), 0.0), 8.0)
        self._update_style(stroke_width=width, reset=True)

    def setShadowEnabled(self, enabled):
        self._update_style(shadow_enabled=bool(enabled), reset=True)

    def setShadowStrength(self, strength):
        strength = max(0, min(int(strength), 100))
        self._update_style(shadow_strength=strength, reset=True)

    def setSpeedFactor(self, factor):
        self._roll_layout.setSpeedFactor(factor)

    def setDenseLevel(self, level):
        self._roll_layout.setDenseLevel(level)
        self.reset()

    def setTopEnabled(self, enabled):
        self._top_enabled = bool(enabled)
        if not self._top_enabled:
            self._active = [item for item in self._active if item.kind != self.TOP_KIND]
            self._top_layout.reset()
            self._request_update()

    def setBottomEnabled(self, enabled):
        self._bottom_enabled = bool(enabled)
        if not self._bottom_enabled:
            self._active = [item for item in self._active if item.kind != self.BOTTOM_KIND]
            self._bottom_layout.reset()
            self._request_update()

    def setViewportSize(self, width, height):
        next_width = max(0, int(width))
        next_height = max(0, int(height))
        if next_width == self._viewport_width and next_height == self._viewport_height:
            return
        self._viewport_width = next_width
        self._viewport_height = next_height
        self._configure_layouts()
        self._request_update()

    def _configure_layouts(self):
        self._roll_layout.configure(
            self._viewport_width,
            self._viewport_height,
            font_size=self._style.font_size,
            display_ratio=self._style.display_ratio,
        )
        self._top_layout.configure(
            self._viewport_width,
            self._viewport_height,
            font_size=self._style.font_size,
            display_ratio=1.0,
        )
        self._bottom_layout.configure(
            self._viewport_width,
            self._viewport_height,
            font_size=self._style.font_size,
            display_ratio=1.0,
        )

    def _active_count_by_kind(self, kind):
        return sum(1 for bullet in self._active if bullet.kind == kind)

    def addDanmaku(self, text, color='#FFFFFF', kind='scroll', uname=''):
        if not self._enabled or self._viewport_width <= 0 or self._viewport_height <= 0:
            return

        normalized_kind = self._normalize_kind(kind)
        if normalized_kind == self.TOP_KIND and not self._top_enabled:
            return
        if normalized_kind == self.BOTTOM_KIND and not self._bottom_enabled:
            return
        if normalized_kind in {self.TOP_KIND, self.BOTTOM_KIND} and self._active_count_by_kind(normalized_kind) >= self._MAX_FIXED_PER_KIND:
            return

        item = DanmakuItemData(text=str(text), color=str(color), kind=normalized_kind, uname=str(uname))
        if self._run_data_filters(item).filtered:
            return

        sprite = self._image_cache.get_or_create(item.text, item.color, self._style)
        if normalized_kind == self.ROLL_KIND:
            placement = self._roll_layout.allocate(item.created_at, sprite.width, sprite.layout_height, self._roll_duration)
            if placement is None:
                return
            expire_time = item.created_at + float(placement.duration)
            start_x = float(placement.start_x)
            speed = float(placement.speed)
            y = float(placement.y)
        else:
            layout = self._top_layout if normalized_kind == self.TOP_KIND else self._bottom_layout
            placement = layout.allocate(item.created_at, sprite.width, sprite.layout_height, self._FIXED_DURATION)
            if placement is None:
                return
            expire_time = item.created_at + float(placement.duration)
            start_x = float(placement.x)
            speed = 0.0
            y = float(placement.y)

        if self._run_layout_filters(item, placement).filtered:
            return

        self._active.append(ActiveDanmaku(
            sprite=sprite,
            kind=normalized_kind,
            y=y,
            width=sprite.width,
            height=sprite.layout_height,
            start_time=item.created_at,
            start_x=start_x,
            speed=speed,
            expire_time=expire_time,
        ))
        self._request_update()

    def stop(self):
        self._active.clear()
        self._roll_layout.reset()
        self._top_layout.reset()
        self._bottom_layout.reset()
        self._request_update()

    def reset(self):
        self.stop()

    def _purge(self, now):
        self._roll_layout.release_expired(now)
        self._top_layout.release_expired(now)
        self._bottom_layout.release_expired(now)
        kept = []
        for bullet in self._active:
            if bullet.kind == self.ROLL_KIND:
                if self._x_for(bullet, now) + bullet.width > 0:
                    kept.append(bullet)
            elif now < bullet.expire_time:
                kept.append(bullet)
        self._active = kept

    def _x_for(self, bullet: ActiveDanmaku, now):
        if bullet.kind != self.ROLL_KIND:
            return bullet.start_x
        elapsed = max(0.0, now - bullet.start_time)
        return bullet.start_x - elapsed * bullet.speed

    def paint(self, painter, logical_width, logical_height):
        if not self._enabled:
            return
        self.setViewportSize(logical_width, logical_height)
        if not self._active or self._viewport_width <= 0 or self._viewport_height <= 0:
            return

        now = time.monotonic()
        self._purge(now)
        if not self._active:
            return

        painter.save()
        try:
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            painter.setOpacity(self._style.opacity)
            for bullet in self._active:
                sprite = bullet.sprite
                x = self._x_for(bullet, now)
                if x >= logical_width or x + sprite.width <= 0:
                    continue
                if bullet.y >= logical_height or bullet.y + sprite.height <= 0:
                    continue
                painter.drawImage(QRectF(x, bullet.y, sprite.width, sprite.height), sprite.image)
        finally:
            painter.restore()
