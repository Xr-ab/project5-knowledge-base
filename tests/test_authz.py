"""tests/test_authz.py —— 越权防护的负向测试。

重点不是"有没有返回 404"——404 太容易误判：记录本来不存在也会 404。
真正要断言的是：**越权请求在破坏发生之前就被拦住**，
所以向量删除函数一次都不能被调用。

这两个用例合起来才有意义：
  - 拦住别人（B 删 A 的文档 → 404 且什么都没动）
  - 放行自己（A 删自己的 → 200 且该做的都做了）
只测前一半，等于把门焊死也能通过。
"""
import os
import uuid

# ⚠️ 必须在 import app 之前：app.config 模块级会构造 Settings()（必填字段）
os.environ.setdefault("LLM_API_KEY", "env-test-key")
os.environ.setdefault("BOCHA_API_KEY", "env-test-bocha")

from fastapi.testclient import TestClient

from app.db.main import get_session
from app.db.models import Document, Thread
from app.main import app
from app.security import create_access_token


class _Result:
    """假的查询结果：把事先准备好的对象原样交回去。"""

    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar_one(self):
        return self._value


class _ScriptedSession:
    """按"查哪张表"回答的假会话（脚本化替身）。

    查 documents → 交出给定文档（模拟"记录确实存在"）
    查 threads  → 交出给定会话或 None（模拟归属命不命中）

    故意不去数调用次数：代码中间多插一次查询时，
    数次数会假绿或假红；按实体回答不会。
    """

    def __init__(self, document=None, thread=None):
        self.document = document
        self.thread = thread
        self.added: list[object] = []
        self.deleted: list[object] = []

    async def execute(self, stmt):
        entity = stmt.column_descriptions[0]["entity"]  # 这条 SELECT 在查哪个模型
        if entity is Thread:
            return _Result(self.thread)
        raise AssertionError(f"测试未预期的查询实体: {entity}")

    async def get(self, entity, pk):
        # 注意：文档是按主键查的（repository.get_document_by_id 用的是 session.get），
        # 会话却是走 select().where()——同一项目里两种查法并存，假对象两样都得支持。
        if entity is Document:
            return self.document
        if entity is Thread:
            return self.thread
        raise AssertionError(f"测试未预期的实体: {entity}")

    def add(self, obj):
        self.added.append(obj)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def commit(self):
        # 模拟真实行为：主键 default 是 INSERT 时才生成，不补这一下对象就一直是 id=None
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    async def refresh(self, obj):
        pass


def _client_with(session) -> TestClient:
    """装好假会话的测试客户端。调用方负责在 finally 里 clear 覆盖。"""

    async def _override():
        yield session

    app.dependency_overrides[get_session] = _override
    return TestClient(app)


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    """造一个属于该用户的合法 token。"""
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}


def _spy_chunk_delete(monkeypatch) -> list:
    """把向量删除换成记录器：返回一个列表，调用一次就多一个元素。"""
    calls: list = []

    async def _fake(document_id):
        calls.append(document_id)

    monkeypatch.setattr("app.documents.routes.delete_document_chunks", _fake)
    return calls


def test_other_user_cannot_delete_document(monkeypatch):
    """B 拿 A 的 document_id 删除 → 404，且向量与数据库记录都没被碰。

    关键构造：文档必须真实存在（属于 A），否则 404 的理由变成
    "记录不存在"，就证明不了归属校验起作用了。
    """
    a_id, b_id = uuid.uuid4(), uuid.uuid4()
    thread_id, doc_id = uuid.uuid4(), uuid.uuid4()

    a_doc = Document(id=doc_id, file_name="a.txt", thread_id=thread_id)
    # 文档能查到，但按 B 的 user_id 查会话查不到 → 归属校验该拦下
    session = _ScriptedSession(document=a_doc, thread=None)
    chunk_calls = _spy_chunk_delete(monkeypatch)

    client = _client_with(session)
    try:
        r = client.delete(f"/api/v1/documents/{doc_id}", headers=_auth(b_id))
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 404
    assert chunk_calls == []      # 核心：破坏没有发生
    assert session.deleted == []  # 数据库记录同样没被删


def test_owner_can_delete_document(monkeypatch):
    """A 删自己的文档 → 200，向量删除正好被调用一次。"""
    a_id = uuid.uuid4()
    thread_id, doc_id = uuid.uuid4(), uuid.uuid4()

    a_doc = Document(id=doc_id, file_name="a.txt", thread_id=thread_id)
    a_thread = Thread(id=thread_id, user_id=a_id, title="A 的会话")
    session = _ScriptedSession(document=a_doc, thread=a_thread)
    chunk_calls = _spy_chunk_delete(monkeypatch)

    client = _client_with(session)
    try:
        r = client.delete(f"/api/v1/documents/{doc_id}", headers=_auth(a_id))
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    assert chunk_calls == [doc_id]     # 放行时该做的做了
    assert len(session.deleted) == 1   # 数据库记录被删一次


def test_upload_filename_traversal_is_sanitized(monkeypatch):
    """上传文件名带 ../ 时：展示名被清洗，落盘名换成 uuid，不跳出 tmp 目录。"""
    a_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    a_thread = Thread(id=thread_id, user_id=a_id, title="A 的会话")
    session = _ScriptedSession(thread=a_thread)
    recorded = {}

    async def fake_process(document_id, temp_path, thread_id, file_name):
        # 换成记录器：真实的 process_document 会去碰 Chroma，测试里不需要
        recorded["file_name"] = file_name
        recorded["temp_path"] = temp_path

    monkeypatch.setattr("app.documents.routes.process_document", fake_process)

    client = _client_with(session)
    try:
        r = client.post(
            f"/api/v1/documents/upload/{thread_id}",
            headers=_auth(a_id),
            files={"file": ("../../evil.txt", b"hello", "text/plain")},
        )
    finally:
        app.dependency_overrides.clear()
        leftover = recorded.get("temp_path")
        if leftover is not None and leftover.exists():
            leftover.unlink()

    assert r.status_code == 202
    assert r.json()["file_name"] == "evil.txt"          # 只留最后一段
    assert recorded["file_name"] == "evil.txt"          # 传给后台的也是干净名字
    assert recorded["temp_path"].parent.name == "tmp"   # 没跳出 tmp 目录
    assert recorded["temp_path"].name != "evil.txt"     # 落盘名是 uuid，不是用户给的
    assert session.added[0].file_name == "evil.txt"     # 数据库存展示名
