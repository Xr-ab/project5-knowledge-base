"""repository.py —— 数据访问层。只写"怎么写查询"，不做业务判断（不抛异常）。"""

import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Thread

async def create_thread(session: AsyncSession) -> Thread:
    """挪 service.py 第 18-24 行：建对象 + add + commit + refresh。返回 Thread。"""
    thread = Thread()
    session.add(thread)
    await session.commit()
    await session.refresh(thread)
    return thread

async def get_all_threads(session: AsyncSession) -> list[Thread]:
    """挪 service.py 第 29-31 行：select + execute + scalars().all()。"""
    stmt = select(Thread).order_by(Thread.created_at.desc())  # SELECT ... ORDER BY 最新在前
    result = await session.execute(stmt)  # 执行查询（异步，等数据库）
    return list(result.scalars().all())  # .scalars() 取"一行行对象"，.all() 拉全量，转列表

async def get_thread_by_id(thread_id: uuid.UUID, session: AsyncSession) -> Thread | None:
    """挪 service.py 第 36 行：session.get。查不到返回 None，不抛异常。"""
    thread = await session.get(Thread, thread_id)
    return thread
    