"""threads/routes.py —— 会话的 HTTP 端点（路由层，只接线不干业务）。

三层分工：routes 管"HTTP 长相"（URL/状态码/响应模型），
service 管"业务逻辑"，models 管"表结构"。每个端点只有几行——
因为它只是把 HTTP 请求翻译成对 service 的调用。
"""
import uuid  # 路径参数类型：URL 里的 {thread_id} 必须是合法 UUID

from fastapi import APIRouter, status
# APIRouter: 路由分组；status: 标准 HTTP 状态码常量（比裸数字可读）

from app.db.main import SessionDep  # 依赖注入：类型注解后 FastAPI 自动递会话
from app.threads import service  # 业务层（所有真活都在这）
from app.threads.schemas import ThreadPublic, ThreadUpdate  # 请求/响应"长相合同"

thread_router = APIRouter()  # main.py 里 include_router 挂的就是这个


@thread_router.get("", response_model=list[ThreadPublic])
async def get_threads(session: SessionDep):
    """列出全部会话。"""
    # response_model=list[ThreadPublic]：自动把 ORM 对象列表转成合同里的字段
    return await service.get_user_threads(session)


@thread_router.post("", response_model=ThreadPublic, status_code=status.HTTP_201_CREATED)
async def create_thread(session: SessionDep):
    """新建会话（无请求体，用默认标题）。"""
    # 201 = Created（创建成功），POST 创建资源的标准语义；默认 200 是给查询用的
    return await service.create_new_thread(session)


@thread_router.get("/{thread_id}", response_model=ThreadPublic)
async def get_thread(thread_id: uuid.UUID, session: SessionDep):
    """查单个会话。"""
    # 路径参数 {thread_id} 声明为 uuid.UUID → FastAPI 自动校验格式，非法直接 400
    return await service.get_thread(thread_id, session)


@thread_router.patch("/{thread_id}", response_model=ThreadPublic)
async def update_thread(thread_id: uuid.UUID, thread_update: ThreadUpdate, session: SessionDep):
    """改标题。"""
    # thread_update: ThreadUpdate → FastAPI 自动校验请求体（空标题 400），解析后传入
    return await service.update_thread(thread_update, thread_id, session)


@thread_router.delete("/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thread(thread_id: uuid.UUID, session: SessionDep):
    """删除会话。"""
    # 204 = No Content（删除成功，没有响应体）
    await service.delete_thread(thread_id, session)
