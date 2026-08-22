# project5 —— 全栈 AI 知识库

> 临摹重构 `LangGraph-RAG-Agent-main`：上传私有文档 → RAG/Agent 问答，前端+后端+向量库一条龙。
> 教学大纲：`docs/project5-拆解表.md`（仓库根目录）。协作约定：见 `CLAUDE_BRIEF.md`。

## 第一版技术栈（降门槛版）
- 后端：FastAPI + SQLAlchemy(轻) + LangGraph ReAct Agent + Chroma（本地向量库）
- 记忆：AsyncSqliteSaver（本地 .sqlite）
- LLM/Embedding：DeepSeek(v4-flash) + bge-small-zh-v1.5（本地 embedding，免费无 key）
- 搜索工具：BoCha（博查）
- 前端：Streamlit（调 HTTP API + 流式渲染）
- 部署：最后用 Docker 一键起（后端 + 前端 + 向量库文件）

## 目录
```
backend/app/       # FastAPI 后端（config / main / threads / documents / chat / db）
frontend/gui/      # Streamlit 前端
outputs/           # 运行产物（Chroma 数据、记忆 sqlite、上传文档）
tests/             # pytest
```

## 部署（Docker Compose）

前置条件：装好 Docker Desktop，项目根 `.env` 里配置 `DEEPSEEK_API_KEY` / `BOCHA_API_KEY`（见 `.env.example`）。

```bash
docker compose build   # 构建后端 + 前端两个镜像（首次 5-10 分钟）
docker compose up -d   # 启动；前端容器等后端健康检查通过后才起
```

访问 `http://localhost:8501`。两个服务：

| 服务 | 端口 | 健康检查 | 说明 |
|---|---|---|---|
| backend | 8000 | `GET /health` | FastAPI + LangGraph Agent + Chroma |
| frontend | 8501 | `/_stcore/health` | Streamlit UI |

数据安全：SQLite / Chroma / 上传文档在 `./outputs`（挂载卷，容器删除不丢）；embedding 模型缓存走命名卷 `chroma_cache`。密钥只经环境变量透传进容器，不写入镜像。
