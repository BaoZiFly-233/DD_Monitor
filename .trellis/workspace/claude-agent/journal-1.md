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


## Session 3: Release 启动崩溃、隐私泄露与资源缺失修复

**Date**: 2026-03-06
**Task**: Release 启动崩溃、隐私泄露与资源缺失修复

### Summary

修复 Windows Release 的 mpv DLL、日志递归、私人配置泄露与 qdark.qss 缺失问题，并重新发布可用的 2.26。

### Main Changes

﻿## 根因分析

本次会话主要围绕 GitHub Release 的 Windows 包启动失败与发布污染问题展开，最终确认并修复了两条关键问题链：

1. `python-mpv` 在打包版中无法找到 `libmpv-2.dll`。
   - 代码原先只把模块目录加入 `PATH`，但 PyInstaller one-dir 产物下 DLL 实际位于发行目录根部。
   - 因此 `import mpv` 在 Release 中会直接抛出 `OSError`。

2. `mpv` 导入失败后，日志桥接流在无效 `stderr/stdout` 环境下继续回写到 logging。
   - 导致 `NoneType.write` 与 `logging -> stream -> logging` 递归自咬。
   - 最终触发 `RecursionError`，掩盖了原始报错。

3. Windows 打包脚本曾直接复制整个 `utils` 目录。
   - 这会把本地 `config.json`、`config_备份*.json`、登录态、窗口布局和个人预设一起带进 Release。
   - 后续为剔除这些敏感配置时，曾一度误删到运行时必需资源，导致 `utils/qdark.qss` 缺失并再次启动失败。

## 主要修改

- `VideoWidget_mpv.py`
  - 增加 `prepare_mpv_runtime()`，统一补充冻结目录、模块目录、`_MEIPASS` 与 `mpv` 子目录到 DLL 搜索路径。
  - 在 Windows 下通过 `os.add_dll_directory()` 显式注册候选路径，降低打包版 `mpv` 装载失败概率。

- `log.py`
  - 重写 `LoggerStream`，加入线程级防重入保护。
  - 为 `stdout/stderr` 提供安全回退流，避免异常场景下再次递归写日志。
  - 日志初始化改为显式使用 `sys.__stderr__ / sys.__stdout__`，并关闭 logging 内部异常回抛。

- `DD监控室.py`
  - 启动阶段显式调用 `prepare_mpv_runtime()` 后再导入 `mpv`。
  - 默认配置中的 `roomid` 改为空，避免发布包自带开发环境预设。
  - 版本号最终恢复为 `2.26`，避免额外后缀污染正式发布。

- `scripts/build_win.bat`
  - 保留对 `utils` 运行时资源的复制，确保 `qdark.qss`、`splash.jpg`、`vtb.csv` 等文件存在于程序实际读取的位置。
  - 在复制后明确删除 `utils/config.json` 与 `utils/config_备份*.json`，防止再次把私人配置打进 Release。
  - 构建默认版本恢复为 `2.26`。

- `.github/workflows/python-app.yml`
  - Release 默认版本恢复为 `2.26`。
  - Release 默认标题改为 `DDMonitor 2.26`，不再追加额外后缀。

## 发布与仓库处理

- 删除了带错误内容的旧 Release，并重新发布可用的 `v2.26`。
- 将最近几次 Git 提交信息统一改为中文。
- 更新了 GitHub Release 正文，按用户要求改为“与 2.16 相比”的中文差异说明，涵盖新增功能、功能改进与修复项。

## 验证

- [OK] `python -m py_compile "VideoWidget_mpv.py" "log.py" "DD监控室.py"`
- [OK] `cmd /c "scripts\build_win.bat x64"`
- [OK] 检查 `dist/DDMonitor/utils`，确认包含 `qdark.qss` 等运行时资源
- [OK] 检查 `dist/DDMonitor/utils`，确认不包含 `config*.json`
- [OK] 本地启动 `dist/DDMonitor/DDMonitor.exe`，确认程序可启动且不再出现 `mpv` 缺失、日志递归或资源缺失报错
- [OK] GitHub Actions `DDMonitor Release` 成功产出新的 `v2.26` Release

## 相关提交

- `e44778d` 修复启动崩溃并移除发布包中的私人配置
- `2f7214a` 修复发布包资源缺失并恢复 2.26 发布配置
- `96cc0f8` 修复发布工作流中的标签变量展开
- `7ce024c` 修复发布工作流中的 PowerShell 编码问题


### Git Commits

| Hash | Message |
|------|---------|
| `e44778d` | (see git log) |
| `2f7214a` | (see git log) |
| `96cc0f8` | (see git log) |
| `7ce024c` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 4: 原生弹幕方案调研 + UI轻量化与包体瘦身设计

**Date**: 2026-03-06
**Task**: 原生弹幕方案调研 + UI轻量化与包体瘦身设计

### Summary

