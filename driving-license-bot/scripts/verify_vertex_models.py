"""Vertex AI（Claude / Gemini / text-embedding-004）の実機到達性を確認する CLI。

Phase 2-B1 の smoke verify。Marketplace 承認 + IAM 設定 が完了しているか
最小コール 1 回で確認する。

使い方:
    cd driving-license-bot
    # 全モデル
    make vertex-verify

    # 個別 (Marketplace 承認が間に合わなかったモデルだけスキップ等)
    uv run python scripts/verify_vertex_models.py --include embedding
    uv run python scripts/verify_vertex_models.py --include claude,embedding

各モデル:
- 200 OK + token 数 + サンプル出力 + 所要時間を表示
- 失敗時は例外メッセージを表示し exit code を立てる（部分実行でも残りは続行）

このスクリプトは Vertex AI を **実コール** するため微小な料金（合計 < $0.01）が発生する。
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

ALL_MODELS = ["claude", "gemini", "embedding"]


@dataclass
class VerifyResult:
    name: str
    ok: bool
    model: str = ""
    elapsed_ms: float = 0.0
    detail: str = ""
    error: str = ""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Smoke-verify Vertex AI Claude / Gemini / Embedding."
    )
    p.add_argument(
        "--include",
        default="all",
        help=(
            "Comma-separated model names to verify (claude,gemini,embedding). "
            "Default: all."
        ),
    )
    p.add_argument(
        "--project",
        default=os.getenv("GOOGLE_CLOUD_PROJECT"),
        help="GCP project id（未指定なら GOOGLE_CLOUD_PROJECT env）",
    )
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def select_models(arg: str) -> list[str]:
    if arg == "all":
        return list(ALL_MODELS)
    selected = [s.strip() for s in arg.split(",") if s.strip()]
    invalid = [s for s in selected if s not in ALL_MODELS]
    if invalid:
        raise SystemExit(
            f"ERROR: unknown models {invalid}. Supported: {ALL_MODELS}"
        )
    return selected


def verify_claude() -> VerifyResult:
    from app.agent.llm_client import build_llm_client

    print("[verify_vertex] claude: building client ...")
    try:
        client = build_llm_client()
    except Exception as exc:  # noqa: BLE001
        return VerifyResult(name="claude", ok=False, error=f"build failed: {exc}")
    print(f"[verify_vertex] claude: model={getattr(client, '_model', '?')}")

    t0 = time.perf_counter()
    try:
        resp = client.generate(
            system="You are a smoke-test assistant. Reply with the single word OK.",
            user="ping",
            max_tokens=20,
            temperature=0.0,
            cache_system=True,
        )
    except Exception as exc:  # noqa: BLE001
        return VerifyResult(name="claude", ok=False, error=f"call failed: {exc}")
    elapsed = (time.perf_counter() - t0) * 1000

    detail = (
        f"in={resp.input_tokens} out={resp.output_tokens} "
        f"cache_read={resp.cache_read_input_tokens} "
        f"cache_create={resp.cache_creation_input_tokens} "
        f"text={resp.text!r}"
    )
    return VerifyResult(
        name="claude",
        ok=True,
        model=resp.model,
        elapsed_ms=elapsed,
        detail=detail,
    )


def verify_gemini() -> VerifyResult:
    from app.agent.llm_client import build_reviewer_llm_client

    print("[verify_vertex] gemini: building client ...")
    try:
        client = build_reviewer_llm_client()
    except Exception as exc:  # noqa: BLE001
        return VerifyResult(name="gemini", ok=False, error=f"build failed: {exc}")
    print(f"[verify_vertex] gemini: model={getattr(client, '_model', '?')}")

    t0 = time.perf_counter()
    try:
        # Gemini 2.5 系は "thinking" モードで内部的に tokens を消費するため
        # max_tokens を絞ると finish_reason=MAX_TOKENS で空文字応答になる。
        # smoke では 200 tokens 程度の余裕を持たせる。
        resp = client.generate(
            system="You are a smoke-test assistant.",
            user="Reply with the single word OK.",
            max_tokens=200,
            temperature=0.0,
        )
    except Exception as exc:  # noqa: BLE001
        return VerifyResult(name="gemini", ok=False, error=f"call failed: {exc}")
    elapsed = (time.perf_counter() - t0) * 1000

    detail = (
        f"in={resp.input_tokens} out={resp.output_tokens} text={resp.text!r}"
    )
    return VerifyResult(
        name="gemini",
        ok=True,
        model=resp.model,
        elapsed_ms=elapsed,
        detail=detail,
    )


def verify_embedding() -> VerifyResult:
    from app.agent.embedding import build_embedding_client

    print("[verify_vertex] embedding: building client ...")
    try:
        client = build_embedding_client()
    except Exception as exc:  # noqa: BLE001
        return VerifyResult(name="embedding", ok=False, error=f"build failed: {exc}")
    print(
        f"[verify_vertex] embedding: model={getattr(client, '_model', '?')} "
        f"dim={client.dimension}"
    )

    t0 = time.perf_counter()
    try:
        vec = client.embed("運転免許学科試験の標識問題")
    except Exception as exc:  # noqa: BLE001
        return VerifyResult(name="embedding", ok=False, error=f"call failed: {exc}")
    elapsed = (time.perf_counter() - t0) * 1000

    if len(vec) != client.dimension:
        return VerifyResult(
            name="embedding",
            ok=False,
            error=f"dimension mismatch: expected {client.dimension}, got {len(vec)}",
        )
    detail = (
        f"dim={len(vec)} sample[0:3]={vec[:3]} norm≈{sum(v * v for v in vec) ** 0.5:.4f}"
    )
    return VerifyResult(
        name="embedding",
        ok=True,
        model=getattr(client, "_model", ""),
        elapsed_ms=elapsed,
        detail=detail,
    )


VERIFIERS = {
    "claude": verify_claude,
    "gemini": verify_gemini,
    "embedding": verify_embedding,
}


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.project:
        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", args.project)
        os.environ.setdefault("ANTHROPIC_VERTEX_PROJECT_ID", args.project)
    if not os.getenv("GOOGLE_CLOUD_PROJECT"):
        raise SystemExit(
            "ERROR: GOOGLE_CLOUD_PROJECT が必要です（--project または env）"
        )

    selected = select_models(args.include)
    print(f"[verify_vertex] verifying: {', '.join(selected)}")
    print(f"[verify_vertex] project={os.environ['GOOGLE_CLOUD_PROJECT']}")

    results: list[VerifyResult] = []
    for name in selected:
        results.append(VERIFIERS[name]())

    print("")
    print("[verify_vertex] === summary ===")
    fails = 0
    for r in results:
        if r.ok:
            print(f"  ✓ {r.name:9s}  model={r.model}  {r.elapsed_ms:6.1f} ms")
            print(f"      {r.detail}")
        else:
            fails += 1
            print(f"  ✗ {r.name:9s}  FAIL: {r.error}", file=sys.stderr)

    if fails > 0:
        print(f"\n[verify_vertex] {fails} model(s) failed.", file=sys.stderr)
        return 2
    print("\n[verify_vertex] ALL OK.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
