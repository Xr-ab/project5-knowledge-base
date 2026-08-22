"""middleware.py —— 注册中间件（目前只有 CORS）。"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def register_middleware(app: FastAPI):
    # 前端在 8501、后端在 8000 → 跨域，浏览器默认拦。v1 全部放行，
    # 部署前收紧到前端真实地址（见规范 §7.6）。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )