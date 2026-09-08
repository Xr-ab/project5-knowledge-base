"""threads/service.py —— 会话的增删改查（业务层，纯逻辑不含 HTTP）。

分层职责：routes 管 HTTP 长相，service 管业务逻辑（怎么用 session 跟数据库对话）。
所以这里的 session 是"别人递进来的"（FastAPI 依赖注入），service 自己不创建。
"""
import uuid  # UUID 类型注解

from app.exceptions import NotFoundError  # 业务异常（找不到 → 404）
from loguru import logger
from sqlalchemy import select  # 构造查询语句（SELECT ...）
from sqlalchemy.ext.asyncio import AsyncSession  # 异步会话类型（类型注解用）

from app.db.checkpointer import get_checkpointer  # 聊天记忆存档器（删会话时要一起清）
from app.db.models import Thread
from app.threads.schemas import ThreadUpdate


async def create_new_thread(session: AsyncSession) -> Thread:
    """新建会话：标题用模型默认值 "New Chat"。"""
    thread = Thread()  # 建对象，id/title/created_at 都用模型里的默认值
    session.add(thread)  # 加入工作区（注意：还没写库！）
    await session.commit()  # commit 才真正写入数据库（漏了它 = 数据不生效的经典坑）
    await session.refresh(thread)  # 重新从库里读一遍，拿到数据库填的字段（created_at）
    return thread


async def get_user_threads(session: AsyncSession) -> list[Thread]:
    """列出全部会话（v1 单用户，不用按 user 过滤）。"""
    stmt = select(Thread).order_by(Thread.created_at.desc())  # SELECT ... ORDER BY 最新在前
    result = await session.execute(stmt)  # 执行查询（异步，等数据库）
    return list(result.scalars().all())  # .scalars() 取"一行行对象"，.all() 拉全量，转列表


async def get_thread(thread_id: uuid.UUID, session: AsyncSession) -> Thread:
    """查单个会话；不存在 → 404。"""
    thread = await session.get(Thread, thread_id)  # 按主键查（比 select 快且短），查不到返回 None
    if not thread:
        raise NotFoundError("Thread not found")  # 业务异常 → 全局 handler 翻译成 404
    return thread


async def update_thread(thread_update: ThreadUpdate, thread_id: uuid.UUID, session: AsyncSession) -> Thread:
    """改标题：先查（404），再改，再提交。"""
    thread = await get_thread(thread_id, session)  # 复用 get_thread → 查不到自动 404，不用重复写
    thread.title = thread_update.title  # 改字段（改对象即可，不用 add——它已在工作区里）
    await session.commit()  # 提交生效
    await session.refresh(thread)  # 拿最新状态
    return thread


async def delete_thread(thread_id: uuid.UUID, session: AsyncSession) -> None:
    """删除会话：先删数据库记录，再清聊天记忆（checkpointer）——两处都要删，否则孤儿记忆残留。

    以前只删数据库，checkpoints.db 里该会话的历史还在；删完再拿同 id 问问题会读到旧记忆。
    """
    thread = await get_thread(thread_id, session)  # 查不到自动 404
    await session.delete(thread)  # 标记删除（和 add 一样，未提交不生效）
    await session.commit()  # 提交生效

    # 清该会话的聊天记忆：AsyncSqliteSaver 提供 adelete_thread
    # 清理失败不阻断删除（会话已删成功是主目标，残留记忆是次生问题）
    async with get_checkpointer() as checkpointer:
        try:
            await checkpointer.adelete_thread(str(thread_id))
        except Exception:
            logger.exception(f"清理会话 {thread_id} 的记忆失败（可忽略，会话本身已删除）")
