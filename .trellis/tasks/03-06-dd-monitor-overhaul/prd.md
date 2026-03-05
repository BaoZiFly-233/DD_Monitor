# DD监控室全面重构

## Goal
修复并现代化 DD监控室 项目，涵盖弹幕系统、播放器引擎、登录流程、关注列表和性能优化。

## Requirements

### 阶段 1：修复弹幕系统
- 重写 `remote.py`，在 QThread 中正确运行 asyncio 事件循环
- 使用项目内置的 `blivedm` 库接收弹幕
- 用 Signal 推送替代 20ms QTimer 轮询

### 阶段 2：简化登录 + 修复关注列表
- 引入 `bilibili-api-python`，实现扫码登录
- 使用 Credential 统一管理凭据（支持持久化）
- 修复 GetFollows 关注列表查询（需要登录 cookie）

### 阶段 3：VLC → MPV 迁移
- 创建 `VideoWidget_mpv.py` 替换 `VideoWidget_vlc.py`
- MPV 直接播放直播流 URL（消除 FLV 手动缓存下载）
- 修改 `DD监控室.py` 中 3 处 VLC 硬编码调用

### 阶段 4：添加滚动弹幕
- 在 VideoWidget 上添加透明 overlay
- QPainter + QPropertyAnimation 渲染滚动弹幕

### 阶段 5：性能优化
- 延迟初始化播放器
- HTTP 连接池复用
- 消除不必要的轮询

## Acceptance Criteria
- [ ] 弹幕可以正常接收和显示
- [ ] 扫码登录可用，无需 QWebEngineView
- [ ] MPV 播放器正常播放直播流
- [ ] 滚动弹幕效果可用
- [ ] 关注列表可正常获取
- [ ] 启动速度和运行性能显著提升

## Technical Notes
- PySide6 GUI 框架
- 内置 blivedm 弹幕库
- bilibili-api-python 用于登录和 API 调用
- python-mpv 用于视频播放
