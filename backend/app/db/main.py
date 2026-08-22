"""db/main.py —— 数据库引擎与会话管理（ORM 的接线处）。"""
from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from typing import Annotated

from app.config import settings
from app.db.models import Base


# 引擎：连接数据库的"总管道"，懒加载——不真正连接，等第一次使用时才建连接
engine: AsyncEngine = create_async_engine(url=settings.database_uri)

# SQLite 默认不执行外键约束（参考书用 Postgres 没这问题）。
# 每次连接数据库时手动打开，ondelete="CASCADE" 才能生效。
# 注意：必须写在 engine 定义之后——装饰器在 import 时就要取 engine.sync_engine。
@event.listens_for(engine.sync_engine, "connect")
def _enable_sqlite_fk(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


# 会话工厂：每次需要会话时，从 engine 的连接池里取一个，包装成 session
async_session: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    expire_on_commit=False,  # commit 后对象上的属性还能访问（默认会过期，访问要重新查库）
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：每个请求给一个独立会话，请求结束自动关闭。"""
    async with async_session() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]
# 类型别名：路由函数里写 session: SessionDep，
# FastAPI 看到它就知道"这个参数从 get_session 拿"，自动注入会话


async def init_db() -> None:
    """启动时调用：按 models.py 里的类建表（表已存在则跳过）。"""
    async with engine.begin() as conn:      # 开启一个事务
        await conn.run_sync(Base.metadata.create_all)  # run_sync: 把同步的建表代码丢到数据库线程跑
