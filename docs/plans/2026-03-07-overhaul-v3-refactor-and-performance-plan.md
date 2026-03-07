# DD监控室 Overhaul V3 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 一次性收敛弹幕观感、渲染性能、列表稳定性与关键已知 Bug，交付可长期维护的 v3 主干。

**Architecture:** 采用“接收层（remote）-调度布局层（renderer/layout）-播放器呈现层（mpv_gl_widget/VideoWidget）-业务数据层（LiverSelect/login）”四层收口。以本地参考仓库调研结果驱动重构边界，优先做低风险高收益优化，再做结构化重构与行为一致性修复。

**Tech Stack:** Python 3.x, PySide6, python-mpv, blivedm, bilibili-api-python, requests(session pool)

---

## 0. 重新调查三个目标仓库（结论）

### 目标仓库 A: KikoPlay（`.tmp-reference/KikoPlay`）

- 关键可迁移点：
  - `CacheWorker` 独立线程构建弹幕位图和纹理，主渲染线程只合成。
  - 三布局分离（滚动/顶部/底部）+ subtitle protect + display area。
  - LRU 缓存与纹理引用计数，显式清理过期纹理。
- 不迁移点：
  - 直接照搬 C++ OpenGL 纹理图集实现（当前 Python 版本维护成本过高）。

### 目标仓库 B: AkDanmaku（`.tmp-reference/AkDanmaku`）

- 关键可迁移点：
  - `Data -> Layout -> Render` 三阶段明确职责。
  - `DanmakuConfig` generation 机制：布局/缓存/测量/过滤增量失效。
  - `DrawingCachePool` 内存上限池化思路 + data/layout filter 分离。
- 不迁移点：
  - Android/libGDX/ECS 具体工程实现。

### 目标仓库 C: DanmakuFlameMaster（`.tmp-reference/DanmakuFlameMaster`）

- 关键可迁移点：
  - `CacheManagingDrawTask` 的“绘制线程 + 缓存线程”双节奏模型。
  - Retainer（顶部/底部/滚动）碰撞与占位策略分治。
  - 同屏数量控制、重叠策略、配置实时生效。
- 不迁移点：
  - Android Surface/TextureView 和 ndkbitmap 细节。

## 1. 当前仓库代码 Review（v3 输入清单）

### P0 / 立即修复

1. `LiverSelect.py:1491` 键类型不一致  
   `self.roomIDDict[int(info[0])] = info[1]` 与其余流程的字符串房号键混用，可能导致重复卡片、置顶状态错乱、刷新漏更新。

2. `VideoWidget_mpv.py:143-147` 直播流 URL 组装缺少强校验  
   `host/base/extra` 组合后可产生非法 URL，已在日志出现 `Invalid URL ''`。

3. 列表/封面即时刷新链路仍存在竞争窗口  
   当前删除与新增后已做 refresh 请求，但缺少统一“数据源变化 -> UI 原子重排”收口点。

### P1 / 本轮应修

1. `LiverSelect.py:376`, `VideoWidget_mpv.py:998`, `LiverSelect.py:700` 仍有 `exec_` 旧 API。
2. `LiverSelect.py` 多处 `except: pass` 静默吞错，排障困难。
3. `blivedm/handlers.py:147` unknown cmd 警告噪声仍偏高（命令类型持续变化时仍刷屏）。

### P2 / 性能持续优化

1. `danmaku_renderer.py` 每帧对所有弹幕做 sprite 字典查找与绘制，可进一步减少查找开销。
2. `mpv_gl_widget.py` 当前 16ms tick 已较好，但缺少按负载自适应降帧（低端机高窗口数仍可能抖动）。
3. `LiverSelect.py` 刷新线程存在固定 sleep 节拍，峰值刷新仍偏保守。

## 2. v3 目标与验收

### 用户体验目标

- 滚动/顶部/底部弹幕观感接近原生：位置、速度、遮挡、留白一致。
- 多窗口（16/32）场景 CPU 与 UI 卡顿显著下降。
- 列表新增/删除/状态变化无需手动刷新即可稳定更新。

### 稳定性目标

- 无 `Invalid URL ''`、无短号解析 `KeyError: 'data'` 类崩溃。
- `-352` 场景自动降级可持续工作。
- 日志噪声可控，关键异常可追踪。

### 定量验收（建议）

- 16 窗口播放 + 弹幕开启，主线程平均帧间隔抖动下降 20%+。
- 热门/关注列表首屏加载时间下降 20%+（同网络条件）。
- 新增/删除卡片后 UI 刷新可见延迟 < 1s。

## 3. 分阶段执行（一次性收尾）

### Phase 1: 数据与配置一致性收口（P0）

**Files:**
- Modify: `LiverSelect.py`
- Test: `tests/manual_danmaku_layout_check.md`（补充列表刷新检查项）

