# Smart Ranker システム設計

## 目的

- Smart Ranker のシステム構成、実行基盤、保存方式、外部インターフェースを整理する。
- [設計書.md](./設計書.md) を要件・仕様の親文書とし、本書はそれを実装へ落とすための技術文書とする。
- GUI から変更しうる設定項目の保持先、ジョブ分割、責務分離を明確にする。

## 対象範囲

- Smart Ranker の v1 システム構成
- Immich との接続方式
- 学習、推論、自動処理の実行フロー
- 補助ストレージと設定 DB の責務
- 採用する主要技術スタック

## 設計方針

- Immich 本体のデータを主系とし、Smart Ranker 側は補助的な設定、Weak Positive の履歴、差分収集カーソルのみを保持する。
- 学習ラベルは Immich の現在状態と Smart Ranker 側の Weak Positive フィードバック履歴から再構成する。
- 推論責務とアクション責務は分離する。
- GUI から変更しうる設定は DB に寄せる。
- v1 は単一プロセスでもよいが、責務は将来分割しやすい形で保つ。
- 画像と動画を同一パイプラインで扱うが、動画スコアは Immich の preview image と通常メタデータに依存する近似値とみなす。

## システムコンテキスト

```mermaid
flowchart LR
  user[User]
  gui[Smart Ranker GUI]
  immich[Immich Server]
  db[(Immich DB)]
  ml[Immich Machine Learning]
  ranker[Smart Ranker Runtime]
  rankerdb[(Smart Ranker DB)]

  user --> gui
  user --> immich
  gui --> ranker
  ranker --> immich
  immich --> db
  immich --> ml
  ranker --> rankerdb
```

## 論理アーキテクチャ

```mermaid
flowchart TB
  subgraph immich_side[Immich 側]
    api[Immich API]
    people[People Metadata]
    assets[Asset Metadata]
    embed[CLIP Embedding]
  end

  subgraph ranker_side[Smart Ranker 側]
    collector[Event Collector]
    configsvc[Config Service]
    labeler[Label Resolver]
    trainer[Training Engine]
    infer[Inference Engine]
    policy[Action Policy Engine]
    executor[Action Executor]
    modelstore[Model Store]
    appdb[(Settings DB / Feedback / Cursor)]
    smart[Smart Search Weak Labels]
  end

  api --> collector
  api --> smart
  people --> labeler
  assets --> labeler
  embed --> trainer
  embed --> infer
  smart --> labeler

  collector --> appdb
  configsvc --> appdb
  appdb --> labeler
  appdb --> trainer
  appdb --> policy
  labeler --> trainer
  labeler --> infer
  trainer --> modelstore
  modelstore --> infer
  infer --> policy
  policy --> executor
  executor --> api
```

## コンポーネント責務

| コンポーネント | 主責務 | 主な入出力 |
| --- | --- | --- |
| `Event Collector` | Immich API の差分取得。削除候補からの手動除外検知。差分収集カーソル更新。 | 入力: asset 差分、出力: `feedback_event`, `collector_cursor` |
| `Config Service` | GUI 設定の読書き。人物グループ、カテゴリ、閾値、保護ルールの管理。 | 入力: GUI 更新、出力: 設定 DB |
| `Label Resolver` | People、通常メタデータ、smart search の弱ラベル、ルーティングルールから候補ラベル集合を生成。 | 入力: asset、設定 DB、弱ラベル候補、出力: ラベル集合 |
| `Training Engine` | 現在状態と Weak Positive フィードバック履歴から教師信号を再構成し、ラベル別モデルと汎用モデルを学習。 | 入力: asset、embedding、`feedback_event`、出力: 学習済みモデル |
| `Inference Engine` | 汎用モデルとカテゴリ別モデルでスコア算出。 | 入力: asset、embedding、モデル、出力: ラベル別スコア |
| `Action Policy Engine` | 閾値、保護ルール、実行モードから実行可否を判定。 | 入力: スコア、設定 DB、出力: 実行計画 |
| `Action Executor` | Immich API への tag 付与、album 追加、description 更新などを実行。 | 入力: 実行計画、出力: API 呼び出し結果 |
| `Model Store` | 学習済みモデルとメタ情報の保存。 | 入力: 学習結果、出力: モデル読出し |

