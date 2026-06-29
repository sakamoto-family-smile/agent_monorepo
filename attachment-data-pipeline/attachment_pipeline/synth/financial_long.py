"""実物スケールの長文 有価証券報告書 生成器 (option 2)。

短い指標サマリ (gold ブロック) を、定性記述・脚注・撹乱テーブル (セグメント/四半期) で
囲んで数万字規模にする。狙いは検証層の以下のストレス:
  - **逆引きの曖昧性**: 同じ数値が複数テーブルに出現 → evidence_span 絞り込みの有効性
  - **長文ハンドリング**: チャンク分割 + global offset 復元 (validate/chunking.py)

撹乱テーブルには canonical ラベル (「当期売上高」等) を **使わない** ので、帰属チェックは
依然として本物の指標行だけを所有者として扱える。値だけが衝突する状況を作る。

注意: 抽出側 (mock) は gold span を知っているため、長文での『取りこぼし (lost in the
middle)』は本ハーネスでは再現されない。これは実 LLM 抽出器でのみ評価できる。
"""

from __future__ import annotations

import random

from ..schema_financial import FINANCIAL_FIELD_TYPES
from .financial import _MILLION, _Builder, _fmt_million, compute_displays, emit_header, emit_summary
from .generator import GoldSample

_SECTIONS = [
    "事業等のリスク",
    "経営者による財政状態及び経営成績の検討と分析",
    "コーポレート・ガバナンスの状況",
    "事業の内容",
    "研究開発活動",
]
_SENTENCES = [
    "当社グループは、国内外の市場環境の変化に対応するため、継続的な構造改革を推進している。",
    "需要動向は地域によって差異があり、為替変動の影響を受ける可能性がある。",
    "原材料価格の上昇は調達コストに影響を及ぼすため、価格転嫁と効率化を進めている。",
    "人材の確保と育成は持続的成長の基盤であり、教育投資を拡充している。",
    "サプライチェーンの強靱化に向け、調達先の多様化と在庫の最適化に取り組んでいる。",
    "気候変動に関する規制動向を注視し、温室効果ガスの排出削減目標を設定している。",
    "新製品の投入により、既存事業の収益性改善と新規市場の開拓を図っている。",
    "情報セキュリティの強化とガバナンス体制の整備を経営の重要課題と位置づけている。",
]
_REGIONS = ["日本", "北米", "欧州", "アジア"]


def _paragraph(rng: random.Random, n: int) -> str:
    return "".join(rng.choice(_SENTENCES) for _ in range(n))


def _emit_narrative(b: _Builder, rng: random.Random, section: str, paras: int) -> None:
    b.add(f"\n【{section}】\n")
    for _ in range(paras):
        b.add(_paragraph(rng, rng.randint(4, 8)))
        b.add("\n\n")


def _emit_segment_table(b: _Builder, rng: random.Random, values_yen: dict[str, int]) -> None:
    """撹乱テーブル: 数値の一部を本物の指標値と一致させる (canonical ラベルは使わない)。"""
    b.add("\nセグメント情報 (撹乱):\n")
    collide = [values_yen["net_sales_current"], values_yen["operating_income_prior"]]
    for i, region in enumerate(_REGIONS):
        # 一部の地域に本物の指標値を再利用して数値衝突を作る。
        sales = collide[i] if i < len(collide) else rng.randint(1, 999) * 1000 * _MILLION
        profit = rng.randint(1, 200) * 1000 * _MILLION
        b.add(f"  {region} 売上高: {_fmt_million(sales)}  営業利益: {_fmt_million(profit)}\n")
    b.add("\n")


def _emit_quarterly_table(b: _Builder, rng: random.Random) -> None:
    b.add("\n四半期別情報 (撹乱):\n")
    for q in range(1, 5):
        rev = rng.randint(100, 800) * 1000 * _MILLION
        b.add(f"  第{q}四半期 売上収益: {_fmt_million(rev)}\n")
    b.add("\n")


def generate_long_sample(sample_id: int, target_chars: int = 20000) -> GoldSample:
    """gold サマリを長文ボディに埋め込んだ 1 サンプルを生成 (seed 固定)。"""
    rng = random.Random(sample_id * 31 + 1)  # 短文版と同じ値系列
    singletons, metrics, values_yen = compute_displays(rng)
    noise = random.Random(sample_id * 97 + 3)

    b = _Builder()
    b.add("有価証券報告書\n\n")
    b.add("【表紙】\n")
    emit_header(b, singletons)
    b.add("\n")
    _emit_segment_table(b, noise, values_yen)

    # gold ブロックは中盤に置く (lost-in-the-middle 的配置)。
    _emit_narrative(b, noise, _SECTIONS[0], paras=3)
    b.add("\n主要な経営指標等の推移:\n")
    emit_summary(b, metrics)
    _emit_quarterly_table(b, noise)

    # 目標文字数まで定性記述で埋める。
    si = 1
    while len(b.text()) < target_chars:
        _emit_narrative(b, noise, _SECTIONS[si % len(_SECTIONS)], paras=4)
        si += 1

    return GoldSample(
        sample_id=sample_id,
        text=b.text(),
        spans=b.spans,
        field_types=dict(FINANCIAL_FIELD_TYPES),
        record=None,
        labels=b.labels,
    )


def generate_long_dataset(start: int, end: int, target_chars: int = 20000) -> list[GoldSample]:
    return [generate_long_sample(i, target_chars) for i in range(start, end)]
