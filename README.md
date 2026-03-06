# DD监控室

多窗口 Bilibili 直播监控工具，支持同时观看多个直播间，基于 PySide6 + MPV 播放器。

## 功能特性

- 16 个嵌入式播放窗口 + 16 个悬浮窗口，最多同时监控 32 个直播间
- MPV 播放器内核，硬件加速解码，低 CPU 占用
- 实时弹幕接收与显示（WebSocket 连接，Signal 推送）
- ASS 字幕轨道滚动弹幕渲染（libass 原生帧率插值）
- 扫码登录 B站账号，自动获取关注列表
- 直播间卡片面板，开播状态实时刷新
- 画质选择（原画/蓝光/超清/流畅/仅音频）
- 拖拽交换播放窗口、自定义布局
- 弹幕机透明度/位置/过滤/同传分离
- 录制直播流

## 运行指南

### 环境要求

- Python 3.8+
- [libmpv](https://github.com/shinchiro/mpv-winbuild-cmake/releases)：将 `libmpv-2.dll` 放置在项目根目录

### 安装依赖

```bash
pip install -r requirements.txt
```

### 启动

```bash
python DD监控室.py
```

## 所需依赖

| 包名 | 用途 |
|------|------|
| PySide6 | GUI 框架 |
| python-mpv | MPV 播放器绑定 |
| requests | HTTP 请求 |
| aiohttp | 弹幕 WebSocket 连接 |
| qrcode[pil] | 二维码生成（扫码登录） |
| pure-protobuf | blivedm 协议解析 |
| dnspython | DNS 解析 |
| bilibili-api-python | B站 API |

## 项目结构

```
DD监控室.py          # 主窗口入口
VideoWidget_mpv.py   # MPV 播放器窗口
remote.py            # 弹幕接收线程（blivedm WebSocket）
danmu.py             # 弹幕显示 + ASS 滚动弹幕渲染器
LiverSelect.py       # 主播卡片面板 + 关注列表
login.py             # 扫码登录模块
http_utils.py        # 共享 HTTP 连接池
blivedm/             # B站弹幕库 v1.1.5
```

## 打包

### Windows

- `2.26` 首发 Release 仅提供 `Windows x64`
- 默认读取仓库根目录的 `libmpv-2.dll`
- 也可以通过环境变量 `MPV_DLL` 指定当前架构对应的 DLL 路径
- 打包命令：

```bat
scripts\build_win.bat x64
```

- 可选环境变量：

```bat
set APP_VERSION=2.26
set MPV_DLL=D:\path\to\libmpv-2.dll
set MPV_RUNTIME_DIR=D:\path\to\mpv-runtime
```

- 打包完成后会在 `release/` 目录生成可直接分发的 zip：

```text
DDMonitor-2.26-windows-x64.zip
```

### 其他平台

在 `scripts` 文件夹下保留了其他平台的历史打包脚本，如需继续使用，请在仓库根目录执行。

## 致谢

- [blivedm](https://github.com/xfgryujk/blivedm) — B站弹幕协议库
- [mpv](https://mpv.io/) — 开源视频播放器
- [DD_Monitor](https://github.com/zhimingshenjun/DD_Monitor) — 原始项目
