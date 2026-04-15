# Web調査スキル

## 概要
複数のWeb検索MCPツールを効果的に組み合わせて、政策文書・最新情報・専門情報を収集するスキルです。

## ツール選択ガイド

### google-search（推奨用途）
- 日本語の政策文書・政府レポート
- 日本のニュース・時事情報
- 国内の企業・組織の活動情報
- 日本語の学術情報（CiNii等）

### brave-search（推奨用途）
- 英語の技術情報・学術情報
- 国際機関・国際NGOの情報
- 海外の政策動向
- プライバシー配慮の必要な調査

### fetch（推奨用途）
- 特定URLの全文取得が必要な場合
- PDFや長文ドキュメントの取得
- 検索結果の詳細確認

## 効果的な検索戦略

### キーワード最適化

#### 日本語検索（google-search）
```
# 基本形
"キーワード1 キーワード2 site:gov.jp"

# 最新情報を優先
"SDGs 政策 2024年度"

# 特定機関の情報
"蟹江憲史 site:keio.ac.jp"

# PDF文書を検索
"SDG報告書 filetype:pdf"
```

#### 英語検索（brave-search）
```
# 学術的表現を使用
"SDG governance framework" site:un.org

# 著者検索
"Norichika Kanie" SDGs

# 機関検索
"SDSN" sustainable development goals

# 最新レポート
"SDG progress report 2024"
```

### 段階的な情報収集

```
ステップ1: 概要の把握
→ google-search で基本的な情報収集

ステップ2: 詳細な情報収集
→ brave-search で英語情報を補完

ステップ3: 特定文書の全文取得
→ fetch で重要文書を取得

ステップ4: 情報の統合・整理
→ 収集した情報を体系的にまとめる
```

## 信頼性評価

### 情報ソースの優先順位

**第1優先（高信頼性）**
- 政府・自治体の公式Webサイト（.gov.jp, .go.jp）
- 国連・国際機関の公式サイト（.un.org）
- 査読済み学術誌・論文データベース

**第2優先（中信頼性）**
- 大学・研究機関のWebサイト（.ac.jp, .edu）
- 主要シンクタンク（NIRA、RIETI等）
- 信頼性の高いNGO・NPO（CSOs）

**第3優先（要確認）**
- ニュースメディア（事実確認が必要）
- 個人ブログ・SNS
- Wikipediaなどのユーザー生成コンテンツ

### 情報の鮮度確認
- 政策情報は最新年度のものを優先
- 統計データは調査年と発表年を確認
- 廃止・改正された法令は要注意

## 蟹江研究室関連の重要リソース

### 公式サイト
- 蟹江研究室: https://kanie.sfc.keio.ac.jp/
- xSDGラボ: https://xsdg.jp/
- SDSN Japan: https://sdsnjapan.org/
- 慶應SFC: https://www.sfc.keio.ac.jp/

### 重要な国際機関
- 国連（UN）: https://www.un.org/
- UNDP: https://www.undp.org/
- UNEP: https://www.unep.org/
- IPCC: https://www.ipcc.ch/

### 日本の政府機関
- 外務省（SDGs担当）: https://www.mofa.go.jp/
- 環境省: https://www.env.go.jp/
- 内閣府SDGs推進: https://www.kantei.go.jp/jp/singi/sdgs/

## アウトプット形式

Web調査結果は以下の形式でまとめる：

```markdown
## Web調査結果: [テーマ]

**調査日**: YYYY年MM月DD日
**使用ツール**: google-search / brave-search / fetch

---

### 主要な発見事項

1. [発見1]
   - 出典: [URL]
   - 概要: [内容の要約]

2. [発見2]
   - 出典: [URL]
   - 概要: [内容の要約]

---

### 関連リソース

| タイトル | URL | 種別 | 信頼度 |
|---------|-----|------|--------|
| [タイトル] | [URL] | 政府文書 | 高 |

---

### 調査メモ

[調査の限界・補完が必要な情報等を記載]
```
