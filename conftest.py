"""pytest 共享配置：把 backend/ 加进 sys.path，让测试能 `from app.config import ...`。

为什么需要：app 包在 backend/ 目录下（backend/app/...），而测试在仓库根的 tests/。
pytest 不会自动把 backend/ 加进 import 路径，所以统一在这里手动加一次，
所有测试文件都共享这个配置（conftest.py 是 pytest 自动加载的约定文件名）。
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))
