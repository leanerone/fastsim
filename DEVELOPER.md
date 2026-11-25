# FastSim 开发者手册

> 面向后续 AI / 接手开发者的快速上手文档。读完本文件 + `PROGRESS.md` 即可开始迭代。

---

## 1. 5 分钟启动

```bash
# 环境要求：Python 3.11+，无 npm 构建步骤
pip install -r backend/requirements.txt

cd backend
python -m fastsim.app --host 127.0.0.1 --port 8000    # 启动（含前端）
# 或 run.bat / run.sh

# 打开 http://127.0.0.1:8000
# 首页点"创建双端演示" → 向导会同时生成 DEMO-EQ(PASSIVE) + DEMO-HOST(ACTIVE)

# 跑全量测试
cd backend
python -m pytest tests/ -q   # 80/80 当前基线

# MCP 自检
python -m fastsim.mcp_server --selftest
```

---

## 2. 项目结构

```
fastsim/
├─ backend/
│  ├─ fastsim/
│  │  ├─ app.py                 # FastAPI 入口，挂载 /api/v1 + /ws + 静态前端
│  │  ├─ api/routes.py          # 全部 REST + WebSocket 路由（单文件，约 250 行）
│  │  ├─ core/
│  │  │  ├─ manager.py          # SessionManager：会话生命周期 + 日志 + 事件总线
│  │  │  ├─ profile.py          # Profile YAML → Pydantic 模型
│  │  │  ├─ scenario.py         # 场景运行器（YAML DSL + 跨会话步骤）
│  │  │  └─ recording.py        # 录制/回放/黄金文件比对
│  │  ├─ engine/
│  │  │  ├─ adapter.py          # EngineAdapter 抽象基类（内置 secsgem 两种实现）
│  │  │  └─ builtin/
│  │  │     ├─ hsms.py          # HSMS-SS asyncio 实现（T3~T8，事务匹配）
│  │  │     ├─ secs2.py         # SECS-II 14 种类型编解码
│  │  │     ├─ sml.py           # SML 解析/格式化（兼容 WinSECS 方言）
│  │  │     └─ session.py       # GEM 会话：状态机 + S1~S10 处理器全集
│  │  └─ mcp_server/            # MCP stdio server（21 tools）
│  ├─ profiles/                 # 机台 Profile YAML（Git 管理）
│  ├─ scenarios/                # 场景 YAML
│  ├─ tests/                    # pytest 套件，7 个文件 80 用例
│  └─ requirements.txt
├─ frontend/                    # 无构建，浏览器直接 ESM
│  ├─ index.html                # 骨架，所有静态资源挂 /static/
│  ├─ css/tokens.css            # CSS 变量（双主题）
│  ├─ css/app.css               # 全局样式 + 响应式
│  └─ js/
│     ├─ app.js                 # 入口：Hash 路由 + 主题 + 顶栏
│     ├─ api.js                 # fetch API 封装（REST + WebSocket 连接管理）
│     ├─ ui.js                  # 工具：icon / toast / esc / smlHighlight / stateLabel
│     ├─ newsession.js          # 新建会话向导（3 场景 → 双端创建）
│     └─ views/
│        ├─ overview.js         # 首页：任务导向 + 会话列表
│        ├─ session.js          # 联调工作台：5 标签页
│        ├─ scenarios.js        # 场景中心
│        └─ profiles.js         # 机台配置编辑器
├─ PROGRESS.md                  # 迭代进度 + 里程碑
├─ README.md                    # 产品介绍 + 快速开始
└─ DEVELOPER.md                 # 本文件
```

**前端静态服务**：FastAPI 的 `StaticFiles` 挂载 `frontend/` 到 `/static/`，无热更新，改完刷新即可。

---

## 3. 后端关键约定

### 3.1 SessionManager 是单例

```python
from fastsim.core.manager import get_manager
manager = get_manager()
```

- `manager.create_session(profile, role, name, host, port, session_id, mode)` — 创建会话
  - `role="host"` → 自动 `mode="ACTIVE"`，其它 → `"PASSIVE"`（可显式传 `mode` 覆盖）
  - **这是修复后的语义**，旧版只改名称不改传输模式，会让主机端也监听端口
- `manager.get_logs(session_id, direction, sf, text, kind, tail)` — 日志查询
  - `kind="data"` 或 `kind="control"` 过滤，再 tail；业务 600 条 / 控制帧 100 条分别保留
- `manager.to_dict()` 暴露 `.mode`（PASSIVE / ACTIVE），前端据此显示连接方向

### 3.2 引擎可替换

`engine/adapter.py` 定义 `EngineAdapter`，内置实现是 `engine/builtin/`。secsgem 适配器是待办（见 PROGRESS.md #4）。**不要在业务代码里 import 内置引擎类**，一律走 `SessionManager → EngineAdapter`。

