"""threads/schemas.py —— 会话接口的请求/响应模型（长相合同）。

和 config.py 的 Settings 一样都是 Pydantic 模型，但职责不同：
Settings 管"配置输入"，这里的类管"API 输入输出"。
FastAPI 拿它们做两件事：请求体校验（不合格自动 400）+ 响应裁剪（只露声明的字段）。
"""
import uuid  # UUID 类型（thread 主键）
from datetime import datetime  # 时间戳类型

from pydantic import BaseModel, Field
# BaseModel: Pydantic 模型基类；Field: 字段级配置（长度限制、默认值等）


class ThreadUpdate(BaseModel):
    """改标题的请求体：只收一个 title。"""
    title: str = Field(min_length=1, max_length=100)  # 空标题/超长标题 → FastAPI 自动 400


class ThreadPublic(BaseModel):
    """返回给前端的线程长相：只露这三个字段。

    即使 Thread 表将来加了别的字段，只要不写进这里，前端就看不到——
    这就是"表结构"和"对外形象"解耦。
    """
    id: uuid.UUID
    title: str
    created_at: datetime

    # 关键配置：允许从 ORM 对象构造（response_model=ThreadPublic 时，
    # FastAPI 把你查出来的 Thread 对象直接往里塞）。没有它响应会 500。
    model_config = {
        "from_attributes": True,
    }
