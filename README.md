# FastSim — SECS/GEM 模拟与测试平台

半导体 EAP 工程师的 Host↔Equipment 模拟、联调与回归测试平台。目标：替代 WinSECS 2.7 + VB 脚本工作流，AI 原生（MCP）。

## 架构

```
浏览器 UI (原生JS) ─┐
MCP AI 客户端 ──────┼─→ FastAPI (REST + WebSocket) ─→ SessionManager ─→ EngineAdapter
REST/脚本 ──────────┘                                                    └→ 内置 asyncio SECS/GEM 引擎
                                                                          （可换 secsgem/.NET 引擎）
```

## 快速开始

```bash
# 1. 安装依赖（Python 3.11+）
pip install fastapi uvicorn pydantic pyyaml httpx

# 2. 启动后端（含前端 UI）
cd fastsim/backend
python -m fastsim.app --host 127.0.0.1 --port 8000

# 3. 浏览器打开 http://127.0.0.1:8000

# 4. AI 接入（可选，任一 MCP 客户端）
#    配置 MCP stdio server: python -m fastsim.mcp_server
#    （需 FastSim 后端已启动，可用 FASTSIM_API 环境变量指向其它地址）
```

## 功能

- **双端模拟**：设备端（Passive，供 MES 连入）/ 主机端（Active，连真实机台），一实例多会话
- **SECS/GEM 内核**：HSMS-SS（T3-T8/Linktest/事务匹配）、SECS-II 全 14 类型、SML 解析/格式化（兼容 WinSECS 方言）、E30 设备端处理器全集（S1/S2/S5/S6/S7/S9/S10）
- **行为引擎**：机台 Profile（YAML）声明 SVID/DV/EC/ALID/CEID/RPTID/远程命令与联动行为——零代码即可让机台"像真的"（命令→状态变化→事件上报）
- **可视化工作台**：运行总览（链路/报警/报文 KPI + 会话卡片）、五标签会话工作台、GEM 数据字典面板、双主题与响应式布局
- **消息收发**：SML 文本直发（W 位自动等应答）、标准消息库、实时 SML 着色日志
- **场景自动化**：YAML 步骤 DSL + 断言 + 跨会话编排，替代 VB 脚本，可进 Git
- **录制回放**：抓取会话帧存 JSONL，回放与黄金文件比对回归
- **REST + WebSocket**：供 CI/其他系统/AI 调用
- **MCP Server**：21 个工具（建会话/发消息/触发报警事件/查日志/跑场景…），ZCode/Claude/GLM 等直接操控

## 机台 Profile 示例

见 `backend/profiles/etcher-001.yaml`（与开发文档第六章对应）。

## 场景示例

```yaml
scenario:
  name: "remote-command-flow"
  steps:
    - action: subscribe
      ceid: 6003
      rptid: 7002
      svids: [2001, 2002, 1003]
    - action: remote_command
      rcmd: START
      params: { RECIPE: "R-DEMO-001" }
      expect_hcack: 0
    - action: wait_event
      event: collection_event
      timeout: 5
      where: { ceid: 6003 }
    - action: query_sv
      svids: [1002, 2001]
      expect: { 1002: RUNNING, 2001: R-DEMO-001 }
```

## 测试

```bash
cd fastsim/backend
python -m pytest tests/ -q        # 78 用例：引擎/SML/GEM 回环/场景/录制/API/WS/MCP
python -m fastsim.mcp_server --selftest
```

## 目录

```
fastsim/
├─ backend/
│  ├─ fastsim/
│  │  ├─ engine/builtin/   # SECS-II + SML + HSMS-SS + GEM 会话
│  │  ├─ core/             # Profile/SessionManager/场景/录制
│  │  ├─ api/              # REST + WS
│  │  └─ mcp_server/       # MCP stdio server
│  ├─ profiles/            # 机台 Profile（Git 管理）
│  ├─ scenarios/           # 场景库
│  └─ tests/               # pytest 套件
├─ frontend/               # 无构建原生 ES Module UI（css/tokens.css 设计变量）
└─ PROGRESS.md             # 迭代进度
```

## 许可

本项目自研代码 MIT。运行时可选依赖 secsgem（LGPL-2.1+，独立安装即合规）。
