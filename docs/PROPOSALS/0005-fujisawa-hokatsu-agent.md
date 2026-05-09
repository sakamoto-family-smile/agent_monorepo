# PROPOSAL-0005: 藤沢市保活エージェント (`fujisawa-hokatsu-agent`)

| | |
|---|---|
| **Status** | Draft |
| **Author** | @kurama554101 |
| **Created** | 2026-05-09 |
| **Updated** | 2026-05-09 |
| **Target** | fujisawa-hokatsu-agent (新規エージェント) |
| **Related PRs** | (none yet) |
| **Depends on** | [PROPOSAL-0003 fujisawa-platform 共通基盤](0003-fujisawa-platform-shared-base.md) |
| **Supersedes** | — |
| **Superseded by** | — |

---

## 1. Summary

藤沢市在住の保護者向け、認可・認可外保育施設 (合計 160 施設) への保活を一気通貫で支援する
LINE Bot エージェント。**保活戦略立案・指数算定・希望順位提案・スケジュール管理・コスト試算・空き状況確認・自由質問** を提供。

技術スタックは LangGraph Supervisor + 9 サブエージェント + 6 MCP Server (Fujisawa-Hoiku /
Score-Calc / Cost-Calc / Geo / Document / Plan)。`fujisawa-platform` (proposal 0003) を
path dep で参照し、データ取得層は共通基盤に委譲。

事前調査 ([`notes/fujisawa-platform-investigation-2026-05-09.md`](notes/fujisawa-platform-investigation-2026-05-09.md)) で
**設計書の不確実点 2 件と修正点 11 件を解消**、令和 4 年データのバックフィルで **過去最低内定指数の正確値**を保持できることを確認済。

## 2. Motivation

### 現状の課題

- 藤沢市の保活情報 (認可 128 / 認可外 32 / 申込ナビ 47 ページ・14 MB / 月次空き状況 PDF / 過去倍率) が**完全に分散**しており、保護者は複数 PDF・HTML・電話を行き来する
- 選考基準が複雑 (基礎点 / 優先順位 10 階層 / 調整指数 / 同点タイブレーカー 6 段)、特にイレギュラー世帯 (育休 + 進学・自営 + 介護・夜勤・単身赴任) の判定が困難
- 月次空き状況 PDF は鮮度が低い (掲載後の動きは反映なし) かつ「最新は施設に直接電話」が市の公式方針 → ユーザーは鮮度を判断できない
- コスト試算 (利用者負担額 19 階層 + 藤沢型補助金 5 階層 + 多子軽減) を **手で計算するのは現実的でない**
- 過去倍率データが消える (Wayback Machine のみが過去スナップショット保持)

### 放置するとどうなるか

- 個人プロジェクトとして藤沢市民の保活負担を軽減する機会を逃す
- 申込ナビ PDF P19-20 の不確実点 (B 優先順位 H / 児童相談所 +20) を未解決のまま実装すると Score-Calc DSL を後で大改修
- Wayback Machine の保持期限内に過去 PDF をバックフィルしないと過去倍率の正確データを永久に失う

### 2.1 Goals

- [ ] LINE Bot のオンボーディングで世帯情報 (父母の状態・収入・希望条件) を構造化収集
- [ ] イレギュラー世帯 55 ケースを網羅した **指数算定** (Score-Calc MCP)
- [ ] 世帯年収 → 住民税推定 → **保育料 + 藤沢型補助金 + 国の無償化 + 多子軽減を反映した実質月コスト** (Cost-Calc MCP)
- [ ] 候補園の **送迎手段別距離スコア** (徒歩 / 自転車、Geo MCP)
- [ ] **3 段階競合分類 + 令和 4 年正確指数のハイブリッド** で勝率予測 (Plan MCP)
- [ ] 希望順位の自動組み立て (攻め/本命/守り 3 カテゴリ × 同一カテゴリ内距離順)
- [ ] 入所月から逆算した個別タスクリスト (Cloud Tasks で LINE Push リマインド)
- [ ] 空き状況確認 (鮮度注記 + 電話番号併記強制)
- [ ] 自由質問への RAG 回答 (申込ナビ PDF + 出典 URL)
- [ ] 100 ユーザー想定で **月 ¥40,000 以下** (LLM + GCP)

### 2.2 Non-Goals

