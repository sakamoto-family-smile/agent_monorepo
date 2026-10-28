"""通知の送り先 (LINE Messaging API の push と GitHub Issues)。

どちらも httpx で直接呼ぶ (SDK を増やさない)。認証情報は notify コンテナにだけ渡す
(config/notify.env)。未設定なら ``configured`` が False になり、呼び出し側は送らずに記録だけ残す。
"""
from __future__ import annotations

import uuid
from typing import Any

import httpx

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
LINE_TEXT_LIMIT = 4900  # 1 メッセージ 5000 字の上限に余裕を持たせる
LINE_MESSAGES_PER_PUSH = 5  # 1 回の push で送れるメッセージ数の上限
GITHUB_API = "https://api.github.com"


class ChannelError(RuntimeError):
    pass


def split_text(text: str, limit: int = LINE_TEXT_LIMIT) -> list[str]:
    """行の区切りで limit 字以内に分ける (1 行が長すぎるときだけ行の途中で切る)。"""
    chunks: list[str] = []
    current = ""
    for line in text.splitlines():
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [""]


class LineChannel:
    def __init__(self, client: httpx.Client, token: str, recipients: list[str]) -> None:
        self.client = client
        self.token = token
        self.recipients = recipients

    @property
    def configured(self) -> bool:
        return bool(self.token and self.recipients)

    def send(self, text: str, dedupe_key: str) -> None:
        """全員に送る。dedupe_key から作る X-Line-Retry-Key で、再送しても LINE 側で二重にならない。"""
        chunks = split_text(text)
        for to in self.recipients:
            for i in range(0, len(chunks), LINE_MESSAGES_PER_PUSH):
                part = chunks[i:i + LINE_MESSAGES_PER_PUSH]
                retry_key = uuid.uuid5(uuid.NAMESPACE_URL, f"{dedupe_key}\n{to}\n{i}")
                resp = self.client.post(
                    LINE_PUSH_URL,
                    headers={"Authorization": f"Bearer {self.token}", "X-Line-Retry-Key": str(retry_key)},
                    json={"to": to, "messages": [{"type": "text", "text": t} for t in part]},
                    timeout=30.0,
                )
                # 409: 同じ Retry-Key で送信済み (前回の送信は届いている)
                if resp.status_code >= 400 and resp.status_code != 409:
                    raise ChannelError(f"LINE push failed: {resp.status_code} {resp.text[:300]}")


class GitHubIssues:
    def __init__(self, client: httpx.Client, token: str, repo: str) -> None:
        self.client = client
        self.token = token
        self.repo = repo

    @property
    def configured(self) -> bool:
        return bool(self.token and self.repo)

    def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        resp = self.client.request(
            method, f"{GITHUB_API}/repos/{self.repo}{path}",
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28"},
            timeout=30.0, **kw,
        )
        return resp

    def _check(self, resp: httpx.Response, what: str) -> httpx.Response:
        if resp.status_code >= 400:
            raise ChannelError(f"GitHub {what} failed: {resp.status_code} {resp.text[:300]}")
        return resp

    def ensure_label(self, name: str, color: str) -> None:
        if self._request("GET", f"/labels/{name}").status_code == 404:
            resp = self._request("POST", "/labels", json={"name": name, "color": color})
            if resp.status_code != 422:  # 422: 同時に作られて既にある
                self._check(resp, "create label")

    def create(self, title: str, body: str, labels: list[str]) -> int:
        resp = self._check(self._request("POST", "/issues", json={"title": title, "body": body, "labels": labels}),
                           "create issue")
        return int(resp.json()["number"])

    def update(self, number: int, *, title: str, body: str, labels: list[str], state: str) -> None:
        self._check(self._request("PATCH", f"/issues/{number}", json={
            "title": title, "body": body, "labels": labels, "state": state,
        }), "update issue")
