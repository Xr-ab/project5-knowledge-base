"""db/embeddings.py —— embedding 单例（规范 §7.1）。

入库和查询必须共用同一个实例/模型：换模型 = 向量空间变了，
库里已有的向量全部失效。所以全局只建一个，两边共用。

⚠️ 换模型必须同时重建向量库——不同模型的向量互相不可比较。

两个后端：
  BAAI/bge-small-zh-v1.5（默认）fastembed + ONNX，512 维，中文检索
  "default"                     chromadb 内置 all-MiniLM-L6-v2，384 维
                                英文模型，中文语料打分整体压在 0.4~0.6 窄区间，
                                只留作 A/B 对照，别当生产配置
"""
from loguru import logger

from app.config import settings


class Embeddings:
    """embedding 的薄封装：唯一的换模型入口。

    模型惰性加载：构造时不下载，第一次 embed 才初始化。
    这样 import 本模块不会拖慢启动（模型文件 90MB，冷启动要几秒）。
    """

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or settings.embeddings_model_name
        self._impl = None
        self._dim: int | None = None

    @property
    def dim(self) -> int | None:
        """向量维度（评估报告要记录；还没加载过就是 None）。"""
        return self._dim

    def _load(self):
        """第一次用时才真正加载模型。"""
        if self._impl is not None:
            return self._impl
        if self.model_name == "default":
            from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

            self._impl = DefaultEmbeddingFunction()
            self._dim = 384
        else:
            from fastembed import TextEmbedding

            # 缓存目录必须显式指定：fastembed 默认丢在系统 Temp，
            # 那里会被清理，下次启动就得重新下载（国内还下不动）。
            # 放 outputs/models 下，跟向量库/数据库一起都在数据目录里。
            self._impl = TextEmbedding(
                model_name=self.model_name,
                cache_dir=str(settings.data_dir / "models" / "fastembed"),
            )
            # 维度从 fastembed 的模型清单里查，别写死——换模型时会骗人
            info = [
                m for m in TextEmbedding.list_supported_models()
                if m.get("model") == self.model_name
            ]
            self._dim = info[0].get("dim") if info else None
        logger.info(f"embedding 模型已加载：{self.model_name}（{self._dim} 维）")
        return self._impl

    def use(self, model_name: str) -> None:
        """运行期切换模型（**只给评估脚本做 A/B 对照用，生产别调**）。

        切完必须重建向量库：旧向量是另一个空间里的坐标，混着查会得到乱序结果。
        """
        if model_name == self.model_name and self._impl is not None:
            return
        self.model_name = model_name
        self._impl = None
        self._dim = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        """文字列表 → 向量列表（入库、查询都走这里）。"""
        impl = self._load()
        if self.model_name == "default":
            return impl(texts)  # chromadb 的接口：吃 list 回 list
        # fastembed 返回 numpy 数组的生成器，转成 list[list[float]] 才能进 Chroma
        return [v.tolist() for v in impl.embed(texts)]


# 模块级单例：import embeddings 拿到的是同一个实例
embeddings = Embeddings()
