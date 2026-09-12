"""users/service.py —— 注册/登录的业务逻辑（纯逻辑不含 HTTP）。"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.exceptions import ConflictError, NotFoundError
from app.security import hash_password, verify_password, create_access_token
from app.users.repository import create_user, get_user_by_username

async def register_user(username: str, password: str, session: AsyncSession) -> User:
    """注册：用户名唯一 → 密码哈希入库。"""
    existing = await get_user_by_username(username, session)
    if existing:
        raise ConflictError(f"用户名 {username} 已被注册")
    password_hash = hash_password(password)
    return await create_user(username, password_hash, session)

async def login_user(username: str, password: str, session: AsyncSession) -> str:
    """登录：校验密码，返回 JWT。"""
    user = await get_user_by_username(username, session)
    if not user:
        raise NotFoundError("用户名或密码错误")   # 统一 404
    if not verify_password(password, user.password_hash):
        raise NotFoundError("用户名或密码错误")   # 同一个错，同一个状态码
    return create_access_token(str(user.id))