- 認可保育施設の **申込代行** (書類記入支援は提供、提出は本人)
- 藤沢市以外の自治体の保活 (横浜・茅ヶ崎等は将来検討)
- 保育士向け / 行政向け機能 (保護者専用)
- リアルタイム空き状況 (市の方針で月 1 回更新のみ、本エージェントは追従)
- **「ここdeサーチ」のデータ転載** (規約上禁止、リンク誘導のみ)
- 利用者の入所判定の代替 (戦略提案のみ、最終判断は藤沢市保育課)

---

## 3. Proposal

### 3.1 User Stories

#### 3.1.1 ストーリー 1: 育休復帰前の母「うちの保活戦略立てて」

> 藤沢市民・佐藤さん (32) が LINE Bot に「保活戦略立てて」と送ると、Bot が
> 順に「お子さんの生年月、入所希望月は？」「父母の就労状況は？」「自宅・職場住所は？」
> 「希望条件は？」と Flex Message で構造化ヒアリング。データ揃ったら
> Score-Calc / Cost-Calc / Geo / Plan を一気通貫で実行し、希望順位 10 園 (攻め 3 / 本命 4 / 守り 3)
> の保活プランを Flex Carousel で提示。月コスト・距離・過去最低指数 (令和 4 年) も併記。

#### 3.1.2 ストーリー 2: イレギュラー世帯「母が育休中 + 大学院進学予定」

> 田中さんが「母は 4 月復帰、6 月から大学院進学予定」と送ると、Bot が
> Score-Calc MCP の `calculate_scenarios()` で「シナリオ A: 復帰のみ」「シナリオ B: 復帰 + 進学」
> を並列計算。「進学先確定で再算定が必要」と warning + 「進学が確定したら教えてください」と
> プラン更新タスクを自動挿入。

#### 3.1.3 ストーリー 3: 月次プラン更新

> 月次空き状況スナップショット (毎月 22 日 03:00 JST) が更新され、佐藤さんの第 2 希望園の
> 1 歳児クラスに空きが増えると、Bot が「前回プランから ◯◯保育園の空きが増えました。
> 守り枠候補に追加しますか？」と Push。承諾すると hoikatsu_plan を更新。

### 3.2 Notes / Constraints / Caveats

事前調査結果 ([`notes/fujisawa-platform-investigation-2026-05-09.md`](notes/fujisawa-platform-investigation-2026-05-09.md))
で確定した前提:

#### 設計書からの修正 (M1〜M11)

| # | 内容 |
|---|---|
| **M1** | A-1 基礎点数 (基本) に「ひとり親世帯 = 11 点」「その他 (児童相談所通知) = 20 点」の独立行を追加 |
| **M2** | A-2 加減算項目から「児童相談所通知 +20」を削除 (M1 に統合) |
| **M3** | ひとり親 11 点は A-1 基本表内の正規行として実装 (特例ではなく early return) |
| **M4** | **B 優先順位は A〜K のうち H なし、10 階層**で確定 (H は元から存在しない) |
| **M5** | A-2 ⑨ 内定辞退ペナルティは「3 年度間」固定でなく「再度入所決定 OR 減点期間経過のいずれか早い方」 |
| **M6** | 認可保育施設は **128 施設** (公立 13 / 法人等 88 / 認定こども園 6 / 小規模 19 / 家庭的 2) |
| **M7** | 認可外保育施設は **32 施設** (駅エリア別 4 テーブル) |
| **M8** | 過去倍率: **令和 4 年は最低内定指数を完全公表、令和 5 年以降は公表停止** → ハイブリッドモデル採用 |
| **M9** | 認可施設一覧 ETL は `pandas.read_html` + BeautifulSoup の 2 段で URL 抽出 (`fujisawa-platform.crawler` で共通化) |
| **M10** | 過去倍率バックフィルは **Wayback Machine 経由で実現可能** (curl 直撃で 2022-2024 全取得済) |
| **M11** | 転園申請の **6 ヶ月優先ペナルティ** を追加 (P20 注意事項①) |

#### その他の前提

- **個人情報の Claude/Gemini への送信ポリシー**: 年収 / 住民税額の **生値**は LLM に送らない。
  Score-Calc / Cost-Calc は **階層識別子** (例: `tier=C7`) のみ LLM に渡す
- **0 歳児の自転車送迎**: 安全規格違反になり得るため、`commute_mode=cycling` 選択時に
  児童年齢が 1 歳未満なら警告表示
- **空き状況の鮮度免責**: 全応答に鮮度日付 / PDF 直リンク / 該当施設電話番号 / 「最新は施設へ直接」を**強制付与**
- **コスト試算の精度**: ±1 階層程度のズレは常態。「住民税通知書の所得割額を直接入力」導線を必須提示

### 3.3 Risks and Mitigations

| リスク | 影響度 | 対策 |
|---|---|---|
| 指数算定の誤判定 | High | YAML DSL + 55 ケーステスト + `confidence` / `unresolved_questions` 強制、低 confidence 時は保育課誘導 |
| ひとり親 11 点・児童相談所 20 点の実装ミス | High | M1〜M3 を YAML DSL の最初に実装、3 ケース集中テスト |
| Wayback バックフィルの中断 / 失敗 | Medium | 1 度きりの操作なので手動再開可、半永久的な保存先として GCS にも複製 |
| 月次空き状況の誤情報 | High | freshness メタデータ強制、"市公式: 最新は施設に直接" を全応答に |
| プラン陳腐化 (見直し提案過多で push 公害) | Medium | 月次自動再生成は差分が一定以上のときのみ通知、ユーザーが opt-out 可 |
| 個人情報の LLM 送信 | High | Cost-Calc / Score-Calc は階層識別子のみ LLM に、生年収・住民税額は MCP 内で完結 |
| 0 歳児の自転車送迎を提案してしまう | Medium | Geo MCP の `commute_mode` バリデーションで年齢判定 |
| 制度年度改定で YAML 全部書き換え | Medium | `rules/reiwa{N}/` で年度別バージョニング、改定検知のため市 HP の該当ページ hash 監視 |
| 法的整理 (利用規約 / 個人情報保護) | High | Pre-launch checklist で保育課に一報 + 利用規約 / プライバシーポリシー作成 |
| 保活プランの精度誤認 | High | 全プランに「最終判断は藤沢市保育課の入所審査会で決定」「過去データに基づく推定」と明示 |
| Cost-Calc YAML schema 未定 | Medium | Phase 1 着手前に申込ナビ P6 の利用者負担額表を Docling 抽出して YAML 化 |

---

## 4. Design Details

設計書 (送信済 Markdown) の §1〜§14 をベースに、調査結果 M1〜M11 の修正を反映した最終設計。

### 4.1 アーキテクチャ概略

```
                     ┌────────────────────────┐
                     │ LINE Platform          │
                     │ (info-bot とは別 Channel)│
                     └───────────┬────────────┘
                                 │ Webhook
                                 ▼
                    ┌─────────────────────────────────┐
                    │ Cloud Run: api (FastAPI)         │
                    │  Webhook 即 200 → Pub/Sub        │
                    └────────────┬────────────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────────────┐
                    │ Cloud Run: agent-core            │
                    │ (LangGraph Supervisor + 9 sub)   │
                    │                                  │
                    │  ┌────────┐ ┌────────┐ ┌────────┐│
                    │  │Intake  │ │Score   │ │Cost    ││
                    │  └────────┘ └────────┘ └────────┘│
                    │  ┌────────┐ ┌────────┐ ┌────────┐│
                    │  │Search  │ │Strategy│ │Planning││
                    │  └────────┘ └────────┘ └────────┘│
                    │  ┌────────┐ ┌────────┐ ┌────────┐│
                    │  │Vacancy │ │Compare │ │QA(RAG) ││
                    │  └────────┘ └────────┘ └────────┘│
                    └────────────┬─────────────────────┘
                                 │ MCP (HTTP/SSE)
                                 ▼
                    ┌─────────────────────────────────┐
                    │ MCP Servers (FastMCP)            │
                    │  ① Fujisawa-Hoiku                │
                    │  ② Score-Calc (YAML DSL)         │
                    │  ③ Cost-Calc (YAML DSL)          │
                    │  ④ Geo (国土地理院 + Routes/OSRM)│
                    │  ⑤ Document (RAG)                │
                    │  ⑥ Plan (倍率 + 逆算スケジュール)│
                    └────────┬────────────────┬───────┘
                             │                │
                             ▼                ▼
                ┌──────────────────────┐  ┌──────────────────┐
                │ fujisawa-platform     │  │ Firestore         │
                │  (path dep)           │  │ (user / hoikatsu_ │
                │  - knowledge_base/    │  │  plan / vacancy_  │
                │  - crawler/wayback    │  │  snapshots /      │
                │  - pdf_pipeline/      │  │  competition_     │
                │  - resolver/          │  │  stats / sessions)│
                │  - skills/            │  └──────────────────┘
                └──────────┬────────────┘
                           │
                           ▼
                ┌──────────────────────────────────────┐
                │ Cloud SQL (driving-license-bot 共有  │
                │   instance、DB 分離)                 │
                │  - hokatsu_db (user data + RAG)       │
                │  - fujisawa_kb_db (公開知識、proposal │
                │    0003 で共通)                       │
                └──────────────────────────────────────┘

   バッチ層 (Cloud Run Jobs):
   - 月次 22 日 03:00: 空き状況 + 申込状況 PDF 取得 → Docling → vacancy_snapshots
   - 月次 23 日 03:00: competition_stats 集計
   - 半年次: 認可・認可外施設一覧 HTML → facilities
   - 年次: 申込ナビ PDF 再構造化 + Cost-Calc YAML 検証
   - 年 2 回 (2/3 月): 4月入所結果 PDF → admission_results
   - 1 度きり: Wayback バックフィル (令和 4-6 年)
```