## データストアの役割分担

## Immich 側

- アセット本体
- `isFavorite`, `isTrashed`, `visibility`
- People メタデータ
- CLIP embedding
- `search/smart` の検索結果
- タグ、アルバム、説明欄などの最終反映先

## Smart Ranker 側

- 設定 DB
- Weak Positive フィードバック履歴
- 差分収集カーソル
- GUI 変更可能な運用設定
- 学習済みモデルのメタデータ
- ジョブ実行履歴と dry-run 記録

## Smart Ranker DB に置く項目

- 人物グループ
- カテゴリ定義
- カテゴリ振り分けルール
- `search/smart` クエリ設定
- 閾値とアクションポリシー
- 保護ルール
- フィードバック履歴
- 差分収集カーソル
- 実行スケジュール

詳細な論理スキーマは [db.md](./db.md) を参照。

## 配備構成

```mermaid
flowchart LR
  subgraph docker_net[Docker Network]
    immich_server[immich-server]
    immich_ml[immich-machine-learning]
    immich_db[(database)]
    smart_ranker[smart-ranker]
  end

  subgraph smart_ranker_state[Smart Ranker 永続領域]
    sqlite[(SQLite or Postgres)]
    models[(Model Artifacts)]
    logs[(Job Logs)]
  end

  smart_ranker --> immich_server
  immich_server --> immich_ml
  immich_server --> immich_db
  smart_ranker --> immich_db
  smart_ranker --> sqlite
  smart_ranker --> models
  smart_ranker --> logs
```

## 実行形態

| 項目 | v1 方針 |
| --- | --- |
| 実行単位 | 単一コンテナ。FastAPI と build 済み frontend asset を同梱 |
| API サーバ | FastAPI + Uvicorn |
| GUI | 別 frontend パッケージ。Svelte + TypeScript + Vite+ |
| GUI 配信 | 開発時は Vite dev server。本番は build 済み asset を FastAPI から配信 |
| スケジューラ | APScheduler の `BackgroundScheduler` |
| 長時間ジョブ実行 | `ProcessPoolExecutor` による別プロセス実行 |
| 補助 DB | SQLite を第一候補。必要なら Postgres へ移行 |
| モデル保存 | ローカル volume 上のファイル保存 |
| デプロイ形態 | Immich と同一 Docker network 内で常駐 |

## 実装モジュール構成

| モジュール | 採用技術 | 役割 |
| --- | --- | --- |
| `web` | FastAPI, Uvicorn | JSON API、build 済み frontend asset 配信、ヘルスチェック |
| `frontend` | Svelte, TypeScript, Vite+, kiso.css | 管理画面、フォーム UI、画面内状態管理 |
| `immich_client` | `requests.Session`, Pydantic DTO | Immich API 呼び出し、レスポンス正規化 |
| `immich_db_reader` | Postgres クライアント | `smart_search` から CLIP embedding を read-only 取得 |
| `scheduler` | APScheduler | 定期ジョブ登録、手動実行の受付 |
| `job_runner` | `ProcessPoolExecutor` | 学習、推論などの長時間ジョブ実行 |
| `domain` | 純粋 Python モジュール | ラベル解決、学習、推論、ポリシー評価 |
| `storage` | SQLAlchemy 2.0, Alembic | 設定 DB、イベント台帳、実行履歴の永続化 |
| `model_store` | `pickle`, `json` | 学習済みモデルとスナップショット保存 |

## API クライアント層

```mermaid
flowchart LR
  service[Web / Scheduler / Domain Service]
  gateway[Immich Gateway]
  session[requests.Session]
  dto[Pydantic DTO Mapper]
  immich[Immich API]

  service --> gateway
  gateway --> session
  gateway --> dto
  session --> immich
```

### レイヤ分割

