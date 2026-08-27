"""main.py —— FastAPI 应用入口（总装车间）。

职责：创建 app 实例、挂中间件、挂路由器、提供健康检查。
不写业务逻辑——业务都在各自的 routes/service 里。
"""
from fastapi import FastAPI
from pydantic import BaseModel

from app.chat.routes import chat_router          # 聊天路由（模块 5 填充）
from app.documents.routes import document_router  # 文档路由（模块 4 填充）
from app.lifespan import lifespan                 # 启动/关闭钩子（建目录、建表）
from app.middleware import register_middleware    # 中间件注册（CORS）
from app.security import create_access_token      # JWT 签发（模块 6）
from app.threads.routes import thread_router      # 会话路由（模块 3 填充）

version = "v1"
version_prefix = f"/api/{version}"  # 统一前缀：所有接口都挂 /api/v1 下，方便以后升级 v2

app = FastAPI(
    title="AI 知识库",
    description="上传私有文档 → RAG/Agent 问答（临摹 LangGraph-RAG-Agent）",
    version=version,
    docs_url=f"{version_prefix}/docs",  # 自动生成的 Swagger 文档地址（不用写文档）
    lifespan=lifespan,  # 注册启动/关闭钩子
)

register_middleware(app)  # 注册中间件（目前只有 CORS）
# 挂路由器：prefix 是 URL 前缀，tags 是 Swagger 文档里的分组名
app.include_router(thread_router, prefix=f"{version_prefix}/threads", tags=["THREADS"])
app.include_router(document_router, prefix=f"{version_prefix}/documents", tags=["DOCUMENTS"])
app.include_router(chat_router, prefix=f"{version_prefix}/chat", tags=["CHAT"])


@app.get("/health")
async def health():
    """健康检查：给 Docker healthcheck 用（不需要 API Key 也能调）。"""
    return {"status": "ok"}


class LoginRequest(BaseModel):
    """登录请求体：开发期直接拿用户名当身份，不搞密码那套。"""
    username: str


@app.post(f"{version_prefix}/auth/login")
async def login(req: LoginRequest):
    """登录：拿用户名换一个 JWT token（24 小时有效）。"""
    token = create_access_token(req.username)
    return {"access_token": token, "token_type": "bearer"}