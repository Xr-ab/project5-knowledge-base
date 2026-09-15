"""config.py —— 全项目的"配置总开关"（单一真相来源）。

所有外部信息（API Key、模型名、目录路径）只从这里取，
代码里不出现第二处硬编码的配置值。
"""
import logging
import os  # 读环境变量（容器里用 DATA_DIR/PROJECT_ROOT 覆盖默认路径）
from pathlib import Path  # 路径对象：跨平台，比字符串拼接安全

from loguru import logger  # 第三方日志库：好看 + 自动轮转压缩
from pydantic import Field, SecretStr
# Field: 字段配置（别名等）；SecretStr: 密钥类型，打印自动打码成 ******
from pydantic_settings import BaseSettings, SettingsConfigDict
# BaseSettings: 配置类的父类（自动读环境变量/.env）；
# SettingsConfigDict: 行为配置（从哪个文件读等）

# 项目根目录：默认按源码路径向上推 3 层（裸机时 = 项目根）
# 但容器里源码层级是 /app/app/config.py（向上3层=/），必须靠环境变量纠正
PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", str(Path(__file__).resolve().parent.parent.parent)))
# 数据目录：容器里要落在 /app/outputs（compose 挂载卷这里），裸机默认项目根/outputs
DATA_DIR = Path(os.environ.get("DATA_DIR", PROJECT_ROOT / "outputs"))

# 日志目录：根目录/logs，不存在就先建（启动前日志就绪）
LOGS_DIR = PROJECT_ROOT / "logs"
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
    # Langfuse 可观测性（技术雷达 Demo）：本地面板 http://localhost:8080
    # key 由 docker-compose.langfuse.yml 的 LANGFUSE_INIT_* 自动初始化，与 compose 保持一致
    langfuse_public_key: str = "pk-lf-0123456789abcdef0123456789abcdef"
    langfuse_secret_key: str = "sk-lf-abcdef0123456789abcdef01234567"
    langfuse_host: str = "http://localhost:8080"          # 本地自托管面板地址
    data_dir: Path = DATA_DIR                             # 数据落盘目录（数据库/向量库都在这）
    jwt_secret: str = "dev-secret-key-change-me"          # JWT 签名密钥（先给个开发用默认值，生产必须换）   
    database_host: str = "localhost"                      # 数据库地址：裸机默认本机；容器里由 compose 注入 postgres    
    # 从项目根目录 .env 读值；extra="allow" 容忍文件里多余键
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="allow")

    @property
    def database_uri(self) -> str:
        """Postgres 连接串（开发阶段先写死，值对应 docker-compose 里 postgres 服务）。

        格式：协议+驱动://用户名:密码@地址:端口/库名。
        注意：密码直接写在代码里只适合本地开发，生产必须挪到 .env。
        """
        return f"postgresql+asyncpg://postgres:p5-secret@{self.database_host}:5432/knowledge_base"
    @property
    def chroma_dir(self) -> Path:
        """向量库目录（Chroma 数据落盘位置，在 outputs/ 下）。"""
        return self.data_dir / "chroma"

# 模块级单例：全项目 import settings 拿到的都是同一个实例
# （type: ignore 是告诉类型检查器：pydantic 的动态字段它看不懂，跳过）
settings = Settings()  # type: ignore