| レイヤ | 主責務 | 主な操作 |
| --- | --- | --- |
| `ImmichSession` | `base_url`、認証ヘッダ、timeout、retry の統一 | GET / POST / PUT / DELETE の共通実行 |
| `AssetReadClient` | アセット一覧、状態、差分、People 付き snapshot の取得 | asset metadata、search metadata 系 |
| `PeopleClient` | Person 解決とキャッシュ更新 | people list、person search 系 |
| `ActionWriteClient` | tag、album、description、trash / restore 反映 | asset update、album/tag 操作系 |
| `CapabilityRegistry` | Immich バージョン差分の吸収 | 起動時 capability check |
| `DtoNormalizer` | Immich 応答の内部 DTO 化 | `AssetSnapshot`, `PersonSnapshot`, `ActionResult` |

### 実装ルール

1. Immich への HTTP アクセスは、すべて `immich_client` を経由する。
1. CLIP embedding は `immich_db_reader` から read-only 接続で取得し、Immich DB への書き込みは行わない。
1. ドメイン層は Immich の生 JSON を直接扱わず、正規化済み DTO のみ扱う。
1. 読み取り系 API は retry 対象とする。
1. 書き込み系 API は自動 retry を既定で無効にし、呼び出し元で冪等性を担保する。
1. timestamp、visibility、people 配列の正規化は DTO 層で吸収する。
1. Immich の API 変更は `CapabilityRegistry` と `DtoNormalizer` で局所化する。

## ジョブ scheduler 設計

```mermaid
flowchart LR
  aps[APScheduler]
  dispatch[Job Dispatcher]
  guard[Overlap Guard]
  pool[ProcessPoolExecutor]
  worker[Job Worker]
  state[(Settings DB / Feedback / Cursor)]
  logs[(Job Run History)]

  aps --> dispatch
  dispatch --> guard
  guard --> pool
  pool --> worker
  worker --> state
  worker --> logs
```

### 採用方針

- 定期実行は APScheduler で統一する。
- スケジュール定義の既定値はアプリ側に持ち、GUI 変更値は DB の `execution_schedule` で上書きする。
- 長時間ジョブは Web リクエストスレッドから分離し、`ProcessPoolExecutor` へ投入する。
- 同一ジョブ種別の同時実行は `max_instances=1` とアプリ内 overlap guard で禁止する。
- 手動実行も scheduler を経由し、定期実行と同じランナーを使う。

### v1 の標準ジョブ

| `job_type` | 既定トリガ | 実行方式 | 役割 |
| --- | --- | --- | --- |
| `collect_asset_diffs` | 5 分ごと | 軽量同期実行 | `updatedAfter` / `trashedAfter` 差分取得、Weak Positive 検知、カーソル更新 |
| `sync_people_catalog` | 30 分ごと | 軽量同期実行 | Person 一覧同期と名前解決 |
| `train_models` | 毎日 03:00 | `ProcessPoolExecutor` | 教師データ再構成とモデル学習 |
| `score_pending_assets` | 10 分ごと | `ProcessPoolExecutor` | 未評価アセットの推論 |
| `apply_action_plan` | 10 分ごと | 軽量同期実行 | 実行計画の反映 |
| `cleanup_runtime_state` | 毎日 04:00 | 軽量同期実行 | 古い履歴、期限切れ状態の整理 |

### 実行制御

1. scheduler は起動時に `execution_schedule` を読み込む。
1. 無効化されたジョブは登録しない。
1. 手動実行は GUI から発火し、scheduler の one-shot job として登録する。
1. 実行結果は成功、失敗、スキップを履歴へ残す。
1. dry-run は `apply_action_plan` と同じ実行経路を通し、反映だけ抑止する。

## GUI 構成

### 採用方針

- v1 の GUI は Python backend と分離した frontend パッケージとして実装する。
- frontend の package manager は pnpm に固定する。
- frontend の build / dev / check / test は Vite+ の流れに寄せる。
- 画面実装は Svelte + TypeScript を使う。
- base style は kiso.css を先に読み込み、その上に project 固有 style を重ねる。
- 開発時は Vite dev server から配信し、FastAPI へ proxy する。
- 本番は build 済み asset を FastAPI から配信する。

### 画面構成

