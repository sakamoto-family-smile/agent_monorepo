"""本番イメージの SBOM を作る (ホストで実行: ``make detection-images``)。

detection コンテナはネットワークを持たないので、イメージの取得と SBOM の生成はここで行い、
結果を data/sbom/images/ に置く。照合 (scan) はそのファイルを読むだけ。

1. gcloud で Cloud Run のサービス・ジョブが今使っているイメージを調べ、
   Artifact Registry でダイジェストに解決する (タグは付け替えられるので、照合はダイジェスト単位)
2. まだ SBOM の無いダイジェストだけ、syft (コンテナ、ダイジェスト固定) で CycloneDX JSON にする。
   レジストリの認証は gcloud の短命なアクセストークンを環境変数で渡す (コマンドラインに出さない)
3. サービスごとのマニフェスト ``<service_id>.json`` を書き換え、どこからも参照されない SBOM を消す

イメージを 1 つでも調べられなかったサービスはマニフェストを書き換えない (前回の SBOM で照合を続ける)。
SQLite には触らないので、ホストから実行してよい。
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess  # nosec B404  gcloud / docker を引数リストで呼ぶだけ (シェルは使わない)
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..common.services import ImageRef, Service
from ..common.timeutil import utc_now_iso

logger = logging.getLogger(__name__)

BLOBS = "blobs"
COMMAND_TIMEOUT = 900  # 秒。大きなイメージの syft でも収まる長さ
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def is_digest(value: str) -> bool:
    return bool(_DIGEST.match(value))

# (argv, 追加の環境変数) → 標準出力。テストでは差し替える
Runner = Callable[[list[str], Mapping[str, str] | None], str]


def run_command(argv: list[str], extra_env: Mapping[str, str] | None = None) -> str:
    env = {**os.environ, **extra_env} if extra_env else None
    done = subprocess.run(  # nosec B603  argv は固定のコマンド + services.yaml の名前
        argv, env=env, capture_output=True, text=True, timeout=COMMAND_TIMEOUT, check=False,
    )
    if done.returncode != 0:
        raise RuntimeError(f"{argv[0]} {argv[1]} が失敗しました: {done.stderr.strip()[-500:]}")
    return done.stdout


def manifest_path(sbom_dir: Path, service_id: str) -> Path:
    return sbom_dir / f"{service_id}.json"


def blob_path(sbom_dir: Path, digest: str) -> Path:
    return sbom_dir / BLOBS / f"{digest.replace(':', '-')}.cdx.json"


def read_manifest(sbom_dir: Path, service_id: str) -> dict[str, Any] | None:
    path = manifest_path(sbom_dir, service_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"{path.name} を読めません ({e})") from e
    if not isinstance(data, dict) or not isinstance(data.get("images"), list):
        raise ValueError(f"{path.name} の形式が違います")
    return data


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


@dataclass
class FetchResult:
    services: int = 0
    images: int = 0
    generated: int = 0  # 新しく SBOM を作ったダイジェスト
    removed: int = 0  # 参照されなくなって消した SBOM
    errors: list[str] = field(default_factory=list)


class ImageSbomFetcher:
    def __init__(
        self, sbom_dir: Path, syft_image: str, project: str = "", runner: Runner = run_command,
    ) -> None:
        self.sbom_dir = sbom_dir
        self.syft_image = syft_image
        self.project = project
        self.run = runner
        self._token: str | None = None

    def _gcloud(self, *args: str) -> str:
        argv = ["gcloud", *args]
        if self.project:
            argv.append(f"--project={self.project}")
        return self.run(argv, None).strip()

    def image_of(self, ref: ImageRef) -> str:
        """Cloud Run の設定にあるイメージ (タグかダイジェスト付き)。"""
        if ref.cloud_run is not None:
            fmt = "value(spec.template.spec.containers[0].image)"
            image = self._gcloud("run", "services", "describe", ref.cloud_run, f"--region={ref.region}",
                                 f"--format={fmt}")
        else:
            fmt = "value(spec.template.spec.template.spec.containers[0].image)"
            image = self._gcloud("run", "jobs", "describe", str(ref.cloud_run_job), f"--region={ref.region}",
                                 f"--format={fmt}")
        if not image:
            raise RuntimeError(f"{ref.key}: イメージを取得できません")
        return image

    def digest_of(self, image: str) -> str:
        if "@" in image:
            digest = image.rsplit("@", 1)[1]
        else:
            digest = self._gcloud("artifacts", "docker", "images", "describe", image,
                                  "--format=value(image_summary.digest)")
        if not is_digest(digest):
            raise RuntimeError(f"{image}: ダイジェストを解決できません ({digest!r})")
        return digest

    def _access_token(self) -> str:
        if self._token is None:
            self._token = self.run(["gcloud", "auth", "print-access-token"], None).strip()
        return self._token

    def generate(self, repository: str, digest: str) -> None:
        """syft で ``repository@digest`` の SBOM を作る。"""
        registry = repository.split("/", 1)[0]
        auth = {
            "SYFT_REGISTRY_AUTH_AUTHORITY": registry,
            "SYFT_REGISTRY_AUTH_USERNAME": "oauth2accesstoken",
            "SYFT_REGISTRY_AUTH_PASSWORD": self._access_token(),
        }
        argv = ["docker", "run", "--rm"]
        for name in auth:
            argv += ["-e", name]  # 値は環境変数から渡す (docker のコマンドラインに出さない)
        argv += ["-e", "SYFT_CHECK_FOR_APP_UPDATE=false", self.syft_image,
                 f"registry:{repository}@{digest}", "--platform", "linux/amd64", "-o", "cyclonedx-json", "-q"]
        out = self.run(argv, auth)
        try:
            data = json.loads(out)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"{repository}@{digest}: syft の出力を読めません ({e})") from e
        if data.get("bomFormat") != "CycloneDX":
            raise RuntimeError(f"{repository}@{digest}: CycloneDX ではありません")
        _write_atomic(blob_path(self.sbom_dir, digest), out)

    def fetch(self, services: list[Service]) -> FetchResult:
        result = FetchResult()
        for svc in services:
            if not svc.images:
                continue
            result.services += 1
            try:
                entries = self._fetch_service(svc, result)
            except Exception as e:  # noqa: BLE001  1 サービスの失敗で他を止めない
                logger.warning("%s: %s", svc.id, e)
                result.errors.append(f"{svc.id}: {e}")
                continue
            manifest = {"service_id": svc.id, "generated_at": utc_now_iso(), "images": entries}
            _write_atomic(manifest_path(self.sbom_dir, svc.id),
                          json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        result.removed = self._prune()
        return result

    def _fetch_service(self, svc: Service, result: FetchResult) -> list[dict[str, str]]:
        entries = []
        for ref in svc.images:
            image = self.image_of(ref)
            digest = self.digest_of(image)
            repository = repository_of(image)
            if not blob_path(self.sbom_dir, digest).exists():
                logger.info("%s: %s@%s の SBOM を作ります", svc.id, repository, digest[:19])
                self.generate(repository, digest)
                result.generated += 1
            result.images += 1
            entries.append({"ref": ref.key, "image": image, "digest": digest,
                            "sbom": blob_path(self.sbom_dir, digest).name})
        return entries

    def _prune(self) -> int:
        """どのマニフェストからも参照されない SBOM を消す。"""
        blobs = self.sbom_dir / BLOBS
        if not blobs.is_dir():
            return 0
        used: set[str] = set()
        for path in self.sbom_dir.glob("*.json"):
            try:
                used.update(e["sbom"] for e in json.loads(path.read_text(encoding="utf-8"))["images"])
            except (OSError, ValueError, KeyError, TypeError):
                return 0  # 読めないマニフェストがあれば安全側で何も消さない
        removed = 0
        for blob in blobs.glob("*.cdx.json"):
            if blob.name not in used:
                blob.unlink()
                removed += 1
        return removed


def repository_of(image: str) -> str:
    """``host/path/name:tag`` / ``host/path/name@sha256:...`` からリポジトリ部分を取り出す。"""
    name = image.split("@", 1)[0]
    last = name.rsplit("/", 1)
    if ":" in last[-1]:
        name = name[: len(name) - len(last[-1])] + last[-1].split(":", 1)[0]
    return name
