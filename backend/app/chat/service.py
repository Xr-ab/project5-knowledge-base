"""chat/service.py —— 聊天的业务层：调 Agent 图、翻聊天记录。"""
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import HTTPException
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from app.db.checkpointer import get_checkpointer

from .langgraph_agent import build_retrieval_graph
from .schemas import Message, PromptInput


async def chat_stream(thread_id: UUID, prompt_input: PromptInput) -> AsyncIterator:
    """把问题喂给 Agent 图，流式返回它的执行过程（工具调用 + 模型蹦字）。

    注意：这个函数是 async generator（有 yield）——调用方边消费边执行。
    async with 的记忆连接靠 yield 保持存活，覆盖整个流式输出过程。
    """
    async with get_checkpointer() as checkpointer:  # 打开记忆存档器（退出自动关连接）
        graph = build_retrieval_graph(checkpointer)  # 拼图：模型 + 工具 + 提示词 + 记忆
        config = RunnableConfig(
            configurable={"thread_id": str(thread_id), "checkpoint_ns": ""}  # checkpoint_ns 新版必填
        )
        async for chunk in graph.astream(
            input={"messages": [HumanMessage(content=prompt_input.prompt)]},
            config=config,
            stream_mode=["updates", "messages"],  # 两种流：节点动作 + 模型 token
        ):
            yield chunk  # 转手给上层（ChatStreamResponse 负责翻译成 NDJSON）


async def get_chat_history(thread_id: UUID) -> list[Message]:
    """从存档器翻出该会话的聊天记录（只留 human/ai 消息，工具消息过滤掉）。"""
    async with get_checkpointer() as checkpointer:
        config = RunnableConfig(
            configurable={"thread_id": str(thread_id), "checkpoint_ns": ""}
        )
        checkpoint_tuple = await checkpointer.aget_tuple(config)  # 新版 API：aget → aget_tuple
        if checkpoint_tuple is None:  # 这个会话从没聊过 → 404（和 threads 同一个套路）
            raise HTTPException(status_code=404, detail="Chat history not found")
        all_messages = checkpoint_tuple.checkpoint.get("channel_values", {}).get("messages", [])
        return [
            Message(role=message.type, content=message.content)
            for message in all_messages
            if message.content and message.type in ["human", "ai"]
        ]
