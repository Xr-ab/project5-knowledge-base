from app.config import settings
from langchain_openai import ChatOpenAI
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from langchain.agents import create_agent  # 新版组装机（create_react_agent 已弃用，搬到 langchain 包并改名）

from .prompts import SYSTEM_PROMPT
from .tools import tools

def create_model(streaming: bool = False) -> BaseChatModel:
    """创建聊天模型：DeepSeek 走 OpenAI 兼容协议，只需三个参数。"""
    return ChatOpenAI(
        model=settings.model_name,          # 模型名：deepseek-v4-flash
        api_key=settings.api_key,           # 密钥（SecretStr 也能直接吃）
        base_url=settings.model_base_url,   # https://api.deepseek.com/v1
        streaming=streaming,                # 是否流式（问答时要 True）
    )


def build_retrieval_graph(checkpointer: BaseCheckpointSaver) -> CompiledStateGraph:
    """组装 Agent 图：模型 + 工具 + 提示词 + 记忆 → 一张可调用的图。"""
    model = create_model()
    return create_agent(
        model=model,
        tools=tools,                  # chat/tools.py 里的两个工具
        system_prompt=SYSTEM_PROMPT,  # chat/prompts.py 的决策规则（新 API 改名：prompt → system_prompt）
        checkpointer=checkpointer,    # db/checkpointer.py 的记忆
    )