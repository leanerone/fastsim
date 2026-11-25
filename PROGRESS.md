# FastSim 开发进度

> 本文件由自动化迭代任务维护。每次迭代：读本文件 → 继续未完成任务 → 跑测试 → 更新本文件。
> 面向 AI 开发者的详细指引见 `DEVELOPER.md`。

## 项目状态总览

- **技术路线**：Python 3.11 + 自研 asyncio 内置引擎（EngineAdapter 可换 secsgem）+ FastAPI + 原生 JS 前端（无构建，ES Module + CSS 变量） + MCP Server
- **开发文档**：`DEVELOPER.md`（架构/约定/API/测试），`README.md`（快速开始）
- **最后更新**：2026-11-25（迭代#4 完成，87/87 测试通过）
- **Git 分支**：仅 `main`，直接 push（`d9d5e95 → 300f358` → 见下文）

## 已完成

| 模块 | 状态 | 说明 |
|------|------|------|
| SECS-II 编解码 | ✅ | 14 种类型全覆盖，JSON 双向，单测 12 个 |
| SML 解析/格式化 | ✅ | 兼容 WinSECS 方言（事务语法/方向标注/注释），单测 15 个 |
| HSMS-SS 协议 | ✅ | asyncio 双端，Select/Deselect/Linktest/Separate，T3/T5/T6/T7/T8，事务按 SystemBytes 匹配 |
| GEM 设备端 | ✅ | S1F1-F18/S2F13-F41/S5F1-F8/S6F11-F20/S7F1-F20/S9F5,F7/S10F1-F5；通讯+控制状态机 |
| GEM 主机端 | ✅ | 订阅(S2F33/35/37)/S2F41/S1F3/S7 上下载/S10F3/S5F1/S6F11 解析 |
| 行为引擎 | ✅ | Profile behavior 段：远程命令→改变量→触发事件→报警联动，@PARAM 参数引用 |
| Profile 加载 | ✅ | Pydantic 校验，int/str ID 规范化 |
| SessionManager | ✅ | 多会话 + 事件总线 + 日志环形缓冲 |
| REST API | ✅ | /api/v1 全套（sessions/logs/alarms/events/variables/scenario/record） |
| WebSocket | ✅ | /ws/{id} 实时日志/状态/事件推送 |
| 前端工作台 | ✅ | 任务导向首页（一键双端演示）/ 三场景向导 / 消息流重构（默认隐藏控制帧）/ 会话五标签 / 使用指南 / 原生 ES Module，双主题，960/760/480 响应式 |
| MCP Server | ✅ | stdio JSON-RPC 2.0，21 tools + 2 prompts，`python -m fastsim.mcp_server` |
| 场景运行器 | ✅ | YAML DSL + 断言 + 事件缓冲（防竞态）+ 跨会话步骤 |
| 录制回放 | ✅ | JSONL 录制/回放/黄金文件比对 |
| 测试 | ✅ | 8 个测试文件 87 用例（引擎/SML/GEM 回环/场景/录制/API/WS/MCP/UX 后端，覆盖角色推导+日志分类过滤+端口探测+连接问题+场景角色校验） |
| 易用性（迭代#4） | ✅ | 一键双端演示（自动选端口+自动验证）/ 连接问题中文化 / 命令效果闭环 / 应答解码 / 表单化消息构造 / 角色化 GEM 与消息库 / 场景角色匹配 |

## 与文档的偏差记录

1. **内置引擎优先于 secsgem**：文档推荐 secsgem 0.3.0 引擎；实际先用自研 asyncio 引擎（零线程桥接、规避 secsgem 已知瑕疵与 LGPL），EngineAdapter 接口保留，secsgem 已 pip 安装可做后续适配器。前端先用无构建原生 JS（Vue3 迁移列入 P2）。

## 待办（按优先级）

