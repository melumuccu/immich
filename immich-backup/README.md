# Immich to Backblaze B2 自動バックアップシステム 構築覚書

## 1. 概要

セルフホストしている写真管理アプリ「Immich」のデータおよび設定ファイルを、オブジェクトストレージ「Backblaze B2」へ毎日深夜に自動同期（`rclone sync`）するDockerコンテナ環境の構築手順。

---

## 2. システム構成・仕様

### 基本仕様

- **実行環境**: Dockerコンテナ（Alpine Linuxベース、タイムゾーンは `Asia/Tokyo`）。
- **サービス構成**: 同じ `immich-backup` ソースから、`immich-backup-koki` と `immich-backup-mie` を起動。
- **スケジュール**: 毎日深夜 2:30（日本時間）に `cron` で自動実行。 (Dockerfile内で `cron` をセットアップ)
- **同期の性質**: `rclone sync` による片方向同期（Immich側で削除されたファイルはB2側でも自動削除）。
- **ポータビリティ**: ホスト側の `rclone.conf` は不使用。設定はすべて `.env`（環境変数）経由でコンテナへ注入。

### セキュリティ・安全対策

- **マウント権限**: ホスト側の元データ破損を防ぐため、すべてのボリュームを読み込み専用（`Read-Only :ro`）でマウント。
- **バケット暗号化**: B2バケット側で「Default Encryption: Enable（SSE-B2）」を設定。Webブラウザからの直接ダウンロードを制限し、セキュリティを担保。
- **誤削除対策（重要）**: B2側のライフサイクルルールで「削除後14日間のバージョン保持」を設定。誤同期発生時も2週間以内なら復元可能な「ゴミ箱機能」を実装。

---

## 3. ディレクトリ構造とボリュームマウント

### パスマッピング

ホスト側の各データをコンテナ内の `/data` 配下に読み込み専用でマウント。

| 対象データ               | ホスト側ソースパス（Mac環境） | コンテナ内マウントパス |
| ------------------------ | ----------------------------- | ---------------------- |
| **KOKI/MIE 写真データ**  | `${LIBRARY_PATH}`             | `/data/library:ro`     |
| **設定・DBダンプ**       | `${IMMICH_APP_PATH}`          | `/data/settings:ro`    |

同期対象は `.env` の `KOKI_BACKUP_*` / `MIE_BACKUP_*` で指定。

---

## 4. Backblaze B2 側の事前設定

### バケットの作成

以下の設定でバケットを個別作成。

1. **`immich-koki`** （KOKIの写真用）
1. **`immich-mie`** （MIEの写真用）
1. **`immich-settings`** （構成ファイル・DBバックアップ用）

- **共通オプション設定**:
- Files in Bucket are: `Private`
- Default Encryption: `Enable`
- Object Lock: `Disable`（※`rclone sync` による削除連動を通すため必須）

### ライフサイクルルールの設定（誤削除対策）

各バケットの「Lifecycle Settings」を以下に変更。

- **設定値**: `Keep prior versions for this number of days` ＞ **`14`**
- **挙動**: `rclone sync` で削除されたファイルに非表示マーカー（`*`）が付与され、14日間保持されたのちに自動で物理完全消去。

### 認証キー（Application Key）の取得

「Application Keys」からバックアップ専用キーを新規発行。画面に一度だけ表示される以下の値を控える。

- `keyID`（`.env`の `B2_KEY_ID` に使用）
- `applicationKey`（`.env`の `B2_APPLICATION_KEY` に使用）

---

## 6. 運用・検証コマンド

### コンテナの起動・ビルド

```bash
docker compose up -d --build

```

### コンテナの再ビルド

```bash
docker compose stop immich-backup-koki immich-backup-mie
docker compose rm -f immich-backup-koki immich-backup-mie
docker compose up -d --build immich-backup-koki immich-backup-mie

```

### 即時実行（手動強制実行）

深夜のcronを待たずに、コンテナ内のスクリプトを直接叩いてバックアップを実行。

```bash
docker compose exec immich-backup-koki /app/backup.sh
docker compose exec immich-backup-mie /app/backup.sh

```

### ログの確認

同期の進捗、削除されたファイルのステータス（`Deleted`）などをリアルタイム監視。

```bash
docker compose logs -f immich-backup-koki immich-backup-mie

```

### データの復元（リストア）方法

B2側で暗号化（SSE-B2）されているため、Web管理画面からの直接ダウンロードは不可。復元時はホスト側またはコンテナ側から `rclone copy` を使用。

```bash
rclone copy b2:immich-koki/admin/2026/06-10 /Users/fujisawakoki/Desktop/restore -v

```
