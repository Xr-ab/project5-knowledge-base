"""eval/retrieval_eval.py —— 检索评估：文档级 + 切片级 + 排序 + 拒答

为什么这么设计（面试会问）：
  只看"切片级命中"是不够的：k 固定时，切片越小 → top-k 覆盖的文字总量越少
  → 关键词越难被覆盖到。实测跌幅几乎完全等于覆盖率跌幅，是数学稀释、不是检索变差。
  所以主指标用【文档级】——top-k 里有没有把答案所在的整份文档捞出来，
  这个指标不受切片大小影响，跨切分策略可比。

五个指标：
  doc_hit@k         top-k 覆盖的文档里，是否包含全部 gold_docs（多跳题要求更高）
  chunk_hit@k       top-k 里是否有片段包含 gold_keywords（原有指标，保留对比）
  MRR               第一个相关切片的排名倒数平均（排第 1 得 1 分）
  no_answer_fp_rate 无答案题里，top-1 相似度达阈值的比例（假阳：没有资料却硬答）
  false_reject_rate 有答案题里，top-1 相似度不到阈值的比例（假阴：有资料却说没有）

  后两个必须一起看：阈值调高，假阳↓但假阴↑，单看一个会被骗。
  所以另有 threshold_sweep，扫一遍阈值给出「两个错误率的最小交点」在哪里。

集合名带切分指纹：切分参数一改，集合名就变 → 自动重建。
  以前集合名固定 + "count()==0 才索引"，改了切分还在测旧切片，数字看着没变化。

两段式精排开关（--rerank / --no-rerank）：
  精排分数是 cross-encoder 的 logits，不是 0~1 的余弦相似度，
  所以扫描档位也跟着换（SWEEP_THRESHOLDS / RERANK_SWEEP_THRESHOLDS）。
  报告文件名带 rr / nor / rr<N>，不同配置的结论不会互相覆盖。

用法（项目根目录）：
  .venv\\Scripts\\python.exe -m eval.retrieval_eval            # 增量：集合已存在就复用
  .venv\\Scripts\\python.exe -m eval.retrieval_eval --rebuild  # 强制重建集合
  .venv\\Scripts\\python.exe -m eval.retrieval_eval --rerank   # 开精排
  .venv\\Scripts\\python.exe -m eval.retrieval_eval --rerank --recall-n 9
  .venv\\Scripts\\python.exe -m eval.retrieval_eval --rerank --rerank-model BAAI/bge-reranker-base
"""
import asyncio
import hashlib
import inspect
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

# 让 `python -m eval.retrieval_eval` 能 import 到 app 包（backend 在上一级）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chromadb

from app.config import settings
from app.db.embeddings import embeddings
from app.db.reranker import reranker
from app.db.vector_store import (
    _split_text,
    index_document,
    query_with_sources,
    select_with_doc_quota,
)

ROOT = Path(__file__).resolve().parent.parent.parent
TEST_DOCS = ROOT / "test_docs"
TEST_SET = Path(__file__).resolve().parent / "test_set.json"
REPORT_DIR = Path(__file__).resolve().parent / "reports"

K = 3                      # 和线上工具 retrieve_user_documents 的 k 保持一致
NO_ANSWER_THRESHOLD = 0.5  # top-1 相似度 < 它 → 拒答（回答"资料里没有"）

# 阈值扫描档位：从 0.30 扫到 0.60，看两个错误率在哪里此消彼长
SWEEP_THRESHOLDS = (0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60)

# 精排分数是 cross-encoder 的 logits，不是余弦相似度（可负、无上界），
# 上面那套 0~1 的档位对它完全无效（实测七档结果一模一样），必须另给一套。
RERANK_SWEEP_THRESHOLDS = (-4.0, -2.0, 0.0, 1.0, 1.5, 2.0, 3.0)

