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
os.environ["LLM_API_KEY"] = "env-test-key"
os.environ["BOCHA_API_KEY"] = "env-test-bocha"

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from app.chat.schemas import ChatStreamResponse
from app.chat.tools import tools
from app.db.main import get_session
from app.main import app
from app.security import create_access_token


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


async def test_ndjson_emits_sources_from_artifact():
    """工具的 artifact 里有引用 → 多吐一条 sources 事件（前端靠它画引用卡片）。

    artifact 是「给程序看的附带数据」，所以引用不走 content、单独成一条事件。
    """
    async def fake_stream():
        yield "updates", {
            "tools": {
                "messages": [
                    ToolMessage(
                        content="片段正文",
                        name="retrieve_user_documents",
                        tool_call_id="call_1",
                        artifact={"sources": [
                            {"index": 1, "file_name": "手册.txt", "score": 0.4225, "snippet": "E09"}
                        ]},
                    )
                ]
            }
        }

    response = ChatStreamResponse(fake_stream())
    body = "".join([chunk async for chunk in response.body_iterator])
    lines = [json.loads(line) for line in body.splitlines() if line]

    assert lines[0]["type"] == "tool_result"
    assert lines[1] == {
        "type": "sources",
        "items": [{"index": 1, "file_name": "手册.txt", "score": 0.4225, "snippet": "E09"}],
    }


async def test_ndjson_no_sources_when_artifact_absent():
    """没有引用的工具（联网搜索）不该凭空多出一条 sources 事件。"""
    async def fake_stream():
        yield "updates", {
            "tools": {
                "messages": [
                    ToolMessage(content="搜索结果", name="web_search", tool_call_id="call_1")
                ]
            }
        }

    response = ChatStreamResponse(fake_stream())
    body = "".join([chunk async for chunk in response.body_iterator])
    types = [json.loads(line)["type"] for line in body.splitlines() if line]

    assert types == ["tool_result"]  # 只有一条，没有 sources


def test_history_attaches_sources_to_answer():
    """刷新页面后引用还在：ToolMessage 的 artifact 要挂到紧随其后的 AI 回答上。

    真实序列是 Human → AI(只带 tool_calls) → Tool(带 artifact) → AI(最终回答)。
    """
    from langchain_core.messages import HumanMessage
    from app.chat.service import _to_history

    messages = [
        HumanMessage(content="E03 是什么"),
        AIMessage(
            content="",
            tool_calls=[{"name": "retrieve_user_documents", "args": {"query": "E03"}, "id": "c1"}],
        ),
        ToolMessage(
            content="片段正文",
            name="retrieve_user_documents",
            tool_call_id="c1",
            artifact={"sources": [
                {"index": 1, "file_name": "手册.txt", "score": 0.42, "snippet": "E09 引导分区"},
                {"index": 2, "file_name": "手册.txt", "score": 0.40, "snippet": "E09 引导分区"},  # 重复
            ]},
        ),
        AIMessage(content="E03 表示密封圈劣化"),
    ]

    history = _to_history(messages)

    assert [m.role for m in history] == ["human", "ai"]   # 空的 AI(调工具那条) 被挡掉
    assert history[0].sources == []                      # 用户消息永远没有引用
    assert len(history[1].sources) == 1                   # 重复引用被去重
    assert history[1].sources[0]["index"] == 1            # 去重后重新编号
    assert history[1].content == "E03 表示密封圈劣化"


def test_chat_history_without_token_401():
    """没带 token 查历史 → 401（把"必须登录"锁进测试）。"""
    client = TestClient(app)  # 不跑 lifespan：本测试不碰 Postgres（test_health 同款）
    r = client.get(f"/api/v1/chat/{uuid.uuid4()}")
    assert r.status_code == 401


class _EmptyResult:
    """假的查询结果：模拟"数据库里没有这一行"。"""

    def scalar_one_or_none(self):
        return None


class _FakeSession:
    """假的数据库会话：不管传什么查询进来，都返回空结果。

    只需要 execute + scalar_one_or_none 两个方法——get_thread_by_id 就用到这两个。
    """

    async def execute(self, stmt):
        return _EmptyResult()


async def _fake_session():
    """替代 get_session 的依赖：给每个请求发一个假会话（不连真库）。"""
    yield _FakeSession()


def test_chat_history_not_found_404():
    """带合法 token 查一个库里不存在的会话 → 404（挂在归属校验那一步，不碰存档器）。

    归属校验要求先查 Postgres，所以把 get_session 换成假会话：
    查不到 → service 抛 NotFoundError → 全局 handler 转 404。
    """
    app.dependency_overrides[get_session] = _fake_session
    try:
        client = TestClient(app)
        token = create_access_token(str(uuid.uuid4()))
        r = client.get(
            f"/api/v1/chat/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()  # 全局状态，不清会污染后面的测试
