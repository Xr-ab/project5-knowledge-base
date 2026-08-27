"""security.py —— JWT 签发与校验（新增文件，不动任何现有逻辑）。

角色：所有需要登录的接口，挂上 get_current_user 这一层依赖。
"""
import datetime

import jwt  # pip install pyjwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

# HTTPBearer：FastAPI 标准组件，从请求头提取 "Authorization: Bearer <token>"
# auto_error=False：没带 token 时不自动抛错，让我们自己控制报错
bearer_scheme = HTTPBearer(auto_error=False)

def create_access_token(user_id: str) -> str:
    """签发 JWT：把用户 id + 过期时间塞进 payload，用密钥签名。"""
    payload = {
        "sub": user_id,  # sub = 主体（标准字段），存用户 id
        # 过期时间 = 现在 + 24 小时；必须用 UTC 时间
        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=24),
    }
    # encode 三件套：payload + 密钥 + 算法（HS256 = 对称签名）
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")

def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    """FastAPI 依赖：从请求头拿 token → 验签 → 返回用户 id；失败抛 401。"""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录：缺少 Authorization 头")
    try:
        # decode 会同时验签名 + 查过期，任一不过就抛异常
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token 无效或已过期")
    return payload["sub"]  # 验签通过，把用户 id 交给接口用