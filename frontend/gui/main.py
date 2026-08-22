"""frontend/gui/main.py —— 前端入口：页面布局 + 交互逻辑（v1 单用户版，无登录）。

界面结构：
  侧边栏 = 会话管理（新建/切换/删除）+ 当前会话的文档列表 + 上传
  主区   = 聊天界面（历史消息 + 输入框 + 流式打字机）
"""
import asyncio
import json

import streamlit as st

from api_utils import (
    delete_document,
    get_chat_history,
    list_documents,
    stream_chat,
    upload_document,
)
from state_management import (
    delete_thread_by_id,
    get_state,
    new_thread,
    refresh_threads,
    select_thread,
)

st.set_page_config(page_title="AI 知识库", page_icon="📚", layout="wide")


def render_sidebar() -> None:
    """侧边栏：会话列表 + 文档管理。"""
    st.sidebar.title("📚 AI 知识库")
    if st.sidebar.button("＋ 新建会话", use_container_width=True):
        asyncio.run(new_thread())  # 建完立即选中（state_management 里做了）
        st.rerun()  # 重跑刷新界面

    state = get_state()
    # ---- 会话列表：整行按钮 = 点击选中；👉 标记当前会话 ----
    st.sidebar.divider()
    st.sidebar.markdown("### 💬 会话")
    if state["threads"]:
        for thread in state["threads"]:
            title = f"👉 {thread['title']}" if thread["id"] == state["current_thread_id"] else thread["title"]
            col1, col2 = st.sidebar.columns([0.85, 0.15])
            with col1:
                if st.button(title, key=f"sel_{thread['id']}", use_container_width=True):
                    select_thread(thread["id"])
            with col2:
                if st.button("🗑️", key=f"del_{thread['id']}", help="删除会话"):
                    asyncio.run(delete_thread_by_id(thread["id"]))
                    st.rerun()
    else:
        st.sidebar.caption("暂无会话")

    # ---- 文档管理：只对"当前选中"的会话有效 ----
    thread_id = state["current_thread_id"]
    if thread_id:
        st.sidebar.divider()
        st.sidebar.markdown("### 📂 文档")
        docs = asyncio.run(list_documents(thread_id)) or []
        for doc in docs:
            col1, col2 = st.sidebar.columns([0.85, 0.15])
            with col1:
                st.markdown(f"📄 {doc['file_name']}")
            with col2:
                if st.button("🗑️", key=f"docdel_{doc['id']}", help="删除文档"):
                    asyncio.run(delete_document(doc["id"]))
                    st.rerun()
        if not docs:
            st.sidebar.caption("暂无文档，上传后可问文档内容")
        st.sidebar.divider()
        uploaded = st.sidebar.file_uploader("上传文档", type=["pdf", "docx", "txt"], key="uploader")
        if uploaded is not None:
            if st.sidebar.button("上传", key="do_upload", use_container_width=True):
                with st.sidebar.spinner(f"上传 {uploaded.name}…"):
                    ok = asyncio.run(upload_document(thread_id, uploaded))
                if ok:
                    # 清掉文件选择器的残留文件：否则重跑后它还显示旧文件，像"默认上传"
                    if "uploader" in st.session_state:
                        del st.session_state["uploader"]
                    st.rerun()  # 成功就重跑刷新文档列表
                else:
                    st.sidebar.error("上传失败（检查文件类型/大小）")


def render_chat() -> None:
    """主区：聊天界面（没选中会话就提示）。"""
    thread_id = get_state()["current_thread_id"]
    if thread_id is None:
        st.info("👈 先在左侧新建或选择一个会话")
        return

    # 历史消息：每次重跑都从后端拉（数据永远准，代价是慢一点）
    for msg in asyncio.run(get_chat_history(thread_id)) or []:
        with st.chat_message(msg["role"]):  # 后端 role 是 human/ai，st 原生支持这俩
            st.markdown(msg["content"])

    if prompt := st.chat_input("问点什么…（可以问上传的文档）", key="chat_prompt"):
        # 先把用户消息画上去
        with st.chat_message("human"):
            st.markdown(prompt)

        # 助手区：过程（工具调用）+ 打字机（流式内容）
        with st.chat_message("ai"):
            steps_container = st.container()  # 工具调用事件放这里
            answer_placeholder = st.empty()   # 打字机占位符
            full_response = ""

            async def fetch_stream():
                nonlocal full_response  # 嵌套函数里改外层变量必须声明
                async for line in stream_chat(thread_id, prompt):
                    event = json.loads(line)
                    etype = event["type"]
                    if etype == "tool_call":
                        with steps_container:
                            st.markdown(f"🔧 调用工具 **{event['name']}**")
                    elif etype == "tool_result":
                        with steps_container:
                            with st.expander(f"📦 工具结果：{event['name']}", expanded=False):
                                st.code(event["content"], language="text")
                    elif etype == "llm_chunk":
                        full_response += event.get("content", "")
                        answer_placeholder.markdown(full_response + "▌")
                answer_placeholder.markdown(full_response)  # 收尾：去掉光标

            with st.spinner("思考中…"):
                asyncio.run(fetch_stream())
        # 清掉输入框残留状态：否则下次任何重跑都会"自动重发"旧问题
        if "chat_prompt" in st.session_state:
            del st.session_state["chat_prompt"]
        st.rerun()  # 重跑：重新拉历史，把这一轮固定进记录


# ---- 入口：脚本每次重跑都从上到下执行一遍 ----
asyncio.run(refresh_threads())
render_sidebar()
render_chat()
