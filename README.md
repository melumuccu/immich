# immich

## Mac Studio 向け Docker Compose 構成

Mac Studio 上で Immich を動かすための最小構成。保存先はハイブリッド構成。

### ストレージ構成

- **内蔵 SSD**: PostgreSQL データ、一時アップロード領域、サムネイル、プロフィールデータ、エンコード済み動画キャッシュ、バックアップ、ML キャッシュ
- **外付け HDD**: 写真・動画のオリジナルデータ

### 同梱ファイル

- `.env.example`: `.env` のひな形
- `docker-compose.yml`: SSD と外付け HDD を分離したハイブリッドマウント構成
- `immich-cleaner/`: Smart Search で低重要度候補を確認する追加 UI

### 前提

- 公式手順: <https://docs.immich.app/install/docker-compose/>
- このリポジトリには `docker-compose.yml` と `.env.example` を同梱
- そのため、公式手順の「必要ファイルのダウンロード」は不要
- この README の対象は、クローン後のローカル調整と起動手順

### セットアップ

- クローン直後に tool と Git hook をセットアップする

  ```bash
  mise install
  mise run hooks-install
  ```

- hook 設定や secret scan を手元で確認したい場合は以下を実行する

  ```bash
  mise run hooks-validate
  mise run hooks-run
  ```

- [こちらを参照](docs/setup.md): `.env` の調整から起動まで

### 完全リセット

- [こちらを参照](docs/full-reset.md): DB と保存データを初期化する手順

### 外付け HDD を交換したときの復旧

- [こちらを参照](docs/replace-external-hdd.md): Time Machine などから `library` を復元して `LIBRARY_PATH` を切り替える手順

### 外付け HDD を交換時 の起動トラブル

- [こちらを参照](docs/docker-desktop-mount-error.md): `/host_mnt/Volumes/...: file exists` エラーの原因と対処

### Google Photos から Immich へ全量移行する手順

- [こちらを参照](docs/copy-from-google-photo.md): Takeout 取り込み手順

### Immich Cleaner

- `.env` の `IMMICH_CLEANER_IMMICH_API_KEY` に Immich の API キーを設定
- `mise run cleaner:up` で起動
- <http://127.0.0.1:2293> を開く
