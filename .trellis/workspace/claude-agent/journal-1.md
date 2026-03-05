# Journal - claude-agent (Part 1)

> AI development session journal
> Started: 2026-03-06

---



## Session 1: 弹幕渲染重写+VLC移除+blivedm升级+bilibili-api集成

**Date**: 2026-03-06
**Task**: 弹幕渲染重写+VLC移除+blivedm升级+bilibili-api集成

### Summary

(Add summary)

### Main Changes

## 核心变更

| 模块 | 变更 |
|------|------|
| danmu.py | 全面重写为 ASS 字幕轨道方案，\move() 动画由 libass 原生帧率渲染 |
| remote.py | 重写为 blivedm WebSocket 异步架构，过滤镜像弹幕去重 |
| VideoWidget_mpv.py | 新 MPV 播放器模块，直接播放直播流 URL |
| LiverSelect.py | 修复热门列表 API (-352)，改用 getListByAreaID |
| login.py | 新扫码登录模块，登录后显示用户信息 |
| DD监控室.py | 登录后自动获取关注列表，标题显示用户名 |
| requirements.txt | 新增 bilibili-api-python, pure-protobuf, yarl, qrcode |

## 删除文件
- VideoWidget_vlc.py, VideoWidget.py (VLC 播放器模块)
- libvlc.dll, libvlccore.dll (VLC 动态库)
- docs/vlc-*.md, hooks/hook-vlc.py (VLC 文档和钩子)

## 关键技术决策
1. **弹幕渲染**: OSD overlay 因 python-mpv _make_node_str_map 类型 bug 无法正确传递 INT64 参数，改用 ASS 字幕轨道 + sub-add/sub-reload (仅位置参数，无类型问题)
2. **热门列表**: xlive/web-interface/v1/second/getList 已要求 WBI 签名 (-352)，改用 room/v1/Area/getListByAreaID (无需签名)
3. **弹幕去重**: blivedm v1.1.5 同时分发 DANMU_MSG + DANMU_MSG_MIRROR，在 handler 中过滤 is_mirror=True


### Git Commits

| Hash | Message |
|------|---------|
| `317d261` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete
