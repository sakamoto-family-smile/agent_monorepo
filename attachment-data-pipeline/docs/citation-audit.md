# 引用監査 (C1 検証): 設計ガイドの arXiv 引用の実在・内容照合

設計ガイド `high_precision_extraction.md` が依拠する arXiv 論文について、レビューで
「2025-10 以降の論文 ID が捏造の可能性がある(C1)」と懸念したため実在を照合した。

**結論: C1 リスクは解消。** 照合した全 ID が実在し、中核(load-bearing)の主張は引用元の
内容とよく一致する。捏造は確認されなかった。ただし一部にドメイン転用・タイトル省略・
出典帰属の緩さがあり、対外文書化の際は脚注で正確化することを推奨する。

検証日: 2026-06-26 / 方法: arXiv・ACL Anthology・公式ブログ等の Web 照合(タイトル+ID 突合)。

## 実在・内容照合の結果

| arXiv ID | 文書での引用 | 実在 | 内容一致 | 備考 |
|---|---|---|---|---|
| 2602.14743 | LLMStructBench | ✅ | ✅ | 構造妥当性 vs 値正確性の分離評価。2026-02-16 |
| 2510.08623 | PARSE | ✅ | ✅ 強 | EMNLP 2025 Industry 採択 (Amazon)。ARCHITECT/SCOPE 実在 |
| 2512.10004 | SciEx (REV) | ✅ | ✅ | Retrieval-Extraction-Verification モジュール実在 |
| 2604.12491 | Tabular QA 過信 | ✅ | ✅ 強 | ECE 0.35–0.64 vs テキスト 0.10–0.15 が本文と完全一致 |
| 2402.15610 | ReCoVERR | ✅ | ✅ | ACL 2024 Findings。過剰棄却の緩和 |
| 2601.06151 | PromptPort | ✅ | ✅ 強 | per-field confidence / safe-override が本文と一致 |
| 2603.21172 | Entropy 不十分 | ✅ | ✅ | Oxford。AURC/校正。entropy+probe |
| 2502.06233 | CISC / 自己一貫性 | ✅ | ✅ | ACL 2025 Findings。Taubenfeld ら = 本文 "Taubenfeld 2025" と一致 |
| 2202.03629 | Hallucination Survey | ✅ | ✅ | Ji ら。著名 |
| 2102.08585 | Table-to-text faithfulness | ✅ | ✅ 強 | table record coverage + ratio of hallucination が引用通り |
| 2212.10815 | ZEROTOP | ✅ | ◯ | 実在。confidence/logit の文脈はやや補足的 |
| 2606.11949 | Online Shift Detection | ✅ | ◯ | 実在。下記「ドメイン転用」参照 |
| 2605.07062 | From Assistance to Agency (CI/CD) | ✅ | ✅ | control-plane 権限は人間 = 本文と一致 |
| 2601.00138 | Explicit Abstention Knobs | ✅ | ◯ | 実在。下記「ドメイン転用」参照 |
| LangExtract | Google OSS | ✅ | ✅ 強 | Apache 2.0, 2025-07-30, char_interval=None, 実験的位置づけ すべて一致 (現 PyPI v1.2.0) |

未個別照合: `2403.17134` (RepairAgent) — Bouzenia ら の既知の実在論文で問題なし。

## 残る小さな問題 (実在は確認できたが引用精度に難)

1. **ドメイン転用の引用**
   - `2602.15391` (Hybrid Abstention) は実体が**安全フィルタ/有害出力検知**で、抽出の
     確信度の話ではない。「単一しきい値は脆い/ハイブリッドが良い」の一般論の裏付けには
     使えるが文脈はズレる。正式タイトルは "…Hybrid Abstention **and Adaptive Detection**"
     で文書は後半を省略。
   - `2606.11949` (Online Shift Detection) は**安全分類器**が対象。KS監視・conformal 閾値
     適応の技法は転用可能だが原文脈は抽出ではない。
   - `2601.00138` (Explicit Abstention Knobs) は **Video QA**。標準指標 (coverage/selective
     risk/AURC) の出典として引くのは可だが、この論文自体は「しきい値制御は分布内では
     むしろ滑らかに効く (ECE 0.018)」とも報告しており、文書の「素朴なしきい値は脆い」
     基調とは半分しか整合しない (分布シフト下で崩れる点は一致)。

2. **出典帰属の緩さ** — 「coverage/selective risk/AURC は Geifman & El-Yaniv 系
   (2601.00138, 2603.21172)」とあるが、Geifman & El-Yaniv は 2017年の原著者で、挙げた
   2本は 2026年の**利用側**論文。原著と利用例の混同。

3. **査読・権威性のばらつき** — 強い裏付け (PARSE=EMNLP'25, CISC=ACL'25, ReCoVERR=ACL'24,
   LangExtract=Google OSS) がある一方、`2606.11949` `2601.00138` `2602.15391` は単著・
   直近の未査読プレプリント。「実在する」ことと「査読済みで権威がある」ことは別であり、
   設計根拠としての重みは割り引くのが妥当。

## 推奨

- 中核の主張 (接地=LangExtract、構造 vs 値の分離=LLMStructBench、tabular 過信=2604.12491、
  faithfulness 指標=2102.08585、per-field/safe-override=PromptPort) は引用元で裏付けられて
  おり、設計の土台にできる。
- 対外文書化の際は上記 1–3 を脚注で正確化する。特に `2602.15391` は「抽出の確信度設計」の
  直接根拠としては弱いので、必要なら抽出ドメインの確信度論文へ差し替えるのが無難。

## 参照 URL

- LLMStructBench: https://arxiv.org/abs/2602.14743
- PARSE: https://aclanthology.org/2025.emnlp-industry.184/
- SciEx: https://arxiv.org/abs/2512.10004
- Calibrated Confidence for Tabular QA: https://arxiv.org/abs/2604.12491
- ReCoVERR: https://arxiv.org/abs/2402.15610
- Hybrid Abstention (and Adaptive Detection): https://arxiv.org/abs/2602.15391
- PromptPort: https://arxiv.org/abs/2601.06151
- Online Shift Detection and Conformal Adaptation: https://arxiv.org/abs/2606.11949
- From Assistance to Agency: https://arxiv.org/abs/2605.07062
- Entropy Alone is Insufficient: https://arxiv.org/abs/2603.21172
- CISC: https://arxiv.org/abs/2502.06233
- ZEROTOP: https://arxiv.org/abs/2212.10815
- Towards Faithfulness in Table-to-text: https://arxiv.org/abs/2102.08585
- Explicit Abstention Knobs: https://arxiv.org/abs/2601.00138
- Google LangExtract: https://github.com/google/langextract