### 4.2 機能要件と Phase 配分

設計書 §1.2 の機能一覧を Phase に再配分:

| Phase | 内容 | 機能 |
|---|---|---|
| **0. データ調査** | 1-2 週 | M1〜M11 反映、YAML DSL 5 本作成、55 ケース YAML、Wayback バックフィル |
| **1. ローカル MVP** | 3-4 週 | Docker Compose + Score-Calc + Cost-Calc + IntakeAgent (P0 機能) |
| **2. 戦略・計画機能** | 4-5 週 | SearchAgent / StrategyAgent / PlanningAgent / Geo MCP / VisitPlannerAgent (P0) |
| **3. その他エージェント** | 2 週 | VacancyAgent / QAAgent / CompareAgent (P1) |
| **4. LINE 統合** | 1-2 週 | Webhook + リッチメニュー + Flex + Push リマインド |
| **5. ETL 自動化** | 1-2 週 | 月次バッチ + 差分検知 + Slack 通知 |
| **6. GCP 移行** | 1-2 週 | Terraform + Cloud Run + Workload Identity |
| **7. 観測・運用** | 1 週 | analytics-platform 計装、KPI ダッシュボード、戦略の精度評価 |

### 4.3 データモデル

設計書 §2.3 をベースに、修正点を反映:

```
users/{lineUserId}
  ├ profile               # 氏名（任意）, 居住地区, 自宅住所, 勤務先住所
  ├ guardians/{id}        # 父母それぞれ。複数ステータス並列
  │   ├ status_type       # employed | self_employed | studying | job_seeking
  │   │                   # | sick | disabled | caring | pregnant | postpartum
  │   │                   # | parental_leave | other
  │   ├ details
  │   ├ start_date
  │   ├ planned_end_date
  │   └ secondary_status
  ├ children/{id}
  ├ household_context     # is_single_parent / 多子 / 生活保護 / 障害児加点要因
  ├ income                # 階層判定材料（生値は MCP 内で完結、LLM には階層識別子のみ）
  │   ├ input_mode        # "annual_income" | "municipal_tax_direct"
  │   ├ father_annual_income | father_municipal_tax
  │   └ ...
  ├ preferences
  │   ├ commute_mode      # "walking" | "bicycle" | "both"
  │   ├ max_commute_min   # mode 別 dict
  │   └ ...
  ├ scores                # ScoreBreakdown 履歴 (シナリオ別)
  ├ cost_estimates
  ├ hoikatsu_plan         # wishlist / tasks / target_admission / cost
  ├ visits/{id}
  ├ reminders/{id}
  └ sessions/{id}         # 30 日 TTL

facilities/{id}            # fujisawa-platform 経由で同期、本 DB は読み取り中心
  ├ name / facility_type / address / phone / capacity / lat / lng
  ├ aliases               # FacilityResolver 用
  └ source_url / as_of

vacancy_snapshots/{YYYY-MM}/{facility_id}
application_snapshots/{YYYY-MM}/{facility_id}
admission_results/{year}/{round}/{facility_id}
competition_stats/{facility_id}/{age_class}
  ├ history               # 各年の倍率
  ├ historical_minimum_index_2022   # 令和 4 年の最低内定指数 (10F11 形式)
  ├ competition_level
  ├ trend
  └ confidence
```