| 画面 | 主目的 | 主な操作 |
| --- | --- | --- |
| `Dashboard` | 実行状態の把握 | 最新ジョブ結果、モデルバージョン、件数確認 |
| `Person Groups` | 「家族」「我が子」設定 | Person 検索、グループ追加、順序変更 |
| `Categories & Routing` | ラベル定義と振り分け条件管理 | カテゴリ有効化、ルーティングルール編集 |
| `Policies` | 閾値、保護、アクション設定 | review 閾値、保護条件、dry-run 切替 |
| `Jobs & Models` | 運用制御 | 再学習、差分収集、推論の手動実行 |
| `Event Ledger` | 監査とデバッグ | Weak Positive 履歴、差分収集カーソル確認 |

### ルーティング構成

| 区分 | 代表パス | 用途 |
| --- | --- | --- |
| GUI entry | `/gui`, `/gui/*` | フロントエンド entry と client-side routing |
| Static assets | `/assets/*` | Vite build asset 配信 |
| JSON API | `/api/*` | GUI からの設定変更、実行操作 |
| 運用系 endpoint | `/healthz`, `/readyz` | ヘルスチェック |

### 画面から操作する設定

- Person Group
- Category
- Routing Rule
- Score Policy
- Action Policy
- Protected Rule
- Execution Schedule

### GUI の実装境界

1. GUI は設定の登録、変更、実行指示のみを行う。
1. 学習、推論、反映の本体ロジックは `domain` と `job_runner` に置く。
1. GUI は `storage` と `domain` を直接呼ばず、`/api/*` と FastAPI の service 層を経由する。
1. 一覧のソート、検索、ページングは API 側で処理する。

## 開発基盤

- frontend を含むため、開発環境は devcontainer を前提とする。
- runtime、補助 CLI、日常 task の正本は `mise.toml` に寄せる。
- frontend の依存管理は pnpm に固定する。
- `pnpm-workspace.yaml` を置き、supply chain 設定を初期値として入れる。
- 日常コマンドは `mise run` から呼び、frontend 側は `dev`、`check`、`test`、`build` の Vite+ 流儀へ寄せる。

### pnpm の初期セキュリティ設定

| 設定 | 値 | 目的 |
| --- | --- | --- |
| `minimumReleaseAge` | `10080` | 公開直後 package の取り込み抑止 |
| `strictDepBuilds` | `true` | 未承認 lifecycle script の遮断 |
| `blockExoticSubdeps` | `true` | git / tarball 依存の混入防止 |
| `trustPolicy` | `no-downgrade` | 配布経路の信頼性低下検知 |
| `onlyBuiltDependencies` | `[]` から開始 | build script 実行 package の明示許可 |

## 技術スタック

| 領域 | 採用技術 | 用途 |
| --- | --- | --- |
| Web / API | FastAPI, Uvicorn | 制御 API、静的 asset 配信、ヘルスチェック |
| Frontend | Svelte, TypeScript | 管理画面 |
| Frontend build | pnpm, Vite+ | frontend の dev、check、test、build |
| CSS baseline | kiso.css | reset と基礎スタイル |
| 開発基盤 | devcontainer, mise | tools、env、tasks の統一 |
| Node package security | pnpm-workspace.yaml | supply chain 設定の管理 |
| 言語 | Python 3.10+ | バッチ、学習、推論、API 呼び出し |
| DTO / 検証 | Pydantic v2 | Immich 応答の内部 DTO 化、設定検証 |
| 学習 | scikit-learn | Logistic Regression |
| 数値処理 | numpy, pandas | ベクトル処理、特徴量整形 |
| HTTP 通信 | requests | Immich API 呼び出し |
| Embedding 取得 | Postgres クライアント | Immich DB の read-only 参照 |
| ORM / Migration | SQLAlchemy 2.0, Alembic | 設定 DB、イベント台帳、履歴管理 |
| 補助 DB | SQLite / Postgres | 設定、イベント台帳、ジョブ履歴 |
| モデル保存 | pickle, JSON | モデル本体、設定スナップショット |
| 実行基盤 | Docker | Immich と同一ネットワーク配置 |
| スケジューリング | APScheduler | 定期学習、差分ポーリング、手動実行 |
| ジョブ並列化 | concurrent.futures.ProcessPoolExecutor | 長時間学習、推論の分離 |
| 図表 | Mermaid | アーキテクチャ図 |

## 主要ランタイムフロー

### 差分収集

