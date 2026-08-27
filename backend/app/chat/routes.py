"""chat/routes.py —— 聊天的 HTTP 端点：发消息（流式）、看历史。

流式原理：POST 返回的不是普通 JSON，而是一个 StreamingResponse——
服务器把 NDJSON 一行一行推给前端，前端边读边显示（打字机效果）。
"""
from uuid import UUID

from fastapi import APIRouter, Depends

from app.chat import service as chat_service
from app.chat.schemas import ChatStreamResponse, Message, PromptInput
from app.db.main import SessionDep
from app.security import get_current_user
from app.threads import service as thread_service

chat_router = APIRouter()


@chat_router.post("/{thread_id}")
async def chat_stream(thread_id: UUID, prompt_input: PromptInput, session: SessionDep, user: str = Depends(get_current_user)):
    """发消息：Agent 处理 + 流式返回 NDJSON。

    不设 response_model——返回的是流不是单个 JSON，没法校验。
    """
    # 先确认会话存在（不存在 get_thread 抛 404）——避免拿假 id 去聊，静默建出奇怪的状态
    await thread_service.get_thread(thread_id, session)
    return ChatStreamResponse(chat_service.chat_stream(thread_id, prompt_input))


@chat_router.get("/{thread_id}", response_model=list[Message])
async def get_chat_history(thread_id: UUID, user: str = Depends(get_current_user)):
    """看这个会话的聊天记录（没聊过 → 404）。"""
    return await chat_service.get_chat_history(thread_id)