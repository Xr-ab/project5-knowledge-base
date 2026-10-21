"""chat/service.py —— 聊天的业务层：调 Agent 图、翻聊天记录。"""
import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import HTTPException
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import AIMessageChunk, HumanMessage
from langchain_core.runnables import RunnableConfig
from langfuse import Langfuse
from loguru import logger

from app.config import settings
from app.db.checkpointer import get_checkpointer

from .langfuse_handler import LangfuseCallbackHandler
from .langgraph_agent import build_retrieval_graph
from .schemas import Message, PromptInput

# Langfuse 上报器（技术雷达）：模块级单例，把 Agent 每次运行的 trace 发到本地面板。
# key + 面板地址来自 config.py 单一配置源。
# 面板是 langfuse/langfuse:2 镜像（只认经典 JSON 协议），所以 SDK 锁 2.55.0，
# 且官方 LangChain 集成只兼容 v0——这里用自写的轻量回调（见 langfuse_handler.py）。
langfuse_client = Langfuse(
    public_key=settings.langfuse_public_key,
    secret_key=settings.langfuse_secret_key,
    host=settings.langfuse_host,
    timeout=5,  # 单请求超时（默认 20s）：面板没起时失败得快一点，配合下面的后台 flush
)
langfuse_handler = LangfuseCallbackHandler(langfuse_client)

# 后台任务引用集合：fire-and-forget 的任务必须留引用，否则可能被 GC 提前回收
_background_tasks: set[asyncio.Task] = set()


def _flush_langfuse_in_background() -> None:
    """把 Langfuse flush 丢到后台线程，不阻塞响应收尾。

    为什么不是直接调、也不是 await asyncio.to_thread：面板没起时 SDK 上报带
    重试退避，实测同步 flush() 卡 22.2 秒（占一次问答总耗时的 77%）；
    to_thread 只是换到别的线程等 —— 只有"发起后不等待"才真正和响应解耦。
    """
    async def _flush() -> None:
        try:
            await asyncio.to_thread(langfuse_client.flush)
        except Exception:  # 观测失败绝不能影响主流程
            logger.warning("Langfuse flush 失败（面板可能没启动），已忽略")

    task = asyncio.create_task(_flush())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


class TokenPump(AsyncCallbackHandler):
    """把模型的逐字输出"泵"进队列，让 chat_stream 能一边执行一边往外发。

    为什么不用 LangGraph 的 stream_mode="messages"：
      实测（langchain 1.3.15 / langchain-core 1.5.5 / langgraph 1.2.11）下，
      create_agent 的 model 节点被标了 trace=False，token 事件不会变成 messages 流事件，
      整段回答只会作为【一个】chunk 出来 —— 183 字的回答只收到 1 个分片，前端就没有打字机。
      改成直接挂回调拿 token：同一句 61 字的回答能收到 334 次回调，
      从 0.16s 陆续到 1.70s，拼出来完整且无重复（空 token 必须过滤掉）。
    """

    def __init__(self, queue: "asyncio.Queue[tuple[str, object]]") -> None:
        self._queue = queue

    async def on_llm_new_token(self, token: str, *, chunk=None, **kwargs) -> None:
        """每来一个 token 就丢进队列；chunk 里是标准 AIMessageChunk，直接喂给翻译层。"""
        message = getattr(chunk, "message", None) or AIMessageChunk(content=token)
        if getattr(message, "content", ""):  # 工具调用之类的空 token 直接丢
            await self._queue.put(("messages", message))