# 当前切分策略：递归边界切分（按 段落→行→句→标点 逐级退让）
SPLIT_TAG = "recursive"
# 切片参数直接取生产切分函数的默认值：两处分开维护迟早会忘，
# 一旦不符，集合名（指纹）就是假的，报告会跟着撒谎
_SPLIT_DEFAULTS = inspect.signature(_split_text).parameters
CHUNK_SIZE = _SPLIT_DEFAULTS["chunk_size"].default
CHUNK_OVERLAP = _SPLIT_DEFAULTS["chunk_overlap"].default
# embedding 模型：默认取 config 里配的中文模型；EMBED_MODEL=default 切回 minilm 做对照。
# 模型变了向量空间就变了，所以 MODEL_TAG 必须进集合名——否则会拿旧向量算新指标。
MODEL_NAME = os.environ.get("EMBED_MODEL", settings.embeddings_model_name)
MODEL_TAG = {
    "BAAI/bge-small-zh-v1.5": "bgezh",  # 512 维中文模型
    "default": "minilm",                # 384 维英文模型（all-MiniLM-L6-v2）
}.get(MODEL_NAME, "custom")

# 是否给切片拼文档身份前缀（B 实验的自变量）。改它必须换集合名——
# 嵌入的输入变了，旧向量一个都不能复用。
# ⚠️ 实测有害：开它 doc_hit@3 从 0.6087 掉到 0.4348（同文档垄断 top-3），故关闭。
USE_DOC_CONTEXT = False
CTX_TAG = "ctx" if USE_DOC_CONTEXT else "plain"

# 每份文档最多占几个检索名额（0 = 不限）。C 实验的自变量：治"同文档霸榜"。
# ⚠️ 实测在 k=3 下零影响：无前缀时 top3 同文档重复只出现在 6 道**单文档题**上，
#    配额跳掉重复后 gold_docs 仍被覆盖，doc_hit 不变。
#    多跳题失败的真因不是霸榜，而是检索根本没找对（#15 两份 whale 文档一份都没进 top3），
#    那是 query decomposition 要解决的问题。故默认关闭。
# 配额只影响挑选策略、不影响向量，所以不进集合名（不用重建集合）。
PER_DOC_LIMIT = 0
QUOTA_TAG = f"q{PER_DOC_LIMIT}" if PER_DOC_LIMIT else "nq"

# 是否启用两段式精排（D 实验的自变量）。精排不改向量，所以不进集合名，只进报告名。
USE_RERANK = False  # 默认关（跟生产 settings.rerank_enabled 解耦，方便做对照实验）
QUOTA_TAG = f"q{PER_DOC_LIMIT}" if PER_DOC_LIMIT else "nq"

# 评估专用固定 thread_id：search 按 thread_id 隔离，索引和查询必须一致
EVAL_THREAD_ID = uuid.UUID("00000000-0000-0000-0000-0000000000e5")

# 早期短版与 full 内容重复，留在库里会让命中虚高
EXCLUDE_FILES = {"bluewhale42.txt"}


def collection_name() -> str:
    """集合名带切分指纹：参数一变名字就变，旧集合不会被误用。"""
    return f"eval_kb_{SPLIT_TAG}_{CHUNK_SIZE}_{CHUNK_OVERLAP}_{MODEL_TAG}_{CTX_TAG}"


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def corpus_digest(files: list[Path]) -> str:
    """整体语料指纹：文件名 + 内容一起算，任一文件变动都会变。"""
    h = hashlib.sha256()
    for f in sorted(files):
        h.update(f.name.encode())
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


def git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except Exception:
        return "unknown"


def load_test_set(path: Path = TEST_SET) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)["cases"]


