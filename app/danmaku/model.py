"""Bounded Qt models for the live danmaku workbench."""

from __future__ import annotations

from collections import deque
from enum import IntEnum

from PySide6.QtCore import QAbstractListModel, QModelIndex, QSortFilterProxyModel, Qt, QTimer, Signal

from app.danmaku.events import DanmakuEvent


class DanmakuRole(IntEnum):
    EVENT = Qt.UserRole + 1
    KIND = Qt.UserRole + 2
    USER_NAME = Qt.UserRole + 3
    TIMESTAMP = Qt.UserRole + 4
    COLOR = Qt.UserRole + 5
    CATEGORY = Qt.UserRole + 6


class DanmakuEventModel(QAbstractListModel):
    """A batched, deduplicating and bounded event history."""

    countChanged = Signal(int)
    droppedChanged = Signal(int)

    def __init__(self, parent=None, max_events=1000, max_pending=512, flush_interval_ms=16):
        super().__init__(parent)
        self._events = []
        self._event_ids = set()
        self._pending = deque()
        self._pending_ids = set()
        self._max_events = max(1, int(max_events))
        self._max_pending = max(1, int(max_pending))
        self._dropped_count = 0
        self._reported_dropped_count = 0

        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(max(0, int(flush_interval_ms)))
        self._flush_timer.timeout.connect(self.flush_pending)

    def roleNames(self):
        roles = super().roleNames()
        roles.update(
            {
                int(DanmakuRole.EVENT): b"event",
                int(DanmakuRole.KIND): b"kind",
                int(DanmakuRole.USER_NAME): b"userName",
                int(DanmakuRole.TIMESTAMP): b"timestamp",
                int(DanmakuRole.COLOR): b"color",
                int(DanmakuRole.CATEGORY): b"category",
            }
        )
        return roles

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._events)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._events):
            return None
        event = self._events[index.row()]
        if role == Qt.DisplayRole:
            return event.text
        if role == Qt.ToolTipRole:
            user = event.uname or "系统"
            return f"{user}\n{event.text}"
        if role == Qt.AccessibleTextRole:
            user = f"{event.uname}: " if event.uname else ""
            return f"{event.kind_label} {user}{event.text}"
        if role == DanmakuRole.EVENT:
            return event
        if role == DanmakuRole.KIND:
            return event.kind
        if role == DanmakuRole.USER_NAME:
            return event.uname
        if role == DanmakuRole.TIMESTAMP:
            return event.timestamp_ms
        if role == DanmakuRole.COLOR:
            return event.color
        if role == DanmakuRole.CATEGORY:
            return event.category
        return None

    @property
    def dropped_count(self):
        return self._dropped_count

    @property
    def max_events(self):
        return self._max_events

    def event_at(self, row):
        if 0 <= int(row) < len(self._events):
            return self._events[int(row)]
        return None

    def append_event(self, event):
        if not isinstance(event, DanmakuEvent):
            raise TypeError("DanmakuEventModel only accepts DanmakuEvent")
        if event.event_id in self._event_ids or event.event_id in self._pending_ids:
            return False

        if len(self._pending) >= self._max_pending:
            discarded = self._pending.popleft()
            self._pending_ids.discard(discarded.event_id)
            self._increase_dropped(1)

        self._pending.append(event)
        self._pending_ids.add(event.event_id)
        if not self._flush_timer.isActive():
            self._flush_timer.start()
        return True

    def append_events(self, events):
        accepted = 0
        for event in events:
            accepted += bool(self.append_event(event))
        return accepted

    def flush_pending(self):
        if not self._pending:
            self._report_dropped_count()
            return 0

        batch = list(self._pending)
        self._pending.clear()
        self._pending_ids.clear()

        if len(batch) > self._max_events:
            skipped = len(batch) - self._max_events
            batch = batch[-self._max_events :]
            self._increase_dropped(skipped)

        overflow = max(0, len(self._events) + len(batch) - self._max_events)
        if overflow:
            self.beginRemoveRows(QModelIndex(), 0, overflow - 1)
            removed = self._events[:overflow]
            del self._events[:overflow]
            self._event_ids.difference_update(event.event_id for event in removed)
            self.endRemoveRows()
            self._increase_dropped(overflow)

        start = len(self._events)
        self.beginInsertRows(QModelIndex(), start, start + len(batch) - 1)
        self._events.extend(batch)
        self._event_ids.update(event.event_id for event in batch)
        self.endInsertRows()
        self.countChanged.emit(len(self._events))
        self._report_dropped_count()
        return len(batch)

    def clear(self):
        self._flush_timer.stop()
        self._pending.clear()
        self._pending_ids.clear()
        if self._events:
            self.beginResetModel()
            self._events.clear()
            self._event_ids.clear()
            self.endResetModel()
            self.countChanged.emit(0)
        if self._dropped_count:
            self._dropped_count = 0
        self._report_dropped_count()

    def reclassify_translations(self, words):
        """Re-evaluate translation markers after the user's rules change."""
        tokens = tuple(str(word).strip() for word in words if str(word).strip())
        changed_rows = []
        for row, event in enumerate(self._events):
            if event.kind not in {"danmaku", "super_chat"}:
                continue
            marked = any(token in event.text for token in tokens)
            updated = event.mark_translation(marked)
            if updated is event:
                continue
            self._events[row] = updated
            changed_rows.append(row)
        self._pending = deque(
            event.mark_translation(any(token in event.text for token in tokens))
            if event.kind in {"danmaku", "super_chat"}
            else event
            for event in self._pending
        )
        if changed_rows:
            first, last = min(changed_rows), max(changed_rows)
            self.dataChanged.emit(
                self.index(first, 0),
                self.index(last, 0),
                [Qt.DisplayRole, int(DanmakuRole.EVENT), int(DanmakuRole.CATEGORY)],
            )
        return len(changed_rows)

    def _increase_dropped(self, count):
        self._dropped_count += max(0, int(count))

    def _report_dropped_count(self):
        if self._reported_dropped_count == self._dropped_count:
            return
        self._reported_dropped_count = self._dropped_count
        self.droppedChanged.emit(self._dropped_count)


