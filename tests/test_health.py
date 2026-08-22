"""test_health.py —— 验证路由挂载。"""
import os

# ⚠️ 模块 1 的坑第二次出现了：import app.main → app.lifespan → app.config，
# config 模块级 settings = Settings() 会立即执行，必须先给环境变量
os.environ["DEEPSEEK_API_KEY"] = "test-key"
os.environ["BOCHA_API_KEY"] = "test-bocha"

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}