"""chat/schemas.py —— 聊天接口的请求/响应模型（含 NDJSON 流式协议转换）。

NDJSON = Newline-Delimited JSON：每行一个独立 JSON 对象。
前端逐行读取、边读边显示 → 打字机效果。
"""
import json
from typing import Any, AsyncGenerator, AsyncIterable

from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from pydantic import BaseModel


class PromptInput(BaseModel):
    """聊天请求体。v1 简化：删掉 model_name，固定用 config 里的 DeepSeek。"""
    prompt: str


class Message(BaseModel):
    """历史消息（读聊天记录时返回）：role 是 human/ai，content 是内容。"""
    role: str
    content: str


class ChatStreamResponse(StreamingResponse):
    """流式响应：把 LangGraph 的流翻译成前端好读的 NDJSON。
    LangGraph 的流有 2 种模式，我们都要处理：
      - "messages" 模式 → 模型蹦的字 → {"type": "llm_chunk", "content": ...}
      - "updates" 模式 → 节点的动作 → {"type": "tool_call"/"tool_result", ...}
    """

    def __init__(self, astream: AsyncIterable[dict[str, Any | Any]], **kwargs):
        # StreamingResponse 的 content 参数可以传一个异步生成器——它边读边发给客户端
        super().__init__(content=self.process_stream(astream), **kwargs)

    async def process_stream(self, astream: AsyncIterable[dict[str, Any | Any]]) -> AsyncGenerator[str, Any]:
        # 拆流：LangGraph 每吐一段，都带上它属于哪个模式（stream_mode）
        async for stream_mode, chunk in astream:
            if stream_mode == "messages":
                # 模式一：模型生成的 token 流 → 直接转成 llm_chunk
                yield self._handle_messages_stream(chunk)  # type: ignore

            elif stream_mode == "updates":
                # 模式二：每个节点执行完的动作快照 → 可能是工具调用/工具结果
                async for formatted_chunk in self._handle_updates_stream(chunk):  # type: ignore
                    yield formatted_chunk

    def _handle_messages_stream(self, chunk: tuple[AIMessageChunk | AIMessage, Any]) -> str:
        # 模型蹦字：chunk[0] 是消息对象，.content 非空才发（空片段跳过）
        message = chunk[0]
        if isinstance(message, (AIMessageChunk, AIMessage)) and message.content:
            response = {"type": "llm_chunk", "content": str(message.content)}
            return json.dumps(response) + "\n"
        return ""

    async def _handle_updates_stream(self, chunk: dict[str, Any]) -> AsyncGenerator[str, Any]:
        # 节点动作：每个节点的输出里找最后一条消息，按类型翻译
        for node_output in chunk.values():
            if "messages" not in node_output:
                continue  # 有些节点不产消息（比如纯工具执行），跳过

            message = node_output["messages"][-1]

            if isinstance(message, AIMessage):
                # 模型要调工具：把工具名和参数发出去（前端可以显示"AI 正在搜索…"）
                if message.tool_calls:
                    for tool_call in message.tool_calls:
                        response = {"type": "tool_call", "name": tool_call["name"], "args": tool_call["args"]}
                        yield json.dumps(response) + "\n"

            elif isinstance(message, ToolMessage):
                # 工具执行完的结果
                response = {"type": "tool_result", "name": message.name, "content": message.content}
                yield json.dumps(response) + "\n"
