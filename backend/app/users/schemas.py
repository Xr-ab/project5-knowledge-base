from pydantic import BaseModel, Field
import uuid
from datetime import datetime

class RegisterRequest(BaseModel):
    """注册请求体：用户名 + 密码。"""
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=100)

class UserPublic(BaseModel):
    """返回给前端的用户长相（不含 hash！）。"""
    id: uuid.UUID
    username: str
    created_at: datetime
    model_config = {"from_attributes": True}

class LoginResponse(BaseModel):
    """登录成功的响应：就一个 access_token。"""
    access_token: str = Field(description="JWT 访问令牌")