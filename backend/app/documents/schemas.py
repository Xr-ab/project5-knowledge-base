"""documents/schemas.py —— 文档接口的请求/响应模型。

（注意：这个文件在 documents/ 包下，不在 db/ 下——db/ 管数据库，
documents/ 管 HTTP 接口，schemas 属于接口这一侧。）
"""
import uuid
from datetime import datetime

from pydantic import BaseModel


class DocumentBase(BaseModel):
    """上传登记/响应共用的基础字段：文件名 + 属于哪个会话。"""
    file_name: str
    thread_id: uuid.UUID


class DocumentPublic(BaseModel):
    """返回给前端的文档信息：id + 文件名 + 会话 + 上传时间。"""
    id: uuid.UUID
    file_name: str
    thread_id: uuid.UUID
    uploaded_at: datetime

    model_config = {"from_attributes": True}  # 允许从 ORM 对象构造（FastAPI 转换用）


class DocumentUploadResponse(DocumentBase):
    """上传成功的响应：继承基础字段 + 新的 document_id + 消息。

    继承 DocumentBase = 响应里必须带上 file_name/thread_id，
    路由返回时要提供全（参考书是独立类，这里用继承省两行——取舍合理）。
    """
    document_id: uuid.UUID
    message: str


class DocumentDeleteResponse(BaseModel):
    """删除成功的响应。"""
    message: str