class DanmakuFilterProxyModel(QSortFilterProxyModel):
    """Search and category filtering for one event model."""

    VALID_MODES = frozenset({"all", "chat", "translation", "interaction"})

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = "all"
        self._query = ""
        self._translation_mode = 0
        self._interaction_mode = 0
        self.setDynamicSortFilter(True)

    @property
    def mode(self):
        return self._mode

    def set_mode(self, mode):
        mode = str(mode or "all").strip().lower()
        if mode not in self.VALID_MODES or mode == self._mode:
            return
        self._mode = mode
        self._refresh_filter()

    def set_search_text(self, text):
        query = str(text or "").strip().casefold()
        if query == self._query:
            return
        self._query = query
        self._refresh_filter()

    def set_display_policy(self, translation_mode=0, interaction_mode=0):
        translation_mode = max(0, min(int(translation_mode), 2))
        interaction_mode = max(0, min(int(interaction_mode), 3))
        if (translation_mode, interaction_mode) == (self._translation_mode, self._interaction_mode):
            return
        self._translation_mode = translation_mode
        self._interaction_mode = interaction_mode
        self._refresh_filter()

    def _refresh_filter(self):
        self.beginFilterChange()
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def filterAcceptsRow(self, source_row, source_parent):
        source = self.sourceModel()
        if source is None:
            return False
        index = source.index(source_row, 0, source_parent)
        event = index.data(DanmakuRole.EVENT)
        if not isinstance(event, DanmakuEvent):
            return False

        if self._mode == "chat" and event.category != "chat":
            return False
        if self._mode == "translation" and event.category != "translation":
            return False
        if self._mode == "interaction" and event.category != "interaction":
            return False
        if self._mode == "all":
            if event.category == "translation" and self._translation_mode == 1:
                return False
            if event.category == "chat" and self._translation_mode == 2:
                return False

        if event.category == "interaction" and not self._accept_interaction(event):
            return False

        if self._query:
            haystack = "\n".join(
                (event.text, event.uname, event.medal_name, event.kind_label)
            ).casefold()
            if self._query not in haystack:
                return False
        return True

    def _accept_interaction(self, event):
        if self._interaction_mode == 3:
            return False
        if self._interaction_mode == 1:
            return event.kind in {"gift", "guard", "super_chat"}
        if self._interaction_mode == 2:
            return event.kind == "enter"
        return True
