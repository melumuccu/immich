# Immich Cleaner

Immich の Smart Search を使って、低重要度候補を確認しながら一括でゴミ箱へ移動する SvelteKit アプリ。

## 環境変数

- `IMMICH_URL`: Immich API の接続先。Compose では `http://immich-server:2283`。
- `IMMICH_API_KEY`: Immich の API キー。Compose では `IMMICH_CLEANER_KOKI_IMMICH_API_KEY` / `IMMICH_CLEANER_MIE_IMMICH_API_KEY` から渡す。
- `IMMICH_CLEANER_DB_PATH`: SQLite ファイル。既定は `/app/data/immich-cleaner.sqlite3`。
- `IMMICH_CLEANER_TRASH_METHOD`: Immich の一括削除 API メソッド。既定は `DELETE`。
- `IMMICH_CLEANER_TRASH_FORCE`: `DELETE` 時の `force`。既定は `false`。

## Compose サービス

- `immich-cleaner-koki`: KOKI 用。既定の公開ポートは `2293`、SQLite は `immich-cleaner-koki.sqlite3`。
- `immich-cleaner-mie`: MIE 用。既定の公開ポートは `2294`、SQLite は `immich-cleaner-mie.sqlite3`。

## IMMICH_API_KEY　必要権限

- `asset.read`
- `asset.view`
- `asset.delete`

## ローカル開発

```bash
mise run cleaner:install
mise run cleaner:dev
```

## 検証

```bash
mise run cleaner:check
mise run cleaner:test
mise run cleaner:build
```
