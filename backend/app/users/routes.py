"""users/routes.py —— 认证接口（注册/登录）。"""
from fastapi import APIRouter

from app.db.main import SessionDep
from app.users import service
from app.users.schemas import RegisterRequest, UserPublic, LoginResponse

auth_router = APIRouter()

@auth_router.post("/register", response_model=UserPublic, status_code=201)
async def register(body: RegisterRequest, session: SessionDep):
    """注册新用户。"""
    return await service.register_user(body.username, body.password, session)

@auth_router.post("/login", response_model=LoginResponse)
async def login(body: RegisterRequest, session: SessionDep):
    """登录，返回 JWT。"""
    token = await service.login_user(body.username, body.password, session)
    return LoginResponse(access_token=token)
