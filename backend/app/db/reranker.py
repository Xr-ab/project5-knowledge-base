"""db/reranker.py —— 精排模型（cross-encoder）。

和 embedding 的区别（面试常问）：
  embedding  双塔：query 和 doc 各自独立编码成向量 → 能预先算好存库
             → 快，适合全库粗召
  reranker   交叉编码：query 和 doc 拼一起送进模型 → 每对都要跑一次前向
             → 慢，但能看到两者的交互，能判断「这段里到底有没有答案」

所以标准用法是两段式：
  粗召 top-N（N 通常 20~50）→ 精排打分 → 取 top-k 喂给 LLM。

为什么值得多这一步：向量只能判断「话题相关」，判断不了「含不含答案」。
实测 bge-small-zh 下，3 道无答案题的最相关片段得分 0.6277~0.7286，
比有答案题的中位数（0.6906）还高 —— 阈值拒答彻底失效，只有交叉编码能救。
"""
from loguru import logger

from app.config import settings


class Reranker:
    """精排模型单例。惰性加载，第一次打分才初始化（模型 0.57GB，冷启动要几秒）。"""

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or settings.reranker_model_name
        self._impl = None

    def _load(self):
        if self._impl is not None:
            return self._impl
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self._impl = TextCrossEncoder(
            model_name=self.model_name,
            # 和 embedding 共用一个模型目录，别用默认的系统 Temp（会被清理）
            cache_dir=str(settings.data_dir / "models" / "fastembed"),
        )
        logger.info(f"reranker 模型已加载：{self.model_name}")
        return self._impl

    def use(self, model_name: str) -> None:
        """运行期换模型（只给评估做 A/B，生产别调）。"""
        if model_name == self.model_name and self._impl is not None:
            return
        self.model_name = model_name
        self._impl = None

    def score(self, query: str, documents: list[str]) -> list[float]:
        """给每对 (query, doc) 打相关性分，返回与 documents 等长的列表。

        ⚠️ 这是同步阻塞调用（ONNX 推理），在 async 上下文里必须丢到线程池，
        否则会卡住整个事件循环（和当初 Langfuse flush 卡 22 秒同一个坑）。

        batch_size=1 是反直觉但实测最优：批处理会把一批里的所有切片补齐到
        最长那条，400 字的切片和 80 字的切片混在一批，短的全在做无用计算。
        实测 v2-m3-int8 精排 12 条 400 字切片：batch_size=64 要 2029ms，
        batch_size=1 只要 863ms（2.35 倍）。反正总共就十几条，批不批无所谓。
        """
        if not documents:
            return []
        return [
            float(s) for s in self._load().rerank(query, documents, batch_size=1)
        ]


# 模块级单例：全项目一份
reranker = Reranker()
