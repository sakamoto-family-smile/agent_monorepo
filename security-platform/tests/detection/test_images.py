"""本番イメージの SBOM 取得 (make detection-images) のテスト。gcloud・docker は偽物に差し替える。"""
from __future__ import annotations

import json
from collections.abc import Mapping

import pytest

from src.common.services import ImageRef, Service
from src.detection.images import ImageSbomFetcher, blob_path, manifest_path, read_manifest

REPO = "asia-northeast1-docker.pkg.dev/proj/app/app"
D1, D2 = "sha256:" + "1" * 64, "sha256:" + "2" * 64
TOKEN = "ya29.secret-token"
CDX = json.dumps({"bomFormat": "CycloneDX", "components": []})


class FakeShell:
    def __init__(self) -> None:
        self.images = {"run services describe line": f"{REPO}:abc", "run services describe worker": f"{REPO}:abc",
                       "run jobs describe batch": f"{REPO}:old"}
        self.digests = {f"{REPO}:abc": D1, f"{REPO}:old": D2}
        self.calls: list[tuple[list[str], Mapping[str, str] | None]] = []
        self.syft_output = CDX

    def __call__(self, argv: list[str], env: Mapping[str, str] | None) -> str:
        self.calls.append((argv, env))
        if argv[:3] == ["gcloud", "auth", "print-access-token"]:
            return TOKEN + "\n"
        if argv[:2] == ["gcloud", "run"]:
            return self.images[" ".join(argv[1:5])] + "\n"
        if argv[:3] == ["gcloud", "artifacts", "docker"]:
            return self.digests[argv[5]] + "\n"
        if argv[0] == "docker":
            return self.syft_output
        raise AssertionError(argv)

    def syft_calls(self) -> list[tuple[list[str], Mapping[str, str] | None]]:
        return [c for c in self.calls if c[0][0] == "docker"]


SVC = Service(id="app", path="app/", exposure="external", deployed=True, images=(
    ImageRef(cloud_run="line"), ImageRef(cloud_run="worker"), ImageRef(cloud_run_job="batch"),
))


@pytest.fixture
def fetcher(tmp_path):
    shell = FakeShell()
    return ImageSbomFetcher(tmp_path / "sbom", "anchore/syft:v1@sha256:" + "f" * 64, "proj", shell), shell


def test_image_ref_needs_exactly_one_source():
    with pytest.raises(ValueError):
        ImageRef()
    with pytest.raises(ValueError):
        ImageRef(cloud_run="a", cloud_run_job="b")
    assert ImageRef(cloud_run_job="b").key == "cloud_run_job:b"


def test_fetch_writes_manifest_and_one_sbom_per_digest(fetcher):
    f, shell = fetcher
    r = f.fetch([SVC, Service(id="lib", path="lib/", exposure="none", deployed=False)])
    assert (r.services, r.images, r.generated, r.errors) == (1, 3, 2, [])
    manifest = read_manifest(f.sbom_dir, "app")
    assert [(e["ref"], e["digest"]) for e in manifest["images"]] == [
        ("cloud_run:line", D1), ("cloud_run:worker", D1), ("cloud_run_job:batch", D2),
    ]
    assert blob_path(f.sbom_dir, D1).read_text() == CDX
    syft = shell.syft_calls()
    assert [c[0][-6] for c in syft] == [f"registry:{REPO}@{D1}", f"registry:{REPO}@{D2}"]
    # トークンは環境変数でだけ渡し、コマンドラインには出さない
    assert all(TOKEN not in " ".join(argv) for argv, _ in shell.calls)
    assert syft[0][1]["SYFT_REGISTRY_AUTH_PASSWORD"] == TOKEN
    assert syft[0][1]["SYFT_REGISTRY_AUTH_AUTHORITY"] == "asia-northeast1-docker.pkg.dev"
    assert all("--project=proj" in argv for argv, _ in shell.calls if argv[:2] == ["gcloud", "run"])
    jobs = [argv for argv, _ in shell.calls if argv[:3] == ["gcloud", "run", "jobs"]]
    assert "--format=value(spec.template.spec.template.spec.containers[0].image)" in jobs[0]


def test_existing_sbom_is_reused_and_unused_ones_pruned(fetcher):
    f, shell = fetcher
    f.fetch([SVC])
    shell.images["run jobs describe batch"] = f"{REPO}:abc"  # ジョブも新しいイメージに
    shell.calls.clear()
    r = f.fetch([SVC])
    assert (r.generated, r.removed) == (0, 1)
    assert shell.syft_calls() == []
    assert not blob_path(f.sbom_dir, D2).exists() and blob_path(f.sbom_dir, D1).exists()


def test_failure_keeps_previous_manifest(fetcher):
    f, shell = fetcher
    f.fetch([SVC])
    before = manifest_path(f.sbom_dir, "app").read_text()
    shell.digests[f"{REPO}:old"] = "not-a-digest"
    shell.images["run jobs describe batch"] = f"{REPO}:new"
    shell.digests[f"{REPO}:new"] = "oops"
    r = f.fetch([SVC])
    assert r.errors and "ダイジェストを解決できません" in r.errors[0]
    assert manifest_path(f.sbom_dir, "app").read_text() == before
    assert r.removed == 0


def test_rejects_non_cyclonedx_output(fetcher):
    f, shell = fetcher
    shell.syft_output = json.dumps({"spdxVersion": "SPDX-2.3"})
    r = f.fetch([SVC])
    assert r.errors and "CycloneDX" in r.errors[0]
    assert not manifest_path(f.sbom_dir, "app").exists()


def test_digest_pinned_image_skips_lookup(fetcher):
    f, shell = fetcher
    shell.images["run services describe line"] = f"{REPO}@{D2}"
    assert f.digest_of(f"{REPO}@{D2}") == D2
    assert not any(argv[:2] == ["gcloud", "artifacts"] for argv, _ in shell.calls)
