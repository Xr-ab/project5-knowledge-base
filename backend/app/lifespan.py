"""lifespan.py —— 应用启动/关闭钩子。

yield 前 = 启动时要做的事（建目录、建表）；yield 后 = 关闭时要做的事。
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from app.config import settings
from app.db.main import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("应用启动，准备目录...")
    settings.data_dir.mkdir(parents=True, exist_ok=True)  # 建 outputs/，已存在就跳过
    await init_db()  # 建表（表已存在则跳过，幂等）
    yield
    logger.info("应用关闭")