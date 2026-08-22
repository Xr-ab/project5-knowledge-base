"""documents/service.py —— 文档的业务层（数据库记录 CRUD，纯逻辑不含 HTTP）。

注意职责边界：这里只管 SQLite 里的"文档登记记录"，
向量库（Chroma）的存取在 db/vector_store.py——两者由路由层编排。
"""
import uuid
from collections.abc import Sequence

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document
from app.documents.schemas import DocumentBase


async def get_documents(thread_id: uuid.UUID, session: AsyncSession) -> Sequence[Document]:
    """列出该会话下的所有文档（按上传时间倒序，最新的在前）。"""
    stmt = (
        select(Document)
        .where(Document.thread_id == thread_id)
        .order_by(Document.uploaded_at.desc())
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def insert_document(document_data: DocumentBase, session: AsyncSession) -> Document:
    """登记一条文档记录。"""
    new_document = Document(**document_data.model_dump())  # Pydantic 对象 → dict → 展开成关键字参数
    session.add(new_document)
    await session.commit()
    await session.refresh(new_document)
    # 参考书漏了上面这行 refresh——uploaded_at 是 server_default，
    # 数据库填的时间 commit 后不刷新对象上读不到（模块 3 学过的坑，这里复现）。
    return new_document


async def delete_document(document_id: uuid.UUID, session: AsyncSession) -> None:
    """删除文档登记记录（不存在 → 404）。"""
    db_document = await session.get(Document, document_id)
    if db_document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} not found.",
        )
    await session.delete(db_document)
    await session.commit()