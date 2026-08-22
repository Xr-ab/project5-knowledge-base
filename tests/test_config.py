"""test_config.py —— 测试 Settings 这个"输入→输出机器"。

测试思路：配置类的输入是（环境变量 + .env 文件 + 默认值），
输出是 settings 的各个字段。测的就是这个映射对不对。
"""
import os
# ⚠️ 必须在 import 之前：模块 import 时 settings = Settings() 会立即读环境
# （import app.config → 模块级代码执行 → 构造 Settings → 必填字段缺失就崩）
os.environ["DEEPSEEK_API_KEY"] = "env-test-key"
os.environ["BOCHA_API_KEY"] = "env-test-bocha"

from app.config import Settings


def test_reads_key_from_env_file(tmp_path, monkeypatch):
    """输入 1：.env 文件。验证：能从文件读到 key。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)  # 删掉环境变量，让文件当唯一来源
    env = tmp_path / ".env"
    env.write_text("DEEPSEEK_API_KEY=file-key-123\nBOCHA_API_KEY=file-bocha\n", encoding="utf-8")

    s = Settings(_env_file=env)  # 用临时文件构造，不碰真实 .env（测试隔离）

    assert s.api_key.get_secret_value() == "file-key-123"  # SecretStr 要显式取明文才能比


def test_defaults(monkeypatch):
    """输入 2：只有环境变量。验证：没写的字段用默认值。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-deepseek")
    monkeypatch.setenv("BOCHA_API_KEY", "env-bocha")

    s = Settings()  # 直接用默认构造，读取环境变量

    assert s.model_provider == "openai"
    assert s.model_name == "deepseek-v4-flash"
    assert s.embeddings_model_name == "BAAI/bge-small-zh-v1.5"


def test_secret_masked(monkeypatch):
    """输入 3：验证 SecretStr 的隐藏能力：能取到明文，但打印时不透出。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "supersecret")  # 只改这一个，BOCHA 留着
    s = Settings()
    assert s.api_key.get_secret_value() == "supersecret"  # 能取到明文
    assert "supersecret" not in str(s.api_key)            # 打印是星号，不透明文
