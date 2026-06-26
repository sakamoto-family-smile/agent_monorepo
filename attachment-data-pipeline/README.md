# attachment-data-pipeline

非構造化テキスト → 構造化テーブル変換の **高Precision抽出/検証パイプライン**(精度検証ハーネス)。

設計ガイド `high_precision_extraction.md`(「絶対に誤った値を入れない」要件)の **精度検証フェーズ** を、
LLM クレデンシャル無しで決定的に回せる形に落とした実装。スコープ確定の根拠は [docs/DESIGN.md](docs/DESIGN.md)。

## 何を検証するか

請求書ドメイン(数値中心)で、**合成-but-grounded** データ(既知レコード→原文を生成し正解spanを記録)に対し、
典型的な抽出誤りを注入したモック抽出器を流し、**検証層(接地＋帰属＋τ棄却)が誤りを弾けるか**を測る。
検証層は完全に LLM 非依存・決定的(設計ガイド 4.7「コア検証は LLM 非依存」)。実 LLM 抽出器は同じ
`Extractor` Protocol の差し替えとして後から挿せる(`extract/llm_extractor.py`)。

## 検証ドメイン

2 ドメインで「抽出のみ vs 抽出+検証」を比較。検証層 (接地/帰属/τ) は共通で、ドメイン
固有部分 (スキーマ・生成器・ラベル辞書) だけ差し替える。

### 請求書 (test 30件, `python -m attachment_pipeline.eval.run`)

| 構成 | precision | coverage | recall | 誤採用(FP) | 誤り捕捉 |
|---|---|---|---|---|---|
| 検証なし(baseline) | 0.805 | 1.000 | 1.000 | **128** | 0 / 128 |
| 検証あり(τ=0.5) | **1.000** | 0.711 | 0.883 | **0** | 128 / 128 |
| 検証あり(τ=0.0) | **1.000** | 0.805 | 1.000 | **0** | 128 / 128 |

### 財務/有価証券報告書 (test 30件, `python -m attachment_pipeline.eval.run_financial`)

| 構成 | precision | coverage | recall | 誤採用(FP) | 誤り捕捉 |
|---|---|---|---|---|---|
| 抽出のみ(baseline) | 0.617 | 1.000 | 1.000 | **241** | 0 / 241 |
| 抽出+検証(τ=0.5) | **1.000** | 0.533 | 0.864 | **0** | 241 / 241 |
| 抽出+検証(τ=0.0) | **1.000** | 0.617 | 1.000 | **0** | 241 / 241 |

財務固有の誤り (**スケール忘れ `1,495,000百万円→1,495,000` / 符号反転 `△12,345→12,345` /
当期↔前期の列取り違え**) を、スケール対応接地・符号正規化・期間ラベル帰属で全捕捉。
baseline precision が請求書より低い (0.617) のは、スケール/符号/期間という財務特有の
誤りが多く混入するため。検証層はいずれも τ=0 でも FP=0・recall=1.0 を達成。

### 長文/実物スケール有報 (test 30件・平均約20,000字, `python -m attachment_pipeline.eval.run_financial_long`)

定性記述・脚注・**数値が衝突する撹乱テーブル**(セグメント/四半期)で gold ブロックを
囲んで実物スケール化し、逆引きの曖昧性を増やしたストレステスト。

| 構成 | precision | coverage | recall | 誤採用(FP) |
|---|---|---|---|---|
| 抽出のみ(baseline) | 0.617 | 1.000 | 1.000 | **241** |
| 抽出+検証(τ=0.5) | **1.000** | 0.533 | 0.864 | **0** |

平均20,393字・チャンク平均12.4個。**数値衝突があっても evidence_span 絞り込み＋接地の
precision硬化(evidence領域外の遠方一致は棄却)で誤接地ゼロ**、clean の過棄却も0を維持。
チャンク分割は global offset を保存(`validate/chunking.py`、テストで復元を検証)。

> 限界: mock 抽出器は gold span を知るため、長文での**取りこぼし(lost in the middle)は
> 未再現**。長文での抽出側劣化は実 LLM 抽出器でのみ評価できる。

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
├── schema.py            # 請求書スキーマ＋型別接地レジストリ(FieldType)
├── schema_financial.py  # 財務スキーマ・型・期間ラベル辞書(当期/前期)
├── contracts.py         # ExtractionResult / DecidedField (抽出↔検証の唯一の境界, 4.7.2)
├── synth/
│   ├── generator.py      # 請求書 合成-but-grounded 生成器(正解span＋ラベル位置)
│   ├── financial.py      # 財務 生成器(百万円スケール/△負数/当期前期列)
│   └── financial_long.py # 財務 長文生成器(定性記述+撹乱テーブルで実物スケール化)
├── extract/
│   ├── base.py             # Extractor Protocol
│   ├── mock_extractor.py   # 請求書 誤り注入モック(部分一致罠/スロット入替/捏造)
│   ├── financial_mock.py   # 財務 誤り注入モック(scale_drop/sign_flip/wrong_period)
│   └── llm_extractor.py    # 実LLM抽出器スケルトン(llm-client差し替え)
├── validate/            # 検証パイプライン(LLM非依存・決定的, ドメイン共通)
│   ├── grounding.py     # 型別接地＋正規化(スケール/符号/全角)＋数値再検証
│   ├── labels.py        # ラベル辞書＋帰属チェック(lexicon注入式, goldに非依存)
│   ├── chunking.py      # チャンク分割(構造境界+overlap, global offset保存)
│   └── decide.py        # 検証チェーン: 接地→帰属→τ棄却 → DecidedField
└── eval/
    ├── metrics.py             # precision@coverage / recall / 誤り捕捉率
    ├── run.py                 # 請求書ハーネス(baseline vs 検証あり, τ掃引)
    ├── run_financial.py       # 財務ハーネス
    └── run_financial_long.py  # 長文(実物スケール)財務ハーネス
```

## 使い方

```bash
uv venv --python 3.12 && uv pip install -e . pytest ruff
uv run python -m attachment_pipeline.eval.run                 # 請求書 精度レポート
uv run python -m attachment_pipeline.eval.run_financial       # 財務 精度レポート
uv run python -m attachment_pipeline.eval.run_financial_long  # 長文(実物スケール)財務
uv run pytest -q                                              # 回帰テスト(32件)
```

## v1 の対象外 (後続フェーズ)

NER クロスチェック(V4/GiNZA・dateparser)、LLM 検証(V5)、ReCoVERR(証拠探索復活)、
確信度の校正(温度スケーリング)、self-healing 監視ループ。詳細は docs/DESIGN.md §5。
`test_pipeline.py` の `false_positive == 0` を**回帰ゲート**として今後の拡張で維持する。
