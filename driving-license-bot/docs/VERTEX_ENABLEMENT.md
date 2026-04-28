# Vertex AI 利用承認手順（Phase 2-B1）

driving-license-bot の自動生成バッチ（PR B2 の Cloud Run Job）が Vertex AI 上の
Claude / Gemini / text-embedding-004 を呼び出せるようにするための **手動セットアップ
手順**。Terraform では完結しない（Marketplace 利用承認が必要）。

実行後は `scripts/verify_vertex_models.py` で 1 回実コールして到達性を確認する。

## 0. 前提

- gcloud CLI 認証済（Project Owner / Editor 相当）
- Phase 2-A3 で `aiplatform.googleapis.com` / `workflows.googleapis.com` /
  `cloudscheduler.googleapis.com` 有効化済
- `sa-batch@${PROJECT}.iam.gserviceaccount.com` に `roles/aiplatform.user` 付与済
- リージョンは `asia-northeast1`（Tokyo）で確定（[INFRA_DECISIONS.md §1](./INFRA_DECISIONS.md)）

## 1. Anthropic Claude

### 1.1 Vertex AI のモデル ID 命名規則 ⚠️

Vertex AI 上の Anthropic モデル ID は **`<base>@<YYYYMMDD>` 形式**。Anthropic 直接 API の
モデル名（例: `claude-opus-4-7`）とは異なるため、**そのままでは 404 になる**。

例（2026-04 時点で asia-northeast1 配信中）:
- `claude-opus-4-1@20250805`
- `claude-opus-4@20250805`
- `claude-sonnet-4-5@20250929`
- `claude-sonnet-4@20250514`
- `claude-3-7-sonnet@20250219`

最新一覧は [Anthropic Claude on Vertex AI](https://docs.anthropic.com/en/api/claude-on-vertex-ai)。

`app/config.py` の `vertex_claude_model` は env で override 可能:

```bash
VERTEX_CLAUDE_MODEL='claude-sonnet-4-5@20250929' make vertex-verify
```

### 1.2 Marketplace 承認

GCP Console → **Vertex AI > Model Garden** → "Anthropic Claude" を検索:

1. 採用するモデル（例: **Claude Sonnet 4.5**）の "View details"
2. **"Enable"** または **"Request access"** をクリック
3. Anthropic の利用規約（Acceptable Use Policy + Commercial Terms）に同意
4. プロンプト: 用途を「driving-license-bot — Japanese driving license written test
   question generation with citation requirements」と入力
5. 通常 **数時間〜1 営業日** で承認メール（Google Cloud → "Vertex AI Model Garden")

> 承認前は実コールで以下のエラーが返る:
> ```
> 404 NOT_FOUND: Publisher Model `projects/.../models/claude-XXX@YYYYMMDD`
>   was not found or your project does not have access to it.
> ```
> モデル名が正しくても Marketplace 承認前は 404 になる点に注意。

### 1.3 prompt caching の確認

