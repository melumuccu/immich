# セットアップ

1. `.env` を作成する

   ```bash
   cp .env.example .env
   ```

   既存の `.env` がある場合は上書きせず、必要な差分のみ反映する。

1. `.env` の必須項目を修正する
   - `TODO` コメントを確認する
   - 必須パス、パスワード、ボリューム名を置き換える

1. `.env` の任意項目を調整する
   - `TZ`: 既定値は `Asia/Tokyo`
   - `IMMICH_VERSION`: 既定値は `release`
   - `DB_USERNAME`: 特別な要件がなければ既定値のまま
   - `DB_DATABASE_NAME`: 特別な要件がなければ既定値のまま

1. `docker-compose.yml` の扱いを確認する
   - 原則そのまま使用する
   - 想定は「原本を外付け HDD、それ以外を内蔵 SSD」
   - 通常の修正対象は `.env` のパスのみ

   この構成は Storage Template 有効前提。`library` がオリジナル資産の保存先、`upload` が永続化済みの一時アップロード領域。将来 Storage Template を無効化した場合、新規資産の保存先は `upload` に切り替わる。

   `docker-compose.yml` の編集が必要なケースは以下のみ。
   - `2283` ポートが競合する
   - マウント先ディレクトリ構成を意図的に変更する
   - コンテナ名や再起動ポリシーを変更する

1. 設定を検証する

   ```bash
   docker compose config
   ```

   エラー時は `.env` のパスまたは環境変数名を修正する。

1. 起動する

   ```bash
   docker compose up -d
   ```

   `Error response from daemon: Head "https://ghcr.io/v2/...": denied: denied` が出る場合、Docker Desktop に保存された `ghcr.io` の認証情報が壊れている可能性がある。対処は以下。

   ```bash
   docker logout ghcr.io
   ```

   その後、`docker compose up -d` を再実行する。

## 初回アクセス

- ブラウザ確認: `http://localhost:2283`
- 表示先: Immich の初回セットアップ画面
- Web UI 上の一般的なアカウント作成やアプリ連携は公式ドキュメント側の範囲

## Tailscale 接続

Tailscale 経由で iPhone などのモバイルアプリから接続する場合、サーバのエンドポイント URL には Mac Studio の MagicDNS 名を指定する。

- 基本形: `http://<MagicDNS名>:2283`
- 完全修飾名: `http://<machine-name>.<tailnet-name>.ts.net:2283`
- `/api` の付与は不要

## 初回設定

初回アップロード開始前に、Web UI の `Administration -> Settings -> Storage Template` で Storage Template を有効化する。
