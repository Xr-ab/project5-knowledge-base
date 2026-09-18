"""chat/routes.py —— 聊天的 HTTP 端点：发消息（流式）、看历史。

流式原理：POST 返回的不是普通 JSON，而是一个 StreamingResponse——
服务器把 NDJSON 一行一行推给前端，前端边读边显示（打字机效果）。
"""
import uuid  # 字符串 user_id（token 里解出来的）→ UUID

from fastapi import APIRouter, Depends

from app.chat import service as chat_service
from app.chat.schemas import ChatStreamResponse, Message, PromptInput
from app.db.main import SessionDep
from app.security import get_current_user
from app.threads import service as thread_service

chat_router = APIRouter()


@chat_router.post("/{thread_id}")
async def chat_stream(thread_id: uuid.UUID, prompt_input: PromptInput, session: SessionDep, user: str = Depends(get_current_user)):
    """发消息：Agent 处理 + 流式返回 NDJSON。

    不设 response_model——返回的是流不是单个 JSON，没法校验。
    """
    # 先确认会话存在且归属当前用户（get_thread 带归属校验，不存在/别人的 → 404）
    # ——避免拿假 id 去聊，静默建出奇怪的状态
    thread = await thread_service.get_thread(thread_id, uuid.UUID(user), session)

    # 自动起标题：会话还是默认名 "New Chat" 时，用第一条用户消息前 30 字当标题。
    # 没有这一步，侧边栏全是 "New Chat"，多会话时根本分不清谁是谁。
    if thread.title == "New Chat":
        thread.title = prompt_input.prompt[:30]
        await session.commit()

    return ChatStreamResponse(chat_service.chat_stream(thread_id, prompt_input))


@chat_router.get("/{thread_id}", response_model=list[Message])
async def get_chat_history(thread_id: uuid.UUID, user: str = Depends(get_current_user)):
    """看这个会话的聊天记录（没聊过 → 404）。"""
    return await chat_service.get_chat_history(thread_id)