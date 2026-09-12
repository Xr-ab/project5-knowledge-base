"""repository.py —— 数据访问层。只写"怎么写查询"，不做业务判断（不抛异常）。"""

import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Thread

async def create_thread(user_id: uuid.UUID, session: AsyncSession) -> Thread:
    """挪 service.py 第 18-24 行：建对象 + add + commit + refresh。返回 Thread。"""
    thread = Thread(user_id=user_id)  # 创建时写入归属人
    session.add(thread)
    await session.commit()
    await session.refresh(thread)
    return thread

async def get_all_threads(user_id: uuid.UUID, session: AsyncSession) -> list[Thread]:
    """挪 service.py 第 29-31 行：select + execute + scalars().all()。只查该用户的会话。"""
    stmt = select(Thread).where(Thread.user_id == user_id).order_by(Thread.created_at.desc())  # SELECT ... WHERE user_id=? ORDER BY 最新在前
    result = await session.execute(stmt)  # 执行查询（异步，等数据库）
    return list(result.scalars().all())  # .scalars() 取"一行行对象"，.all() 拉全量，转列表

async def get_thread_by_id(thread_id: uuid.UUID, user_id: uuid.UUID, session: AsyncSession) -> Thread | None:
    """按 id + 归属人查：两条条件都命中才算数。查不到（不存在或不是你的）返回 None，不抛异常。"""
    stmt = select(Thread).where(Thread.id == thread_id, Thread.user_id == user_id)  # 隔离核心：WHERE 里带归属
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
    