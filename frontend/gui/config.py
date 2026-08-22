"""frontend/gui/config.py —— 前端配置（只需知道后端在哪）。"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
# 前端在 frontend/gui/config.py → 上两级 = 项目根（和 backend 共用同一个 .env）
BASE_DIR = Path(__file__).resolve().parent.parent.parent

class Settings(BaseSettings):
    backend_base_url: str = "http://localhost:8000"
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="allow")

settings = Settings()
