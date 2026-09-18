"""技术雷达 Demo：Rerank（cross-encoder）对比 bi-encoder 检索效果。

机制演示：同一个 query + 一批候选文档
  1. bi-encoder（SentenceTransformer）算余弦相似度排序 —— 模拟 RAG 第一阶段召回
  2. cross-encoder（ms-marco-MiniLM-L-6-v2）打分排序 —— 模拟第二阶段精排
对比两张排序表，看 rerank 如何把"字面相似但无关"的文档压下去。

用法: python rerank_demo.py  （模型首次运行自动下载，约 90MB + 81MB）
"""
import os

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")  # 国内加速下载

from sentence_transformers import SentenceTransformer, CrossEncoder
from sentence_transformers.util import cos_sim

QUERY = "How to deploy a web application with Docker?"

DOCS = [
    "Docker is a tool used to package and deploy web applications inside containers.",  # 强相关
    "We use Docker Compose to manage multi-service local development environments.",    # 相关（但没直接答 deploy web app）
    "Docker containers are physically shipped across the ocean by cargo vessels.",      # 陷阱：词面全重叠，实际无关
    "A web application needs a domain name, hosting server and a database to run.",     # 弱相关（无 Docker 词，但语义沾边）
    "I like to eat pizza on the weekend.",                                              # 无关
]


def main():
    print("query:", QUERY, "\n")

    # ---- 第一阶段：bi-encoder 余弦相似度 ----
    bi = SentenceTransformer("all-MiniLM-L6-v2")  # 双塔编码
    q_vec = bi.encode(QUERY)
    d_vecs = bi.encode(DOCS)
    sims = cos_sim(q_vec, d_vecs)[0]
    bi_rank = sorted(range(len(DOCS)), key=lambda i: sims[i], reverse=True)
    print("== ① bi-encoder 余弦排序（RAG 第一阶段召回） ==")
    for i in bi_rank:
        print(f"   {sims[i]:.3f}  {DOCS[i][:58]}")

    # ---- 第二阶段：cross-encoder 打分 ----
    ce = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")  # 拼接打分
    scores = ce.predict([(QUERY, d) for d in DOCS])
    ce_rank = sorted(range(len(DOCS)), key=lambda i: scores[i], reverse=True)
    print("\n== ② cross-encoder 重排（RAG 第二阶段精排） ==")
    for i in ce_rank:
        print(f"   {scores[i]:.3f}  {DOCS[i][:58]}")

    # ---- 对比 ----
    print("\n== 对比：排名变化 ==")
    print(f"   {'文档':<12} bi排名 -> ce排名")
    for i in range(len(DOCS)):
        print(f"   {DOCS[i][:24]:<26} {bi_rank.index(i)+1} -> {ce_rank.index(i)+1}")


main()
