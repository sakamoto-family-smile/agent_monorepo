# driving-license-bot

車の運転免許（仮免・本免）の学科試験対策を行う LINE Bot。問題は LLM（Claude on Vertex AI）で自動生成し、根拠条文・教則ページを必ず添付する。

> **本サービスは個人運営の学習支援ツールであり、学科試験合格を保証するものではありません。** 公認教習所が提供するものではなく、最終的な学習・確認は公式情報源（道路交通法・交通の方法に関する教則）でお願いします。

---

## ステータス

**Phase 0（基盤整備）進行中** — [docs/DESIGN.md §11 実装フェーズ](docs/DESIGN.md#11-実装フェーズ) を参照。

## ドキュメント

| ドキュメント | 内容 |
|---|---|
| [docs/DESIGN.md](docs/DESIGN.md) | 設計書（全体像・データフロー・スキーマ・フェーズ） |
| [docs/INFRASTRUCTURE.md](docs/INFRASTRUCTURE.md) | GCP インフラ構成と各コンポーネントの役割 |
| [docs/SETUP.md](docs/SETUP.md) | ローカル / 本番環境のセットアップ手順 |
| [docs/POLICIES/TERMS_OF_SERVICE.md](docs/POLICIES/TERMS_OF_SERVICE.md) | 利用規約（初版） |
| [docs/POLICIES/PRIVACY_POLICY.md](docs/POLICIES/PRIVACY_POLICY.md) | プライバシーポリシー（初版） |
| [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md) | 法令・教則・標識データの調達方針 |
| [docs/INFRA_DECISIONS.md](docs/INFRA_DECISIONS.md) | GCP インフラに関する決定メモ |
| [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) | analytics-platform / security-platform 連携方針 |

## アーキテクチャの概要

```
LINE Platform
   │
   ▼
Cloud Run: line-bot-service (FastAPI)
   │  ├─ 即時 200 OK + Cloud Tasks に enqueue
   │  └─ analytics-platform: AnalyticsLogger 計装
   │
   ▼
Cloud Run: agent-service (Claude Agent SDK + Vertex AI Claude)
   │  全 MCP 呼び出し → security-platform/MCP Proxy 経由
   │
   ├──► Vertex AI: Claude (Question Generator / Tutor)
   ├──► Vertex AI: Gemini (Quality Reviewer cross-check)
   ├──► Firestore (セッション・ユーザー)
   ├──► BigQuery (出題履歴・分析、analytics-platform と共用)
   └──► GCS (標識画像・教則 PDF・問題プール)
```

詳細は [docs/DESIGN.md](docs/DESIGN.md) を参照。

## 連携基盤

- **analytics-platform**: イベント計装・OTel トレース・BigQuery 出力（[詳細](docs/INTEGRATIONS.md#analytics-platform)）
- **security-platform**: MCP Proxy・CVE 監視・Red Team・CI Security（[詳細](docs/INTEGRATIONS.md#security-platform)）

## ライセンス

リポジトリ直下の [LICENSE](../LICENSE) を参照。
