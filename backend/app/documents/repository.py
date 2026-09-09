"""repository.py —— 数据访问层。只写"怎么写查询"，不做业务判断（不抛异常）。"""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document
from app.documents.schemas import DocumentBase


async def get_documents_by_thread(thread_id: uuid.UUID, session: AsyncSession) -> Sequence[Document]:
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
    await session.refresh(new_document)  # uploaded_at 是 server_default，commit 后不 refresh 读不到
    return new_document


async def get_document_by_id(document_id: uuid.UUID, session: AsyncSession) -> Document | None:
    """按主键查单条；查不到返回 None，不抛异常。"""
    return await session.get(Document, document_id)
