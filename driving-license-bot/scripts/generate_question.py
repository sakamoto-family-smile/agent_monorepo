"""Question Generator を 1 回呼び出して JSON を出力する CLI（手動検証用）。

使い方:
    cd driving-license-bot
    GOOGLE_CLOUD_PROJECT=... uv run python scripts/generate_question.py \
        --goal full --category rules --difficulty standard \
        --topic-hint "高速道路の最低速度"

CI / 開発環境で誤って実 LLM を叩かないために、`AGENT_LLM_MOCK=true` の場合は
Mock LLM が空文字列を返し、生成が失敗する（パースエラー）ことで気付ける。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from app.agent import (
    GenerationParseError,
    GenerationRequest,
    GenerationValidationError,
    LLMClientError,
    QuestionGenerator,
    build_llm_client,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate a single question via Vertex AI Claude")
    p.add_argument("--goal", choices=["provisional", "full"], required=True)
    p.add_argument(
        "--category",
        choices=["signs", "rules", "manners", "hazard"],
        required=True,
    )
    p.add_argument(
        "--difficulty",
        choices=["basic", "standard", "advanced"],
        default="standard",
    )
    p.add_argument("--topic-hint", default=None)
    p.add_argument("--max-retries", type=int, default=1)
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    try:
        llm = build_llm_client()
    except LLMClientError as exc:
        print(f"failed to build LLM client: {exc}", file=sys.stderr)
        return 1
    generator = QuestionGenerator(llm, max_retries=args.max_retries)
    request = GenerationRequest(
        goal=args.goal,
        category=args.category,
        difficulty=args.difficulty,
        topic_hint=args.topic_hint,
    )
    try:
        result = generator.generate(request)
    except (GenerationParseError, GenerationValidationError) as exc:
        print(f"generation failed: {exc}", file=sys.stderr)
        return 2
    payload = {
        "question": result.question.model_dump(mode="json"),
        "metadata": {
            "model": result.model,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "cache_read_input_tokens": result.cache_read_input_tokens,
            "cache_creation_input_tokens": result.cache_creation_input_tokens,
        },
    }
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
