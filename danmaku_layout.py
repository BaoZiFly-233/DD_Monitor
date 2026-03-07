# -*- coding: utf-8 -*-
"""弹幕布局器。"""

from dataclasses import dataclass


@dataclass
class LayoutMetrics:
    font_size: int = 36
    lane_gap: int = 4
    display_ratio: float = 0.55
    top_padding: int = 4


@dataclass
class RollTrack:
    y: float
    width: float
    height: float
    speed: float
    start_time: float
    start_x: float
    duration: float

    def x_at(self, now):
        elapsed = max(0.0, now - self.start_time)
        return self.start_x - elapsed * self.speed

    def right_at(self, now):
        return self.x_at(now) + self.width

    def is_expired(self, now):
        return now >= self.start_time + self.duration or self.right_at(now) <= 0


@dataclass
class FixedTrack:
    y: float
    height: float
    start_time: float
    duration: float

    def is_expired(self, now):
        return now >= self.start_time + self.duration


@dataclass
class RollPlacement:
    y: float
    start_x: float
    speed: float
    duration: float


@dataclass
class FixedPlacement:
    x: float
    y: float
    duration: float


class RollLayout:
    """滚动弹幕布局。"""

    def __init__(self):
        self._width = 0
        self._height = 0
        self._metrics = LayoutMetrics()
        self._tracks = []
        self._dense_level = 0
        self._base_speed = 200.0
        self._speed_factor = 1.0

    def configure(self, width, height, font_size=None, display_ratio=None):
        self._width = max(0, int(width))
        self._height = max(0, int(height))
        if font_size is not None:
            self._metrics.font_size = max(20, int(font_size))
        if display_ratio is not None:
            self._metrics.display_ratio = min(max(float(display_ratio), 0.1), 1.0)
        self._metrics.top_padding = max(2, int(round(self._metrics.font_size * 0.08)))
        self._metrics.lane_gap = max(2, int(round(self._metrics.font_size * 0.08)))

    def reset(self):
        self._tracks.clear()

    def setDenseLevel(self, level):
        self._dense_level = max(0, min(int(level), 2))

    def setSpeedFactor(self, factor):
        self._speed_factor = min(max(float(factor), 0.5), 2.0)

    def allocate(self, now, width, height, duration):
        self.release_expired(now)
        start_x = float(self._width)
        width = float(max(1, int(width)))
        height = float(max(1, int(height)))
        if start_x <= 0 or self.usable_height <= 0:
            return None

        speed = self._resolve_speed(width)
        duration = (start_x + width) / speed
        candidate = RollTrack(
            y=0.0,
            width=width,
            height=height,
            speed=speed,
            start_time=now,
            start_x=start_x,
            duration=duration,
        )

        current_y = float(self._metrics.top_padding)
        current_gap_anchor = float(self._metrics.top_padding)
        bottom = float(self._metrics.top_padding + self.usable_height)
        max_chase_space = start_x / 2.0
        max_space = 0.0
        dense_y_by_chase = current_y
        dense_y_by_gap = current_y
        dense_replace_index = None
        dense_insert_index = len(self._tracks)

        for index, track in enumerate(self._tracks):
            gap_space = track.y - current_gap_anchor
            if gap_space > max_space:
                max_space = gap_space
                dense_y_by_gap = current_gap_anchor + gap_space / 2.0
                dense_insert_index = index

            if track.y - current_y - self._metrics.lane_gap >= height:
                candidate.y = current_y
                self._tracks.insert(index, candidate)
                return RollPlacement(y=candidate.y, start_x=start_x, speed=speed, duration=duration)

            if not self._is_collided(track, candidate, now):
                candidate.y = current_y
                self._tracks[index] = candidate
                return RollPlacement(y=candidate.y, start_x=start_x, speed=speed, duration=duration)

            chase_space = start_x - track.x_at(now) - track.width
            if chase_space > max_chase_space:
                max_chase_space = chase_space
                dense_replace_index = index
                dense_y_by_chase = current_y

            current_gap_anchor = track.y + self._metrics.lane_gap
            current_y = current_gap_anchor + track.height
            if current_y + height > bottom:
                break

        if current_y + height <= bottom:
            candidate.y = current_y
            self._tracks.append(candidate)
            return RollPlacement(y=candidate.y, start_x=start_x, speed=speed, duration=duration)

        if self._dense_level > 0:
            if dense_replace_index is not None:
                candidate.y = dense_y_by_chase
                self._tracks[dense_replace_index] = candidate
                return RollPlacement(y=candidate.y, start_x=start_x, speed=speed, duration=duration)
            if (self._dense_level == 1 and max_space >= height) or self._dense_level == 2:
                candidate.y = min(
                    max(float(self._metrics.top_padding), dense_y_by_gap),
                    max(float(self._metrics.top_padding), bottom - height),
                )
                self._tracks.insert(dense_insert_index, candidate)
                self._tracks.sort(key=lambda track: track.y)
                return RollPlacement(y=candidate.y, start_x=start_x, speed=speed, duration=duration)

        return None

    def release_expired(self, now):
        self._tracks = [track for track in self._tracks if not track.is_expired(now)]

    @property
    def usable_height(self):
        return max(0, int(self._height * self._metrics.display_ratio) - self._metrics.top_padding)

    def _resolve_speed(self, width):
        return (width / 5.0 + self._base_speed) * self._speed_factor

    @staticmethod
    def _is_collided(track, candidate, now):
        current_right = track.right_at(now)
        candidate_x = candidate.start_x
        if current_right > candidate_x:
            return True
        if candidate.speed <= track.speed:
            return False
        current_exit_time = current_right / track.speed
        chase_time = (candidate_x - current_right) / (candidate.speed - track.speed)
        return chase_time < current_exit_time