async def build_eval_collection(rebuild: bool = False) -> tuple[chromadb.Collection, list[Path]]:
    """把 test_docs 下全部 txt 索引进评估集合（独立集合，不污染生产库）。"""
    client = chromadb.PersistentClient(path=str(settings.chroma_dir))
    name = collection_name()

    if rebuild:
        try:
            client.delete_collection(name)
            print(f"已删除旧集合 {name}，准备重建")
        except Exception:
            pass

    col = client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})

    files = sorted(p for p in TEST_DOCS.glob("*.txt") if p.name not in EXCLUDE_FILES)

    if col.count() > 0:
        print(f"复用已有集合 {name}（{col.count()} 片）；要重建请加 --rebuild")
        return col, files

    for path in files:
        # document_id 由文件名派生：同一份文档每次跑都是同一个 id，重建可复现
        doc_id = uuid.uuid5(uuid.NAMESPACE_URL, f"eval/{path.name}")
        n = await index_document(
            path, doc_id, EVAL_THREAD_ID, collection=col,
            file_name=path.name, add_context=USE_DOC_CONTEXT,
        )
        print(f"  索引 {path.name}: {n} 片")
    return col, files


async def query_top_k(
    col: chromadb.Collection, question: str, k: int,
    per_doc_limit: int = 0, use_rerank: bool = False,
    recall_n: int | None = None,
) -> list[dict]:
    """查 top-k，并把 documents / metadatas / 分数一起拿回来。

    **直接复用生产的 query_with_sources**：以前这里自己写了一遍 col.query，
    等于评估和生产各有一套检索逻辑——生产改了、评估没改，指标就是在测旧代码。
    现在只有一处实现，评估量的就是线上真实行为。

    per_doc_limit > 0 启用文档配额；use_rerank 启用两段式精排；
    recall_n 是精排的粗召池大小（None = 生产默认 k*6）。
    """
    rows = await query_with_sources(
        question,
        EVAL_THREAD_ID,
        k=k,
        collection=col,
        per_doc_limit=per_doc_limit or None,
        use_rerank=use_rerank,
        recall_n=recall_n,
    )
    return [
        {"text": r["text"], "file_name": r["file_name"], "score": r["score"]}
        for r in rows
    ]


def chunk_hit(chunks: list[dict], keywords: list[str]) -> int | None:
    """切片级命中：第一个包含任一关键词的片段排名（1 起），没命中返回 None。"""
    if not keywords:
        return None
    for rank, c in enumerate(chunks, start=1):
        if any(kw in c["text"] for kw in keywords):
            return rank
    return None


def doc_hit(chunks: list[dict], gold_docs: list[str]) -> bool:
    """文档级命中：top-k 覆盖的文档必须包含全部 gold_docs。"""
    if not gold_docs:
        return False
    got = {c["file_name"] for c in chunks}
    return all(g in got for g in gold_docs)


def threshold_sweep(per_question: list[dict], thresholds=SWEEP_THRESHOLDS) -> list[dict]:
    """阈值扫描：每个档位下的假阳率 vs 假阴率，并排看。

    单看 no_answer_fp_rate 会被骗——阈值定得越高假阳越低，看着越"安全"，
    但真问题也越容易被拒。两个错误率必须一起看，才知道代价最小的点在哪。

    「答」判定用 score >= t，与线上「score < t 就拒答」严格互补。
    """
    scored = [q for q in per_question if q["type"] != "no_answer"]
    no_answer = [q for q in per_question if q["type"] == "no_answer"]
    total = len(scored) + len(no_answer)

    rows = []
    for t in thresholds:
        false_answer = sum(1 for q in no_answer if q["top1_score"] >= t)  # 没资料却硬答
        false_reject = sum(1 for q in scored if q["top1_score"] < t)      # 有资料却说没有
        rows.append({
            "threshold": t,
            "false_answer": false_answer,
            "false_answer_rate": round(false_answer / len(no_answer), 4) if no_answer else 0.0,
            "false_reject": false_reject,
            "false_reject_rate": round(false_reject / len(scored), 4) if scored else 0.0,
            # 两类错误平权相加，只用来选档位；真实业务应按代价加权（拒答比硬答便宜得多）
            "error_rate": round((false_answer + false_reject) / total, 4) if total else 0.0,
        })
    return rows


async def eval_retrieval(
    col: chromadb.Collection, cases: list[dict], k: int = K,
    per_doc_limit: int = PER_DOC_LIMIT, use_rerank: bool = USE_RERANK,
    recall_n: int | None = None,
) -> dict:
    per_question = []
    for case in cases:
        chunks = await query_top_k(
            col, case["question"], k, per_doc_limit, use_rerank, recall_n
        )
        rank = chunk_hit(chunks, case.get("gold_keywords") or [])
        per_question.append({
            "id": case["id"],
            "type": case.get("type", "single"),
            "question": case["question"],
            "gold_docs": case.get("gold_docs") or [],
            "doc_hit": doc_hit(chunks, case.get("gold_docs") or []),
            "chunk_first_hit_rank": rank,
            "top1_score": chunks[0]["score"] if chunks else 0.0,
            "n_chunks": len(chunks),  # 开丢弃阈值后会小于 k，用来量"丢了多少"
            "top_files": [c["file_name"] for c in chunks],
        })

    scored = [q for q in per_question if q["type"] != "no_answer"]
    no_answer = [q for q in per_question if q["type"] == "no_answer"]

    doc_hit_rate = sum(q["doc_hit"] for q in scored) / len(scored) if scored else 0.0
    chunk_hit_rate = (
        sum(1 for q in scored if q["chunk_first_hit_rank"]) / len(scored) if scored else 0.0
    )
    mrr = (
        sum(1 / q["chunk_first_hit_rank"] for q in scored if q["chunk_first_hit_rank"])
        / len(scored)
        if scored
        else 0.0
    )
    fp_rate = (
        sum(1 for q in no_answer if q["top1_score"] >= NO_ANSWER_THRESHOLD) / len(no_answer)
        if no_answer
        else 0.0
    )
    fr_rate = (
        sum(1 for q in scored if q["top1_score"] < NO_ANSWER_THRESHOLD) / len(scored)
        if scored
        else 0.0
    )

    return {
        "k": k,
        "per_doc_limit": per_doc_limit,
        "use_rerank": use_rerank,
        "recall_n": recall_n,
        "min_score": settings.rerank_min_score if use_rerank else None,
        "chunks_returned": sum(q["n_chunks"] for q in per_question),
        "chunks_full": len(per_question) * k,  # 不丢弃时应该是 题数 × k
        "metrics": {
            f"doc_hit@{k}": round(doc_hit_rate, 4),
            f"chunk_hit@{k}": round(chunk_hit_rate, 4),
            "mrr": round(mrr, 4),
            "no_answer_fp_rate": round(fp_rate, 4),
            "false_reject_rate": round(fr_rate, 4),
        },
        "counts": {
            "scored_cases": len(scored),
            "no_answer_cases": len(no_answer),
        },
        "threshold_sweep": threshold_sweep(
            per_question,
            RERANK_SWEEP_THRESHOLDS if use_rerank else SWEEP_THRESHOLDS,
        ),
        "per_question": per_question,
    }