**Tasks:**
1. 统一 `roomIDDict` 键类型为 `str`，修复置顶变更路径。
2. 新增 room id 规范化函数（仅一处入口），替换散落转换。
3. 把新增/删除/置顶变更后的 refresh 触发合并到一个原子函数。
4. 针对短号解析与 batch 接口 fallback 增加结构化错误日志字段（room_id/api/code）。

### Phase 2: 流地址与封面拉取健壮化（P0）

**Files:**
- Modify: `VideoWidget_mpv.py`
- Modify: `LiverSelect.py`

**Tasks:**
1. 为 stream URL 组装增加 `http/https` 前缀与空值校验，非法候选直接丢弃。
2. 引入“候选 URL 质量排序 + 首个可用回退”策略，减少空 URL 触发。
3. 封面/头像下载线程统一空 URL 早返回与失败限频日志。
4. 为封面刷新补“状态没变但 keyframe 变化”刷新条件，避免卡旧图。

### Phase 3: 弹幕渲染性能与观感提升（P1）

**Files:**
- Modify: `danmaku_renderer.py`
- Modify: `danmaku_layout.py`
- Modify: `mpv_gl_widget.py`
- Modify: `VideoWidget_mpv.py`
- Modify: `danmu.py`

**Tasks:**
1. `ActiveDanmaku` 持有 sprite 直引或缓存句柄，减少每帧哈希查找。
2. 增加“可见区域裁剪后绘制”与“超界快速跳过”。
3. 引入自适应 tick（16/24/33ms）策略：按活动弹幕数与窗口数降载。
4. 完成顶部/底部安全区参数化（保留默认开启），并暴露最小可调项。
5. 统一滚动/顶部/底部生命周期统计，输出渲染调试指标（drop/active/paint_ms）。

### Phase 4: 列表线程与请求节奏优化（P1）

**Files:**
- Modify: `LiverSelect.py`
- Modify: `http_utils.py`

**Tasks:**
1. 将固定 sleep 轮询改为可中断等待 + 抖动退避策略。
2. 批量请求失败时分片回退，避免全量逐个请求造成卡顿。
3. 给 `http_utils` 增加可选重试策略（仅幂等 GET），集中控制超时与重试。
4. 为热门/关注加载补充成功率与耗时日志，便于后续调参。

### Phase 5: 日志治理与兼容性修复（P1）

**Files:**
- Modify: `blivedm/handlers.py`
- Modify: `LiverSelect.py`
- Modify: `VideoWidget_mpv.py`
- Modify: `DD监控室.py`

**Tasks:**
1. unknown cmd 日志改为“按 cmd + 时间窗口限流”，默认 warning -> info。
2. 将 UI 菜单相关 `exec_` 全量替换为 `exec`。
3. 清理高频 `except: pass`，替换为分级日志与可定位上下文。
4. 对历史兼容路径（旧配置字段）补集中迁移函数，避免散点兼容。

### Phase 6: 全仓回归与发布准备（P0 Gate）

**Files:**
- Modify: `README.md`（如行为有变更）
- Add: `docs/plans/2026-03-07-overhaul-v3-test-matrix.md`

**Tasks:**
1. 语法编译回归：核心文件全量 `py_compile`。
2. 手工场景回归：16/32 窗口、登录态/游客态、热门/关注、增删卡片、弹幕三模式。
3. 性能基准采样：记录 CPU 占用、刷新耗时、渲染掉帧指标。
4. 发布说明草案：列出修复点、兼容说明、已知限制。

## 4. 关键设计约束（DRY/KISS/YAGNI）

- DRY：所有 room_id 解析、URL 校验、刷新触发必须单点实现。
- KISS：不在 v3 引入重型 OpenGL 纹理图集新子系统，先在现架构内拿稳定收益。
- YAGNI：不提前实现跨平台渲染后端抽象层，仅聚焦当前 PySide6 + mpv 链路。

## 5. 风险与回退

- 风险 1：渲染节奏调优可能影响弹幕平滑度。  
  回退：保留固定 16ms 模式开关。

- 风险 2：列表线程节奏调整影响实时性。  
  回退：保留旧轮询参数作为隐藏兼容项。

- 风险 3：日志降噪后误伤关键告警。  
  回退：提供 `DEBUG_VERBOSE_WS` 开关恢复详细输出。

## 6. 执行顺序建议（一次性完成）

1. 先做 Phase 1 + Phase 2（先止血）。
2. 再做 Phase 3（弹幕观感/性能主收益）。
3. 接着 Phase 4 + Phase 5（稳定性与可维护性）。
4. 最后 Phase 6（完整验证与文档收尾）。

## 7. 本计划对应当前“默认开启”策略

- 顶部弹幕：默认开启（保持）。
- 底部弹幕：默认开启（保持）。
- 若性能压力过高，仅在运行时降帧，不默认关闭顶部/底部。

