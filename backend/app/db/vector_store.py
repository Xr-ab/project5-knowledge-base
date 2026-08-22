"""db/vector_store.py —— 向量库（Chroma）+ 切片 + 文档解析。

参考书 pgvector_utils.py 的 v1 版：
  pgvector（数据库插件）→ Chroma（本地文件，和 SQLite 同一哲学）
  远程 embedding API    → 本地单例（db/embeddings.py）
"""
import uuid
from pathlib import Path

import chromadb
import docx2txt
from loguru import logger
from pypdf import PdfReader

from app.config import settings
from app.db.embeddings import embeddings

# ① 客户端 + 集合：模块级单例（和 engine 一个道理，全项目一份）
_client = chromadb.PersistentClient(path=str(settings.chroma_dir))  # 数据落盘在 outputs/chroma/
_collection = _client.get_or_create_collection(
    name="knowledge_base",
    metadata={"hnsw:space": "cosine"},  # 相似度算法：余弦（比默认的 L2 更贴合语义）
)
# get_or_create：集合不存在才建——重启服务不会重复建

def _split_text(text:str, chunk_size: int = 1000, chunk_overlap: int = 200) -> list[str]:
   """切片：1000 字一段，段间重叠 200 字，防止句子被拦腰截断。

   参考书用 RecursiveCharacterTextSplitter（优先按段落边界切），
   v1 用简化版（按字符硬切）——原理一样，够用。
   TODO(待处理清单🟢7): 中文没有空格，按字符硬切会把一句话拦腰截断，影响检索质量；
   后续换 langchain-text-splitters 的 RecursiveCharacterTextSplitter（按标点/语义边界切）。
   """
   chunks = []
   start = 0
   while start < len(text):
            end = start + chunk_size
            chunks.append(text[start:end])
            if end >= len(text):
                break
            start = end - chunk_overlap
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

async def index_document(
          file_path: Path, document_id: uuid.UUID, thread_id: uuid.UUID, collection=None
) ->int:
     """文档入库：解析 → 切片 → 向量化 → 存 Chroma；返回切片数。
     collection参数是给测试用的（传临时库），生产不传。"""
     text = _load_document(file_path)
     chunks = _split_text(text)
     ids =[str(uuid.uuid4()) for _ in chunks]# 每片一个全局唯一 id（删片时用）
     metadatas = [{"document_id": str(document_id), 
                   "thread_id": str(thread_id),
                   "file_name": file_path.name} 
                   for _ in chunks]
     vectors = embeddings.embed(chunks)  # 向量化
     col = collection or _collection
     col.add(
         ids=ids,
         metadatas=metadatas,
         documents=chunks,
         embeddings=vectors
     )
     return len(chunks)

async def search_chunks(query: str, thread_id: uuid.UUID, k: int = 4, collection=None) -> list[str]:
     """查询：问题向量化 → 搜该会话最相关的 k 段（模块 5 问答时用）。"""
     col = collection or _collection
     k = min(k, col.count())  # 库里片数不够 k 会报错，先掐到上限
     vector = embeddings.embed([query])
     hits = col.query(
        query_embeddings=vector,
        n_results=k,
        where={"thread_id": str(thread_id)},  # 只搜本会话的文档
    )
     return hits["documents"][0] if hits["documents"] else []

async def delete_document_chunks(document_id: uuid.UUID, collection=None) -> None:
    """删除某文档的全部切片：先按 document_id 查出片 id，再删。"""
    col = collection or _collection
    hits = col.get(where={"document_id": str(document_id)})
    if hits["ids"]:
        col.delete(ids=hits["ids"])
