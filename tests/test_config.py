"""test_config.py —— 测试 Settings 这个"输入→输出机器"。

测试思路：配置类的输入是（环境变量 + .env 文件 + 默认值），
输出是 settings 的各个字段。测的就是这个映射对不对。
"""
import os
# ⚠️ 必须在 import 之前：模块 import 时 settings = Settings() 会立即读环境
# （import app.config → 模块级代码执行 → 构造 Settings → 必填字段缺失就崩）
os.environ["LLM_API_KEY"] = "env-test-key"
os.environ["BOCHA_API_KEY"] = "env-test-bocha"

from app.config import Settings


def test_reads_key_from_env_file(tmp_path, monkeypatch):
    """输入 1：.env 文件。验证：能从文件读到 key。"""
    # 两个别名都要删干净：只要环境变量源里还剩任一别名，它的优先级就高于 .env 文件，
    # 这条"文件是唯一来源"的断言就会变成假通过/假失败（实测踩过）。
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("LLM_API_KEY=file-key-123\nBOCHA_API_KEY=file-bocha\n", encoding="utf-8")

    s = Settings(_env_file=env)  # 用临时文件构造，不碰真实 .env（测试隔离）

    assert s.api_key.get_secret_value() == "file-key-123"  # SecretStr 要显式取明文才能比


def test_defaults(monkeypatch):
    """输入 2：只有环境变量。验证：没写的字段用默认值。"""
    monkeypatch.setenv("LLM_API_KEY", "env-test-key")
    monkeypatch.setenv("BOCHA_API_KEY", "env-bocha")

    s = Settings()  # 直接用默认构造，读取环境变量

    assert s.model_provider == "openai"
    assert s.model_name == "glm-4-flash"          # 智谱免费档（原 DeepSeek 余额耗尽后换的）
    assert s.embeddings_model_name == "BAAI/bge-small-zh-v1.5"


def test_old_deepseek_key_still_works(monkeypatch):
    """别名回退：只配了旧名 DEEPSEEK_API_KEY 也要能起来。

    为什么值得测：alias 是「按序回退」，不是「任选其一」。写错成单值 alias 时，
    旧 .env / 老部署脚本会在 import 面直接崩（早失败设计反噬），这里钉死行为。
    """
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "legacy-key")
    monkeypatch.setenv("BOCHA_API_KEY", "env-bocha")

    assert Settings().api_key.get_secret_value() == "legacy-key"


def test_secret_masked(monkeypatch):
    """输入 3：验证 SecretStr 的隐藏能力：能取到明文，但打印时不透出。"""
    monkeypatch.setenv("LLM_API_KEY", "supersecret")  # 只改这一个，BOCHA 留着
    s = Settings()
    assert s.api_key.get_secret_value() == "supersecret"  # 能取到明文
    assert "supersecret" not in str(s.api_key)            # 打印是星号，不透明文
