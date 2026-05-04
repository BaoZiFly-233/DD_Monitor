# DD监控室 — B站多窗口直播监控

基于 PySide6 + MPV 的 B站多直播间监控工具，支持同时观看最多 32 个直播间，实时弹幕显示，低资源占用。

> **当前版本**: v3.51 魔改版 — 弹幕系统全面重构为 MPV `osd-overlay` 滚动弹幕渲染。

> **原作者**: [神君Channel](https://space.bilibili.com/637783) · **魔改维护**: [BaoZi_Fly](https://space.bilibili.com/34094740)
>
> 本项目 fork 自 [zhimingshenjun/DD_Monitor](https://github.com/zhimingshenjun/DD_Monitor)，感谢原作者的开源贡献。

## 功能特性

### 直播播放
- 16 个嵌入式播放窗口 + 16 个悬浮窗口，最多同时监控 32 个直播间
- MPV 播放器内核，支持硬件解码，CPU / GPU 占用低
- 五档画质切换：原画 / 蓝光 / 超清 / 流畅 / 仅音频
- 单窗口音量增强（0.5x ~ 4.0x）
- 全局播放控制：一键暂停/重载/静音/停止
- 自定义窗口布局（拖拽网格、预设切换）

### 弹幕系统
- **滚动弹幕**: MPV `osd-overlay` 渲染，无临时 ASS 文件、无字幕刷新闪烁
- **弹幕机**: 可拖拽的独立悬浮窗，半透明显示，支持弹幕/同传分离、礼物和进入信息筛选
- 同传弹幕过滤（空格分隔关键词），自动归类到独立面板
- 弹幕机透明度 / 字体 / 横向纵向比例均可调
- 单窗口一键切换弹幕模式（全开 / 仅弹幕机 / 全关）

### B站账号集成
- 扫码登录（qrcode 库生成二维码），自动获取关注列表
- Session 持久化，启动自动验证登录状态，Token 自动刷新
- 基于关注列表的直播间卡片面板

### 交互体验
- 拖拽卡片到播放窗口 → 一键加载直播间
- 拖拽播放窗口边缘 → 交换窗口位置（同时交换音量、弹幕设置）
- 鼠标悬停窗口静音排除模式（M/S 键）
- 自动隐藏控制栏与鼠标指针（无操作 2 秒后消失）
- 开播提醒弹窗

### 其他
- 录制直播流（最高画质）
- 配置预设导入/导出（JSON 格式）
- 窗口布局持久化
- 热门直播分区浏览（虚拟主播 / 网游 / 手游 / 单机 / 娱乐）
- 内置 VUP（虚拟主播）名单

## 快速开始

### 环境要求

| 组件 | 说明 |
|------|------|
| Python | 3.9+ |
| libmpv | MPV 播放器库 ([Windows 下载](https://github.com/shinchiro/mpv-winbuild-cmake/releases)) |
| 操作系统 | Windows / macOS / Linux |

**Windows 用户**: 下载 `libmpv-2.dll` 放在项目根目录，或设置环境变量 `MPV_DLL` 指向 DLL 路径。

**macOS 用户**:
```bash
brew install mpv
```

**Linux 用户**:
```bash
sudo apt install libmpv-dev    # Debian/Ubuntu
sudo dnf install mpv-libs      # Fedora
```

### 安装依赖

```bash
pip install -r requirements.txt
```

### 启动

```bash
python DD监控室.py
```

## 使用指南

### 快捷键

| 按键 | 功能 |
|------|------|
| `F` / `f` | 全屏 / 退出全屏 |
| `H` / `h` | 显示 / 隐藏控制条和菜单 |
| `M` / `m` / `S` / `s` | 除当前鼠标悬停窗口外全部静音（再按恢复） |
| `Esc` | 退出全屏 |

### 右键菜单

- **播放窗口右键**: 画质切换 / 音量增强 / 悬浮窗播放
- **卡片槽右键**: 添加直播间 / 清空
- **主播卡片右键**: 添加至窗口 / 置顶 / 录制 / 复制房号 / 打开直播间

### 菜单栏

- **设置**: 布局方式、全局画质、全局音效、解码方案、开播提醒、缓存设置、弹幕设置、预设导入/导出
- **B站账号**: 扫码登录 / 账号管理
- **帮助**: 快捷键说明、版本检查、B站视频教程
- **开源和投喂**: GitHub 仓库、打赏作者

## 常见问题

### 弹幕不显示

1. 确认弹幕按钮状态：点击窗口控制栏「弹」按钮在「全开 / 仅弹幕机 / 全关」之间切换
2. 检查弹幕设置中「自动加载弹幕」选项是否开启
3. 检查网络连接，弹幕依赖 WebSocket 长连接
4. 如使用代理，确保 WebSocket 协议未被拦截

### 画面卡顿

1. 切换画质至较低档位（流畅）
2. 在菜单「解码方案」中尝试切换硬解/软解
3. 减少同时播放的窗口数量
4. Windows 下 OpenGL 渲染路径已自动禁用硬件解码以规避花屏

### 扫码登录失败

1. 检查网络是否能访问 `passport.bilibili.com`
2. 二维码 180 秒后过期，点击「刷新二维码」重试
3. 确认已安装 `qrcode[pil]` 依赖
4. 登录状态有效期约 6 个月，过期后需重新登录

### libmpv 未找到 (ImportError)

1. Windows: 确保 `libmpv-2.dll` 在项目根目录
2. macOS: `brew install mpv`
3. Linux: 安装 `libmpv-dev` / `mpv-libs`
4. 设置环境变量 `MPV_DLL=/path/to/libmpv.so`

### 配置文件损坏

程序会自动维护 3 份轮转备份 (`config_备份1.json` ~ `config_备份3.json`)。如果主配置损坏，将自动从备份恢复。

## 项目结构

```
DD监控室.py              # 主窗口入口（配置加载、窗口管理、全局控制）
config_manager.py         # 配置管理（加载、保存、迁移、备份轮转）
VideoWidget_mpv.py        # MPV 播放器窗口（流获取、播放控制、弹幕管理）
danmu.py                  # 弹幕系统（弹幕机 UI、全局设置面板）
danmaku_renderer.py       # 滚动弹幕渲染器（OpenGL 叠加层）
danmaku_layout.py         # 弹幕布局引擎（滚动/顶部/底部轨道）
LiverSelect.py            # 主播卡片面板（热门直播、关注列表、VUP 名单）
login.py                  # 扫码登录模块
remote.py                 # 弹幕 WebSocket 接收线程
http_utils.py             # 共享 HTTP 连接池
CommonWidget.py           # 通用组件（Slider 等）
bili_credential.py        # B站凭据规范化工具
LayoutConfig.py           # 布局配置数据
LayoutPanel.py            # 布局选择面板
mpv_gl_widget.py          # MPV OpenGL 渲染控件
ReportException.py        # 异常日志收集
checkUpdate.py            # 版本更新检查
log.py                    # 日志初始化
pay.py                    # 赞助页面
blivedm/                  # B站弹幕协议库（vendored）
utils/                    # 资源文件 (QSS主题、启动图、图标)
scripts/                  # 打包脚本
docs/                     # 文档
```

## 打包发布

### Windows

```bat
scripts\build_win.bat x64
# 可选环境变量
set APP_VERSION=3.51
set MPV_DLL=D:\path\to\libmpv-2.dll
```

打包完成后在 `release/` 目录生成 `DDMonitor-3.51-windows-x64.zip`。

### 其他平台

使用 PyInstaller 手动打包：

```bash
pyinstaller DDMonitor_unix.spec    # Linux
pyinstaller DDMonitor_macos.spec   # macOS
```

## 更新日志

详见 [docs/release-notes/](docs/release-notes/)

## 致谢

- **原作者**: [神君Channel](https://space.bilibili.com/637783) ([zhimingshenjun/DD_Monitor](https://github.com/zhimingshenjun/DD_Monitor)) — 项目原始开发者
- [blivedm](https://github.com/xfgryujk/blivedm) — B站弹幕 WebSocket 协议库
- [mpv](https://mpv.io/) — 开源视频播放器
- [bilibili-api-python](https://github.com/Nemo2011/bilibili-api) — B站 API 封装
- [PySide6](https://wiki.qt.io/Qt_for_Python) — Qt for Python GUI 框架
- 特别鸣谢：大锅饭、美东矿业、inkydragon、聪_哥 PR

## License

MIT — 原作者 [zhimingshenjun](https://github.com/zhimingshenjun) 保留原始版权。魔改部分同样以 MIT 协议开源。
