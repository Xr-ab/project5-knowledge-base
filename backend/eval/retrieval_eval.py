"""eval/retrieval_eval.py —— 检索评估：Recall@k / MRR

为什么需要：
  现在 search_chunks 返回 top-3，但没人验证这 3 段是否真的包含答案。
  本脚本对测试集每个问题做检索，量化两件事：
    ① 召回（Recall@k）：答案片段有没有被搜出来？
    ② 排序（MRR）：正确答案排在第几？（排第 1 分最高）

指标公式（背下来，面试用）：
  Recall@k = 问题中"答案片段被 top-k 命中"的数量 / 问题总数
  MRR      = 每个问题"第一个命中片段位置的倒数"的平均值（1/1=1，1/2=0.5，没命中=0）

用法（backend 目录，用项目 venv）：
  .venv\\Scripts\\python.exe -m eval.retrieval_eval
"""
import asyncio
import json
import sys
import uuid
from pathlib import Path

# 让 `python -m eval.retrieval_eval` 能 import 到 app 包（backend 在上一级）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chromadb

from app.config import settings
from app.db.embeddings import embeddings
from app.db.vector_store import index_document, search_chunks

TEST_DOC = Path(__file__).resolve().parent.parent.parent / "test_docs" / "bluewhale42_full.txt"
TEST_SET = Path(__file__).resolve().parent / "test_set.json"
K = 3  # 和线上工具 retrieve_user_documents 的 k 保持一致，评估才真实

# 评估专用固定 thread_id：search_chunks 按 thread_id 做数据隔离（where 过滤），
# 索引和查询必须用同一个 id，否则两条随机 uuid 对不上，检索结果恒为空。
EVAL_THREAD_ID = uuid.UUID("00000000-0000-0000-0000-0000000000e5")


def load_test_set(path: Path = TEST_SET) -> list[dict]:
    """① 加载测试集：读 json，返回 cases 列表。"""
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return data["cases"]


def is_hit(chunk: str, gold_keywords: list[str]) -> bool:
    """② 片段命中判定：片段文本包含 gold_keywords 中任意一个词 = 命中。

    注意：关键词可能被切片拦腰截断（1000 字硬切），所以用"任一关键词"而非"全部"。
    """
    return any(kw in chunk for kw in gold_keywords)


async def build_eval_collection() -> chromadb.Collection:
    """③ 建独立评估集合：把测试文档索引进临时库，不污染生产 knowledge_base。"""
    client = chromadb.PersistentClient(path=str(settings.chroma_dir))
    col = client.get_or_create_collection(name="eval_kb", metadata={"hnsw:space": "cosine"})
    # 已索引过就跳过（幂等）：避免重复向量化同一份文档
    if col.count() == 0:
        await index_document(TEST_DOC, EVAL_THREAD_ID, EVAL_THREAD_ID, collection=col)
    return col


async def eval_retrieval(col: chromadb.Collection, cases: list[dict], k: int = K) -> dict:
    """④ 主评估：对每个问题检索 top-k，记录命中位置，算指标。

    返回 {"recall_at_k": float, "mrr": float, "per_question": [...], "k": k}
    per_question 里每项 = {"id", "question", "hit": bool, "first_hit_rank": int|None}
    """
    per_question = []
    for case in cases:
        # 固定用 EVAL_THREAD_ID：与索引时一致，才能绕过数据隔离搜到评估文档
        hits = await search_chunks(case["question"], EVAL_THREAD_ID, k=k, collection=col)

        # 找第一个命中片段：enumerate(start=1) 让 rank 从 1 起
        first_hit_rank = None
        for rank, chunk in enumerate(hits, start=1):
            if is_hit(chunk, case["gold_keywords"]):
                first_hit_rank = rank
                break

        per_question.append({
            "id": case["id"],
            "question": case["question"],
            "hit": first_hit_rank is not None,
            "first_hit_rank": first_hit_rank,
        })

    # 汇总指标
    hit_count = sum(1 for item in per_question if item["hit"])
    recall_at_k = hit_count / len(per_question)          # 命中问题数 / 总数
    mrr = sum(1 / item["first_hit_rank"] for item in per_question if item["hit"]) / len(per_question)
    # MRR：每个命中问题取 1/rank，没命中记 0，再除以总数求平均

    return {"recall_at_k": recall_at_k, "mrr": mrr, "per_question": per_question, "k": k}


async def main():
    cases = load_test_set()
    print(f"加载测试集：{len(cases)} 条问题")
    col = await build_eval_collection()
    print(f"评估集合切片数：{col.count()}")
    result = await eval_retrieval(col, cases)
    print(f"\n=== 检索评估结果 (k={result['k']}) ===")
    print(f"Recall@{result['k']} = {result['recall_at_k']:.2f}")
    print(f"MRR            = {result['mrr']:.3f}")
    print("\n逐题明细：")
    for item in result["per_question"]:
        mark = "✓" if item["hit"] else "✗"
        rank = item["first_hit_rank"] or "-"
        print(f"  [{mark}] #{item['id']} rank={rank}  {item['question']}")


if __name__ == "__main__":
    asyncio.run(main())
