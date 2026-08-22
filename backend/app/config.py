"""config.py —— 全项目的"配置总开关"（单一真相来源）。

所有外部信息（API Key、模型名、目录路径）只从这里取，
代码里不出现第二处硬编码的配置值。
"""
import logging
from pathlib import Path  # 路径对象：跨平台，比字符串拼接安全

from loguru import logger  # 第三方日志库：好看 + 自动轮转压缩
from pydantic import Field, SecretStr
# Field: 字段配置（别名等）；SecretStr: 密钥类型，打印自动打码成 ******
from pydantic_settings import BaseSettings, SettingsConfigDict
# BaseSettings: 配置类的父类（自动读环境变量/.env）；
# SettingsConfigDict: 行为配置（从哪个文件读等）

# 项目根目录：config.py 在 backend/app/ 下，往上三级 = 项目根
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# 日志目录：根目录/logs，不存在就先建（启动前日志就绪）
LOGS_DIR = BASE_DIR / "logs"
if not LOGS_DIR.exists():
    LOGS_DIR.mkdir()

# 标准库日志开关（第三方库如 OpenAI 的日志走这里，设为 INFO 才看得到）
logging.basicConfig(
    level=logging.INFO,  # For displaying the default model calling logs
)

# loguru 日志：每天一个文件，00:00 轮转，留 7 天，压成 zip 省空间
logger.add(
    sink=LOGS_DIR / "api_{time:YYYYMMDD}.log",
    level="INFO",
    rotation="00:00",
    retention="7 days",
    compression="zip",
)


class Settings(BaseSettings):
    """配置类：每个字段 = 一个外部配置项。

    取值优先级：构造参数 > 环境变量 > .env 文件。
    声明字段但不写默认值（api_key/bocha_api_key）= 必填，
    缺失时构造 Settings() 立即报错（早失败，不拖到运行期才炸）。
    """
    api_key: SecretStr = Field(alias="DEEPSEEK_API_KEY")  # DeepSeek 大模型 Key（必填）
    model_provider: str = "openai"                        # 走 OpenAI 兼容协议接 DeepSeek
    model_name: str = "deepseek-v4-flash"                 # 模型名
    model_base_url: str | None = "https://api.deepseek.com/v1"  # DeepSeek 的 API 地址
    embeddings_model_name: str = "BAAI/bge-small-zh-v1.5"  # 本地向量模型（模块 4 用，无需 key）
    bocha_api_key: str                                    # 博查搜索 Key（必填，模块 5 用）
    data_dir: Path = BASE_DIR / "outputs"                 # 数据落盘目录（数据库/向量库都在这）

    # 从项目根目录 .env 读值；extra="allow" 容忍文件里多余键
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="allow")

    @property
    def database_uri(self) -> str:
        """SQLite 连接串（v1 用本地文件，不引数据库服务器）。

        用 property 而不是字段：地址由 data_dir 推导，只有一个真相来源，
        不会出现手填路径和 data_dir 打架的情况。
        .as_posix()：Windows 反斜杠路径转成 /，SQLite URL 只认正斜杠。
        """
        return f"sqlite+aiosqlite:///{(self.data_dir / 'app.db').as_posix()}"
    @property
    def chroma_dir(self) -> Path:
        """向量库目录（Chroma 数据落盘位置，在 outputs/ 下）。"""
        return self.data_dir / "chroma"

# 模块级单例：全项目 import settings 拿到的都是同一个实例
# （type: ignore 是告诉类型检查器：pydantic 的动态字段它看不懂，跳过）
settings = Settings()  # type: ignore