1. [x] 全量测试回归通过（80/80）
2. [x] PROGRESS/DEVELOPER/README 文档补齐
3. [x] 启动脚本 run.bat / run.sh + requirements.txt
4. [ ] secsgem 适配器（EngineAdapter 第二实现）+ 与 secsgem 对端互操作测试
5. [~] S9 系列完整化 ✅（S9F1 device-id 校验 / S9F3 未知流 / S9F5 / S9F7 / S9F9 T3 超时上报）；S2F49、S6F23 trace 骨架待做
6. [x] 前端细节：消息库点击自动填充参数模板（21 个标准消息带 body 模板）
7. [ ] PyInstaller 打包脚本（单机版）
8. [ ] Docker 部署文件（网站版）
9. [ ] VB→Python 迁移指南文档
10. [ ] 移动端窄屏（<760px）真机验收：当前 CSS 断点已补齐但依赖浏览器自动化视口缩放，需桌面浏览器手动拖窄验证

## 迭代记录

### 迭代 #4（2026-11-25）— 易用性重构：让用户 30 秒上手

目标：解决"画面与使用逻辑不友好"。以新用户视角实测全链路后，针对**静默失败、术语轰炸、反馈断链**三类问题做了五个阶段的改造。

- 🚀 **一键双端演示**（`newsession.js` express 流程）：首页主按钮一次点击完成"选空闲端口 → 建设备端 → 建主机端 → 建立通信 → 自动 S1F1 验证"，全程进度时间线可见，成功即落地工作台。端口被占自动避让（实测 5000 被占 → 自动用 5001）。
- 🔌 **连接问题不再静默**：引擎 `listen_failed`/`connect_retry`/`t7_timeout` 等事件原先在 `session.py:_on_hsms_event` 被丢弃，现转发为 `issue` 事件（含中文 message + hint + code，如 `PORT_IN_USE`）。`SessionWrapper.issue` 随 `to_dict`/overview 暴露，首页卡片与工作台引导条直接显示原因与解决办法。
- 🧭 **端口预检**：新增 `GET /ports/free`、`GET /ports/check`（`core/ports.py`，镜像 asyncio 的 bind 选项）。高级向导实时显示"端口可用/被占用 + 自动选择空闲端口"，连接预览随名称/端口输入实时联动（修复旧版静态预览）。
- 🔁 **命令效果闭环**：引擎新增 `variables_changed` 事件（远程命令行为 / S2F15 / API 设值均触发）。主机端 GEM 面板发送远程命令后自动 S1F3 复查设备状态，效果卡片高亮"PROCESS_STATE: IDLE → RUNNING"并列出上报事件；设备端变量字典实时刷新 + 闪烁，"实时动态"面板显示收到的命令/报警/事件。
- 🧩 **角色化 GEM 与消息库**：主机端 GEM 改为"远程命令 / 设备状态(S1F3 查询) / 事件订阅 / 报警与上下线 / 实时动态"；设备端保留"报警 / 事件 / 可编辑变量字典 / 控制状态"。消息库按角色过滤（主机发请求、设备发上报），移除主机库里的应答类与 S9F1。
- 📝 **表单化消息构造 + 应答解码**：S1F3/S2F13/S2F15/S2F41/S5F3/S6F15 提供参数表单（变量勾选、命令下拉、参数字段），自动生成 SML；应答按 `reply.data` 结构化解读（HCACK/COMMACK/EAC/变量名映射），原始 SML 折叠为专家视图。`send_sml` 应答新增 `data` 字段。
- 🎯 **场景角色匹配**：场景 YAML 新增 `role` 元数据，`GET /scenarios/manifest` 返回角色/描述/中文步骤摘要。场景卡片按角色过滤会话下拉框（修复"主机场景默认跑在设备端 → hcack=None"），失败报告显示原因+建议+期望/实际。运行器对角色不符直接返回 `ROLE_MISMATCH`。
- 🈶 **错误中文化 + 术语分层**：`core/errors.py` 统一把异常翻译为中文 message+hint（REST 422 返回 `{code,message,hint,raw}`）；状态 chip 改白话（"链路已建立/通信中"），协议术语移入 tooltip。
- 🐛 **修复 YAML 1.1 陷阱**：PyYAML 把 `on:` 键解析为布尔 `True`，导致 alarm-flow 的"清除报警"步骤一直在重复触发；`_on_flag` 兼容两种键拼写。
- 🛡️ **其它**：危险按钮"断开重启"改名"重启链路"并加确认；WS 重连指数退避；首页改全局 WS 实时刷新 + 真实进度判定（`verified` 按用户 W 主消息而非控制帧）；文档与新行为对齐。
- ✅ **新增回归**：`tests/test_ux_backend.py` 7 用例（端口探测/占用问题上报/未连接友好错误/应答 data+variables_changed/场景清单+角色不符/失败 hint/步骤摘要）。测试 80 → 87。

