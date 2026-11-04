"""extractor イメージのビルド時に Claude Code の CLI (Linux 用の単体バイナリ) を取得する。

npm の platform パッケージの tarball を取り、SHA-512 (registry の integrity と同じ値) を確かめてから展開する。
版とハッシュは infra/Dockerfile の ARG で固定する (タグや latest は使わない)。

    python fetch_claude_code.py <version> <arch: arm64|amd64> <sha512 hex> <出力先>
"""
from __future__ import annotations

import hashlib
import io
import sys
import tarfile
import urllib.request
from pathlib import Path

ARCH = {"arm64": "linux-arm64", "amd64": "linux-x64"}
MAX_BYTES = 500_000_000


def main(version: str, arch: str, sha512: str, dest: str) -> None:
    pkg = f"claude-code-{ARCH[arch]}"
    url = f"https://registry.npmjs.org/@anthropic-ai/{pkg}/-/{pkg}-{version}.tgz"
    with urllib.request.urlopen(url, timeout=300) as r:  # nosec B310 - 固定の https URL
        body = r.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        sys.exit(f"{url}: larger than {MAX_BYTES} bytes")
    got = hashlib.sha512(body).hexdigest()
    if got != sha512.lower():
        sys.exit(f"{url}: sha512 mismatch (got {got})")
    with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as tar:
        member = tar.getmember("package/claude")
        src = tar.extractfile(member)
        if src is None:
            sys.exit("package/claude is not a regular file")
        out = Path(dest)
        out.write_bytes(src.read())
        out.chmod(0o755)
    print(f"claude {version} ({arch}) -> {dest}")


if __name__ == "__main__":
    main(*sys.argv[1:5])
