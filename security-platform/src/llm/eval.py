"""抜き出しの評価。プロバイダ・モデル・指示を変えたら `make llm-eval` で前後を比べる。

評価用の記事 (eval_cases.json) は実際の出来事を参考に書いた架空の短い記事で、期待するパッケージを持つ。
原文との突き合わせ (grounding) を通った主張だけを数え、パッケージ名で期待と比べる。
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .exchange import job_id
from .grounding import ground, normalize
from .providers import ExtractionFailed, Extractor
from .schema import ExtractInput

CASES_PATH = Path(__file__).with_name("eval_cases.json")


@dataclass(frozen=True)
class Case:
    id: str
    title: str
    text: str
    expected: tuple[str, ...]  # パッケージ名

    def item(self) -> ExtractInput:
        rid = "rep_" + "0" * 24
        return ExtractInput(job_id(rid, "0" * 12), rid, "0" * 12, self.title, None, self.text)


CHECK_CASE = Case("check", "Malicious npm package found",
                  "Researchers found that the npm package left-padx version 1.0.3 contains malware that steals "
                  "tokens.", ("left-padx",))


def load_cases(path: Path = CASES_PATH) -> list[Case]:
    return [Case(c["id"], c["title"], c["text"], tuple(c["expected"])) for c in json.loads(path.read_text())]


@dataclass
class Score:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    ungrounded: int = 0
    errors: int = 0
    details: list[str] = field(default_factory=list)

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 1.0


def score(extractor: Extractor, cases: list[Case], echo: Callable[[str], None] = print) -> Score:
    total = Score()
    for case in cases:
        try:
            out = extractor.extract(case.item())
        except ExtractionFailed as e:
            total.errors += 1
            echo(f"ERROR {case.id}: {e}")
            continue
        claims = [ground(f"{case.title}\n{case.text}", c) for c in out["claims"]]
        got = {normalize(c.package) for c in claims if c.grounded}
        ungrounded = [c.package for c in claims if not c.grounded]
        want = {normalize(p) for p in case.expected}
        tp, fp, fn = got & want, got - want, want - got
        total.tp, total.fp, total.fn = total.tp + len(tp), total.fp + len(fp), total.fn + len(fn)
        total.ungrounded += len(ungrounded)
        mark = "OK   " if not fp and not fn else "DIFF "
        echo(f"{mark} {case.id}: got={sorted(got)} want={sorted(want)}"
             + (f" ungrounded={ungrounded}" if ungrounded else ""))
    return total