### 4.4 MCP Server 設計

設計書 §5.1〜§5.6 をベースに、修正反映:

#### ① Fujisawa-Hoiku MCP
施設マスタ・空き状況・申込状況。設計書 §5.1 のまま。
**追加**: M9 修正により内部 ETL は `fujisawa-platform.crawler` を使う。

#### ② Score-Calc MCP (重要修正あり)
M1〜M5 / M11 を YAML DSL に反映。

```
rules/reiwa8/
├── basic_scores.yaml       # M1: ひとり親 11 / 児童相談所 20 を独立行で
├── adjustments.yaml        # M2: 児童相談所 +20 を削除 (basic に移動)
├── priority.yaml           # M4: H なし、10 階層
├── coordination.yaml       # 設計書 §19 そのまま
├── tiebreakers.yaml        # 同点比較順位
└── special_cases.yaml      # M5: 内定辞退の OR 条件、M11: 転園 6 ヶ月ペナルティ
```

`basic_scores.yaml` の修正後例:

```yaml
# M1 / M3 修正: ひとり親特例を A-1 本表に
- rule_id: basic.single_parent
  applies_to: { is_single_parent: true }
  score: 11
  early_return: true              # 父母低い側採用ロジックの前段で即返す
  side_effect:
    priority: C                    # B 優先順位を C 固定
  source: { document: "申込ナビ", year: "令和8年度", page: "P.19" }

# M1 修正: 児童相談所通知の +20 を A-1 「その他」として
- rule_id: basic.other.child_welfare
  applies_to: { has_child_welfare_notice: true }
  score: 20
  source: { document: "申込ナビ", year: "令和8年度", page: "P.19" }

# 既存 (修正なし)
- rule_id: basic.employed.full_time
  applies_to: { status_type: employed, hours_per_month_min: 140 }
  score: 10
  source: { document: "申込ナビ", year: "令和8年度", page: "P.19" }
# ... 他の就労区分
```

`priority.yaml` (M4 修正):

```yaml
# A〜K のうち H は意図的にスキップ。10 階層
- priority: A
  description: 災害
- priority: B
  description: その他 (児童相談所通知等)
- priority: C
  description: ひとり親
- priority: D
  description: 疾病・障がい
- priority: E
  description: 出産
- priority: F
  description: 就労
- priority: G
  description: 介護・看護
# H は存在しない
- priority: I
  description: 就学
- priority: J
  description: 就労内定 (開業予定)
- priority: K
  description: 求職中
```

#### ③ Cost-Calc MCP
申込ナビ P6 の利用者負担額表を Docling で抽出して YAML 化。設計書 §5.6 のまま。
**追加**: 19 階層 × (2 号/3 号) × (標準/短時間) × (第 1 子/第 2 子) × (その他/ひとり親) の組合せを
`rules/reiwa8/cost.yaml` で網羅。

#### ④ Geo MCP
設計書 §5.3 のまま。`commute_mode` バリデーションを追加 (0 歳児 + cycling は warning)。

#### ⑤ Document MCP (RAG)
申込ナビ PDF の解説文章を `fujisawa-platform.knowledge_base.pdf_documents` テーブルに格納。
設計書 §5.4 のまま。

#### ⑥ Plan MCP (M8 反映でハイブリッドモデル化)

`get_facility_competition()` の戻り値に `historical_minimum_index_2022` フィールドを追加:

```python
@mcp.tool()
def get_facility_competition(facility_id, age_class, target_year) -> CompetitionStats:
    """
    Returns:
      CompetitionStats(
        facility_id="...",
        age_class=1,
        target_year=2026,

        # M8 修正: 令和 4 年の正確値 (Wayback 経由バックフィル) があれば併記
        historical_minimum_index_2022=HistoricalMinIndex(
          basic_score=10,
          priority="F",            # 就労
          coordination=11,
          notation="10F11※",
          source="r4-4nyuusyonaiteisisuu.pdf",
          disclaimer="令和 4 年は最低内定指数が公表されていました。"
                     "令和 5 年以降は非公表のため、3 段階分類で代替推定しています。"
        ),

        # 令和 5 年以降は推定値 (3 段階分類)
        latest_ratio=2.6,
        latest_year=2026,
        competition_level="超人気",
        history=[
          {year: 2024, ratio: 2.8, vacancy_after_1st: 0, level: "超人気"},
          {year: 2025, ratio: 2.4, vacancy_after_1st: 0, level: "超人気"},
          {year: 2026, ratio: 2.6, vacancy_after_1st: 0, level: "超人気"},
        ],

        confidence="high",
        based_on=[
          "admission_results/2022 (Wayback)",
          "application_snapshots/2024-01",
          ...
        ],

        disclaimer=(
          "申込数には複数希望による重複が含まれます。"
          "令和 4 年は最低内定指数が公表されていましたが、"
          "令和 5 年以降は非公表のため、過去の申込状況と入所結果から"
          "推定した「内定難易度」を 3 段階で表示しています。"
          "最終的な内定可能性は世帯指数や選考順位によって変動します。"
          "詳しくは藤沢市保育課にご相談ください。"
        ),
      )
    """
```

### 4.5 主要モジュール

設計書 §7.2 のディレクトリ構成をベースに、`fujisawa-platform` 共通基盤への path dep を追加:

```
fujisawa-hokatsu-agent/
├── pyproject.toml             # uv project、fujisawa-platform 等を path dep
├── README.md                  # README_TEMPLATE 準拠
├── docs/
│   └── DESIGN.md              # SYSTEM_DESIGN_TEMPLATE 準拠 (M1〜M11 反映済)
├── api/
│   ├── main.py
│   ├── line_handler.py
│   ├── graph/
│   │   ├── supervisor.py
│   │   ├── state.py
│   │   └── agents/             # 9 agents
│   ├── skills/                 # SKILL.md 群
│   └── tools/                  # MCP client
├── mcp/                        # 6 MCP servers (FastMCP)
│   ├── fujisawa_hoiku/
│   ├── score_calc/
│   ├── cost_calc/
│   ├── geo/
│   ├── document/
│   └── plan/
├── rules/                      # YAML DSL (年度別)
│   └── reiwa8/
│       ├── basic_scores.yaml
│       ├── adjustments.yaml
│       ├── priority.yaml       # M4 (H なし)
│       ├── coordination.yaml
│       ├── tiebreakers.yaml
│       ├── special_cases.yaml  # M5, M11
│       └── cost.yaml
├── data_pipeline/              # ETL (バッチ)
│   ├── scrape_facilities.py    # M9: pandas + bs4
│   ├── scrape_vacancy.py
│   ├── parse_navi_pdf.py       # Docling
│   ├── wayback_backfill.py     # M10: Wayback 経由バックフィル
│   └── compute_competition_stats.py
├── tests/
│   ├── score_cases.yaml        # 55 ケース
│   ├── cost_cases.yaml
│   └── ...
└── Makefile
```

### 4.6 LangGraph State

設計書 §4.1 のまま:

```python
class HokatsuState(TypedDict):
    user_id: str
    messages: list[BaseMessage]
    intent: Literal[
        "onboard","score","cost","search","strategy","planning",
        "vacancy","schedule","compare","qa","escalate",
    ]
    user_profile: UserProfile | None
    score_result: ScoreResult | None
    cost_estimates: list[CostEstimate]
    candidate_facilities: list[Facility]
    hoikatsu_plan: HoikatsuPlan | None
    next_agent: str
    final_response: str | None
```

### 4.7 LLM ルーティング

LINE bot (proposal 0004) と同様、Vertex Gemini を default:

| 役割 | モデル |
|---|---|
| Supervisor (意図分類 / 整形) | Gemini 2.5 Pro (複雑質問のみ) / Gemini 2.0 Flash (default) |
| IntakeAgent / ScoreAgent / CostAgent (説明生成) | Gemini 2.0 Flash |
| StrategyAgent / PlanningAgent (推論重め) | Gemini 2.5 Pro |
| QAAgent (RAG) | Gemini 2.0 Flash |
| Fallback | Anthropic Haiku 4.5 |

### 4.8 Test Plan

- **Unit**:
  - Score-Calc: `score_cases.yaml` 55 ケースで期待値と一致
  - **M1 / M2 / M3 / M4 集中テスト**: ひとり親 / 児童相談所 / 優先順位 H なしの 4 ケースを最初に書く
  - Cost-Calc: `cost_cases.yaml` で年収パターン × 家族構成
  - Geo: 距離スコア化、`commute_mode=cycling` × 0 歳児で warning
  - Plan: M8 ハイブリッドモデルで `historical_minimum_index_2022` が正しく付与
  - Wayback バックフィル: 令和 4 年 PDF からの抽出 fixture
