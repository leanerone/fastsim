# FastSim 开发进度

> 本文件由自动化迭代任务维护。每次迭代：读本文件 → 继续未完成任务 → 跑测试 → 更新本文件。

## 项目状态总览

- **技术路线**：Python 3.11 + 自研 asyncio 内置引擎（EngineAdapter 可换 secsgem）+ FastAPI + 原生 JS 前端 + MCP Server
- **开发文档**：`../FastSim开发方案与技术路线.md`
- **最后更新**：2026-11-20 01:05（迭代#1 完成，77/77 测试通过）

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
| 前端 MVP | ✅ | 仪表盘/会话详情/SML 收发/实时日志/GEM 面板/场景/Profile 编辑（无构建依赖） |
| MCP Server | ✅ | stdio JSON-RPC 2.0，21 tools + 2 prompts，`python -m fastsim.mcp_server` |
| 场景运行器 | ✅ | YAML DSL + 断言 + 事件缓冲（防竞态）+ 跨会话步骤 |
| 录制回放 | ✅ | JSONL 录制/回放/黄金文件比对 |
| 测试 | ✅ | 6 个测试文件 60+ 用例（引擎/SML/GEM 回环/场景/录制/API/WS/MCP） |

## 与文档的偏差记录

1. **内置引擎优先于 secsgem**：文档推荐 secsgem 0.3.0 引擎；实际先用自研 asyncio 引擎（零线程桥接、规避 secsgem 已知瑕疵与 LGPL），EngineAdapter 接口保留，secsgem 已 pip 安装可做后续适配器。前端先用无构建原生 JS（Vue3 迁移列入 P2）。

## 待办（按优先级）

1. [x] 全量测试回归通过（77/77）
2. [x] PROGRESS/README/docs 完成
3. [x] 启动脚本 run.bat / run.sh + requirements.txt
4. [ ] secsgem 适配器（EngineAdapter 第二实现）+ 与 secsgem 对端互操作测试
5. [~] S9 系列完整化 ✅（S9F1 device-id 校验 / S9F3 未知流 / S9F5 / S9F7 / S9F9 T3 超时上报）；S2F49、S6F23 trace 骨架待做
6. [x] 前端细节：消息库点击自动填充参数模板（21 个标准消息带 body 模板）
7. [ ] PyInstaller 打包脚本（单机版）
8. [ ] Docker 部署文件（网站版）
9. [ ] VB→Python 迁移指南文档

## 迭代记录

### 迭代 #1（2026-11-20 01:05）
- 🔴 **修复重大协议 bug：T8 超时误杀长应答连接**。原实现把 T8 用作"整帧头读取超时"，导致 T3(45s) > T8(5s) 的正常慢应答场景必然断链（真实 MES 对接必踩）。按 SEMI E37 语义修正：T8 仅作帧内字符间隔超时，帧间空闲由 Linktest+T6 保活探测。
- ✅ S9 系列完整化：S9F1（device_id 不匹配）、S9F3（未知流，S9F5 只用于已知流的未知功能）、S9F9（T3 超时后主动上报对端，携带原始报文头）
- ✅ run.sh（Linux/Git Bash 启动脚本）
- ✅ 前端消息库 21 条标准消息点击自动填充完整 SML 模板（含 body）
- 测试：74 → 77（新增 S9F1/S9F3/S9F9 三个回环用例）

## 已知问题

- （无阻塞问题；历史修复记录见 git log）