### 3.3 Profile YAML 示例

`backend/profiles/etcher-001.yaml`：

```yaml
connection:
  mode: PASSIVE        # 双端演示时 create_session 会覆盖为 ACTIVE
  port: 5000
equipment:
  model: ETCH300
  serial: FASTSIM-001
  device_id: 0
variables:        # SVID → 声明 + 可选 @PARAM 联动
constants:        # SV 常量
alarms:           # ALID 触发 → status + 事件
events:           # CEID/RPTID
commands:         # 远程命令 → 改变量/触发事件/报警
```

Profile 字段全集见 `core/profile.py` 的 Pydantic 模型。

### 3.4 日志 kind 分类

每条日志 dict 包含：
- `kind`: `"data"`（业务 S1~S10）/ `"control"`（HSMS Select/Deselect/Linktest/Separate）
- `dir`: `"in"` / `"out"`
- `sf`: `"S1F1"` / `"Linktest.req"` 等
- `ts`, `system_bytes`, `sml`, `body`

**心跳默认被 UI 隐藏但 API 仍返回**，导出也包含控制帧。

### 3.5 API 地图

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/v1/health` | 健康检查 |
| GET  | `/api/v1/overview` | 聚合：会话/报警/近一分钟报文/最近日志 |
| GET  | `/api/v1/sessions` | 全部会话 |
| POST | `/api/v1/sessions` | 创建（body: profile, role, name, port, mode） |
| GET/DELETE | `/api/v1/sessions/{id}` | 详情 / 删除 |
| POST | `/api/v1/sessions/{id}/send` | 发送 SML（W 位自动等应答） |
| POST | `/api/v1/sessions/{id}/remote-command` | GEM 远程命令 |
| POST | `/api/v1/sessions/{id}/alarms/{alid}/set` | 触发报警 |
| GET  | `/api/v1/sessions/{id}/logs?tail=&kind=&dir=&sf=&text=` | 日志查询 |
| GET  | `/api/v1/sessions/{id}/variables` | SV/DV 当前值 |
| WS   | `/ws/{id}` | 实时推送 log/state/event |
| GET  | `/api/v1/profiles/{name}/text` | Profile YAML 原文 |
| PUT  | `/api/v1/profiles/{name}` | 保存 Profile |
| GET  | `/api/v1/scenarios` / `/text` | 场景列表 / YAML 原文 |
| POST | `/api/v1/scenarios/{name}/run` | 运行场景 |
| POST | `/api/v1/record/{id}/start\|stop\|export` | 录制控制 |

全部在 `api/routes.py`，不分散。

### 3.6 WebSocket 推送帧

```json
{"type":"log","kind":"data","dir":"out","sf":"S1F1","ts":...,"sml":...}
{"type":"state","state":"COMMUNICATING"}
{"type":"event","ceid":...,"data":...}
{"type":"alarm","alid":...,"status":"set"}
```

---

## 4. 前端关键约定

### 4.1 路由（app.js）

Hash 路由，5 个视图：`overview` / `sessions` / `scenarios` / `profiles` / `docs`。每个 view 模块导出 `render(ctx)` → 返回 `{ cleanup?, refresh? }`。`ctx.navigate(...)` / `ctx.openNewSession(mode)` / `ctx.params` 由 app.js 注入。

### 4.2 状态持久化（localStorage）

| Key | 说明 |
|-----|------|
| `fastsim.activeSession` | 当前选中的会话 ID（刷新后自动恢复） |
| `fastsim.pairs` | 双端配对映射（`{"HOST":"DEMO-HOST","EQ":"DEMO-EQ"}`） |
| `fastsim-theme` | `"dark"` / `"light"` |

### 4.3 消息流过滤策略（session.js）

```js
// 默认只显示业务报文，控制帧被 showControl=false 过滤
const showControl = false;
const controlRows = logs.filter(l => l.kind === 'control');
// 实时 WS 推送同样受 showControl 过滤后再渲染
```

**核心理由**：每 30s 两条 Linktest 心跳，10 分钟就 40 帧，会完全淹没偶发业务报文。调试时再开"显示控制帧与心跳"。

### 4.4 向导三种场景（newsession.js）

| mode | 做了什么 |
|------|---------|
| `demo` | 先创 `${name}-EQ`（PASSIVE, role=equipment, 同端口）→ 再创 `${name}-HOST`（ACTIVE, role=host, 同端口） |
| `equipment` | 单会话，role=equipment, mode=PASSIVE，监听等 MES |
| `host` | 单会话，role=host, mode=ACTIVE，连指定 host:port |

创建失败会清理本次已创建的会话（已实现部分回滚）。

### 4.5 CSS 变量与主题切换

`css/tokens.css` 定义 `data-theme="dark"` 和 `"light"` 两套变量。主题入口点在 `app.js` 的 `initTheme()`，`#theme-toggle` 按钮。

