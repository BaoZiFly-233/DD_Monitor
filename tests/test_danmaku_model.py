from dataclasses import FrozenInstanceError

import pytest

from app.danmaku.events import DanmakuEvent
from app.danmaku.model import DanmakuEventModel, DanmakuFilterProxyModel, DanmakuRole


def _event(index, **changes):
    values = {
        "event_id": f"event-{index}",
        "room_id": "100",
        "connection_id": 3,
        "text": f"message {index}",
        "uname": f"user {index}",
        "timestamp_ms": 1_700_000_000_000 + index,
    }
    values.update(changes)
    return DanmakuEvent(**values)


def test_danmaku_event_is_immutable_and_normalized():
    event = DanmakuEvent(
        room_id=123,
        kind="DANMAKU",
        text="  hello  ",
        color=0x12ABEF,
        position="unknown",
        timestamp_ms=1_700_000_000,
    )

    assert event.room_id == "123"
    assert event.kind == "danmaku"
    assert event.text == "hello"
    assert event.color == "#12ABEF"
    assert event.position == "scroll"
    assert event.timestamp_ms == 1_700_000_000_000
    assert len(event.event_id) == 24
    with pytest.raises(FrozenInstanceError):
        event.text = "changed"


def test_event_normalizes_malformed_numeric_metadata():
    event = DanmakuEvent(
        price="not-a-number",
        quantity=object(),
        medal_level="bad",
        guard_level=None,
    )

    assert event.price == 0.0
    assert event.quantity == 0
    assert event.medal_level == 0
    assert event.guard_level == 0


def test_event_model_batches_deduplicates_and_bounds_history(qapp):
    model = DanmakuEventModel(max_events=3, flush_interval_ms=0)
    assert model.append_event(_event(1)) is True
    assert model.append_event(_event(1)) is False
    assert model.append_events([_event(2), _event(3), _event(4)]) == 3

    assert model.rowCount() == 0
    assert model.flush_pending() == 3
    assert model.rowCount() == 3
    assert model.dropped_count == 1
    assert [model.event_at(row).event_id for row in range(3)] == [
        "event-2",
        "event-3",
        "event-4",
    ]
    assert model.index(1, 0).data(DanmakuRole.EVENT).text == "message 3"


def test_event_model_inserts_bursts_as_one_batch(qapp):
    model = DanmakuEventModel(max_events=1500, max_pending=1500, flush_interval_ms=1000)
    inserted = []
    model.rowsInserted.connect(lambda parent, first, last: inserted.append((first, last)))

    assert model.append_events(_event(index) for index in range(1000)) == 1000
    assert model.rowCount() == 0
    assert model.flush_pending() == 1000

    assert inserted == [(0, 999)]
    assert model.rowCount() == 1000
    assert model.dropped_count == 0


def test_event_model_bounds_pending_queue(qapp):
    model = DanmakuEventModel(max_events=20, max_pending=2, flush_interval_ms=1000)
    dropped_updates = []
    model.droppedChanged.connect(dropped_updates.append)
    model.append_events([_event(1), _event(2), _event(3)])

    assert dropped_updates == []
    model.flush_pending()

    assert model.rowCount() == 2
    assert model.dropped_count == 1
    assert dropped_updates == [1]
    assert model.event_at(0).event_id == "event-2"

    model.clear()
    assert model.rowCount() == 0
    assert model.dropped_count == 0
    assert dropped_updates == [1, 0]


def test_event_model_reclassifies_existing_messages(qapp):
    model = DanmakuEventModel(max_events=20, flush_interval_ms=0)
    model.append_events([_event(1, text="ordinary"), _event(2, text="[EN] translated")])
    model.flush_pending()

    assert model.reclassify_translations(["[EN]"]) == 1
    assert model.event_at(0).is_translation is False
    assert model.event_at(1).is_translation is True
    assert model.reclassify_translations([]) == 1
    assert model.event_at(1).is_translation is False


def test_filter_proxy_supports_modes_policy_and_search(qapp):
    model = DanmakuEventModel(max_events=20, flush_interval_ms=0)
    model.append_events(
        [
            _event(1, text="ordinary"),
            _event(2, text="translated", is_translation=True),
            _event(3, kind="gift", text="gift", uname="alice"),
            _event(4, kind="enter", text="entered", uname="bob"),
        ]
    )
    model.flush_pending()
    proxy = DanmakuFilterProxyModel()
    proxy.setSourceModel(model)

    assert proxy.rowCount() == 4
    proxy.set_mode("translation")
    assert proxy.rowCount() == 1
    proxy.set_mode("interaction")
    assert proxy.rowCount() == 2

    proxy.set_display_policy(translation_mode=0, interaction_mode=1)
    assert proxy.rowCount() == 1
    assert proxy.index(0, 0).data(DanmakuRole.EVENT).kind == "gift"

    proxy.set_mode("all")
    proxy.set_display_policy(translation_mode=1, interaction_mode=3)
    assert proxy.rowCount() == 1
    assert proxy.index(0, 0).data(DanmakuRole.EVENT).text == "ordinary"

    proxy.set_display_policy(translation_mode=0, interaction_mode=0)
    proxy.set_search_text("ALICE")
    assert proxy.rowCount() == 1
    assert proxy.index(0, 0).data(DanmakuRole.EVENT).kind == "gift"