### 迭代 #3（2026-11-25）— 产品化重构，Git 提交 `300f358`
- 🎯 **首页从仪表盘改为任务向导**：首屏"创建双端演示"主按钮，三步进度（创建 → 通信 → S1F1 验证），自动保存配对到 `localStorage["fastsim.pairs"]`
- 🧭 **新建向导三场景**：`demo`（一次生成 `${name}-EQ` PASSIVE + `${name}-HOST` ACTIVE）/ `equipment`（PASSIVE 等 MES 连入）/ `host`（ACTIVE 连真实设备），向导自动推导 HSMS 模式，不需要用户懂 ACTIVE/PASSIVE
- 🔧 **后端自动模式推导**：`SessionManager.create_session(role, mode=None)` 新增 `mode` 参数，`role="host"` → ACTIVE，其它 → PASSIVE；API 透传。修复了旧版"role=host 但仍按 Profile 被动监听"的经典坑
- 📨 **消息流重构**：默认隐藏 `kind=="control"` 的 HSMS 控制帧与 Linktest（每 30s 两条心跳会淹没业务报文），保留"显示控制帧与心跳"开关；每条展示时间/方向/SxFy/中文含义/摘要，可展开原始 SML + SystemBytes；业务与控制帧分别保留（600/100），避免心跳挤出历史
- 📚 **新增使用指南页**：`#/docs` — 双端演示三步、真实双向接入（MES 验证 / 连真实设备）、消息方向、控制帧、连接排查顺序、REST/WS/MCP 与启动命令
- 🎨 **前端响应式收尾**：960/760/480px 三断点补齐，修正旧 `.feed-item` 三列覆盖新版五列的冲突；底部环形缓冲提示改为"业务 600 条 · 控制帧 100 条"
- ✅ **新增回归用例**：`test_role_derives_transport_mode_for_builtin_pair`（同一 etcher-001.yaml 同时创建 PASSIVE 设备端和 ACTIVE 主机端，等待 COMMUNICATING）、`test_log_kind_filter_applies_before_tail`（日志分类过滤应先于 tail 截断）。测试 78 → 80

### 迭代 #2（2026-11-20 11:40）
- 🎨 **前端整体重构为可交付工作台**：侧边导航 + 顶栏 + 运行总览（4 项 KPI、会话卡片、跨会话最近报文）、会话工作台五标签（实时日志 / 报文收发 / GEM / 连接参数 / 录制回放）、场景中心（步骤预览 + 结构化执行报告）、机台 Profile 双栏编辑器（原文 YAML 校验/保存）
- 🧩 **前端架构拆分**：`frontend/js/` 按 api / ui / newsession / views 分模块，原生 ES Module 无构建；`tokens.css` + `app.css` 建立设计变量、深色/浅色主题与响应式断点
- ⚙️ **后端补充聚合接口**：`GET /overview`（总量、活动报警、近一分钟报文、跨会话最近日志）、`GET /profiles/{name}/text`、`GET /scenarios/{name}/text`，避免前端 N+1 请求
- 🐛 修复 `tests/` 缺少包初始化导致的用例收集失败；新增新接口回归用例
- 测试：77 → 78

### 迭代 #1（2026-11-20 01:05）
- 🔴 **修复重大协议 bug：T8 超时误杀长应答连接**。原实现把 T8 用作"整帧头读取超时"，导致 T3(45s) > T8(5s) 的正常慢应答场景必然断链（真实 MES 对接必踩）。按 SEMI E37 语义修正：T8 仅作帧内字符间隔超时，帧间空闲由 Linktest+T6 保活探测。
- ✅ S9 系列完整化：S9F1（device_id 不匹配）、S9F3（未知流，S9F5 只用于已知流的未知功能）、S9F9（T3 超时后主动上报对端，携带原始报文头）
- ✅ run.sh（Linux/Git Bash 启动脚本）
- ✅ 前端消息库 21 条标准消息点击自动填充完整 SML 模板（含 body）
- 测试：74 → 77（新增 S9F1/S9F3/S9F9 三个回环用例）

## 已知问题

- （无阻塞问题；历史修复记录见 git log）
