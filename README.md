# project5 —— 全栈 AI 知识库（React 版）

临摹重构 `LangGraph-RAG-Agent-main`：上传私有文档 → RAG/Agent 问答的完整产品。React 前端 + FastAPI 后端 + LangGraph Agent + 本地向量库，Docker Compose 一键部署。

---

## 一、项目介绍

面向个人的私有知识库问答系统：注册登录后，向会话上传文档，Agent 基于文档内容（而非全网）回答提问；问题超出文档范围时自动联网搜索。聊天带多轮记忆，流式输出。

核心亮点：**用户系统 / 文档管理 / 会话隔离** 三大模块全部打通，每个用户的文档与会话都做了归属隔离。

## 二、功能展示

| 功能 | 说明 |
|---|---|
| 用户注册/登录 | 前端卡片支持「注册/登录」切换（注册成功自动登录）；JWT 鉴权，密码 bcrypt 哈希（`/api/v1/auth/*`） |
| 会话管理 | 新建会话拿到 thread_id，按用户隔离（`/api/v1/threads`） |
| 文档管理 | 上传（后台异步处理，立即返回 202）/ 列表 / 删除；支持 .docx/.pdf/.txt |
| RAG 问答 | Agent 检索上传文档 → 基于片段生成回答，流式返回（NDJSON 打字机） |
| 联网搜索 | 检索不到时自动调用 BoCha 搜索补充 |
| 多轮记忆 | LangGraph checkpointer 存会话历史 |
| 可观测性 | 可选接入 Langfuse 面板，追踪 Agent 每次运行的 trace（技术雷达 Demo） |

## 三、技术架构

```
React 前端 (5173 / Nginx)
   │  /api/v1/*  (JWT)
   ▼
FastAPI 后端 (8001)
   ├─ users/threads/documents        资源模块
   ├─ chat  → LangGraph ReAct Agent
   │            ├─ LLM: DeepSeek(OpenAI兼容协议)
   │            ├─ tools: 文档检索(retrieve_user_documents) + 联网搜索(web_search)
   │            └─ checkpointer: SQLite 多轮记忆
   ├─ db: PostgreSQL(主库) + Chroma(向量库)
   └─ Langfuse(可选): 回调上报 trace → 面板 8080
```

## 四、技术选型

| 层 | 选型 | 说明 |
|---|---|---|
| 后端 | FastAPI + SQLAlchemy(async) | 异步全栈，自动文档 |
| Agent | LangGraph `create_agent` | ReAct：推理 + 工具调用循环 |
| LLM | DeepSeek(v4-flash) | OpenAI 兼容协议，ChatOpenAI 接入 |
| Embedding | bge-small-zh-v1.5 | 本地模型，中文效果好、免费无 key |
| 向量库 | Chroma | 文档切片向量检索 |
| 主库 | PostgreSQL 16 | 用户/会话/文档表单据 |
| 记忆 | AsyncSqliteSaver | LangGraph 检查点，本地 .sqlite |
| 搜索工具 | BoCha（博查） | 联网补全 |
| 前端 | React 19 + Vite | 流式渲染、Markdown+代码高亮 |
| 鉴权 | JWT(pyjwt) + bcrypt | FastAPI 依赖注入 |
| 观测 | Langfuse（自托管） | 技术雷达 Demo，可选 |
| 部署 | Docker Compose | backend+frontend+postgres 三条服务 |

## 五、项目截图

> TODO: 待补（问答页截图 + Langfuse trace 图）

## 六、部署方式

前置条件：Docker Desktop；项目根 `.env` 配 `DEEPSEEK_API_KEY` / `BOCHA_API_KEY`（见 `.env.example`）。

```bash
docker compose up -d --build    # 后端起 8001，前端起 5173，Postgres 起 5434（避开 project6 的 5432）
```

| 服务 | 对外端口 | 容器内 | 说明 |
|---|---|---|---|
| backend | 8001 | 8000 | FastAPI + Agent + Chroma |
| frontend | 5173 | 80 | React 静态站（Nginx 反代 /api） |
| postgres | 5434 | 5432 | 主数据库（宿主机 5434，避开 project6 的 5432） |

**Windows 一键启动（日常用这个）**：双击项目根目录的 `启动.bat` —— 自动拉起 Docker、启动全部服务（含面板）、就绪后自动打开浏览器；已在运行时会秒过。

**本地开发**（不用 Docker）：

```bash
# 后端（backend/ 目录；用项目根统一 venv；8001 对齐 vite 代理）
..\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8001
# 前端（frontend/react-app/ 目录）
npm install && npm run dev     # http://localhost:5173
```

**可选：Langfuse 可观测性面板**

```bash
docker compose -f docker-compose.langfuse.yml up -d   # 面板 http://localhost:8080
```

数据安全：Chroma / SQLite / 上传文档在 `./outputs`（挂载卷，容器删除不丢）；embedding 模型缓存走命名卷；密钥只经环境变量透传，不写入镜像。

## 七、遇到的问题（排坑记录）