调研 KikoPlay、mpv-kernel、bili-kernel，并产出原生弹幕、UI 轻量化与包体瘦身的设计稿和实施计划。

### Main Changes

﻿## 本次会话成果

- 调研并对比 `KikoPlay`、`mpv-kernel`、`bili-kernel`，确认后续方向应为“`libmpv` 播放核心 + 独立弹幕引擎 + B 站服务层抽离”，而不是继续强化 `ASS + sub-reload`。
- 梳理当前滚动弹幕闪烁、刷新感和不够原生的根因，明确旧方案保留为回退路径，新方案转向原生覆盖层弹幕引擎。
- 额外分析 UI 冷启动负担，确认 32 个播放窗预创建、弹幕文本窗即时创建、非关键对象提前初始化是当前主要启动成本来源。
- 额外分析 Windows 发布包体积，确认 `libmpv-2.dll` 是最大体积来源，同时识别出 Qt 冗余模块和 `utils/splash.psd` 等可优先清理项。

## 产出文档

- 新增 `docs/plans/2026-03-06-native-danmaku-ui-lightweight-design.md`
- 新增 `docs/plans/2026-03-06-native-danmaku-ui-lightweight-plan.md`

## 设计结论

- 原生弹幕：改造为独立弹幕引擎，支持总开关、类型开关、滚动弹幕自定义、预设和旧方案回退。
- UI 轻量化：优先做悬浮窗延迟创建、弹幕文本窗懒加载、非关键初始化后置和 `mpv` 预热延后。
- 包体瘦身：优先删除冗余资源、审查 Qt 收集结果，再单独评估 `libmpv` 专项瘦身。

## 后续建议

- 优先实现实施计划中的 Task 1、Task 2、Task 5、Task 11，先拿到“更轻、更快、更小”的可见收益，再进入新弹幕引擎改造。
- 本次为规划与研究会话，未运行自动化测试。


### Git Commits

(No commits - planning session)

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 5: 重构规划 v2：深度调查 + mpv弹幕方案 + bilibili-api融合规划

**Date**: 2026-03-06
**Task**: 重构规划 v2：深度调查 + mpv弹幕方案 + bilibili-api融合规划

### Summary

(Add summary)

### Main Changes

## 本次会话性质

纯规划与调查会话，无代码变更，无 git 提交。

## 工作内容

### 1. v1 规划全面审计

对 Session 4 产出的 v1 规划进行代码级事实验证，发现：

| 类型 | 发现 |
|------|------|
| 事实错误 | Task 5 称 mpv 实例未延迟，实际 `self._mpv = None` 已延迟 |
| 过度设计 | 预设 player/bili/danmaku/ 三个目录（YAGNI）、danmu_v2 配置结构（引擎不存在时就设计） |
| 遗漏 | 弹幕颜色链路断裂、进场消息完全缺失、单 Signal(str) 瓶颈、死代码残留 |

### 2. 启动流程深度调查

量化了启动时的对象创建规模：
- 32 个 VideoWidget、96 个 QTextBrowser、33 个 TextOpation、~98 个 QThread 实例
- MPV 实例和 ASS 临时文件已延迟（v1 规划的错误假设）
- import mpv 在模块级发生是唯一的 mpv 启动开销

### 3. mpv 弹幕渲染方案调查

对比 5 种方案（ASS sub-reload / osd-overlay / overlay-add / QPainter / QOpenGLWidget）：
- **推荐 osd-overlay**：无文件 I/O、无闪烁、无 Z 序问题、libass 原生文字品质
- 发现 python-mpv 1.0.8 的 `osd_overlay()` 有 typo bug（res_Y），需用 `command()` 绕过
- osd-overlay 不支持 `\move()` 动画，需 Python 端 ~30fps 定时器逐帧 `\pos()` 更新
- QPainter 方案因 mpv wid 原生窗口的 Z 序问题降为备选

### 4. bilibili-api-python 融合调查

逐项对比库 v17.4.1 与项目自行实现的功能：
- **迁移**：热榜（解决 WBI -352）、关注列表、直播流（去 Android hack）
- **新增**：Credential 统一凭据、Cookies 自动续期
- **不迁移**：弹幕 WebSocket（blivedm 够用）、批量查询（库无等价）、扫码登录 UI

### 5. 产出 v2 规划

更新 `docs/plans/2026-03-06-overhaul-v2-review-and-plan.md`，6 个 Phase、19 个 Task：
- Phase 0: 清理（死代码/VLC残留/打包修复）
- Phase 1: 启动优化（悬浮窗/TextBrowser/延迟初始化）
- Phase 2: 弹幕数据管线（结构化Signal/进场/颜色）
- Phase 3: osd-overlay 弹幕引擎（核心体验升级）
- Phase 4: 包体瘦身
- Phase 5: bilibili-api-python 融合

## 产出文档

- 更新 `docs/plans/2026-03-06-overhaul-v2-review-and-plan.md`（完整 v2 规划）


### Git Commits

(No commits - planning session)

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete
