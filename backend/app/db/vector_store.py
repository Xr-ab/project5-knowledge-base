"""db/vector_store.py —— 向量库（Chroma）+ 切片 + 文档解析。

参考书 pgvector_utils.py 的 v1 版：
  pgvector（数据库插件）→ Chroma（本地文件，和 SQLite 同一哲学）
  远程 embedding API    → 本地单例（db/embeddings.py）
"""
import asyncio
import uuid
from pathlib import Path

import chromadb
import docx2txt
from loguru import logger
from pypdf import PdfReader

from app.config import settings
from app.db.embeddings import embeddings
from app.db.reranker import reranker

# ① 客户端 + 集合：模块级单例（和 engine 一个道理，全项目一份）
_client = chromadb.PersistentClient(path=str(settings.chroma_dir))  # 数据落盘在 outputs/chroma/
_collection = _client.get_or_create_collection(
    name="knowledge_base",
    metadata={"hnsw:space": "cosine"},  # 相似度算法：余弦（比默认的 L2 更贴合语义）
)
# get_or_create：集合不存在才建——重启服务不会重复建

# 切分边界优先级：越靠前越"整"，越靠后越"没办法"
# 空行=段落边界，换行=行边界，中文标点=句子边界，最后 "" 表示硬切兜底
_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "，", ""]


def _split_text(text: str, chunk_size: int = 400, chunk_overlap: int = 60) -> list[str]:
    """切片：先在语义边界上切，实在没边界才硬切。

    为什么换掉 1000/200 的硬切：中文没有空格，盲切会把一句话拦腰截断，
    半句话的向量什么都不像；检索命中残句时喂给 LLM 的上下文也是断的。
    400 字约一个自然段，重叠只留 60 字（约 1-2 句）做跨句衔接。

    实现思路和 langchain 的 RecursiveCharacterTextSplitter 一致：
    按分隔符优先级逐级退让，切到 ≤ chunk_size 为止。区别是 overlap 只在
    最外层统一加一次——内部每层都加会让片长层层膨胀。
    """

    def _cut(s: str, level: int) -> list[str]:
        """把 s 切成每片 ≤ chunk_size。level = 当前允许用到第几级分隔符。"""
        if len(s) <= chunk_size:
            return [s]  # 已经够小，不用切
        if level >= len(_SEPARATORS) - 1:  # 分隔符用尽 → 按字符硬切兜底
            return [s[i:i + chunk_size] for i in range(0, len(s), chunk_size)]

        sep = _SEPARATORS[level]
        parts = s.split(sep) if sep else [s]
        if len(parts) == 1:  # 这级分隔符在 s 里根本不存在 → 降一级再试
            return _cut(s, level + 1)

        # 分隔符要拼回前一段末尾，否则 s.split() 会把句号吃掉，切出来全是残句
        pieces = [p + sep for p in parts[:-1]] + [parts[-1]]

        # 把相邻短段往 buf 里攒，攒到接近 chunk_size 才封片
        # （按句号切出来是三十几个短句，不能一句一片）
        out: list[str] = []
        buf = ""
        for piece in pieces:
            if not piece:
                continue
            if len(buf) + len(piece) <= chunk_size:
                buf += piece  # 还装得下，继续攒
            else:
                if buf:
                    out.append(buf)
                if len(piece) > chunk_size:
                    out.extend(_cut(piece, level + 1))  # 单段自己就超了 → 降级再切
                    buf = ""
                else:
                    buf = piece
        if buf:
            out.append(buf)
        return out

    # 最外层统一加重叠：把上一片的结尾接到下一片开头
    chunks: list[str] = []
    for piece in _cut(text, 0):
        piece = piece.strip()
        if not piece:  # 连续换行会切出纯空白片，进库会污染检索
            continue
        if chunks and chunk_overlap > 0:
            piece = chunks[-1][-chunk_overlap:] + piece
        chunks.append(piece)
    return chunks

# ② 文档解析：按扩展名选解析器（和参考书 DOCUMENT_LOADER_MAPPING 同构）
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt"}

def _load_document(file_path: Path) -> str:
    """把文件内容读成纯文本（解析 ≠ 向量化，这只是第一步）。"""
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        reader = PdfReader(file_path)
        return "\n".join(page.extract_text()  or "" for page in reader.pages)
    elif suffix == ".docx":
        return docx2txt.process(file_path)
    elif suffix == ".txt":
        return file_path.read_text(encoding="utf-8")
    else:
        raise ValueError(f"不支持的文件类型: {suffix}")

def _doc_title(text: str) -> str:
    """取文档标题：正文第一个非空行。

    蓝鲸 41/42 两份文档的首行就带中文编号（「蓝鲸计划41号 · 全量技术档案」），
    这正是同族文档区分的线索——400 字的小切片里常常一句都没提到自己是哪一号。
    """
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line.lstrip("#").strip()[:60]
    return ""


def _embed_text(chunk: str, file_name: str, title: str) -> str:
    """只用于算向量的文本：正文前面拼上文档身份。

    ⚠️ 实测有害，默认关闭（add_context=False）。别看到这里就打开：
      8 份语料 / 26 题 / k=3 对照，doc_hit@3 从 0.6087 掉到 0.4348。
      原因是「相同前缀」把同一份文档所有切片的向量都往同一方向拉，
      top-3 被这份文档自己占满（实测 #23 的 top3 = budget/budget/bluewhale42），
      多跳题要两份文档同时进 top-3，于是全灭。
      要真想补文档身份，得给每片生成【各不相同】的上下文（LLM contextual retrieval），
      或者在检索后加多样性约束（MMR / 按 document_id 限额），而不是刷同一层漆。
    """
    return f"【{title}】{file_name}\n{chunk}"


async def index_document(
          file_path: Path, document_id: uuid.UUID, thread_id: uuid.UUID, collection=None,
          file_name: str | None = None, add_context: bool = False,
) ->int:
     """文档入库：解析 → 切片 → 向量化 → 存 Chroma；返回切片数。
     collection参数是给测试用的（传临时库），生产不传。
     file_name：展示用的文件名。落盘名是 uuid 时必须显式传，
     否则 metadata 里记的是 uuid，引用卡片会显示错名。
     add_context：算向量时是否给每片拼上文档身份（**默认关闭**，实测有害，
     详见 _embed_text 的说明）。留着只为保留实验开关，换 embedding 模型后可重测。"""
     text = _load_document(file_path)
     chunks = _split_text(text)
     display_name = file_name or file_path.name
     ids =[str(uuid.uuid4()) for _ in chunks]# 每片一个全局唯一 id（删片时用）
     metadatas = [{"document_id": str(document_id), 
                   "thread_id": str(thread_id),
                   "file_name": display_name} 
                   for _ in chunks]
     # 向量用带身份前缀的文本算，documents 仍存干净原文
     if add_context:
         title = _doc_title(text)
         embed_inputs = [_embed_text(c, display_name, title) for c in chunks]
     else:
         embed_inputs = chunks
     vectors = embeddings.embed(embed_inputs)  # 向量化
     col = collection or _collection
     col.add(
         ids=ids,
         metadatas=metadatas,
         documents=chunks,
         embeddings=vectors
     )
     return len(chunks)

def select_with_doc_quota(metadatas: list[dict], k: int, per_doc_limit: int) -> list[int]:
    """按「每份文档最多 per_doc_limit 个」从候选里挑前 k 个，返回保留的下标。

    为什么需要它：向量检索的 top-k 本身不约束来源，同一份文档的多个切片可以霸榜。
    实测 #23 的 top3 = budget/budget/bluewhale42，另一份文档的切片被挤掉，
    多跳问题（答案分散在两份文档）直接失败。

    候选池必须放大（见调用方）：跳掉超额的之后，池子不放大就凑不满 k 个。
    """
    picked: list[int] = []
    per_doc: dict[str, int] = {}
    for i, meta in enumerate(metadatas):
        did = meta.get("document_id", "")
        if per_doc.get(did, 0) >= per_doc_limit:
            continue  # 这份文档名额已满，跳过
        per_doc[did] = per_doc.get(did, 0) + 1
        picked.append(i)
        if len(picked) >= k:
            break
    return picked


async def query_with_sources(
    query: str, thread_id: uuid.UUID, k: int = 4, collection=None,
    per_doc_limit: int | None = None, use_rerank: bool | None = None,
    recall_n: int | None = None,
) -> list[dict]:
    """检索并保留来源：[{text, file_name, document_id, score, score_type}]。

    use_rerank=True 走两段式：先粗召 recall_n 条 → 交叉编码精排 → 取前 k。
    粗召默认 k*4——精排会大幅改变顺序，池子太小对的片段轮不到上场；
    但池子太大纯烧 CPU（精排耗时随条数线性涨）。实测 k=3 时：
        n=3  chunk_hit 0.609 / mrr 0.536
        n=6  chunk_hit 0.870 / mrr 0.746
        n=9  chunk_hit 0.913 / mrr 0.783
        n=12 chunk_hit 1.000 / mrr 0.855   ← 最优性价比
        n=18 chunk_hit 0.957 / mrr 0.862   ← 只多 0.007，耗时多 50%
    所以默认 k*4，不是常见的 k*6。

    score_type 标出分数来源（cosine / rerank）：两种分数量纲不同，
    混着比较会得出错误结论（比如拿精排分去套设想的"0.5 阈值"）。

    精排后还会按 settings.rerank_min_score 丢一次无关片段（保底留 top-1），
    所以返回条数可能少于 k ——这是有意的，凑数的垃圾片段对模型只有干扰。

    per_doc_limit：同一份文档最多占几个名额，作用于**精排后的最终排序**。
    """
    col = collection or _collection
    total = col.count()
    k = min(k, total)  # 库里片数不够 k 会报错，先掐到上限
    if k == 0:
        return []

    use_rerank = settings.rerank_enabled if use_rerank is None else use_rerank
    if use_rerank:
        pool = min(total, recall_n or k * 4)  # 精排要多捞候选
    else:
        pool = min(total, k * 3) if per_doc_limit else k

    vector = embeddings.embed([query])
    hits = col.query(
        query_embeddings=vector,
        n_results=pool,
        where={"thread_id": str(thread_id)},  # 只搜本会话的文档
    )
    docs = hits["documents"][0] if hits["documents"] else []
    metas = hits["metadatas"][0] if hits["metadatas"] else []
    dists = hits["distances"][0] if hits["distances"] else []

    rows = [
        {
            "text": doc,
            "file_name": (meta or {}).get("file_name"),
            "document_id": (meta or {}).get("document_id"),
            "score": round(1 - dist, 4),  # 先放余弦分，精排后覆盖
            "score_type": "cosine",
        }
        for doc, meta, dist in zip(docs, metas, dists)
    ]

    if use_rerank and rows:
        # ⚠️ 交叉编码推理是同步阻塞的，必须丢线程池——
        # 直接在协程里算会卡住整个事件循环（同 Langfuse flush 卡 22 秒那个坑）
        scores = await asyncio.to_thread(
            reranker.score, query, [r["text"] for r in rows]
        )
        for row, s in zip(rows, scores):
            row["score"] = round(s, 4)
            row["score_type"] = "rerank"
        rows.sort(key=lambda r: r["score"], reverse=True)

        # 丢掉无关片段：交叉编码说"这段跟问题没关系"就别塞给模型和用户。
        # 用 `keep or rows[:1]` 保底——全部低于阈值时至少留第一名，
        # 否则会出现"检索到东西却返回空"，模型会误判成库里没资料。
        min_score = settings.rerank_min_score
        if min_score is not None:
            keep = [r for r in rows if r["score"] >= min_score]
            rows = keep or rows[:1]

    # 配额作用于最终排序：先精排重排，再限每份文档的名额
    if per_doc_limit and rows:
        keep = select_with_doc_quota(
            [{"document_id": r["document_id"]} for r in rows], k, per_doc_limit
        )
        rows = [rows[i] for i in keep]

    return rows[:k]


async def search_chunks(
    query: str, thread_id: uuid.UUID, k: int = 4, collection=None,
    per_doc_limit: int | None = None,
) -> list[str]:
    """查询：问题向量化 → 搜该会话最相关的 k 段，只返回纯文本（旧接口）。

    要来源信息就用 query_with_sources——这里只是它的薄包装，
    保持老调用方（模块 5 问答）不用改一行。

    per_doc_limit：同一份文档最多占几个名额（None = 不限）。
    """
    rows = await query_with_sources(query, thread_id, k, collection, per_doc_limit)
    return [r["text"] for r in rows]

async def delete_document_chunks(document_id: uuid.UUID, collection=None) -> None:
    """删除某文档的全部切片：先按 document_id 查出片 id，再删。"""
    col = collection or _collection
    hits = col.get(where={"document_id": str(document_id)})
    if hits["ids"]:
        col.delete(ids=hits["ids"])
