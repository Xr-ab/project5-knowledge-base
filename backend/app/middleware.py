"""middleware.py —— 注册中间件（CORS + 请求日志）。

中间件 = 安检门：每个请求进来/出去都经过这里，与具体路由无关。
"""
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger


def register_middleware(app: FastAPI):
    # CORS：前端在 8501、后端在 8000 → 跨域，浏览器默认拦。v1 全部放行，
    # 部署前收紧到前端真实地址（见规范 §7.6）。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 请求日志中间件：每个请求打印 方法 + 路径 + 状态码 + 耗时(ms)
    @app.middleware("http")
    async def request_logger(request: Request, call_next):
        start = time.perf_counter()          # 请求进来时记开始时间
        response = await call_next(request)  # 放行，等路由处理完
        duration = (time.perf_counter() - start) * 1000
        logger.info(f"{request.method} {request.url.path} -> {response.status_code} ({duration:.0f}ms)")
        return response