async def chat_stream(thread_id: UUID, prompt_input: PromptInput) -> AsyncIterator:
    """把问题喂给 Agent 图，流式返回它的执行过程（工具调用 + 模型蹦字）。

    注意：这个函数是 async generator（有 yield）——调用方边消费边执行。
    async with 的记忆连接靠 yield 保持存活，覆盖整个流式输出过程。

    两条流汇进同一个队列，天然按真实发生顺序排好：
      - 图用 stream_mode="updates" 跑 → 工具调用 / 节点动作
      - 模型逐字输出走 TokenPump 回调 → 打字机
    yield 出去的形状和以前完全一样，ChatStreamResponse 不用改。
    """
    async with get_checkpointer() as checkpointer:  # 打开记忆存档器（退出自动关连接）
        queue: asyncio.Queue = asyncio.Queue()
        pump = TokenPump(queue)
        # 回调挂两处：模型实例上 + 运行 config 里（少了任何一处都可能收不到 token）
        graph = build_retrieval_graph(checkpointer, callbacks=[langfuse_handler, pump])
        config = RunnableConfig(
            configurable={"thread_id": str(thread_id), "checkpoint_ns": ""},  # checkpoint_ns 新版必填
            callbacks=[langfuse_handler, pump],  # Langfuse 上报 + token 泵
        )

        async def _run_graph() -> None:
            """后台跑图：节点动作进队列，跑完（无论成功失败）发一个结束标记。"""
            try:
                async for chunk in graph.astream(
                    input={"messages": [HumanMessage(content=prompt_input.prompt)]},
                    config=config,
                    stream_mode="updates",  # 只要节点动作；模型 token 由 TokenPump 负责
                ):
                    await queue.put(("updates", chunk))
            finally:
                await queue.put(("__end__", None))

        task = asyncio.create_task(_run_graph())
        try:
            while True:
                kind, payload = await queue.get()
                if kind == "__end__":
                    break
                # messages 要包成 (消息, 元数据) 两元组，保持和 LangGraph 原来一致的形状
                yield (kind, (payload, {})) if kind == "messages" else (kind, payload)
            if task.done() and not task.cancelled() and task.exception():
                raise task.exception()  # 图自己炸了 → 原样抛给上层
        finally:
            if not task.done():
                task.cancel()  # 前端断开时别让 Agent 继续空转
            _flush_langfuse_in_background()  # 观测上报丢后台，不拖着响应尾巴等面板


def _dedupe_sources(sources: list[dict]) -> list[dict]:
    """按（文件, 摘要）去重后重新编号。

    一次回答前可能调了多次检索工具（模型会重试），前后召回同一片段很常见；
    带着重复引用展示会让人以为有好几份证据。
    """
    seen: set[tuple] = set()
    uniq: list[dict] = []
    for s in sources:
        key = (s.get("file_name"), s.get("snippet"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(s)
    return [{**s, "index": i} for i, s in enumerate(uniq, start=1)]


def _to_history(all_messages: list) -> list[Message]:
    """把存档里的消息整理成 human/ai，并把工具产出的引用挂到对应的回答上。

    checkpoint 里的真实序列是：
        Human → AI(只带 tool_calls) → Tool(artifact 带引用) → AI(最终回答)
    引用属于「这次回答」，所以要挂在它后面那条 AI 上。一次回答前调了多次工具，
    就把各次的引用攒起来一起挂（再经 _dedupe_sources 去重重编号）。
    """
    out: list[Message] = []
    pending: list[dict] = []  # 攒着的引用，等下一次 AI 回答认领

    for message in all_messages:
        if message.type == "tool":
            artifact = getattr(message, "artifact", None)
            if isinstance(artifact, dict):
                pending.extend(artifact.get("sources") or [])
            continue
        if not message.content:
            continue  # 中间那条"只带 tool_calls、没正文"的 AI 消息在这里被挡掉
        if message.type == "human":
            out.append(Message(role="human", content=message.content))
        elif message.type == "ai":
            out.append(
                Message(role="ai", content=message.content, sources=_dedupe_sources(pending))
            )
            pending = []  # 认领完就清空，别串到下一轮
    return out


async def get_chat_history(thread_id: UUID) -> list[Message]:
    """从存档器翻出该会话的聊天记录。

    只留 human/ai 消息；工具消息不直接展示，但它的 artifact 里的引用会被
    提取出来挂到紧随其后的那条回答上——这样刷新页面后引用卡片还在。
    """
    async with get_checkpointer() as checkpointer:
        config = RunnableConfig(
            configurable={"thread_id": str(thread_id), "checkpoint_ns": ""}
        )
        checkpoint_tuple = await checkpointer.aget_tuple(config)  # 新版 API：aget → aget_tuple
        if checkpoint_tuple is None:  # 这个会话从没聊过 → 404（和 threads 同一个套路）
            raise HTTPException(status_code=404, detail="Chat history not found")
        all_messages = checkpoint_tuple.checkpoint.get("channel_values", {}).get("messages", [])
        return _to_history(all_messages)
