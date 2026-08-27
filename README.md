# project5 —— 全栈 AI 知识库（React 版）

> 临摹重构 `LangGraph-RAG-Agent-main`：上传私有文档 → RAG/Agent 问答，React 前端 + FastAPI 后端 + 本地向量库一条龙。
> 教学大纲：`docs/project5-拆解表.md`（仓库根目录）。协作约定：见 `CLAUDE_BRIEF.md`。

## 技术栈
- 后端：FastAPI + SQLAlchemy(轻) + LangGraph ReAct Agent + Chroma（本地向量库）
- 记忆：AsyncSqliteSaver（本地 .sqlite）
- LLM/Embedding：DeepSeek(v4-flash) + bge-small-zh-v1.5（本地 embedding，免费无 key）
- 搜索工具：BoCha（博查）
- 前端：React（Vite）——多轮聊天 + 流式渲染（打字机）
- 鉴权：JWT（pyjwt 签发 + FastAPI 依赖注入校验）
- 部署：Docker Compose 一键起

## 目录
```
backend/app/          # FastAPI 后端（config / main / threads / documents / chat / db / security）
backend/requirements.txt
frontend/gui/         # 旧版 Streamlit 前端（保留，未用）
frontend/react-app/   # React 前端（Vite）
  ├─ src/App.jsx      # 聊天主组件（状态 + 调后端 + 流式）
  ├─ src/components/  # MessageList / MessageInput
  ├─ Dockerfile       # 多阶段构建（node build → nginx serve）
  └─ nginx.conf       # 反向代理 /api → backend
docker-compose.yml    # backend + frontend 编排
outputs/              # 运行产物（Chroma、sqlite、上传文档）
tests/                # pytest
```

## 本地开发

后端（`backend/` 目录）：
```bash
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

前端（`frontend/react-app/` 目录）：
```bash
npm install
npm run dev            # http://localhost:5173
```
开发时 Vite 把 `/api/v1` 代理到本地后端（见 `vite.config.js`，目标端口需和后端实际端口一致）。

## API 概览
- `POST /api/v1/auth/login` —— 拿 `username` 换 JWT（24h 有效）
- 后续请求带请求头 `Authorization: Bearer <token>`
- `POST /api/v1/threads` —— 新建会话（返回 thread_id）
- `POST /api/v1/chat/{thread_id}` —— 发消息，流式返回 NDJSON
- `GET /api/v1/chat/{thread_id}` —— 查历史记录
- `GET /health` —— 健康检查（Docker healthcheck 用）

聊天接口（chat）受 JWT 保护，未登录返回 401。

## 部署（Docker Compose）

前置条件：装好 Docker Desktop，项目根 `.env` 配 `DEEPSEEK_API_KEY` / `BOCHA_API_KEY`（见 `.env.example`）。

```bash
docker compose build   # 构建后端 + 前端镜像（首次 5-10 分钟）
docker compose up -d   # 前端等后端健康检查通过后才启动
```

访问 `http://localhost:5173`。

| 服务 | 对外端口 | 容器内 | 说明 |
|---|---|---|---|
| backend | 8001 | 8000 | FastAPI + LangGraph Agent + Chroma |
| frontend | 5173 | 80 | React 静态站（Nginx 托管） |

Nginx 把 `/api/*` 转发给 backend，前端代码无需写死后端地址（生产/开发共用一套 `/api/v1` 路径）。

数据安全：SQLite / Chroma / 上传文档在 `./outputs`（挂载卷，容器删除不丢）；embedding 模型缓存走命名卷；密钥只经环境变量透传，不写入镜像。