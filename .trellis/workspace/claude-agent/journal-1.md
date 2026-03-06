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


## Session 2: Login SESSDATA URL编码根因修复

**Date**: 2026-03-06
**Task**: Login SESSDATA URL编码根因修复

### Summary

(Add summary)

### Main Changes

## 问题根因

用户发现登录后重启 app 会丢失登录状态。经分析发现完整的 bug 链：

1. 旧版 `_parseCookiesFromURL()` 用 `split('=')` 保存 SESSDATA，未做 URL 解码
2. SESSDATA 含 `%2C`（逗号）和 `%2A`（星号）等编码字符
3. 重启后 URL 编码的 SESSDATA 原样发给 B站 API → API 拒绝 → `_expired`
4. 触发 `sessionData('')` 清空信号 → config.json 被覆写为空
5. 备份轮转机制（DumpConfig）把清空后的值写入 config.json + 备份1
6. 备份2/3 仍保留着旧的 URL 编码值

这也解释了之前观察到的 **45ms 清空之谜**：验证线程用 URL 编码值调 API → 被拒 → 立即清空。

## 修复内容

| 文件 | 修改 |
|------|------|
| `login.py` | `setSessionData()` 增加 URL 解码防护（`%` 检测 + `unquote()`） |
| `DD监控室.py` | config 加载时对 sessionData 做 URL 解码（兼容旧版存储） |
| `utils/config.json` | 从备份2恢复 URL 解码后的 SESSDATA（有效期至 2026-09-02） |

## 关键发现

- config_备份2/3.json 保留了 URL 编码的 SESSDATA，是恢复线索
- SESSDATA 中的时间戳 `1788323934` → 2026-09-02，session 仍有效
- 双重 URL 解码防护：DD监控室.py 加载时 + login.py 接收时


### Git Commits

| Hash | Message |
|------|---------|
| `ffe75db` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete
