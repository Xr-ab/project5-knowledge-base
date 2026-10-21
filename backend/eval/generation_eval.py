"""eval/generation_eval.py —— 生成评估：LLM-as-Judge（回答质量打分）

为什么需要：
  检索评估只证明"片段找得到"，但没证明"回答答得好"。
  LLM-as-Judge：让一个 LLM 当考官，给"问题 + 参考片段 + 模型回答"打分。

打分维度（规范要求：正确率 · 幻觉情况）：
  ① correctness 正确性    —— 回答与期望答案是否一致（1-5）
  ② faithfulness 忠实度   —— 回答是否只基于片段，有没有编造片段里没有的内容（1-5，幻觉越低分越高）
  ③ overall 总分          —— 加权汇总

**断点续跑**（这个脚本要调 2×题数 次 LLM，中途断掉很常见：余额不足 / 限流 / 网络）：
  每答完一题就立刻落盘，重跑时跳过已完成的题号。所以可以 `--limit 5` 跑一批、
  再跑一批，或者中途失败后接着跑，不会把前面几题的成绩一起丢掉。
  报告按「模型名」分文件，换模型不会覆盖旧结果。

用法（backend 目录）：
  .venv\\Scripts\\python.exe -m eval.generation_eval               # 全部跑完（跳过已完成）
  .venv\\Scripts\\python.exe -m eval.generation_eval --limit 5     # 只跑 5 题（分批跑用这个）
  .venv\\Scripts\\python.exe -m eval.generation_eval --rerun       # 丢掉旧结果重跑
"""
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import OpenAI

from app.config import settings
from app.db.vector_store import query_with_sources
from eval.retrieval_eval import (
    EVAL_THREAD_ID,
    REPORT_DIR,
    build_eval_collection,
    load_test_set,
)

# 和检索评估共用同一份测试集 + 同一个评估集合（一份语料、两套评估）

client = OpenAI(api_key=settings.api_key.get_secret_value(), base_url=settings.model_base_url)

JUDGE_PROMPT = """你是 RAG 系统质量评估员。请对"模型回答"打分，输出 JSON。

## 参考片段（检索到的文档内容）
{context}

## 期望答案（参考答案）
{expected}

## 模型回答
{answer}

## 输出格式（只输出 JSON，不要其他文字）
{{"correctness": 1-5, "faithfulness": 1-5, "reason": "一句话理由"}}
"""


def report_path() -> Path:
    """报告名带模型名：换模型（或换 judge 模型）不会覆盖旧结果。"""
    tag = settings.model_name.replace("/", "-")
    return REPORT_DIR / f"generation_{tag}.json"


def load_done(path: Path) -> dict[int, dict]:
    """读已有报告，返回 {题号: 该题结果}。文件不存在或坏了就当没跑过。"""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {row["id"]: row for row in data.get("rows", []) if "scores" in row}