Anthropic SDK の Vertex バックエンドは `cache_control: ephemeral` を Tokyo region でも
サポートする（ドキュメント: [Anthropic on Vertex AI](https://docs.anthropic.com/en/api/claude-on-vertex-ai)）。
verify で `cache_creation_input_tokens > 0` が返れば OK、2 回目以降の同一 system で
`cache_read_input_tokens > 0` になる。

```bash
make vertex-verify   # 1 回目: cache_create > 0
make vertex-verify   # 2 回目: cache_read > 0 が期待値（5 分以内）
```

> ephemeral cache は 5 分 TTL。長時間放置すると expire するので注意。

### 1.4 Model Armor (Safety filter) の Tokyo 対応

Model Armor は **Phase 2-B1 では必須ではない**（Anthropic 側の builtin safety filter で
最低限担保される）。Phase 5+ で本番化時に検討:

- 2026-04 時点: Model Armor の region サポート状況は要確認
- 道路交通法・教則ベースで PII を含めない設計のため、当面 Anthropic builtin で十分

## 2. Gemini 2.5 Pro (gemini-2.5-pro)

### 2.1 利用承認

Gemini は **Marketplace 承認不要**（Google ファーストパーティ）。`aiplatform.googleapis.com`
の API enable と `roles/aiplatform.user` だけで利用可能。

念のため Console で 1 度開く:
- **Vertex AI > Model Garden > Gemini** → "Use in Studio" でリージョンを `asia-northeast1`
  に設定し、簡単な対話を 1 度走らせる

### 2.2 Tokyo region サポート確認

```bash
# Gemini 2.5 Pro は asia-northeast1 で利用可能（GA, 2026-04 時点）
# 利用可否は実コールで確認するのが最速
make vertex-verify
```

### 2.3 "thinking" モードと max_tokens

Gemini 2.5 系は内部の "thinking" tokens を消費する（usage_metadata の
`thoughts_token_count`）。`max_tokens` を絞りすぎると `finish_reason=MAX_TOKENS`
で空文字応答になる。verify では 200 tokens 確保している。

実バッチで使う際は `agent_max_tokens=4096`（既定）で十分余裕がある。

## 3. text-embedding-004

### 3.1 利用承認

Embedding モデルも **Marketplace 承認不要**。`aiplatform.googleapis.com` 有効化済なら
そのまま利用可能。

`text-embedding-004` は 768 次元（既定）。pgvector の `vector(768)` カラムと一致。

## 4. 実機 verify

ローカルで `gcloud auth application-default login` 済の状態で:

```bash
cd driving-license-bot
make vertex-verify        # claude / gemini / embedding 全部
```

成功時の出力例（**Marketplace 承認後**）:

```
[verify_vertex] verifying: claude, gemini, embedding
[verify_vertex] project=sakamomo-family-agent
[verify_vertex] claude: model=claude-sonnet-4-5@20250929
[verify_vertex] gemini: model=gemini-2.5-pro
[verify_vertex] embedding: model=text-embedding-004 dim=768

[verify_vertex] === summary ===
  ✓ claude     model=claude-sonnet-4-5@20250929  1234.5 ms
      in=42 out=8 cache_read=0 cache_create=42 text='OK'
  ✓ gemini     model=gemini-2.5-pro    987.6 ms
      in=18 out=1 text='OK'
  ✓ embedding  model=text-embedding-004  290.7 ms
      dim=768 sample[0:3]=[-0.010, 0.038, 0.007] norm≈1.0000

[verify_vertex] ALL OK.
```

実機検証ログ（**承認前、2026-04-29 時点**）:

| モデル | 結果 |
|---|---|
| ✓ embedding | text-embedding-004, 290 ms, 768 次元、L2 norm ≈ 1.0 |
| ✓ gemini | gemini-2.5-pro, 3471 ms, "OK" 応答 |
| ✗ claude | `claude-sonnet-4-5@20250929` で 404（Marketplace 承認待ち） |

部分実行（例: Claude 承認待ち中に Gemini と Embedding だけ確認）:

```bash
uv run python scripts/verify_vertex_models.py --include gemini,embedding
```

## 5. 想定エラーと対処

| エラー | 原因 | 対処 |
|---|---|---|
| `403 PERMISSION_DENIED` `aiplatform.endpoints.predict` | `roles/aiplatform.user` 未付与 | Phase 2-A3 で適用済のはず。`gcloud projects get-iam-policy ${PROJECT}` で確認 |
| `404 not found` Claude モデル | Marketplace 承認未完了 or モデル名間違い | Console で承認状態を再確認、`vertex_claude_model` env が `claude-opus-4-7` 等の正しい ID か確認 |
| `401 Unauthorized` | Application Default Credentials 切れ | `gcloud auth application-default login` で再認証 |
| `Model is not supported in this region` | Tokyo で未配信のモデル選択 | `claude-opus-4-7` / `claude-sonnet-4-6` 等の Tokyo 配信モデルへ切替 |
| Anthropic SDK ImportError | `anthropic[vertex]` 未インストール | `uv sync` で再インストール（`pyproject.toml` 必須） |

## 6. 想定コスト（verify 1 回あたり）

| モデル | 1 コール | 1 月 30 回 verify |
|---|---|---|
| Claude Opus 4.7 | $0.0005 (≈42 in / 8 out tok) | $0.015 |
| Gemini 2.5 Pro | $0.0001 | $0.003 |
| text-embedding-004 | $0.00003 | $0.001 |
| **計** | **< $0.001** | **< $0.02** |

実コストは `verify` 出力の token 数 × Marketplace 価格で算出可能。