### 4.6 前端不要做的事

- 不要 import 后端 Python 类（不可能，但别在 JS 里假设字段名——以 API 返回为准）
- 不要直接操作 DOM 以外的全局状态（走 fetch + WebSocket）
- 不要引 npm 包（当前约定原生无构建，如必须引入，先在 PROGRESS.md 登记决策）

---

## 5. Profile YAML 规范（backend/profiles/*.yaml）

最小可用 Profile：

```yaml
connection:
  mode: PASSIVE
  port: 5000          # 端口仅作默认，create_session 可覆盖
equipment:
  model: "ETCH300"
  serial: "SIM-001"
  device_id: 0
variables:
  - svid: 1002
    name: "EQUIPMENT_STATE"
    values: ["IDLE", "RUNNING", "ERROR"]
    initial: "IDLE"
    on_change:
      emit_event:
        ceid: 6003
        rptid: 7002
        svids: [1002]
commands:
  START:
    params: [RECIPE]
    set_variables: {1002: "RUNNING"}
    emit_event: {ceid: 6003}
    expect_hcack: 0
alarms:
  5001:
    text: "CHAMBER PRESSURE HIGH"
    ceid: 6001
    set_variables: {1002: "ERROR"}
```

字段全集 + 校验见 `core/profile.py` 的 Pydantic 模型。新字段 → 先加 Pydantic 模型 → 再补 `engine/builtin/session.py` 的 GEM 处理。

---

## 6. 测试指南

```bash
cd backend

# 全量
python -m pytest tests/ -q

# 带覆盖率（可选，需 pytest-cov）
python -m pytest tests/ --cov=fastsim --cov-report=term-missing

# 只跑某个文件
python -m pytest tests/test_api.py -q -k role_derives
```

**测试分类**：

| 文件 | 覆盖 |
|------|------|
| `test_secs2.py` | 14 种 SECS-II 类型编解码 |
| `test_sml.py` | SML 解析/格式化 + WinSECS 方言兼容 |
| `test_hsms.py` | HSMS-SS 握手、Select、Linktest、事务匹配 |
| `test_gem_loopback.py` | GEM 设备端/主机端回环（ACTIVE↔PASSIVE 真 TCP） |
| `test_profile.py` | YAML → Pydantic 校验 |
| `test_scenario_recording.py` | 场景 DSL + 录制回放 |
| `test_api.py` | REST + WS 全链路，含双端模式推导 + 日志分类过滤 |
| `test_mcp.py` | MCP 21 tools |

**写新测试的要点**：
- 跨会话双端用 `asyncio.start_server` + `SessionManager.create_session(..., mode=...)` 组合，不要依赖真实端口冲突
- 端口用 `socket.getaddrinfo(...)` 动态取空闲端口（`tests/conftest.py` 里已有 fixture）
- 双端测试等待 `state == "COMMUNICATING"`，**不要等 S1F13**——HSMS Select 先完成

---

## 7. 常见陷阱与避坑

| 陷阱 | 表现 | 正确做法 |
|------|------|---------|
| role 只改名称不改 ACTIVE/PASSIVE | 双端演示两个会话都监听同一端口 → bind 失败 | `mode` 参数显式传，或让 create_session 按 role 推导 |
| 心跳日志淹没业务 | UI 显示 40 条全是 Linktest | UI 默认 hide `kind=control`；tail 前先 `kind` 过滤 |
| T8 超时误杀长应答 | T3=45s, T8=5s → 正常慢应答被断链 | T8 是帧内字符间隔，不是帧间超时（已修复，见迭代#1） |
| Profile port 被误认为硬绑定 | 用户改 Profile port 但 create_session 传了不同端口 | `create_session` 的 port 参数优先，Profile 只作默认 |
| 前端假会话残留 | 刷新后看到已不存在的会话 | 监听 WebSocket `state` 帧，delete 后清 localStorage |

---

## 8. 下一步建议（待办清单，从 PROGRESS.md 同步）

1. secsgem EngineAdapter 第二实现 + 与真实 secsgem 对端互操作
2. S2F49 / S6F23 trace 骨架
3. PyInstaller 打包
4. Dockerfile
5. 移动端 <760px 真机验收（CSS 断点已齐，需手动拖窄浏览器）
6. VB→Python 迁移指南

---

## 9. 版本与提交

当前基线：**80 测试通过**，最近提交 `300f358`（迭代#3，产品化重构）。分支仅 `main`，直接 push。

Git 身份（已在仓库本地配置）：`leanerone <leanerone@users.noreply.github.com>`。如接手人使用不同账号，请执行：
```bash
git config user.name "你的名字"
git config user.email "你的邮箱"
```