- **Integration**:
  - 6 MCP × Supervisor の通し
  - 実 Cloud SQL (Workload Identity) で hoikatsu_db に書き込み・読み出し
  - LINE webhook → Pub/Sub → agent-core → Reply の通し (ngrok)
- **Manual / E2E**:
  - [ ] イレギュラー世帯 5 ケース (育休+進学 / 自営+介護 / ひとり親+認可外 / 双子 / 単身赴任) を実行
  - [ ] 月次 ETL の dry-run で 22 日 03:00 に 1 ヶ月 staging 観察
  - [ ] Wayback バックフィルを実行し、competition_stats が 3 年分構築される

### 4.9 Migration / Rollback

- **Migration**:
  - Cloud SQL `hokatsu_db` を新規作成
  - YAML DSL は `rules/reiwa8/` で年度別、改定時は `rules/reiwa9/` を追加
  - Wayback バックフィルは 1 度きりの操作 (Phase 0)
- **Rollback**: LINE Channel 一時停止 → DB は残置可能 (再開時に再利用)
- **既存ユーザー影響**: なし (新規)

### 4.10 Feature Enablement

```
HOKATSU_RULES_VERSION=reiwa8
HOKATSU_LLM_PROVIDER=vertex            # vertex / anthropic
HOKATSU_PLAN_AUTO_REGENERATION=true    # 月次自動再生成
HOKATSU_PRIVACY_MODE=strict            # LLM への階層識別子のみ送信
HOKATSU_HISTORICAL_DATA_ENABLED=true   # 令和 4 年バックフィル使用
```

---

## 5. Operational Concerns

### 5.1 Monitoring

- analytics-platform (`service_name="fujisawa-hokatsu-agent"`) で計装
- 重要メトリクス:
  - `score.confidence_distribution` (low confidence 比率を追跡)
  - `score.unresolved_questions_count`
  - `cost.tier_estimation_accuracy` (実際に届いた住民税通知書との突合、ユーザーフィードバック)
  - `plan.regeneration_count`
  - `vacancy.freshness_disclaimer_compliance` (鮮度注記の付与率、100% でない場合 alert)
  - `etl.docling_failures`

### 5.2 Troubleshooting

| 症状 | 原因 / 対処 |
|---|---|
| 指数が想定と違う | YAML DSL の rule_id を `explain_rule()` で確認 |
| ひとり親 11 点が出ない | `is_single_parent` フラグの送信確認、`basic.single_parent` の `early_return` ロジック |
| 児童相談所 +20 が出ない | A-2 加減算ではなく A-1 として実装されているか確認 (M1) |
| B 優先順位 H が現れる | YAML DSL から H が削除されているか確認 (M4) |
| 月次 ETL 失敗 | Slack alert、旧データ温存、手動再開 |
| Wayback PDF 取得失敗 | Internet Archive の rate limit、5 秒間隔で再試行、503 持続時は手動 |

### 5.3 Dependencies

- **新規**:
  - LangGraph / LangChain
  - FastMCP (MCP server 実装)
  - Docling (PDF 構造化)
  - rapidfuzz (FacilityResolver)
  - pandas (`read_html`)
  - feedparser (RSS、不要かも)
- **path dep**: `fujisawa-platform`, `analytics-platform`
- **GCP**: Cloud Run / Cloud SQL / Vertex AI / Firestore / Pub/Sub / Cloud Tasks / Cloud Scheduler / GCS

### 5.4 Non-Functional Requirements

#### 性能
- 単純 Q&A: 3 秒以内
- 戦略立案 (Step 1〜7): 10〜30 秒、Loading Indicator + Push パターン
- 月次 ETL: 22 日 03:00 開始、5 時間以内完了

#### コスト (100 ユーザー想定)
- Cloud Run (api / agent-core / 6 MCP、**全部 min=0**): 月 ¥3,000-6,000 (アイドル時 ¥0、リクエスト時のみ課金)
- Cloud SQL (instance 共有): ¥0 増
- Vertex Gemini (Pro 30% / Flash 70%): 月 ¥5,000-15,000
- Vertex Embedding: 月 ¥500
- Firestore: 無料枠内
- Cloud Tasks: 無料枠内
- 合計: **月 ¥10,000-25,000** (100 ユーザー想定、min=0 採用)

