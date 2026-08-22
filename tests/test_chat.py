"""tests/test_chat.py —— 聊天模块测试。

能测的（不需要真实 API key）：
  1. NDJSON 流式协议转换（纯逻辑：喂假的 LangGraph 流，检查输出的每行 JSON）
  2. 工具注册列表
  3. 空会话查历史 → 404
不能测的：真实对话（要 DeepSeek/博查 key，跑起来后手动验证）。
"""
import json
import os
import uuid

# ⚠️ 必须在 import app 之前：app.config 模块级会构造 Settings()（必填字段）
# 且本文件字母序在 test_config.py 之前，pytest 先 import 它——所以这里自己兜底
os.environ["DEEPSEEK_API_KEY"] = "env-test-key"
os.environ["BOCHA_API_KEY"] = "env-test-bocha"

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from app.chat.schemas import ChatStreamResponse
from app.chat.tools import tools
from app.main import app


def test_tools_registered():
    """两个工具都注册进了 Agent 的工具箱（缺一不可）。"""
    assert {t.name for t in tools} == {"retrieve_user_documents", "web_search"}


async def test_ndjson_protocol_translation():
    """喂假的 LangGraph 流，验证 NDJSON 协议翻译正确（核心逻辑测试）。

    假的流模拟真实场景的四种片段，顺序也是真实执行顺序：
    模型蹦字 → 决定调工具 → 工具返回结果 → 继续蹦字。
    """
    async def fake_langgraph_stream():
        # ("messages", (消息对象, 元数据)) —— 模型 token 流
        yield "messages", (AIMessageChunk(content="你"), {"langgraph_node": "model"})
        # ("updates", {节点名: 节点输出}) —— 节点动作快照
        yield "updates", {
            "tools": {
                "messages": [
                    AIMessage(content="", tool_calls=[{"name": "web_search", "args": {"query": "测试"}, "id": "call_1"}])
                ]
            }
        }
        yield "updates", {
            "tools": {"messages": [ToolMessage(content="搜索结果", name="web_search", tool_call_id="call_1")]}
        }
        yield "messages", (AIMessageChunk(content="好"), {"langgraph_node": "model"})

    response = ChatStreamResponse(fake_langgraph_stream())
    body = "".join([chunk async for chunk in response.body_iterator])
    lines = [json.loads(line) for line in body.splitlines() if line]

    assert lines == [
        {"type": "llm_chunk", "content": "你"},
        {"type": "tool_call", "name": "web_search", "args": {"query": "测试"}},
        {"type": "tool_result", "name": "web_search", "content": "搜索结果"},
        {"type": "llm_chunk", "content": "好"},
    ]


def test_chat_history_empty_404():
    """从没聊过的会话查历史 → 404（只查存档器，不触发模型调用）。"""
    with TestClient(app) as client:
        r = client.get(f"/api/v1/chat/{uuid.uuid4()}")
        assert r.status_code == 404
