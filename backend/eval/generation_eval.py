"""eval/generation_eval.py —— 生成评估：LLM-as-Judge（回答质量打分）

为什么需要：
  检索评估只证明"片段找得到"，但没证明"回答答得好"。
  LLM-as-Judge：让一个 LLM 当考官，给"问题 + 参考片段 + 模型回答"打分。

打分维度（规范要求：正确率 · 幻觉情况）：
  ① correctness 正确性    —— 回答与期望答案是否一致（1-5）
  ② faithfulness 忠实度   —— 回答是否只基于片段，有没有编造片段里没有的内容（1-5，幻觉越低分越高）
  ③ overall 总分          —— 加权汇总

用法（backend 目录）：
  .venv\\Scripts\\python.exe -m eval.generation_eval
"""
import asyncio
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import OpenAI

from app.config import settings
from app.db.vector_store import search_chunks
from eval.retrieval_eval import (
    EVAL_THREAD_ID,
    TEST_DOC,
    TEST_SET,
    build_eval_collection,
    load_test_set,
)

# 和检索评估共用同一份测试集 + 同一个评估集合（一份文档、两套评估）

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


def call_llm(messages: list[dict], temperature: float = 0.2) -> str:
    """调 DeepSeek 拿回复文本。temperature 调低：评估场景要稳定，不要发散。"""
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


async def main():
    cases = load_test_set()
    col = await build_eval_collection()
    print(f"评估 {len(cases)} 条问题，等待模型逐条打分…\n")

    rows = []
    for case in cases:
        chunks = await search_chunks(case["question"], EVAL_THREAD_ID, k=3, collection=col)
        context = "\n\n".join(chunks)
        answer = await generate_answer(case["question"], context)
        scores = await judge_answer(
            case["question"], context, case["expected_answer"], answer
        )
        rows.append({**case, "answer": answer, "scores": scores})
        print(f"  #{case['id']} 正确性={scores.get('correctness')} 忠实度={scores.get('faithfulness')}  | {case['question']}")

    # 汇总平均分
    avg_correct = sum(r["scores"].get("correctness", 0) for r in rows) / len(rows)
    avg_faith = sum(r["scores"].get("faithfulness", 0) for r in rows) / len(rows)
    print(f"\n=== 生成评估结果 ===")
    print(f"平均正确性 = {avg_correct:.2f} / 5")
    print(f"平均忠实度 = {avg_faith:.2f} / 5（越低幻觉越重）")


if __name__ == "__main__":
    asyncio.run(main())
