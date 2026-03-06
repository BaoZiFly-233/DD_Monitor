## 根因分析

本次会话先按系统化排障流程复现了“启动软件，加载后就崩”的问题，最终在日志中定位到真实炸点：

- `AddLiverRoomWidget` 初始化时把 `GetFollows.roomInfoChunk` 连接到了不存在的 `collectFollowLiverChunk`。
- 因为这个连接发生在主窗口构造阶段，所以程序会在 UI 尚未完全进入可用状态前直接抛出 `AttributeError` 并退出。
- 这不是播放器或弹幕导致的崩溃，而是上一次“当前列表流式加载”改造存在半截落盘：信号接好了，但对应槽函数、关注表刷新逻辑、`tabWidget` 变量替换和凭据透传没有完整收尾。

## 主要修改

- `LiverSelect.py`
  - 补回 `GetHotLiver.areaLoaded -> collectHotLiverChunk` 的连接，恢复热门列表增量更新链路。
  - 补回 `collectFollowLiverChunk()`，让关注列表支持按块接收数据。
  - 新增 `_fillFollowTable()`，统一关注列表的全量/增量渲染逻辑。
  - 将“只对当前正在看的列表生效”的约束落实到 tab 切换逻辑：只有当前页可见时才即时刷新表格。
  - 查询关注前先清空 `followRoomInfo` 和 `followLiverList`，避免旧数据与新请求混杂。
  - 补回 `AddLiverRoomWidget.setCredential()`，并在 `setSessionData()`、`checkFollows()` 中同步把 credential 传给 `GetFollows` / `GetHotLiver`。
  - 修正 `tab.addTab(...)` 为 `self.tabWidget.addTab(...)`，避免后续再次因未定义变量崩溃。
  - 在关闭添加直播间窗口时同时等待 `getFollows` 线程，降低窗口关闭后残留信号回调风险。

## 验证

- [OK] 复现启动崩溃，并从 `logs/log-2026-03-06.txt` 抓到未捕获异常：`AttributeError: 'AddLiverRoomWidget' object has no attribute 'collectFollowLiverChunk'`
- [OK] `python -m py_compile "LiverSelect.py" "VideoWidget_mpv.py" "DD监控室.py"`
- [OK] 启动 `python "DD监控室.py"` 两次，均能持续运行到超时结束，日志中不再出现 `UNCAUGHT EXCEPTION`、`AttributeError`、`NameError`
- [OK] 日志确认程序可进入 UI 完成和登录后自动拉取关注列表阶段

## Review 结论

- 这次崩溃的直接根因是“跨层流式改动只完成了一半”，属于典型的信号槽和 UI 刷新路径未闭环。
- 当前实现已经满足“仅当前可见列表流式刷新”的功能要求，但关注列表仍采用“每来一批就整表排序重绘”的方式，功能正确，性能和观感还有继续优化空间。
- `GetHotLiver` / `GetFollows` 仍基于 `QThread.run()` 自管流程，`quit()` 不能立刻打断进行中的网络请求；这不是本次崩溃点，但仍是后续可继续收敛的稳定性风险。
