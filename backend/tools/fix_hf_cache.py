"""修复 HuggingFace 缓存：Windows 上软链接创建失败时，snapshots/ 会指向空文件。

现象：blobs/ 里数据是全的（几百 MB），但 snapshots/<commit>/ 下全是 0 字节文件，
      加载模型报 NoSuchFile / Could not load model from any source。

原因：HF 下载完先写 blobs/，再在 snapshots/ 里建软链接指向 blob。
      Windows 非管理员/未开开发者模式时建软链接直接失败，于是留下空壳。

做法：读 trees/<commit>.json 里的 blob_id 映射，用**硬链接**把 blob 挂到
      snapshots/<commit>/<原文件名>。硬链接不占额外空间，效果等同软链接。

用法：
    python tools/fix_hf_cache.py                    # 修缓存目录下全部模型
    python tools/fix_hf_cache.py models--BAAI--xxx   # 只修指定模型
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from app.config import settings

CACHE = settings.data_dir / "models" / "fastembed"


def _link(src: Path, dst: Path) -> None:
    """优先硬链接；跨盘等建不了硬链接时退回复制。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        import shutil

        shutil.copy2(src, dst)


def fix_model(model_dir: Path) -> int:
    trees = list((model_dir / "trees").glob("*.json"))
    if not trees:
        print(f"  跳过（无 trees 清单）: {model_dir.name}")
        return 0
    tree = json.loads(trees[0].read_text(encoding="utf-8"))
    commit = trees[0].stem
    snap = model_dir / "snapshots" / commit
    blobs = model_dir / "blobs"

    fixed = 0
    for name, info in tree.get("files", {}).items():
        size = info.get("size", 0)
        # LFS 大文件在 blobs 里用的是 lfs_sha256 命名，小文件用 blob_id
        candidates = [blobs / info.get("lfs_sha256", ""), blobs / info.get("blob_id", "")]
        src = next((c for c in candidates if c.is_file() and c.stat().st_size == size), None)
        if src is None:
            continue
        dst = snap / name
        # 已经是正确的实体文件就跳过（避免每次重建）
        if dst.is_file() and dst.stat().st_size == size:
            continue
        _link(src, dst)
        print(f"  补齐 {name:<28} {size:>12,} 字节")
        fixed += 1
    return fixed


def main() -> None:
    targets = sys.argv[1:]
    dirs = (
        [CACHE / t for t in targets]
        if targets
        else sorted(p for p in CACHE.glob("models--*") if p.is_dir())
    )
    total = 0
    for d in dirs:
        print(f"[{d.name}]")
        total += fix_model(d)
    print(f"\n共补齐 {total} 个文件")


if __name__ == "__main__":
    main()
