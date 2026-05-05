# DD Monitor

B站多窗口直播监控工具。基于 PySide6 和 MPV，支持同时观看最多 32 个直播间，实时弹幕显示，低资源占用。

---

## 关于本项目

DD Monitor 最初由 [神君Channel](https://space.bilibili.com/637783) 开发，本仓库是魔改分支，由 [BaoZi_Fly](https://space.bilibili.com/34094740) 维护。在保留原作者全部功能的基础上，进行了底层架构重构、弹幕系统重写、配置管理改良和大量 bug 修复。

原项目地址：[zhimingshenjun/DD_Monitor](https://github.com/zhimingshenjun/DD_Monitor)

当前版本：**v3.51 魔改版** — 基于 MPV + OpenGL 的弹幕渲染方案，告别 VLC 依赖。

---

## 功能

### 直播播放

- 16 个嵌入式播放窗口，最多扩展至 32 个（含悬浮窗口）
- MPV 播放器内核，支持硬件解码，CPU 和 GPU 占用远低于 VLC 方案
- 五档画质切换：原画、蓝光、超清、流畅、仅音频
- 单窗口音量增强，范围 0.5x 至 4.0x
- 全局播放控制：一键暂停、重载、静音、停止所有窗口
- 自定义窗口布局，支持拖拽网格和预设模板切换

### 弹幕系统

- 滚动弹幕由 MPV `osd-overlay` + QPainter 叠加渲染，不使用临时 ASS 文件，无字幕刷新闪烁
- 弹幕机为可拖拽的独立悬浮窗，半透明显示
- 支持弹幕与同传分离显示，同传过滤关键词可自定义（空格分隔）
- 礼物和进入信息可独立筛选
- 弹幕机透明度、字体大小、横向和纵向占比均可独立调节
- 每个窗口一键切换弹幕模式：全开、仅弹幕机、全关

### B站账号集成

- 扫码登录，二维码由 `qrcode` 库生成
- Session 本地持久化，启动时自动验证登录状态，Token 自动刷新
- 基于关注列表自动生成直播间卡片面板

### 交互

- 从卡片面板拖拽主播到播放窗口，一键加载直播间
- 拖拽播放窗口边缘，交换两个窗口的位置（同时交换音量和弹幕设置）
- 鼠标悬停窗口时按 M 或 S 键，除当前窗口外全部静音（再按恢复）
- 控制栏和鼠标指针在无操作 2 秒后自动隐藏
- 开播提醒弹窗

### 其他

- 录制直播流，最高画质
- 配置预设导入和导出，JSON 格式
- 窗口布局和 Dock 状态持久化
- 热门直播分区浏览：虚拟主播、网游、手游、单机、娱乐
- 内置 VUP 名单

---

## 快速开始

### 环境要求

| 组件 | 说明 |
|---|---|
| Python | 3.9 或更高版本 |
| libmpv | MPV 播放器库。Windows 用户需下载 DLL，macOS 和 Linux 用户通过包管理器安装 |
| 操作系统 | Windows / macOS / Linux |

### Windows

从 [mpv-winbuild-cmake](https://github.com/shinchiro/mpv-winbuild-cmake/releases) 下载最新的 `mpv-dev-x86_64-*.7z`，解压后将 `libmpv-2.dll` 放到项目根目录。

或者设置环境变量 `MPV_DLL` 指向 DLL 的完整路径。

### macOS

```bash
brew install mpv
```

### Linux

```bash
# Debian / Ubuntu
sudo apt install libmpv-dev

# Fedora
sudo dnf install mpv-libs
```

### 安装依赖

```bash
pip install -r requirements.txt
```

### 启动

```bash
python DD监控室.py
```

---

## 使用指南

### 快捷键

| 按键 | 功能 |
|---|---|
| F / f | 全屏 / 退出全屏 |
| H / h | 显示 / 隐藏控制条和菜单栏 |
| M / m / S / s | 除当前鼠标悬停窗口外全部静音（再按恢复） |
| Esc | 退出全屏 |

### 右键菜单

播放窗口右键：
- 选择画质（原画 / 蓝光 / 超清 / 流畅 / 仅音频）
- 音量增强（0.5x ~ 4.0x）
- 悬浮窗播放

卡片槽右键：
- 添加直播间
- 清空卡片槽

主播卡片右键：
- 添加至指定窗口
- 置顶 / 取消置顶
- 录制直播
- 复制房号
- 在浏览器中打开直播间

### 菜单栏

- **设置**：布局方式、全局画质、全局音效、解码方案、开播提醒、缓存设置、弹幕设置、预设导入导出
- **B站账号**：扫码登录、账号管理、用户信息
- **帮助**：快捷键说明、版本检查、B站视频教程
- **开源和投喂**：GitHub 仓库、打赏作者

---

## 常见问题

### 弹幕不显示

1. 点击窗口控制栏「弹」按钮，确认弹幕模式不是「全关」
2. 检查菜单「弹幕设置」中「自动加载弹幕」是否开启
3. 检查网络连接，弹幕依赖 WebSocket 长连接，如使用代理请确保 WebSocket 未被拦截

### 画面卡顿

1. 右键窗口切换至较低画质
2. 在菜单「解码方案」中切换硬解和软解
3. 减少同时播放的窗口数量
4. Windows 下 OpenGL 渲染路径已自动禁用硬件解码以规避花屏问题，CPU 占用可能略高

### 扫码登录失败

1. 确认网络能访问 `passport.bilibili.com`
2. 二维码 180 秒后过期，点击「刷新二维码」
3. 确认 `qrcode[pil]` 已安装
4. 登录状态有效期约 6 个月，过期后需重新登录

### libmpv 未找到

1. Windows：确认 `libmpv-2.dll` 在项目根目录，或已设置 `MPV_DLL` 环境变量
2. macOS：`brew install mpv`
3. Linux：安装 `libmpv-dev` 或 `mpv-libs`

### 配置文件损坏

程序自动维护 3 份轮转备份（`config_备份1.json` ~ `config_备份3.json`）。主配置损坏时自动从备份恢复。

---

## 项目结构

```
DD监控室.py              主窗口入口，配置加载，窗口管理，全局控制
config_manager.py         配置加载、保存、格式迁移、备份轮转
VideoWidget_mpv.py         MPV 播放器窗口，流获取，播放控制，弹幕管理
danmu.py                  弹幕系统，弹幕机 UI，全局设置面板
danmaku_renderer.py       滚动弹幕渲染器，OpenGL 叠加层，精灵缓存
danmaku_layout.py          弹幕布局引擎，滚动/顶部/底部轨道管理
LiverSelect.py            主播卡片面板，热门直播，关注列表，VUP 名单
login.py                  扫码登录模块，Session 管理
remote.py                 弹幕 WebSocket 接收线程
http_utils.py             共享 HTTP 连接池
CommonWidget.py           通用组件（Slider）
bili_credential.py         B站凭据规范化
LayoutConfig.py           布局配置数据
LayoutPanel.py            布局选择面板
mpv_gl_widget.py           MPV OpenGL 渲染控件
ReportException.py        异常日志收集
checkUpdate.py            版本更新检查
log.py                    日志初始化
pay.py                    赞助页面
blivedm/                  B站弹幕协议库（vendored）
utils/                    资源文件（QSS 主题、启动图、图标、VUP 名单）
scripts/                  打包脚本
docs/                     文档和更新日志
```

---

## 打包发布

### Windows

```bat
scripts\build_win.bat x64
set APP_VERSION=3.51
set MPV_DLL=D:\path\to\libmpv-2.dll
```

打包完成后 `release/` 目录生成 `DDMonitor-3.51-windows-x64.zip`。

### macOS / Linux

使用 PyInstaller 手动打包：

```bash
pyinstaller DDMonitor_macos.spec   # macOS
pyinstaller DDMonitor_unix.spec    # Linux
```

---

## 更新日志

详见 [docs/release-notes/](docs/release-notes/)

---

## 致谢

DD Monitor 由 [神君Channel](https://space.bilibili.com/637783) 创作。没有原作者的多年投入，就不会有这个项目。本魔改分支的维护者 [BaoZi_Fly](https://space.bilibili.com/34094740) 在此基础上进行了重构和修复。

依赖的开源项目：

- [blivedm](https://github.com/xfgryujk/blivedm) — B站弹幕 WebSocket 协议库
- [mpv](https://mpv.io/) — 开源视频播放器
- [bilibili-api-python](https://github.com/Nemo2011/bilibili-api) — B站 API Python 封装
- [PySide6](https://wiki.qt.io/Qt_for_Python) — Qt for Python GUI 框架

特别感谢大锅饭、美东矿业、inkydragon、聪_哥 PR 对原项目的贡献。

## 许可证

LGPL-2.1。原项目版权归 [zhimingshenjun](https://github.com/zhimingshenjun) 所有。魔改部分同样以 LGPL-2.1 协议开源。
