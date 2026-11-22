"""GitHub API (remediation コンテナだけが使う。トークンは config/remediation.env)。

httpx で直接呼ぶ (SDK を増やさない)。リポジトリは public なので、写しを取るだけならトークンなしでも動く
(未認証は 1 時間 60 回まで。写しの確認は ETag の条件付きリクエストにして回数を使わない)。

fine-grained PAT は期限を ``github-authentication-token-expiration`` ヘッダで返すので、
最後に見た値を ``token_expires_at`` に残す (期限が近づいたら通知する)。
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from ..common.http import with_retry

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
EXPIRATION_HEADER = "github-authentication-token-expiration"


class GitHubError(RuntimeError):
    pass


def parse_expiration(value: str) -> datetime | None:
    """``2027-10-31 15:00:00 UTC`` / ``2027-10-31 15:00:00 +0900`` の形。"""
    v = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S %Z", "%Y-%m-%d %H:%M:%S %z"):
        try:
            dt = datetime.strptime(v, fmt)
        except ValueError:
            continue
        if dt.tzinfo is None:  # %Z は tzinfo を付けない
            dt = dt.replace(tzinfo=UTC)
        return dt
    return None


@dataclass
class HeadCache:
    """前回の ``commits/<branch>`` の応答 (ETag が一致すれば 304 で返り、回数を使わない)。"""

    etag: str | None = None
    sha: str | None = None


class GitHub:
    def __init__(self, client: httpx.Client, repo: str, token: str = "") -> None:
        self.client = client
        self.repo = repo
        self.token = token
        self.token_expires_at: datetime | None = None
        self._head = HeadCache()

    def _headers(self, accept: str = "application/vnd.github+json") -> dict[str, str]:
        h = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _observe(self, resp: httpx.Response) -> None:
        value = resp.headers.get(EXPIRATION_HEADER)
        if value and (expires := parse_expiration(value)) is not None:
            self.token_expires_at = expires

    def request(self, method: str, path: str, *, accept: str = "application/vnd.github+json",
                headers: dict[str, str] | None = None, **kw: Any) -> httpx.Response:
        url = path if path.startswith("https://") else f"{GITHUB_API}{path}"

        def send() -> httpx.Response:
            resp = self.client.request(method, url, headers={**self._headers(accept), **(headers or {})}, **kw)
            if resp.status_code >= 500:
                resp.raise_for_status()  # with_retry がやり直す
            return resp

        resp = with_retry(send, what=f"GitHub {method} {path}")
        self._observe(resp)
        return resp

    @staticmethod
    def check(resp: httpx.Response, what: str) -> httpx.Response:
        if resp.status_code >= 400:
            raise GitHubError(f"GitHub {what} failed: {resp.status_code} {resp.text[:300]}")
        return resp

    # ── リポジトリの写し ──────────────────────────────────────────────────
    def head_sha(self, branch: str) -> str:
        """ブランチの先頭のコミット。"""
        headers = {"If-None-Match": self._head.etag} if self._head.etag and self._head.sha else {}
        resp = self.request("GET", f"/repos/{self.repo}/commits/{branch}", accept="application/vnd.github.sha",
                            headers=headers)
        if resp.status_code == 304 and self._head.sha:
            return self._head.sha
        sha = self.check(resp, f"get {branch}").text.strip()
        if len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
            raise GitHubError(f"GitHub get {branch}: unexpected sha {sha[:60]!r}")
        self._head = HeadCache(resp.headers.get("ETag"), sha)
        return sha

    @contextmanager
    def tarball(self, sha: str) -> Iterator[httpx.Response]:
        """コミットの tarball (codeload へのリダイレクトを追う。認証ヘッダは別ホストには送られない)。"""
        url = f"{GITHUB_API}/repos/{self.repo}/tarball/{sha}"
        with self.client.stream("GET", url, headers=self._headers(), follow_redirects=True) as resp:
            self._observe(resp)
            if resp.status_code >= 400:
                resp.read()
                raise GitHubError(f"GitHub tarball {sha[:12]} failed: {resp.status_code} {resp.text[:300]}")
            yield resp

    # ── PR (Git Data API でコミットを作る。手元に git は要らない) ────────────
    def create_commit(self, base_sha: str, path: str, content: str, message: str) -> str:
        """base_sha の上で path だけを content に置き換えたコミットを作る (ブランチはまだ作らない)。"""
        base = self.check(self.request("GET", f"/repos/{self.repo}/git/commits/{base_sha}"), "get commit").json()
        blob = self.check(self.request("POST", f"/repos/{self.repo}/git/blobs",
                                       json={"content": content, "encoding": "utf-8"}), "create blob").json()
        tree = self.check(self.request("POST", f"/repos/{self.repo}/git/trees", json={
            "base_tree": base["tree"]["sha"],
            "tree": [{"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]}],
        }), "create tree").json()
        commit = self.check(self.request("POST", f"/repos/{self.repo}/git/commits", json={
            "message": message, "tree": tree["sha"], "parents": [base_sha],
        }), "create commit").json()
        return str(commit["sha"])

    def create_branch(self, branch: str, sha: str) -> None:
        self.check(self.request("POST", f"/repos/{self.repo}/git/refs",
                                json={"ref": f"refs/heads/{branch}", "sha": sha}), "create branch")

    def delete_branch(self, branch: str) -> None:
        resp = self.request("DELETE", f"/repos/{self.repo}/git/refs/heads/{branch}")
        if resp.status_code not in (204, 404, 422):  # 404/422: 消えている (マージで自動削除など)
            self.check(resp, "delete branch")

    def changed_files(self, base: str, head: str) -> list[str]:
        data = self.check(self.request("GET", f"/repos/{self.repo}/compare/{base}...{head}"), "compare").json()
        return [str(f["filename"]) for f in data.get("files") or []]

    def compare_status(self, base: str, head: str) -> str:
        """head から見た base: ``ahead`` / ``identical`` なら head は base を含む。"""
        data = self.check(self.request("GET", f"/repos/{self.repo}/compare/{base}...{head}"), "compare").json()
        return str(data.get("status", ""))

    def create_pull(self, branch: str, base: str, title: str, body: str) -> dict[str, Any]:
        return self.check(self.request("POST", f"/repos/{self.repo}/pulls", json={
            "title": title, "head": branch, "base": base, "body": body, "maintainer_can_modify": True,
        }), "create pull request").json()

    def get_pull(self, number: int) -> dict[str, Any]:
        return self.check(self.request("GET", f"/repos/{self.repo}/pulls/{number}"), "get pull request").json()

    def close_pull(self, number: int) -> None:
        self.check(self.request("PATCH", f"/repos/{self.repo}/pulls/{number}", json={"state": "closed"}),
                   "close pull request")

    def enable_auto_merge(self, node_id: str, method: str = "MERGE") -> None:
        """CI (必須のチェック) が通ったら GitHub がマージする。"""
        query = ("mutation($id: ID!, $method: PullRequestMergeMethod!) { enablePullRequestAutoMerge("
                 "input: {pullRequestId: $id, mergeMethod: $method}) { clientMutationId } }")
        resp = self.check(self.request("POST", "/graphql", json={
            "query": query, "variables": {"id": node_id, "method": method}}), "enable auto-merge")
        errors = resp.json().get("errors")
        if errors:
            raise GitHubError(f"GitHub enable auto-merge failed: {str(errors)[:300]}")

    def check_runs(self, sha: str) -> list[dict[str, Any]]:
        data = self.check(self.request("GET", f"/repos/{self.repo}/commits/{sha}/check-runs",
                                       params={"per_page": 100}), "list check runs").json()
        return list(data.get("check_runs") or [])

    def workflow_runs(self, workflow: str, head_sha: str) -> list[dict[str, Any]]:
        data = self.check(self.request("GET", f"/repos/{self.repo}/actions/workflows/{workflow}/runs",
                                       params={"head_sha": head_sha, "per_page": 20}), "list workflow runs").json()
        return list(data.get("workflow_runs") or [])

    def run_jobs(self, run_id: int) -> list[dict[str, Any]]:
        data = self.check(self.request("GET", f"/repos/{self.repo}/actions/runs/{run_id}/jobs",
                                       params={"per_page": 100}), "list jobs").json()
        return list(data.get("jobs") or [])
