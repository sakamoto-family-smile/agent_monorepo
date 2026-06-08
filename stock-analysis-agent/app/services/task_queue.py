"""Cloud Tasks への分析タスク enqueue (PROPOSAL-0011 P3-A)。

webhook (stock-analysis-line) が `分析 <銘柄>` を受けたら、分析本体を worker run に
委譲するためのタスクを Cloud Tasks に積む。worker は OIDC 認証付き HTTP POST で
`/api/tasks/analyze` を叩かれ、分析 → LINE Push を行う。

Cloud Tasks が enqueue/dispatch を担うことで:
  - 流量制御 (queue の max_concurrent_dispatches)
  - 失敗時の自動リトライ (指数バックオフ)
  - タスクの永続化 (instance 破棄でも消えない)
が得られる。
"""

from __future__ import annotations

import json
import logging

import config

logger = logging.getLogger(__name__)


def enqueue_analysis(user_id: str, target: str) -> None:
    """`{user_id, target}` を worker の /api/tasks/analyze 宛タスクとして積む。

    必要な設定が欠ける場合は RuntimeError (呼び出し側でフォールバックを判断)。
    """
    s = config.settings
    if not (s.tasks_queue and s.tasks_worker_url):
        raise RuntimeError("TASKS_QUEUE / TASKS_WORKER_URL が未設定です")

    from google.cloud import tasks_v2  # noqa: PLC0415

    client = tasks_v2.CloudTasksClient()
    body = json.dumps({"user_id": user_id, "target": target}).encode("utf-8")

    http_request: dict = {
        "http_method": tasks_v2.HttpMethod.POST,
        "url": s.tasks_worker_url,
        "headers": {"Content-Type": "application/json"},
        "body": body,
    }
    # invoker SA を指定すると Cloud Tasks が OIDC token を付与する (worker が検証)。
    if s.tasks_invoker_sa:
        http_request["oidc_token"] = {
            "service_account_email": s.tasks_invoker_sa,
            "audience": s.tasks_worker_url,
        }

    task: dict = {"http_request": http_request}
    client.create_task(request={"parent": s.tasks_queue, "task": task})
    logger.info("enqueued analysis task for target=%s", target)


__all__ = ["enqueue_analysis"]
