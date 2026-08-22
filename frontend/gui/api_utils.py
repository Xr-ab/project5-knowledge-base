"""frontend/gui/api_utils.py —— 前端调后端 API 的"手"（httpx 异步客户端）。"""
import httpx

from config import settings  # 同目录导入，拿后端地址

BASE_URL = settings.backend_base_url


async def _request_json(method: str, path: str, **kwargs) -> dict | None:
    """小工具：所有普通请求都走这一个（会话/文档的增删查）。

    v1 简化：出错（4xx/5xx）返回 None，界面自己显示提示。
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        r = await client.request(method, path, **kwargs)
        if r.status_code >= 400:
            return None
        if not r.content:  # 204 No Content 等空响应：r.json() 会炸，手动兜底
            return {}
        return r.json()

async def stream_chat(thread_id: str, prompt: str):
    """流式聊天：把后端推来的 NDJSON 逐行吐给界面。

    和 module 5 的 service.chat_stream 是同一课——async generator 边收边吐，
    yield 让连接一直活着，直到后端全部推完。
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=120) as client:
        async with client.stream("POST", f"/api/v1/chat/{thread_id}", json={"prompt": prompt}) as r:
            async for line in r.aiter_lines():
                if line:
                    yield line


# ===== 会话 =====


async def create_thread() -> dict | None:
    """新建会话（后端用默认标题）。"""
    return await _request_json("POST", "/api/v1/threads")


async def list_threads() -> list | None:
    """会话列表。"""
    return await _request_json("GET", "/api/v1/threads")


async def delete_thread(thread_id: str) -> dict | None:
    """删除会话。"""
    return await _request_json("DELETE", f"/api/v1/threads/{thread_id}")


# ===== 文档 =====


async def upload_document(thread_id: str, file) -> dict | None:
    """上传文档（multipart 表单）。

    file 是 Streamlit 的 UploadedFile 对象：.name 文件名 / .type MIME / .getvalue() 字节。
    超时给 120s——embedding 切片要时间，30s 可能不够。
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=120) as client:
        r = await client.post(
            f"/api/v1/documents/upload/{thread_id}",
            files={"file": (file.name, file.getvalue(), file.type)},  # 字段名"file"和后端 UploadFile 对齐
        )
        return r.json() if r.status_code < 400 else None


async def list_documents(thread_id: str) -> list | None:
    """该会话的文档列表。"""
    return await _request_json("GET", f"/api/v1/documents/{thread_id}")


async def delete_document(document_id: str) -> dict | None:
    """删除文档。"""
    return await _request_json("DELETE", f"/api/v1/documents/{document_id}")


# ===== 聊天 =====


async def get_chat_history(thread_id: str) -> list | None:
    """聊天记录（没聊过的会话 → 404 → None）。"""
    return await _request_json("GET", f"/api/v1/chat/{thread_id}")