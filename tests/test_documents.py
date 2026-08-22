"""test_documents.py —— 文档模块测试：切片逻辑 + 向量库索引 + 数据库 CRUD。"""
import os
import uuid

# 老规矩：import 前先给环境变量
os.environ["DEEPSEEK_API_KEY"] = "test-key"
os.environ["BOCHA_API_KEY"] = "test-bocha"

import pytest
import chromadb
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base
from app.db.vector_store import (
    _split_text,
    delete_document_chunks,
    index_document,
    search_chunks,
)
from app.documents import service as document_service
from app.documents.schemas import DocumentBase


# ---------- ① 切片纯函数：验证重叠逻辑 ----------
def test_split_text_overlap():
    text = "啊" * 2500  # 2500 字，1000 字一片、200 字重叠 → 应该切出 3 片
    chunks = _split_text(text, chunk_size=1000, chunk_overlap=200)
    assert len(chunks) == 3
    # 重叠验证：第 2 片开头必须等于第 1 片末尾的 200 字
    assert chunks[1].startswith(chunks[0][-200:])


# ---------- ② 向量库：索引 → 搜索 → 隔离 → 删除（注入临时库） ----------
@pytest.fixture
def tmp_collection(tmp_path):
    """自己定义的 fixture：每次测试给一个全新临时向量库（用完自动删）。"""
    client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    return client.get_or_create_collection("test", metadata={"hnsw:space": "cosine"})


async def test_index_search_delete_roundtrip(tmp_path, tmp_collection):
    doc = tmp_path / "笔记.txt"
    doc.write_text("向量数据库专门存向量，按相似度检索。" * 200, encoding="utf-8")

    tid = uuid.uuid4()
    did = uuid.uuid4()
    n = await index_document(doc, did, tid, collection=tmp_collection)
    assert n > 1  # 长文本应该切成多片

    # 同会话搜得到；异会话搜不到（隔离性）
    hits = await search_chunks("向量数据库是什么", tid, k=2, collection=tmp_collection)
    assert hits
    other = await search_chunks("向量数据库是什么", uuid.uuid4(), k=2, collection=tmp_collection)
    assert not other

    # 按 document_id 删片 → 库清空
    await delete_document_chunks(did, collection=tmp_collection)
    assert tmp_collection.count() == 0


# ---------- ③ 数据库 CRUD（tmp sqlite，模块 3 同款套路） ----------
async def test_document_crud(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        tid = uuid.uuid4()
        doc = await document_service.insert_document(
            DocumentBase(file_name="a.txt", thread_id=tid), session
        )
        assert doc.id is not None  # 数据库填的 id 有了

        got = await document_service.get_documents(tid, session)
        assert [d.id for d in got] == [doc.id]  # 按会话能查到

        await document_service.delete_document(doc.id, session)
        assert await document_service.get_documents(tid, session) == []  # 删后查空

        with pytest.raises(Exception):  # 再删一次 → 404
            await document_service.delete_document(doc.id, session)
    await engine.dispose()