##### コールドスタート対策 (info-bot 同様)

LINE Webhook の 3 秒制約は Webhook handler 側で吸収:
- Webhook handler を最小化 (署名検証 + Pub/Sub publish のみ)
- agent-core / 6 MCP servers は Pub/Sub 経由なのでコールドスタートを吸収可能
- 戦略立案は元々 10-30 秒かかる → Loading Indicator + Push パターン
- env (`CLOUD_RUN_MIN_INSTANCES_API` / `_AGENT` / `_MCP`) で必要に応じて min=1 に切替

#### プライバシー / データ保持
- 世帯収入・診断書情報など PII は Firestore のみ、Claude/Gemini への送信は階層識別子のみ
- ログには PII を出さない (security-platform の DLP proxy を経由)
- session 30 日 TTL、scores / cost_estimates / plan は永続 (ユーザー削除依頼時は手動)
- 利用規約・プライバシーポリシーを Pre-launch checklist で公開

#### キャパシティ
- 同時ユーザー 100 想定
- 認可施設 128 + 認可外 32 = 160 施設
- 月次 vacancy_snapshots: 160 件 / 月、年間 1,920 件
- competition_stats: 160 施設 × 6 クラス = 960 行

---

## 6. Drawbacks

- **YAML DSL の複雑さ**: 55 ケース + イレギュラー対応で DSL が肥大、メンテ負荷
- **コスト ¥20,000-40,000/月** は個人プロジェクトとしては大きい (LINE bot 0004 と合算で月 ¥25,000-45,000)
- **法的整理の限界**: 弁護士確認なしの設計、運用リスク残存
- **過去倍率データの永続性**: Wayback Machine が消えたら令和 4 年データ再取得不可 → GCS バックアップ必須
- **令和 4 年データのみ正確値**: 1 年分のみで時代との乖離あり、令和 5-7 年は推定値で代替

これらを踏まえても、藤沢市民の保活負担軽減 + 個人プロジェクトの技術的挑戦として価値あり。

## 7. Alternatives

### 案 A: 設計書のまま実装し、不確実点は実装しながら解消

- **概要**: M1〜M11 の修正を行わず、原案のまま着手
- **却下理由**:
  - B 優先順位 11 階層 (H 含む) で実装すると Score-Calc DSL の rule_id 体系が後で衝突
  - 児童相談所 +20 を A-2 に置くと加減算ロジックが正しく動かない
  - Phase 1 着手後に発覚すると DSL 大改修

### 案 B: 過去倍率データのバックフィルを諦め、3 段階分類のみ

- **概要**: M8 の発見を活用せず、設計書原案 (3 段階分類のみ) で進める
- **却下理由**:
  - StrategyAgent の応答品質が大幅に下がる (具体指数が出せない)
  - Wayback Machine からのバックフィルは 1 日で完了する操作、コスト対効果が高い
- **採用条件**: Wayback の取得が rate limit 等で失敗し続けた場合の fallback

### 案 C: Score-Calc を YAML DSL ではなくハードコード

- **概要**: 選考ルールを Python コードで直接実装
- **却下理由**:
  - 年度改定 (年 1 回) で全部書き換える羽目に
  - `explain_rule()` の根拠説明 (申込ナビページ番号付き) が困難
  - YAML DSL の方が保守性 / 透明性が高い

### 案 D: LINE Bot ではなく Web UI で提供

- **概要**: Cloud Run + Next.js で UI を作る
- **却下理由**:
  - 保護者は LINE 利用率高、別アプリのインストールは摩擦
  - 緊急性のあるリマインド (締切前日) は LINE Push が効果的
  - piyolog-analytics 等で LINE Bot 基盤の知見が蓄積済

---

## 8. Implementation History

| 日付 | 種別 | 内容 |
|---|---|---|
| 2026-05-09 | Draft | 初稿 (本 PR、proposal 0003 / 0004 と一括) |
| 2026-05-09 | Draft 改訂 | 0004 と同じレビュー反映: Cloud Run min instances を **min=1 → min=0** に変更、合計コスト試算を **¥20,000-40,000 → ¥10,000-25,000** に再見積。コールドスタート対策は Pub/Sub async + Loading Indicator パターンで吸収可能 |
