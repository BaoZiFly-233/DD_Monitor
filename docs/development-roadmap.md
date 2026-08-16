# DD Monitor development roadmap

This document records the architecture direction after the 2026 live playback and
danmaku review. It is intentionally more detailed than the README: the README is
for users, while this file defines engineering boundaries and acceptance gates.

## Reference baseline

The review is pinned to concrete upstream revisions so the conclusions remain
reproducible.

| Project | Revision | What was reviewed |
| --- | --- | --- |
| [KikoPlay](https://github.com/KikoPlayProject/KikoPlay/tree/200abb17ab27bc1e98ee5671cfb1cd804982133f) | `200abb1` | `DanmuRender`, `CacheWorker`, rolling/fixed layouts, `LiveDanmuListModel`, draw-task interaction |
| [PiliPlus](https://github.com/bggRGjQaUbCoE/PiliPlus/tree/c92476e) | `c92476e` | live-room controller, play URL model, chat panel, history/realtime merge, room lifecycle |

These projects are references, not dependencies. No GPL implementation is copied
into DD Monitor. The adopted ideas are general architecture and algorithms,
reimplemented for Python, PySide6, libmpv and multi-room live monitoring.

## Findings

### KikoPlay

KikoPlay separates the danmaku system into five useful responsibilities:

1. `DanmuRender` owns time, visibility and draw dispatch instead of network data.
2. `CacheWorker` pre-renders text and returns reusable image data asynchronously.
3. `RollLayout`, `TopLayout` and `BottomLayout` own independent collision state.
4. Rolling lanes predict both tail overlap and whether a faster new item can catch
   the previous item before it leaves the viewport.
5. `LiveDanmuListModel` exposes live messages through a model, not by appending
   formatted HTML to a text widget.

DD Monitor adopts all five boundaries. The C++ OpenGL texture atlas is deliberately
not ported in this phase: sharing OpenGL resources across Python worker threads
would widen the native crash surface immediately after the libmpv stability work.
The rendering backend remains replaceable behind the same event, cache and layout
interfaces.

### PiliPlus

PiliPlus keeps room ownership in its live-room controller. The controller owns the
room ID, connection, reconnect/dispose lifecycle and playback state. The chat panel
adds two particularly useful behaviours:

- historical messages and realtime messages enter one ordered list;
- scrolling away from the bottom disables automatic following and presents an
  explicit return-to-bottom action.

Its play URL model also keeps quality and URL resolution outside the widget tree.
DD Monitor already follows this rule through `app/media/stream.py`; the same rule is
now applied to danmaku events and room identity.

## Current danmaku architecture

```text
blivedm websocket thread
        |
        | immutable DanmakuEvent
        v
room/request validation (GUI thread)
        |
        +---------------------> DanmakuEventModel
        |                       searchable live timeline
        |                       auto-follow / pause / resume
        |
        v
DanmakuRenderer
  |- filter chain
  |- asynchronous sprite cache
  |- RollLayout
  |- TopLayout
  `- BottomLayout
        |
        v
QOpenGLWidget paint pass over libmpv video
```

### Event contract

Every message crossing the thread boundary is an immutable `DanmakuEvent`. It keeps
the room ID, event ID, timestamp, user identity, message kind, display position,
colour and monetary metadata. UI code must reject an event whose room ID no longer
matches the player. Raw strings are not a valid cross-thread contract.

### Rendering contract

- Layout classes contain no network or widget logic.
- Text rasterisation is requested through an asynchronous bounded cache.
- A cache miss never performs expensive font rendering in the frame paint method.
- The renderer accepts events and translates them into draw items; the video widget
  does not manipulate lanes directly.
- Rolling, top and bottom modes keep independent occupancy.
- The renderer and feed model use bounded queues so a burst cannot grow memory
  without limit.

### Danmaku console contract

The per-player console is a model/view work surface rather than three overlapping
`QTextBrowser` instances. It provides:

- all/chat/translation/interaction views;
- search without mutating source data;
- username, timestamp, kind and price presentation;
- automatic following only while the user is already at the bottom;
- a visible return-to-bottom command after manual history browsing;
- the existing opacity, placement, font and entry/gift filtering settings;
- one cached window per player, hidden and reused on close.

### Playback boundary

libmpv remains the playback engine. DD Monitor supplies its own controls and does
not load mpv's Lua/JavaScript UI scripts. Qt owns the danmaku overlay. This keeps
video decoding, live protocol handling and danmaku rendering replaceable and avoids
coupling the overlay to mpv's script runtime.

## Performance budgets

These budgets are release gates, not aspirations.

| Path | Budget |
| --- | ---: |
| Append one cached live message | `< 1 ms` on the GUI thread |
| Unique text cache miss scheduling | `< 1 ms` on the GUI thread |
| Danmaku paint p95, 1080p / 100 active | `< 8 ms` |
| Live feed retained rows per player | `<= 500` |
| Pending render requests per player | `<= 256` |
| Reopen cached settings/danmaku window | `< 100 ms` |
| Close a cached tool window | `< 50 ms` |
| Fast room/category switching | no stale result, exception or native crash |

## Delivery plan

### Phase 1 - event and render core (implemented)

- [x] Preserve room, connection, user, color, position, gift, medal and time metadata in an immutable event.
- [x] Emit event objects from `blivedm` instead of preformatted strings.
- [x] Reject old-room and old-connection events at the `VideoWidget` boundary.
- [x] Replace rich-text history with a bounded model/delegate workbench, search and manual-scroll protection.
- [x] Move text rasterisation behind an asynchronous cache with duplicate request coalescing.
- [x] Keep KikoPlay-style independent lane schedulers and collision prediction.
- [x] Rebuild the per-player danmaku console as a complete Fluent work surface.
- [x] Keep mpv scripts disabled and verify multi-instance native stability.

Current limits and guarantees:

- each player retains at most 500 events;
- each renderer retains at most 128 cached sprites and 256 pending callbacks;
- room changes clear the previous room history;
- sprite misses are scheduled off the GUI thread;
- the existing scroll/top/bottom overlay behavior remains compatible.

Measured Phase 1 baseline on the current Windows development machine:

- cached event append: about `0.028 ms/event`;
- unique sprite miss scheduling: about `0.019 ms/request`;
- workbench construction: about `45 ms`;
- workbench reopen after hiding: about `4 ms`.

### Phase 2 - reliability and observability

- Add reconnect state and reason reporting to the per-room controller.
- Merge an optional bounded history fetch with the realtime event stream.
- Add renderer counters: accepted, filtered, dropped, cache hit and paint p95.
- Add deterministic recorded-event replay for visual and performance regression.
- Pin and publish a tested stable libmpv build instead of a rolling development DLL.

### Phase 3 - renderer backend evaluation

- Benchmark a shared OpenGL texture atlas against the QImage sprite backend.
- Proceed only if it lowers paint p95 by at least 25% at 200 active messages and
  survives multi-player create/destroy stress without a native exception.
- Keep the current backend as a compatibility fallback.

### Phase 4 - live-room orchestration

- Introduce a room controller that owns stream URL requests, playback, danmaku and
  reconnect state as one cancellable lifecycle.
- Add history/realtime ordering and deduplication by event ID.
- Add per-room diagnostics and exportable support reports with credentials removed.

## Verification checklist

Every phase must pass:

```bash
python -m pytest -q
python -m ruff check app tests scripts DD监控室.py
python -m compileall -q app tests scripts DD监控室.py
python scripts/make_screenshots.py
git diff --check
```

Native playback changes additionally require a multi-instance libmpv stress run
with Python faulthandler enabled and a clean shutdown check on Windows.
