"""documents/service.py —— 文档的业务层（数据库记录 CRUD，纯逻辑不含 HTTP）。

注意职责边界：这里只管 SQLite 里的"文档登记记录"，
向量库（Chroma）的存取在 db/vector_store.py——两者由路由层编排。
"""
import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document
from app.documents.schemas import DocumentBase
from app.documents.repository import (
    get_documents_by_thread,
    insert_document as repo_insert_document,  # 别名：和本文件的 insert_document 区分开
    get_document_by_id,
)
from app.exceptions import NotFoundError  # 业务异常（找不到 → 404）
from app.threads.service import get_thread  # 复用会话归属校验（文档通过 thread 间接归属）


async def ensure_thread_owned(thread_id: uuid.UUID, user_id: uuid.UUID, session: AsyncSession) -> None:
    """校验"这个会话是你的"——不是你的 → 404（get_thread 内部抛）。

    documents 没有 user_id 列，归属是间接的：文档 → thread_id → 会话的归属人。
    上传/列表/删除前先验会话归属，是文档隔离的入口。
    """
    await get_thread(thread_id, user_id, session)


async def get_documents(thread_id: uuid.UUID, user_id: uuid.UUID, session: AsyncSession) -> Sequence[Document]:
    """列出某会话下的文档：先确认这个会话是你的（404），再列文档。"""
    await ensure_thread_owned(thread_id, user_id, session)  # 隔离入口：不是你的会话直接 404
    return await get_documents_by_thread(thread_id, session)  # 查询语句在 repository


async def insert_document(document_data: DocumentBase, session: AsyncSession) -> Document:
    """登记一条文档记录。"""
    return await repo_insert_document(document_data, session)  # 建记录的细节在 repository


async def delete_document(document_id: uuid.UUID, user_id: uuid.UUID, session: AsyncSession) -> None:
    """删除文档：先拿文档 → 用文档身上的 thread_id 验归属 → 再删（不存在 → 404）。"""
    db_document = await get_document_by_id(document_id, session)  # 查库交给 repository
    if db_document is None:
        raise NotFoundError(f"Document with ID {document_id} not found.")  # 业务判断留在 service
    await ensure_thread_owned(db_document.thread_id, user_id, session)  # 文档没有 user_id，绕会话验归属
    await session.delete(db_document)
    await session.commit()
