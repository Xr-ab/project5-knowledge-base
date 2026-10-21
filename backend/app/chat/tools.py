import httpx  # HTTP 客户端库：让 Python 能发网络请求（类似浏览器地址栏输入网址）
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.config import settings  # 拿 bocha_api_key
from app.db.vector_store import query_with_sources

@tool(response_format="content_and_artifact")
async def retrieve_user_documents(query: str, config: RunnableConfig) -> tuple[str, dict]:
    """回答关于用户上传文档的问题时使用（提到"我的文档/我上传的文件"等）。""" # docstring 就是给模型的说明书
    thread_id = config["configurable"].get("thread_id")  # 图运行时配置里拿当前会话
    rows = await query_with_sources(query, thread_id, k=3)  # 复用模块 4 的检索（这条带来源）
    if not rows:
        return "No relevant documents", {"sources": []}

    # ⚠️ 两个返回值分工不同，别混：
    #   content  → 给【模型】看：拼成纯文本，决定它怎么回答
    #   artifact → 给【程序】看：结构化引用，前端据此画引用卡片
    # 分开走的好处：引用信息不占模型的 context，模型也不会把 [1] 这种标记抄进正文。
    content = "\n\n".join(r["text"] for r in rows)
    sources = [
        {
            "index": i,                                  # 引用序号，从 1 起
            "file_name": r["file_name"],
            "document_id": r["document_id"],
            "score": r["score"],                         # cosine=越大越像；rerank=logits，越高越相关
            "score_type": r["score_type"],               # 前端据此决定怎么展示（两种分数量纲不同）
            "snippet": r["text"][:120].replace("\n", " ").strip(),  # 摘要给卡片显示用
        }
        for i, r in enumerate(rows, start=1)
    ]
    return content, {"sources": sources}


@tool
async def web_search(query: str) -> str:
    """联网搜索（博查）。当问题需要最新信息或通用知识时使用。"""
    # ① 发请求（async with = 用完自动关闭连接，不关会漏连接）
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://api.bochaai.com/v1/web-search",  # 博查的接口地址
            headers={"Authorization": f"Bearer {settings.bocha_api_key}"},  # 认证：证明你是谁
            json={"query": query, "summary": True, "count": 5},  # json= 自动转成请求体
        )
        resp.raise_for_status()  # 请求失败（4xx/5xx）直接抛异常，别拿错误数据当结果

    # ② 解析响应：resp.json() 把 JSON 文本变成 Python 字典，逐层往里挖
    pages = resp.json().get("data", {}).get("webPages", {}).get("value", [])

    # ③ 组装成文本：模型只认文本，把每条结果拼成一段
    if not pages:
        return "No search results"
    return "\n\n".join(
        f"[{p.get('name')}]({p.get('url')})\n{p.get('summary') or p.get('snippet')}"
        for p in pages
    )


tools = [retrieve_user_documents, web_search]

