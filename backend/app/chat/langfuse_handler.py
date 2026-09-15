"""chat/langfuse_handler.py —— 轻量 Langfuse 回调（技术雷达 Demo）。

为什么自写：本地面板是 Langfuse v2 服务器，官方新版 SDK(4.x) 走 OTLP 协议它不认；
经典 SDK(2.x) 的官方 LangChain 集成只兼容 LangChain v0，而项目用的是 v1。
所以基于 langchain_core 的 BaseCallbackHandler 写一个"翻译器"：

  LangGraph 每次执行 → 触发 on_chain_start / on_llm_start / on_tool_start 等钩子
  （这些是 LangChain 的标准回调点）→ 我们在这里把它们翻译成
  Langfuse 的 trace / span / generation 并上报到面板。

层级规则（和 LangGraph 的 run 树一一对应）：
  - 根 chain（parent_run_id 为空）= LangGraph 图本身 → 开一条 trace
  - 子 chain（图里的节点，如 model 节点）→ trace 下的 span
  - LLM 调用 → generation（挂在所属 span 下，能记 token/费用）
  - 工具调用 → span
"""
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langfuse import Langfuse


class LangfuseCallbackHandler(BaseCallbackHandler):
    """把 LangChain 回调事件转发成 Langfuse 观测对象。

    run_id 是 LangChain 给每次 run 分配的唯一 id，我们拿它当 key，
    把"开始事件"创建的 trace/span/generation 记下来，等"结束事件"再取出来补 output。
    """

    def __init__(self, client: Langfuse):
        self._client = client
        self._observations: dict[UUID, object] = {}  # run_id → 观测对象
        self._root: object = None                    # 根 trace（找不到父观测时的兜底落点）

    # ---------- chain（含根 graph 与图内节点） ----------

    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, **kwargs):
        """chain 开始：根 → 开 trace；子 chain → 在父观测下开 span。"""
        try:
            if parent_run_id is None:
                obs = self._client.trace(name="agent", input=inputs)
                self._root = obs
            else:
                parent = self._observations.get(parent_run_id)
                # serialized 在 LangGraph 里可能是 None，兜底成空 dict 再取值
                meta = serialized or {}
                obs = parent.span(name=meta.get("name") or "node", input=inputs) if parent is not None else None
            if obs is not None:
                self._observations[run_id] = obs
        except Exception:
            pass  # 回调里绝不能炸，否则会把 Agent 运行也带崩

    def on_chain_end(self, outputs, *, run_id, **kwargs):
        """chain 结束：把输出补到观测对象上。"""
        obs = self._observations.pop(run_id, None)
        if obs is not None:
            try:
                obs.update(output=outputs)
            except Exception:
                pass

    def on_chain_error(self, error, *, run_id, **kwargs):
        """chain 报错：记一条 error 说明（面板上能看出哪步挂了）。"""
        obs = self._observations.pop(run_id, None)
        if obs is not None:
            try:
                obs.update(metadata={"error": str(error)})
            except Exception:
                pass

    # ---------- LLM（记录模型、输入输出，可统计 token/费用） ----------

    def on_llm_start(self, serialized, prompts, *, run_id, parent_run_id=None, **kwargs):
        """LLM 开始：在父 span 下开一个 generation；找不到父就挂 trace 根。"""
        try:
            parent = self._observations.get(parent_run_id) or self._root
            if parent is None:
                return
            meta = serialized or {}
            model = meta.get("kwargs", {}).get("model_name") or meta.get("name")
            obs = parent.generation(name=model or "llm", model=model, input={"prompts": prompts})
            self._observations[run_id] = obs
        except Exception:
            pass

    def on_llm_end(self, response, *, run_id, **kwargs):
        """LLM 结束：补输出；有 token 用量也带上。"""
        obs = self._observations.pop(run_id, None)
        if obs is not None:
            try:
                usage = None
                llm_output = getattr(response, "llm_output", None) or {}
                tu = llm_output.get("token_usage") or {}
                if tu:
                    usage = {
                        "input": tu.get("prompt_tokens"),
                        "output": tu.get("completion_tokens"),
                        "total": tu.get("total_tokens"),
                        "unit": "TOKENS",
                    }
                obs.update(output=response.generations, usage=usage)
            except Exception:
                pass

    def on_llm_error(self, error, *, run_id, **kwargs):
        """LLM 报错。"""
        obs = self._observations.pop(run_id, None)
        if obs is not None:
            try:
                obs.update(metadata={"error": str(error)})
            except Exception:
                pass

    # ---------- 工具调用 ----------

    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, **kwargs):
        """工具开始：在父观测下开一个 span；找不到父就挂 trace 根。"""
        try:
            parent = self._observations.get(parent_run_id) or self._root
            if parent is None:
                return
            meta = serialized or {}
            obs = parent.span(name=meta.get("name", "tool"), input=input_str)
            self._observations[run_id] = obs
        except Exception:
            pass

    def on_tool_end(self, output, *, run_id, **kwargs):
        """工具结束：补输出。"""
        obs = self._observations.pop(run_id, None)
        if obs is not None:
            try:
                obs.update(output=output)
            except Exception:
                pass

    def on_tool_error(self, error, *, run_id, **kwargs):
        """工具报错。"""
        obs = self._observations.pop(run_id, None)
        if obs is not None:
            try:
                obs.update(metadata={"error": str(error)})
            except Exception:
                pass
