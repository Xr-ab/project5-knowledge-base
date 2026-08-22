"""db/embeddings.py —— embedding 单例（规范 §7.1）。

入库和查询必须共用同一个实例/模型：换模型 = 向量空间变了，
库里已有的向量全部失效。所以全局只建一个，两边共用。

方案③：chromadb 内置 all-MiniLM-L6-v2（ONNX，免 torch，384 维）。
以后换 bge-small-zh-v1.5（中文更好）只改这个文件 + 重建向量库。
"""
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

class Embeddings:
    """embedding 的薄封装：唯一的换模型入口。"""

    def __init__(self) -> None:
        self._fn = DefaultEmbeddingFunction()  # 首次调用自动下载模型（已装好）

    def embed(self, texts: list[str]) -> list[list[float]]:
        """文字列表 → 向量列表（入库、查询都走这里）。"""
        return self._fn(texts)


# 模块级单例：import embeddings 拿到的是同一个实例
embeddings = Embeddings()