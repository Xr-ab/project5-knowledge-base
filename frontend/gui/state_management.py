"""frontend/gui/state_management.py —— 页面状态管理（st.session_state 的封装）。

为什么需要：Streamlit 每次交互整个脚本重跑一遍，普通变量全丢。
只有 st.session_state 能跨重跑存活——它是界面状态的"家"。
"""
import streamlit as st

from api_utils import create_thread, list_threads, delete_thread  # 只 import 用到的

def get_state() -> dict:
    """懒初始化：第一次进页面才建，之后每次都返回同一个字典。"""
    if "state" not in st.session_state:
        st.session_state["state"] = {
            "threads": [],          # 会话列表（侧边栏展示用）
            "current_thread_id": None,  # 当前选中哪个会话（None = 没选）
        }
    return st.session_state["state"]

async def refresh_threads() -> None:
    """从后端拉会话列表，刷新状态（每次进页面、增删后都调）。"""
    state = get_state()
    state["threads"] = await list_threads() or []

async def new_thread() -> None:
    """新建会话：后端建 → 放进列表头部 → 立即选中。"""
    created_thread = await create_thread() or {"id": "new", "title": "新会话"}  # 后端出错就用默认
    state = get_state()
    state["threads"].insert(0, created_thread)  # 插到列表头（最新在最上）
    state["current_thread_id"] = created_thread["id"]  # 立即选中新会话

def select_thread(thread_id: str) -> None:
    """选中一个会话（侧边栏点击时调用）。"""
    current_state = get_state()
    current_state["current_thread_id"] = thread_id

async def delete_thread_by_id(thread_id: str) -> None:
    """删除会话：后端删 + 本地列表也去掉；删的是当前会话就清空选中。"""
    await delete_thread(thread_id)  # 第 1 步：删后端
    state = get_state()
    # 第 2 步：列表推导式——从旧列表挑出 id 不等于被删的，组成新列表（一行完成"删除"）
    state["threads"] = [t for t in state["threads"] if t["id"] != thread_id]
    # 第 3 步：删的是当前会话就清空选中
    if state["current_thread_id"] == thread_id:
        state["current_thread_id"] = None