class _BaseFixedLayout:
    def __init__(self, anchor):
        self._anchor = anchor
        self._width = 0
        self._height = 0
        self._metrics = LayoutMetrics()
        self._tracks = []
        self._max_tracks = 20
        self._bottom_guard = 0

    def configure(self, width, height, font_size=None, display_ratio=None):
        self._width = max(0, int(width))
        self._height = max(0, int(height))
        if font_size is not None:
            self._metrics.font_size = max(20, int(font_size))
        if display_ratio is not None:
            self._metrics.display_ratio = min(max(float(display_ratio), 0.1), 1.0)
        self._metrics.top_padding = max(2, int(round(self._metrics.font_size * 0.08)))
        self._metrics.lane_gap = max(2, int(round(self._metrics.font_size * 0.08)))
        # 底部固定弹幕向上抬升，贴近原生客户端的底边留白。
        guard_by_font = int(round(self._metrics.font_size * 1.35))
        guard_by_viewport = int(round(self._height * 0.09))
        self._bottom_guard = min(
            max(22, guard_by_font, guard_by_viewport),
            max(22, self._height // 3),
        )

    def setMaxTracks(self, value):
        self._max_tracks = max(1, int(value))

    def reset(self):
        self._tracks.clear()

    def release_expired(self, now):
        self._tracks = [track for track in self._tracks if not track.is_expired(now)]

    @property
    def usable_height(self):
        return max(0, int(self._height * self._metrics.display_ratio) - self._metrics.top_padding)

    def allocate(self, now, width, height, duration):
        self.release_expired(now)
        width = float(max(1, int(width)))
        height = float(max(1, int(height)))
        if self._width <= 0 or self.usable_height <= 0:
            return None

        for y in self._candidate_positions(height):
            if self._can_place(y, height):
                self._tracks.append(FixedTrack(
                    y=float(y),
                    height=height,
                    start_time=now,
                    duration=float(duration),
                ))
                x = max(0.0, (self._width - width) / 2.0)
                return FixedPlacement(x=x, y=float(y), duration=float(duration))
        return None

    def _candidate_positions(self, height):
        top = float(self._metrics.top_padding)
        bottom = float(self._metrics.top_padding + self.usable_height)
        if self._anchor == 'bottom':
            bottom = max(top, bottom - float(self._bottom_guard))
        if bottom - top < height:
            return []

        step = max(1.0, height + self._metrics.lane_gap)
        positions = []
        if self._anchor == 'top':
            current = top
            while current + height <= bottom:
                positions.append(current)
                current += step
        else:
            current = bottom - height
            while current >= top:
                positions.append(current)
                current -= step
        return positions

    def _can_place(self, y, height):
        if len(self._tracks) >= self._max_tracks:
            return False

        gap = float(max(1, self._metrics.lane_gap))
        new_top = y - gap / 2.0
        new_bottom = y + height + gap / 2.0
        for track in self._tracks:
            track_top = track.y - gap / 2.0
            track_bottom = track.y + track.height + gap / 2.0
            if not (new_bottom <= track_top or new_top >= track_bottom):
                return False
        return True


class TopLayout(_BaseFixedLayout):
    def __init__(self):
        super().__init__('top')


class BottomLayout(_BaseFixedLayout):
    def __init__(self):
        super().__init__('bottom')