async def main():
    rebuild = "--rebuild" in sys.argv
    # --quota N 覆盖文档配额（0 = 关闭，用来做 A/B 对照）
    quota = PER_DOC_LIMIT
    if "--quota" in sys.argv:
        quota = int(sys.argv[sys.argv.index("--quota") + 1])
    quota_tag = f"q{quota}" if quota else "nq"
    # --rerank 打开两段式精排；--no-rerank 显式关掉
    use_rerank = USE_RERANK
    if "--rerank" in sys.argv:
        use_rerank = True
    if "--no-rerank" in sys.argv:
        use_rerank = False
    rerank_tag = "rr" if use_rerank else "nor"
    # --recall-n N 覆盖精排的粗召池大小（None = 生产默认 k*4）
    recall_n = None
    if "--recall-n" in sys.argv:
        recall_n = int(sys.argv[sys.argv.index("--recall-n") + 1])
        rerank_tag = f"rr{recall_n}"
    # --rerank-model NAME 换精排模型做对照（默认用 settings 里那个）
    rerank_model = settings.reranker_model_name
    if "--rerank-model" in sys.argv:
        rerank_model = sys.argv[sys.argv.index("--rerank-model") + 1]
        reranker.use(rerank_model)
        rerank_tag += "_" + rerank_model.split("/")[-1].replace("bge-reranker-", "")
    # --min-score N 覆盖精排后的丢弃阈值；--no-min-score 关掉（等于不丢片段）。
    # 直接改 settings 而不是加参数——评估要量的是线上真实路径，不是另一条分支。
    if "--no-min-score" in sys.argv:
        settings.rerank_min_score = None
        rerank_tag += "_nofilter"
    elif "--min-score" in sys.argv:
        settings.rerank_min_score = float(sys.argv[sys.argv.index("--min-score") + 1])
        rerank_tag += f"_m{settings.rerank_min_score:g}"

    cases = load_test_set()
    # 切模型必须在建集合之前：集合名带 MODEL_TAG，向量维度也随之改变
    embeddings.use(MODEL_NAME)
    col, files = await build_eval_collection(rebuild=rebuild)

    print(f"语料 {len(files)} 份 → 集合切片数 {col.count()}")
    print(f"测试集 {len(cases)} 题，k={K}，每文档配额={'不限' if not quota else quota}")
    print(f"embedding: {MODEL_NAME} | 精排: {'开（' + rerank_model + '）' if use_rerank else '关'}")
    if use_rerank:
        print(f"粗召池: {recall_n or K * 4} 条")

    result = await eval_retrieval(
        col, cases, per_doc_limit=quota, use_rerank=use_rerank, recall_n=recall_n
    )

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "git_commit": git_commit(),
        "command": " ".join(sys.argv),
        "embedding": {"model": MODEL_NAME, "dim": embeddings.dim},
        "chunking": {
            "strategy": SPLIT_TAG,
            "chunk_size": CHUNK_SIZE,
            "chunk_overlap": CHUNK_OVERLAP,
            "doc_context": USE_DOC_CONTEXT,
        },
        "rerank": {
            "enabled": use_rerank,
            "model": rerank_model if use_rerank else None,
            "recall_n": (recall_n or K * 4) if use_rerank else None,
            "min_score": settings.rerank_min_score if use_rerank else None,
        },
        "corpus": {
            "files": [f.name for f in files],
            "count": len(files),
            "chunks": col.count(),
            "sha256": corpus_digest(files),
        },
        "test_set": {
            "path": "backend/eval/test_set.json",
            "cases": len(cases),
            "sha256": sha256_of(TEST_SET),
        },
        "no_answer_threshold": NO_ANSWER_THRESHOLD,
        **result,
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / f"retrieval_{SPLIT_TAG}{CHUNK_SIZE}_{CTX_TAG}_{quota_tag}_{MODEL_TAG}_{rerank_tag}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== 指标 ===")
    print(f"  embedding             {MODEL_NAME}（{embeddings.dim} 维）")
    for k_name, v in result["metrics"].items():
        print(f"  {k_name:<20} {v}")

    n_scored = result["counts"]["scored_cases"]
    n_no_answer = result["counts"]["no_answer_cases"]
    print("\n=== 阈值扫描（假阳 = 没资料硬答 / 假阴 = 有资料说没有）===")
    print("  阈值    假阳      假阴      总错误率")
    for row in result["threshold_sweep"]:
        print(
            f"  {row['threshold']:.2f}    "
            f"{row['false_answer']}/{n_no_answer}      "
            f"{row['false_reject']}/{n_scored}     "
            f"{row['error_rate']}"
        )

    print(f"\n逐题明细（✗ = 未命中）：")
    for q in result["per_question"]:
        mark = "✓" if q["doc_hit"] else "✗"
        print(f"  [{mark}] #{q['id']:<3} {q['type']:<10} top1={q['top1_score']:<7} {q['question'][:34]}")
    print(f"\n报告已写入 {out}")


if __name__ == "__main__":
    asyncio.run(main())