| 问题 | 根因 | 解决 |
|---|---|---|
| 后端启动 Connection refused | config 连接串写死 `localhost`，容器内指不到 postgres | 加 `database_host` 配置项，compose 注入服务名 `postgres` |
| docker compose 起不来（Exited 255） | 本机 5432 被 project6 的 pgvector 占用，postgres 一映射就冲突；config 里端口还写死 | 映射改 `5434:5432`，`config.py` 抽 `database_port`（裸机 .env=5434 / 容器内注入 5432），两项目可同跑 |
| Dockerfile COPY nginx.conf 失败 | COPY 行尾中文注释触发 buildkit 解析异常 | 注释移到文件头部，指令行保持纯 ASCII |
| 前端构建失败 `react-markdown` 解析错误 | package.json 漏声明依赖 | 补装 `react-markdown` + `rehype-highlight` |
| Langfuse SDK 4.x 上报 404 | 新 SDK 走 OTLP，v2 服务器不认 | 降级 SDK 2.55.0 + 自写回调 handler |
| **回答一次性蹦出，没有打字机** | `build_retrieval_graph` 调 `create_model()` 时漏传 `streaming`（默认 `False`），而 langchain-core 对"显式传 False"是**硬禁用**流式，一个 token 回调都没有 | 显式传 `streaming=True`（`chat/langgraph_agent.py`） |
| **传了 `streaming=True` 仍不逐字** | langgraph 1.2.11 的 `create_agent` 把 model 节点标了 `trace=False`，token 事件不会变成 `stream_mode="messages"` 事件 —— 150 字的回答只收到 1 个 chunk | 不再依赖 messages 模式：新增 `TokenPump` 回调把 token 泵进队列，与 `updates` 流合并（`chat/service.py`）。实测 1 → 138 个分片、网络层 1.6s 铺开，NDJSON 协议不变、前端零改动 |
| **前端只有登录卡片，没有注册入口** | 前端一直没做注册 UI（后端 `/auth/register` 可用），新用户无法从界面进入 | 登录卡片加「注册/登录」切换：注册成功自动登录；409 透传后端文案、422 给表单规则提示（`App.jsx`） |
| **部署后普通刷新还是旧页面** | `index.html` 无缓存头 → 浏览器启发式缓存，仍加载旧 bundle（旧条目连请求都不发） | nginx：`index.html` 加 `no-cache`、带 hash 的 `/assets/` 长缓存（`nginx.conf`）；已缓存的旧条目强刷一次即完成过渡 |
| **登录后找不到退出/登录入口** | 前端没有退出按钮；localStorage 有 token 就直接渲染主界面（不校验有效性、没有出口），残留旧 token 会把用户"困"在空主界面 | 侧边栏加「退出登录」（回登录形态卡片）；`fetchThreads` 收 401 自动清 token 回登录卡片（`App.jsx` / `ThreadList.jsx`） |
| **一键启动脚本双击报"不是内部或外部命令"** | cmd 解析 .bat 用系统 ANSI 码页（中文 Windows=GBK），且只认 CRLF 行尾；UTF-8 + LF 的中文脚本会被错行拆解 | `启动.bat` 存为 GBK + CRLF；在 VSCode 里显示乱码属正常现象，不影响双击运行 |

## 八、RAG 评估（工程化）

评估体系在 `backend/eval/`，两套指标 + 一套测试集，量化回答质量：

```
backend/eval/
├── test_set.json         测试集 10 问：含陷阱题 / 无答案题 / 跨片段题
├── retrieval_eval.py     检索评估：Recall@k / MRR
└── generation_eval.py    生成评估：LLM-as-Judge（正确性 / 忠实度）
```

**当前基线（测试文档 bluewhale42_full.txt，k=3）：**

| 指标 | 值 | 说明 |
|---|---|---|
| Recall@3 | 0.90 | 无答案题正确"不命中"，其余 9/9 命中 |
| MRR | 0.70 | 4 题正确答案排 rank=2 → 排序有优化空间（Rerank） |
| 平均正确性 | 5.0 / 5 | 回答与期望答案一致 |
| 平均忠实度 | 4.7 / 5 | 无幻觉；#3 的 2 分经抽查为 Judge 误判 |

**评估中发现的问题（也是后续方向）：**
- LLM-as-Judge 会误判 → 打分后需人工抽查校准（评估工程通用坑）
- MRR 0.70 → 向量检索排序不足，下一步上 Rerank（cross-encoder 精排，见 backend/rerank_demo.py）

## API 概览

- `POST /api/v1/auth/register` —— 注册（username + password）
- `POST /api/v1/auth/login` —— 登录，拿 JWT（24h 有效）
- 后续请求带 `Authorization: Bearer <token>`
- `POST /api/v1/threads` —— 新建会话（返回 thread_id）
- `GET /api/v1/chat/{thread_id}` —— 查会话历史
- `POST /api/v1/chat/{thread_id}` —— 发消息，流式返回 NDJSON
- `POST /api/v1/documents/upload/{thread_id}` —— 上传文档（202 后台处理）
- `GET /api/v1/documents/{thread_id}` —— 列会话下文档
- `DELETE /api/v1/documents/{document_id}` —— 删文档（含向量切片）
- `GET /health` —— 健康检查

聊天/文档/会话接口全部受 JWT 保护，未登录返回 401。