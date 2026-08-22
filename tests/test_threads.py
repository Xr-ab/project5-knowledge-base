"""test_threads.py —— service 层 CRUD 测试（临时 sqlite，不碰真实数据）。"""
import os

# 老规矩：import 前先给环境变量（config 模块级 Settings() 会立即执行）
os.environ["DEEPSEEK_API_KEY"] = "test-key"
os.environ["BOCHA_API_KEY"] = "test-bocha"

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base
from app.threads import service as thread_service
from app.threads.schemas import ThreadUpdate


async def test_thread_crud(tmp_path):
    # ① 临时数据库：建在 pytest 的 tmp_path 里（用完自动清理），绝不碰 outputs/
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)  # 按 models.py 建表
    factory = async_sessionmaker(engine, expire_on_commit=False)

    # ② 会话：测试里自己建（不经过 FastAPI 注入），用完手动关
    async with factory() as session:
        # 创建：不传参数 → 默认标题
        t = await thread_service.create_new_thread(session)
        assert t.title == "New Chat"

        # 查询：能按 id 查到
        got = await thread_service.get_thread(t.id, session)
        assert got.id == t.id

        # 修改：标题改掉
        updated = await thread_service.update_thread(ThreadUpdate(title="我的研究"), t.id, session)
        assert updated.title == "我的研究"

        # 删除：删后再查 → 404
        await thread_service.delete_thread(t.id, session)
        with pytest.raises(Exception):
            await thread_service.get_thread(t.id, session)

    await engine.dispose()  # ③ 关引擎（释放连接），测试结束