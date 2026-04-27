"""LLM ベースの問題生成 / 検証エージェント群（Phase 2 から実装）。

Phase 2-B: Question Generator
Phase 2-C: Fact Checker (rule-based) + Quality Reviewer (Gemini cross-check) + Pipeline
"""

from app.agent.embedding import (
    EmbeddingClient,
    MockEmbeddingClient,
    VertexEmbeddingClient,
    build_embedding_client,
)
from app.agent.errors import (
    GenerationParseError,
    GenerationValidationError,
    LLMClientError,
)
from app.agent.fact_checker import FactChecker, FactCheckResult, FactIssue
from app.agent.llm_client import (
    LLMClient,
    LLMResponse,
    MockLLMClient,
    VertexAnthropicClient,
    VertexGeminiClient,
    build_llm_client,
    build_reviewer_llm_client,
)
from app.agent.models import GenerationRequest, GenerationResult
from app.agent.pipeline import (
    DedupResult,
    GenerationPipeline,
    PipelineOutcome,
    PipelineResult,
)
from app.agent.quality_reviewer import QualityReviewer, QualityReviewResult
from app.agent.question_generator import QuestionGenerator

__all__ = [
    "DedupResult",
    "EmbeddingClient",
    "FactCheckResult",
    "FactChecker",
    "FactIssue",
    "GenerationParseError",
    "GenerationPipeline",
    "GenerationRequest",
    "GenerationResult",
    "GenerationValidationError",
    "LLMClient",
    "LLMClientError",
    "LLMResponse",
    "MockEmbeddingClient",
    "MockLLMClient",
    "PipelineOutcome",
    "PipelineResult",
    "QualityReviewResult",
    "QualityReviewer",
    "QuestionGenerator",
    "VertexAnthropicClient",
    "VertexEmbeddingClient",
    "VertexGeminiClient",
    "build_embedding_client",
    "build_llm_client",
    "build_reviewer_llm_client",
]
