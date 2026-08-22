"""db/checkpointer.py —— 聊天记忆的存档器（参考书的 Postgres 换成 SQLite）。

实测发现新版库的用法（v1 已踩过坑，见注释）：
- from_conn_string 返回的是【异步上下文管理器】不是对象，必须 async with 使用
- 参数是【纯路径字符串】，不能带 sqlite+aiosqlite:/// 前缀（会被当成文件名）
- 不需要手动 setup()，第一次存数据时自动建表
"""
from collections.abc import AsyncIterator

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.config import settings


def get_checkpointer() -> AsyncIterator[AsyncSqliteSaver]:
    """返回"存档器上下文管理器"——service 层用 async with 包住整个流式过程。

    async with 进入 → 打开 SQLite 连接；退出 → 自动关闭。
    生命周期必须覆盖流式输出的全过程，所以由调用方负责包一层。
    """
    path = settings.data_dir / "checkpoints.db"  # 聊天记忆存在这里（和 app.db 同目录）
    path.parent.mkdir(parents=True, exist_ok=True)  # 首次运行确保目录存在
    return AsyncSqliteSaver.from_conn_string(str(path))