def save(path: Path, rows: list[dict], total: int) -> None:
    """把目前所有结果落盘。每完成一题就调一次——崩了也不丢已花的钱。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    done = [r for r in rows if "scores" in r]
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "command": " ".join(sys.argv),
        "model": settings.model_name,
        "judge_model": settings.model_name,
        "retrieval": "query_with_sources（生产路径，含两段式精排）",
        "progress": {"done": len(done), "total": total},
        "rows": rows,
    }
    if done:
        payload["metrics"] = {
            "correctness_avg": round(
                sum(r["scores"].get("correctness", 0) for r in done) / len(done), 2
            ),
            "faithfulness_avg": round(
                sum(r["scores"].get("faithfulness", 0) for r in done) / len(done), 2
            ),
        }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def call_llm(messages: list[dict], temperature: float = 0.2) -> str:
    """调大模型拿回复文本。temperature 调低：评估场景要稳定，不要发散。"""
    resp = client.chat.completions.create(
        model=settings.model_name,
        messages=messages,
        temperature=temperature,
    )
    return resp.choices[0].message.content


async def generate_answer(question: str, context: str) -> str:
    """① 生成回答：把检索到的片段作为依据，让模型回答问题。"""
    messages = [
        {
            "role": "system",
            "content": "你是一名严谨的知识库助手，只能依据给定资料回答；资料中没有的内容不要编造。",
        },
        {
            "role": "user",
            "content": f"资料：\n{context}\n\n问题：{question}",
        },
    ]
    return call_llm(messages)


async def judge_answer(question: str, context: str, expected: str, answer: str) -> dict:
    """② 打分：把 JUDGE_PROMPT 填好发给模型，解析出 JSON 分数。"""
    prompt = JUDGE_PROMPT.format(context=context, expected=expected, answer=answer)
    raw = call_llm([{"role": "user", "content": prompt}])

    # 模型偶尔会带解释文字，只截取 JSON 部分（第一个 { 到最后一个 }）
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        return {"correctness": 0, "faithfulness": 0, "reason": f"解析失败: {raw[:80]}"}
    return json.loads(raw[start : end + 1])


async def main() -> int:
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    cases = load_test_set()
    out = report_path()
    done = {} if "--rerun" in sys.argv else load_done(out)
    if done:
        print(f"续跑：{out.name} 里已有 {len(done)}/{len(cases)} 题，跳过它们")

    todo = [c for c in cases if c["id"] not in done]
    if limit is not None:
        todo = todo[:limit]
    if not todo:
        print("没有待跑的题（全部已完成）。要重跑请加 --rerun")
    else:
        print(f"本次要跑 {len(todo)} 题 × 2 次调用（生成 + 打分）\n")

    # build_eval_collection 返回 (集合, 语料文件列表)——检索评估要用文件清单算 digest，
    # 这里只关心集合，第二个返回值丢掉
    col, _files = await build_eval_collection()
    rows = list(done.values())

    for i, case in enumerate(todo, start=1):
        try:
            # 用生产同一个检索入口（含两段式精排）：生成评估要量的是"线上那套检索
            # 喂给模型什么"，不是另一条只有向量的分支——否则正确性分数是虚的。
            found = await query_with_sources(
                case["question"], EVAL_THREAD_ID, k=3, collection=col
            )
            context = "\n\n".join(r["text"] for r in found)
            answer = await generate_answer(case["question"], context)
            scores = await judge_answer(
                case["question"], context, case["expected_answer"], answer
            )
        except Exception as e:  # 余额不足 / 限流 / 网络：保住已花的钱，说清楚卡在哪
            save(out, rows, len(cases))
            print(f"\n⚠️ 第 {i}/{len(todo)} 题（#{case['id']}）失败：{type(e).__name__}: {e}")
            print(f"已完成的 {len([r for r in rows if 'scores' in r])} 题已存进 {out.name}")
            print("补齐后重跑同一条命令即可从断点继续（不加 --rerun）")
            return 1

        rows.append({**case, "answer": answer, "scores": scores})
        save(out, rows, len(cases))  # 每题立刻落盘
        print(
            f"  [{len([r for r in rows if 'scores' in r])}/{len(cases)}] #{case['id']}"
            f" 正确性={scores.get('correctness')} 忠实度={scores.get('faithfulness')}"
            f"  | {case['question']}"
        )

    rows.sort(key=lambda r: r["id"])
    save(out, rows, len(cases))

    done_rows = [r for r in rows if "scores" in r]
    avg_correct = sum(r["scores"].get("correctness", 0) for r in done_rows) / len(done_rows)
    avg_faith = sum(r["scores"].get("faithfulness", 0) for r in done_rows) / len(done_rows)
    print("\n=== 生成评估结果 ===")
    print(f"已完成 {len(done_rows)}/{len(cases)} 题")
    print(f"平均正确性 = {avg_correct:.2f} / 5")
    print(f"平均忠实度 = {avg_faith:.2f} / 5（越低幻觉越重）")
    print(f"报告已写入 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
