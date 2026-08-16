"""Typed, immutable events shared by danmaku producers and consumers."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, replace

DANMAKU_KINDS = frozenset(
    {
        "danmaku",
        "gift",
        "guard",
        "super_chat",
        "enter",
        "follow",
        "share",
        "like",
        "system",
    }
)
DANMAKU_POSITIONS = frozenset({"scroll", "top", "bottom"})
INTERACTION_KINDS = frozenset(
    {"gift", "guard", "super_chat", "enter", "follow", "share", "like", "system"}
)
OVERLAY_KINDS = frozenset({"danmaku", "super_chat"})


def _now_ms() -> int:
    return int(time.time() * 1000)


def normalize_timestamp_ms(value) -> int:
    """Normalize seconds or milliseconds to a positive millisecond timestamp."""
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return _now_ms()
    if timestamp <= 0:
        return _now_ms()
    if timestamp < 10_000_000_000:
        timestamp *= 1000
    return timestamp


def normalize_color(value) -> str:
    """Return a CSS-style ``#RRGGBB`` color, falling back to white."""
    if isinstance(value, int):
        return f"#{value & 0xFFFFFF:06X}"
    text = str(value or "").strip()
    if text.startswith("#"):
        text = text[1:]
    if len(text) == 3 and all(char in "0123456789abcdefABCDEF" for char in text):
        text = "".join(char * 2 for char in text)
    if len(text) == 6 and all(char in "0123456789abcdefABCDEF" for char in text):
        return f"#{text.upper()}"
    return "#FFFFFF"


def _nonnegative_float(value) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _nonnegative_int(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


@dataclass(frozen=True, slots=True)
class DanmakuEvent:
    """One immutable room event.

    ``connection_id`` identifies a concrete websocket generation.  It prevents
    an event from an old A -> B -> A connection from being accepted merely
    because the room id happens to match again.
    """

    event_id: str = ""
    connection_id: int = 0
    room_id: str = ""
    kind: str = "danmaku"
    text: str = ""
    uname: str = ""
    user_id: str = ""
    user_avatar: str = ""
    color: str = "#FFFFFF"
    position: str = "scroll"
    timestamp_ms: int = 0
    price: float = 0.0
    quantity: int = 0
    gift_name: str = ""
    medal_name: str = ""
    medal_level: int = 0
    guard_level: int = 0
    is_translation: bool = False

    def __post_init__(self):
        kind = str(self.kind or "danmaku").strip().lower()
        position = str(self.position or "scroll").strip().lower()
        timestamp_ms = normalize_timestamp_ms(self.timestamp_ms)
        text = str(self.text or "").strip()
        uname = str(self.uname or "").strip()
        room_id = str(self.room_id or "").strip()
        event_id = str(self.event_id or "").strip()

        if kind not in DANMAKU_KINDS:
            kind = "system"
        if position not in DANMAKU_POSITIONS:
            position = "scroll"
        if not event_id:
            raw = "\x1f".join(
                (
                    str(self.connection_id),
                    room_id,
                    kind,
                    str(timestamp_ms),
                    str(self.user_id or ""),
                    uname,
                    text,
                )
            ).encode("utf-8", "replace")
            event_id = hashlib.blake2s(raw, digest_size=12).hexdigest()

        object.__setattr__(self, "event_id", event_id)
        object.__setattr__(self, "connection_id", _nonnegative_int(self.connection_id))
        object.__setattr__(self, "room_id", room_id)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "uname", uname)
        object.__setattr__(self, "user_id", str(self.user_id or ""))
        object.__setattr__(self, "user_avatar", str(self.user_avatar or ""))
        object.__setattr__(self, "color", normalize_color(self.color))
        object.__setattr__(self, "position", position)
        object.__setattr__(self, "timestamp_ms", timestamp_ms)
        object.__setattr__(self, "price", _nonnegative_float(self.price))
        object.__setattr__(self, "quantity", _nonnegative_int(self.quantity))
        object.__setattr__(self, "gift_name", str(self.gift_name or "").strip())
        object.__setattr__(self, "medal_name", str(self.medal_name or ""))
        object.__setattr__(self, "medal_level", _nonnegative_int(self.medal_level))
        object.__setattr__(self, "guard_level", _nonnegative_int(self.guard_level))
        object.__setattr__(self, "is_translation", bool(self.is_translation))

    @property
    def category(self) -> str:
        if self.is_translation:
            return "translation"
        if self.kind in INTERACTION_KINDS:
            return "interaction"
        return "chat"

    @property
    def kind_label(self) -> str:
        return {
            "danmaku": "弹幕",
            "gift": "礼物",
            "guard": "上舰",
            "super_chat": "醒目留言",
            "enter": "进入",
            "follow": "关注",
            "share": "分享",
            "like": "点赞",
            "system": "系统",
        }[self.kind]

    @property
    def display_text(self) -> str:
        """Human-readable text for list and accessibility views."""
        return self.text or self.kind_label

    @property
    def time_label(self) -> str:
        return time.strftime("%H:%M:%S", time.localtime(self.timestamp_ms / 1000))

    @property
    def is_overlay(self) -> bool:
        return self.kind in OVERLAY_KINDS

    def mark_translation(self, value: bool = True) -> DanmakuEvent:
        if self.is_translation == bool(value):
            return self
        return replace(self, is_translation=bool(value))
