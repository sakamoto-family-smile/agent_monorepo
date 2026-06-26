# attachment-data-pipeline

非構造化テキスト → 構造化テーブル変換の **高Precision抽出/検証パイプライン**(精度検証ハーネス)。

設計ガイド `high_precision_extraction.md`(「絶対に誤った値を入れない」要件)の **精度検証フェーズ** を、
LLM クレデンシャル無しで決定的に回せる形に落とした実装。スコープ確定の根拠は [docs/DESIGN.md](docs/DESIGN.md)。

## 何を検証するか

請求書ドメイン(数値中心)で、**合成-but-grounded** データ(既知レコード→原文を生成し正解spanを記録)に対し、
典型的な抽出誤りを注入したモック抽出器を流し、**検証層(接地＋帰属＋τ棄却)が誤りを弾けるか**を測る。
検証層は完全に LLM 非依存・決定的(設計ガイド 4.7「コア検証は LLM 非依存」)。実 LLM 抽出器は同じ
`Extractor` Protocol の差し替えとして後から挿せる(`extract/llm_extractor.py`)。

## 結果 (test split 30件, `python -m attachment_pipeline.eval.run`)

| 構成 | precision | coverage | recall | 誤採用(FP) | 誤り捕捉 |
|---|---|---|---|---|---|
| 検証なし(baseline) | 0.805 | 1.000 | 1.000 | **128** | 0 / 128 |
| 検証あり(τ=0.5) | **1.000** | 0.711 | 0.883 | **0** | 128 / 128 |
| 検証あり(τ=0.0) | **1.000** | 0.805 | 1.000 | **0** | 128 / 128 |

- **誤採用(FP)を 128 → 0** に。「絶対に誤った値を入れない」要件を満たす。
- τ=0.0(確信度しきい値オフ)でも FP=0・recall=1.0 ── **接地＋帰属だけで全注入誤りを捕捉**でき、
  素朴な確信度しきい値に依存しないことを実証(設計ガイド 3.2「自信を持って間違える」への対処)。
- coverage/recall 低下は precision を買うための棄却コスト(risk–coverage で可視化)。

## 注入する誤りと、それを捕捉する関門

| 誤りモード | 例 | 捕捉する関門 |
|---|---|---|
| `substring_trap` | `18,800` → `800` | 語境界トークン化＋int等価接地(4.5.3) |
| `slot_swap` | issuer ↔ recipient 入替 | **ラベル帰属チェック**(C2対策, `validate/labels.py`) |
| `hallucination` | 原文に無い値 | 接地失敗(逆引き不能) |
| `normalized` | `18,800`→`18800`(正しい) | 双方正規化突合で**採用**(H1対処。誤って棄却しない) |
| `low_conf` | 正しいが低確信 | τ で abstain(reject ではなく復活余地) |

## 構成

```
attachment_pipeline/
├── schema.py          # 所定スキーマ(Invoice)＋型別接地レジストリ(FieldType)
├── contracts.py       # ExtractionResult / DecidedField (抽出↔検証の唯一の境界, 4.7.2)
├── synth/generator.py # 合成-but-grounded 生成器(正解span＋ラベル位置を記録)
├── extract/
│   ├── base.py            # Extractor Protocol
│   ├── mock_extractor.py  # 誤り注入モック(誤りには高確信度を付与)
│   └── llm_extractor.py   # 実LLM抽出器スケルトン(llm-client差し替え)
├── validate/          # 検証パイプライン(LLM非依存・決定的)
│   ├── grounding.py   # 型別接地＋正規化＋数値再検証(int等価)
│   ├── labels.py      # ラベル辞書＋帰属チェック(原文から再検出, goldに非依存)
│   └── decide.py      # 検証チェーン: 接地→帰属→τ棄却 → DecidedField
└── eval/
    ├── metrics.py     # precision@coverage / recall / 誤り捕捉率
    └── run.py         # 統合ハーネス(baseline vs 検証あり, τ掃引)
```

## 使い方

```bash
uv venv --python 3.12 && uv pip install -e . pytest ruff
uv run python -m attachment_pipeline.eval.run   # 精度レポート
uv run pytest -q                                # 回帰テスト(17件)
```

## v1 の対象外 (後続フェーズ)

NER クロスチェック(V4/GiNZA・dateparser)、LLM 検証(V5)、ReCoVERR(証拠探索復活)、
確信度の校正(温度スケーリング)、self-healing 監視ループ。詳細は docs/DESIGN.md §5。
`test_pipeline.py` の `false_positive == 0` を**回帰ゲート**として今後の拡張で維持する。
