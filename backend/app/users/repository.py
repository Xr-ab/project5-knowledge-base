"""repository.py —— 用户数据访问层。只写数据操作，不做业务判断。"""
from sqlalchemy import select    # 写查询用
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import User

async def create_user(username: str, password_hash: str, session: AsyncSession) -> User:
    """注册：把用户名 + 哈希后的密码存库。返回建好的 User 对象。"""
    user = User(
        username=username,
        password_hash=password_hash,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user

async def get_user_by_username(username: str, session: AsyncSession) -> User | None:
    """按用户名查用户。注册（查重）和登录（比对）都用它。查不到返回 None。"""
    stmt = select(User).where(User.username == username)  # SELECT ... WHERE username = ?
    result = await session.execute(stmt)
    return result.scalar_one_or_none()  # 给"一个值或 None"——正好符合"查不到返回 None"
