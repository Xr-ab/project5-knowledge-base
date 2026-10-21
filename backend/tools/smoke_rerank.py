"""端到端冒烟：登录 → 建会话 → 上传文档 → 提问 → 检查精排与引用。

只验证链路通不通，不做断言，结果打屏。

账号从环境变量读，不写死在代码里（这个仓库是公开的）：
    KB_USER=xxx KB_PASS=yyy python tools/smoke_rerank.py
本地账号见项目根目录的 本地账号.txt（已在 .gitignore 里）。
"""
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

BASE = os.environ.get("KB_BASE", "http://127.0.0.1:8001")
USER = os.environ.get("KB_USER", "")
PWD = os.environ.get("KB_PASS", "")
DOC = Path("test_docs/budget_42_2026.txt")
Q = "42 号项目一期设备采购预算是多少？"

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(method, path, body=None, token=None, raw=False, timeout=180):
    url = BASE + path
    headers = {}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with opener.open(req, timeout=timeout) as r:
        blob = r.read()
        return blob if raw else json.loads(blob or b"{}")


def upload(thread_id, path, token):
    boundary = "----wb" + str(int(time.time() * 1000))
    content = path.read_bytes()
    parts = [
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'.encode(),
        b"Content-Type: text/plain\r\n\r\n",
        content,
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    req = urllib.request.Request(
        f"{BASE}/api/v1/documents/upload/{thread_id}",
        data=b"".join(parts),
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    with opener.open(req, timeout=180) as r:
        return json.loads(r.read() or b"{}")


def main():
    if not USER or not PWD:
        print("缺少账号：先设置环境变量 KB_USER / KB_PASS（见项目根 本地账号.txt）")
        return 2
    tok = call("POST", "/api/v1/auth/login", {"username": USER, "password": PWD})
    token = tok.get("access_token") or tok.get("token")
    print(f"登录 OK，token {(token or '')[:12]}...")

    th = call("POST", "/api/v1/threads", {"title": "精排冒烟"}, token=token)
    tid = th["id"]
    print(f"会话 {tid}")

    t0 = time.perf_counter()
    doc = upload(tid, DOC, token)
    print(f"上传 {DOC.name} 返回：{doc}")
    # ⚠️ 索引是后台任务（BackgroundTasks），上传接口立刻返回 processing。
    # 不等它就提问，查的是半成品库——两次跑结果都不一样，还以为是精排不稳定。
    doc_id = doc.get("id") or doc.get("document_id")
    for _ in range(60):
        time.sleep(0.5)
        docs = call("GET", f"/api/v1/documents/{tid}", token=token)
        rows = docs if isinstance(docs, list) else docs.get("items", [])
        cur = next((d for d in rows if d.get("id") == doc_id), None)
        if cur and cur.get("status") in ("ready", "failed"):
            print(
                f"索引 {cur['status']}，切片 {cur.get('chunk_count')}，"
                f"耗时 {time.perf_counter() - t0:.1f}s"
            )
            break
    else:
        print("⚠️ 等待索引超时")

    t0 = time.perf_counter()
    req = urllib.request.Request(
        f"{BASE}/api/v1/chat/{tid}",
        data=json.dumps({"prompt": Q}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    kinds, sources, answer = {}, [], []
    with opener.open(req, timeout=300) as r:
        for line in r:
            line = line.decode().strip()
            if not line:
                continue
            evt = json.loads(line)
            kinds[evt.get("type")] = kinds.get(evt.get("type"), 0) + 1
            if evt.get("type") == "sources":
                sources = evt["items"]
            if evt.get("type") == "llm_chunk":
                answer.append(evt.get("content") or evt.get("text") or "")
    dt = time.perf_counter() - t0
    print(f"\n提问「{Q}」总耗时 {dt:.1f}s")
    print("事件统计:", kinds)
    print("\n引用来源:")
    for s in sources:
        print(
            f"  [{s['index']}] {s['file_name']}  score={s['score']} "
            f"type={s.get('score_type')}  {s['snippet'][:40]}"
        )
    print("\n回答:", "".join(answer)[:200])

    hist = call("GET", f"/api/v1/chat/{tid}", token=token)
    msgs = hist if isinstance(hist, list) else hist.get("messages", [])
    for m in msgs:
        print(f"  历史 {m['role']:<6} sources={len(m.get('sources') or [])}")


if __name__ == "__main__":
    sys.exit(main())
