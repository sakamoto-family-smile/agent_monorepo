"""C2: queue / detail / approve / reject の routes integration テスト。

ReviewService に in-memory 実装を流し込み、create_app() で差し替える。
ADMIN_DEV_BYPASS=true で IAP 認証はスキップ。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.models import Choice, Question, QuestionFormat, Source
from app.models.question import SourceType
from app.repositories.question_bank import InMemoryQuestionBank, StoredQuestion
from app.repositories.question_repo import InMemoryQuestionRepo


def _make_stored(qid: str = "q_test_1", status: str = "needs_review") -> StoredQuestion:
    return StoredQuestion(
        question_id=qid,
        version=1,
        body_hash=f"sha256:{qid}",
        embedding=[0.1] * 768,
        applicable_goals=["provisional"],
        category="rules",
        difficulty="standard",
        status=status,
        created_at=datetime.now(UTC),
    )


def _make_question(qid: str = "q_test_1") -> Question:
    return Question(
        id=qid,
        version=1,
        body="一時停止の標識がある交差点では必ず一時停止しなければならない。",
        format=QuestionFormat.TRUE_FALSE,
        choices=[
            Choice(index=0, text="正しい"),
            Choice(index=1, text="誤り"),
        ],
        correct=0,
        explanation="一時停止標識がある場所では停止線で停止する義務がある。",
        applicable_goals=["provisional", "full"],
        difficulty="standard",
        category="rules",
        sources=[
            Source(
                type=SourceType.LAW,
                title="道路交通法 第43条",
                url="https://elaws.e-gov.go.jp/document?lawid=335AC0000000105",
                quoted_text="一時停止の標識...",
            )
        ],
    )


_CSRF_INPUT_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


async def _csrf_token(client: TestClient, qid: str = "q_csrf_seed") -> str:
    """detail 画面の hidden input から CSRF token を取り出す (session cookie も確立される)。"""
    bank = client.app.state.test_bank
    if await bank.get(qid) is None:
        await bank.add(_make_stored(qid))
    resp = client.get(f"/questions/{qid}")
    assert resp.status_code == 200
    match = _CSRF_INPUT_RE.search(resp.text)
    assert match is not None, "csrf_token hidden input not rendered"
    return match.group(1)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from importlib import reload

    monkeypatch.setenv("ADMIN_DEV_BYPASS", "true")
    monkeypatch.setenv("ADMIN_ALLOWED_EMAILS", "")
    import review_admin_ui.config as config_module

    reload(config_module)
    import review_admin_ui.auth as auth_module

    reload(auth_module)
    import review_admin_ui.main as main_module

    reload(main_module)

    bank = InMemoryQuestionBank()
    repo = InMemoryQuestionRepo()
    from review_admin_ui.services import ReviewService

    svc = ReviewService(bank=bank, repo=repo)
    app = main_module.create_app(review_service=svc)
    # bank/repo もテストで触るため state に保管
    app.state.test_bank = bank
    app.state.test_repo = repo
    return TestClient(app)


@pytest.mark.asyncio
async def test_index_empty_queue(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "needs_review" in resp.text
    assert "該当する問題はありません" in resp.text


@pytest.mark.asyncio
async def test_index_with_items(client: TestClient) -> None:
    bank = client.app.state.test_bank
    repo = client.app.state.test_repo
    await bank.add(_make_stored("q1"))
    await repo.upsert(_make_question("q1"))

    resp = client.get("/")
    assert resp.status_code == 200
    assert "q1" in resp.text
    assert "一時停止" in resp.text  # body excerpt が見える
    assert "rules" in resp.text


@pytest.mark.asyncio
async def test_detail_renders_full_question(client: TestClient) -> None:
    bank = client.app.state.test_bank
    repo = client.app.state.test_repo
    await bank.add(_make_stored("q2"))
    await repo.upsert(_make_question("q2"))

    resp = client.get("/questions/q2")
    assert resp.status_code == 200
    assert "一時停止の標識" in resp.text
    assert "正解" in resp.text  # 正解バッジ
    assert "Approve" in resp.text  # needs_review なのでボタン出る
    assert "道路交通法 第43条" in resp.text


@pytest.mark.asyncio
async def test_detail_404_when_missing(client: TestClient) -> None:
    resp = client.get("/questions/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_approve_transitions_to_published(client: TestClient) -> None:
    bank = client.app.state.test_bank
    await bank.add(_make_stored("q3"))
    token = await _csrf_token(client, "q3")

    resp = client.post("/questions/q3/approve", data={"csrf_token": token}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"

    after = await bank.get("q3")
    assert after is not None
    assert after.status == "published"


@pytest.mark.asyncio
async def test_reject_transitions_to_rejected(client: TestClient) -> None:
    bank = client.app.state.test_bank
    await bank.add(_make_stored("q4"))
    token = await _csrf_token(client, "q4")

    resp = client.post(
        "/questions/q4/reject",
        data={"reason_tag": "factual_error", "csrf_token": token},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    after = await bank.get("q4")
    assert after is not None
    assert after.status == "rejected"


@pytest.mark.asyncio
async def test_approve_404_when_missing(client: TestClient) -> None:
    token = await _csrf_token(client)
    resp = client.post(
        "/questions/nope/approve", data={"csrf_token": token}, follow_redirects=False
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_detail_renders_csrf_token_in_both_forms(client: TestClient) -> None:
    bank = client.app.state.test_bank
    await bank.add(_make_stored("q_forms"))
    resp = client.get("/questions/q_forms")
    assert resp.status_code == 200
    tokens = _CSRF_INPUT_RE.findall(resp.text)
    assert len(tokens) == 3  # approve / reject / header の logout
    assert len(set(tokens)) == 1
    # 同一 session では token は安定 (再描画で変わらない)
    again = client.get("/questions/q_forms")
    assert _CSRF_INPUT_RE.findall(again.text) == tokens


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["approve", "reject"])
async def test_post_without_csrf_token_returns_403(client: TestClient, action: str) -> None:
    bank = client.app.state.test_bank
    await bank.add(_make_stored("q_nocsrf"))
    await _csrf_token(client, "q_nocsrf")  # session には token がある状態

    resp = client.post(
        f"/questions/q_nocsrf/{action}",
        data={"reason_tag": "other"},
        follow_redirects=False,
    )
    assert resp.status_code == 403

    after = await bank.get("q_nocsrf")
    assert after is not None
    assert after.status == "needs_review"  # 状態は変わらない


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["approve", "reject"])
async def test_post_with_wrong_csrf_token_returns_403(client: TestClient, action: str) -> None:
    bank = client.app.state.test_bank
    await bank.add(_make_stored("q_badcsrf"))
    await _csrf_token(client, "q_badcsrf")

    resp = client.post(
        f"/questions/q_badcsrf/{action}",
        data={"csrf_token": "forged-token", "reason_tag": "other"},
        follow_redirects=False,
    )
    assert resp.status_code == 403

    after = await bank.get("q_badcsrf")
    assert after is not None
    assert after.status == "needs_review"


@pytest.mark.asyncio
async def test_post_without_session_token_returns_403(client: TestClient) -> None:
    """session に token が無い (別ブラウザ等からの POST) 場合も 403。"""
    bank = client.app.state.test_bank
    await bank.add(_make_stored("q_nosession"))

    resp = client.post(
        "/questions/q_nosession/approve",
        data={"csrf_token": "anything"},
        follow_redirects=False,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_published_view_shows_published_only(client: TestClient) -> None:
    bank = client.app.state.test_bank
    await bank.add(_make_stored("q_pub", status="published"))
    await bank.add(_make_stored("q_pending", status="needs_review"))

    resp = client.get("/published")
    assert resp.status_code == 200
    assert "q_pub" in resp.text
    assert "q_pending" not in resp.text