1. Immich API から `updatedAfter` と `trashedAfter` に基づく差分を取得する。
1. Smart Ranker が管理する削除候補アルバムの所属差分、または GUI 上の手動除外操作を検出する。
1. 手動除外された asset を `delete_candidate_rescued` の `feedback_event` として追記する。
1. run が成功した場合にのみ `collector_cursor` を更新する。

### 学習

1. 現在の asset 状態と `feedback_event` を読み込む。
1. `trash > archive > favorite > weak positive > unlabeled` の順で教師信号を再構成する。
1. `Label Resolver` が People、OCR、ファイルメタデータ、smart search の弱ラベルからカテゴリ候補を決定する。
1. 人物系ラベルは `我が子 > 家族 > 人物` で有効モデルを 1 つに絞る。
1. 汎用モデルとカテゴリ別モデルを学習する。
1. モデル、モデルバージョン、設定スナップショットを保存する。

### 推論と自動処理

1. 新着または未評価 asset を取得する。
1. 推論対象は `isTrashed: false` かつ `visibility: timeline` に限定する。
1. 汎用モデルとカテゴリ別モデルからラベル別スコアを算出する。
1. v1 は最大値を総合スコアとして採用する。
1. `Action Policy Engine` が保護ルールと閾値を評価する。
1. `Action Executor` が Immich API へ反映する。

## ラベルルーティングの実装方針

- ラベルは排他的にしない。
- 1 asset に複数ラベルを付与可能とする。
- 人物系のみ、学習と推論で有効モデルを 1 つに絞る。
- 書類、スクリーンショットは OCR、ファイル名、パス、タグなどの機械的ルールを優先する。
- 風景、ペットは `search/smart` の結果を弱ラベルとして扱う。
- 非人物系は該当する専用モデルを併用する。
- 汎用モデルは常時併用する。

## 主要設定の保持方針

### DB 保持対象

- 家族、我が子の Person ID 集合
- ラベル定義と表示名
- ルーティング条件
- `search/smart` クエリ語
- 閾値とアクションポリシー
- 保護ルール
- 実行スケジュール
- 差分収集カーソル
- Weak Positive フィードバック履歴

### ファイル保持対象

- 学習済みモデル本体
- モデル保存時の設定スナップショット
- ローカルジョブログ

## Immich 依存 API

| 用途 | API / データ |
| --- | --- |
| アセット一覧と状態取得 | asset metadata 系 API |
| People 解決 | `/people` または検索系 API |
| 非人物系弱ラベル候補 | `search/smart` |
| 差分取得 | metadata search 系 API |
| CLIP embedding 取得 | Immich DB read-only の `smart_search` |
| タグ付与 | tag asset 系 API |
| アルバム追加 | album asset 系 API |
| description 更新 | asset update 系 API |
| trash / restore 反映 | asset delete / trash restore 系 API |

具体的なエンドポイント名は Immich バージョン差分の影響を受けるため、実装では API クライアント層に隠蔽する。

## 動画対応の扱い

- 動画も学習、推論、自動処理の対象とする。
- ただし embedding と People 判定は Immich が生成した preview image に依存する。
- 動画全体の時間的内容や音声情報は v1 では使わない。
- 画像と動画で閾値を分けられるよう、`media_type` 単位のスコアポリシーを持つ前提とする。

## 障害点と運用上の注意

- Immich 側の trash を無効化すると Strong Negative の運用前提が崩れる。
- permanently delete 後は asset が消えるため、PoC では過去 Strong Negative の復元はできない。
- Person 未命名や顔未検出の asset では「家族」「我が子」は付与できない。
- 動画スコアは代表フレーム依存のため、人物やイベント検出に偏りが出る可能性がある。
- `search/smart` の結果は Immich 側のモデルやクエリ語に依存するため、弱ラベルとしてのみ扱う。
- Immich API のフィールド仕様変更に備え、Collector 層はバージョン差分吸収層として実装する。

## v1 の非対象

- 動画全編解析
- 音声解析
- リアルタイム推論
- 分散学習
- Immich 本体 DB への直接書き込み

## 文書間の位置づけ

- 要件・仕様: [設計書.md](./設計書.md)
- 設定 DB の論理スキーマ: [db.md](./db.md)
- 本書: システム構成、責務分割、保存方式、技術スタック
