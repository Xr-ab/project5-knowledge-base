"""db/models.py —— 数据库表结构定义（ORM 模型）。

ORM 的核心思想：一张数据库表 = 一个 Python 类。
这里的每个类都会被 SQLAlchemy 翻译成 CREATE TABLE 语句。
"""
import uuid  # 生成 UUID 主键（全局唯一 ID，不怕多进程冲突）
from datetime import datetime  # created_at 列的类型

from sqlalchemy import ForeignKey, String, func
# ForeignKey: 外键（指向另一张表的主键）；String: 定长字符串列类型；func: 调用 SQL 函数（如 now()）
from sqlalchemy.ext.asyncio import AsyncAttrs
# 异步支持：让模型在 async 环境里也能安全懒加载关联对象（现在还没用到，先挂着）
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
# DeclarativeBase: 声明式基类；Mapped: 用类型注解声明列；mapped_column: 列的具体配置


class Base(AsyncAttrs, DeclarativeBase):
    """所有模型共享的基类。SQLAlchemy 通过它扫描"哪些类建表"。

    建表时用 Base.metadata.create_all(engine)，
    它会把所有继承 Base 的类（Thread 等）都找出来，批量建表。
    """
    pass


class Thread(Base):
    """对话线程表——一个"档案袋"，后面 documents/chat 都挂它身上。"""
    __tablename__ = "threads"  # 表名（显式写，不依赖默认命名）

    # 主键：UUID 类型，不传值时 Python 自动生成（default 是 Python 侧干活）
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # 标题：最长 100 字符，不传值时默认 "New Chat"
    title: Mapped[str] = mapped_column(String(100), default="New Chat")
    # 创建时间：server_default 是数据库侧干活——INSERT 时数据库自己填当前时间
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Document(Base):
    """上传的文档表：每份文档挂在一个会话下。"""
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    file_name: Mapped[str] = mapped_column(String(255))
    thread_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE"),  # 外键：指回 threads 表的主键
        index=True,  # 给这列建索引：按会话查文档是高频操作，索引提速
    )
    uploaded_at: Mapped[datetime] = mapped_column(server_default=func.now())