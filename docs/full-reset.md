# 完全リセット

Immich に登録済みの全データを初期状態に戻したい場合は、以下の順で実行する。

- この手順は PostgreSQL データ、サムネイル、プロフィール、動画キャッシュ、一時アップロード、バックアップ、ML キャッシュに加えて、外付け HDD 側の `library` にある写真・動画の実体も削除する
- `library` を消したくない場合は、この手順をそのまま使わない
- 外付け HDD が未マウントの状態で `library` を削除すると、意図しない場所に空ディレクトリを作る原因になるため、先にマウント状態を確認する

1. Immich を停止する

   ```bash
   docker compose down
   ```

   コンテナを停止して、削除対象ディレクトリへの書き込みを止める。

1. 外付け HDD のマウント状態を確認する

   ```bash
   mount | grep 'on /Volumes/500GB_immich '
   ```

   想定のボリューム名が表示されることを確認する。

1. PostgreSQL データを初期化する

   ```bash
   rm -rf -- /Users/fujisawakoki/immich-app/postgres && mkdir -p -- /Users/fujisawakoki/immich-app/postgres
   ```

   アカウント、設定、アルバム、インデックスを含む DB 全体を初期化する。

1. サムネイルを初期化する

   ```bash
   rm -rf -- /Users/fujisawakoki/immich-app/thumbs && mkdir -p -- /Users/fujisawakoki/immich-app/thumbs
   ```

1. プロフィール画像を初期化する

   ```bash
   rm -rf -- /Users/fujisawakoki/immich-app/profile && mkdir -p -- /Users/fujisawakoki/immich-app/profile
   ```

1. エンコード済み動画キャッシュを初期化する

   ```bash
   rm -rf -- /Users/fujisawakoki/immich-app/encoded-video && mkdir -p -- /Users/fujisawakoki/immich-app/encoded-video
   ```

1. アップロード領域を初期化する

   ```bash
   rm -rf -- /Users/fujisawakoki/immich-app/upload && mkdir -p -- /Users/fujisawakoki/immich-app/upload
   ```

1. バックアップ領域を初期化する

   ```bash
   rm -rf -- /Users/fujisawakoki/immich-app/backups && mkdir -p -- /Users/fujisawakoki/immich-app/backups
   ```

1. ML キャッシュを初期化する

   ```bash
   rm -rf -- /Users/fujisawakoki/immich-app/ml-cache && mkdir -p -- /Users/fujisawakoki/immich-app/ml-cache
   ```

1. 外付け HDD 上のオリジナル資産を初期化する

   ```bash
   rm -rf -- /Volumes/500GB_immich/immich-data/library && mkdir -p -- /Volumes/500GB_immich/immich-data/library
   ```

   写真・動画の実ファイルもここで削除される。

1. Immich を再起動する

   ```bash
   docker compose up -d
   ```

1. 起動状態を確認する

   ```bash
   docker compose ps
   ```

   `immich_server` と `immich_machine_learning` が `healthy` になれば完了。ブラウザで `http://localhost:2283` を開くと初回セットアップ画面に戻る。
