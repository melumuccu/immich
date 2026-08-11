# Immich 外部共有構成 (Cloudflare Tunnel + Cloudflare Access)

Tailscale 閉域網で運用している Immich サーバーの写真を、アカウントを持たない家族（非 Immich ユーザー）に安全に共有するための構成手順・仕様メモ。

ポート開放を行わず、**Cloudflare Tunnel** 経由でトラフィックを引き込み、**Cloudflare Access (Google OAuth)** により特定のメールアドレスのみアクセスを許可する。

---

## 🏗 アーキテクチャ

- **共有用アクセス（Webブラウザ）**
  - `閲覧者` → `https://immich-share.hacksaw.work`
  - → **Cloudflare Access** (Google ログイン認証：許可されたメアドのみ通過)
  - → **Cloudflare Tunnel** (暗号化トンネル)
  - → **`cloudflared` コンテナ** (Docker 内部ネットワーク)
  - → **`immich-server:2283`** (HTTP 通信)

- **管理者・スマホアプリ利用**
  - モバイルアプリのバックアップ・直接閲覧は、これまで通り **Tailscale 経由** (ローカルIP/ホスト名) でアクセス。
  - ※ Cloudflare Access 認証挟み込みによるアプリログイン失敗を回避するため。

---

## 🛠 設定手順

### 1. Google Cloud Platform (GCP) の OAuth 2.0 設定

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクトを作成。
2. **OAuth 同意画面** を作成 (ユーザータイプ: 外部)。
3. **認証情報** → **OAuth クライアント ID** を作成 (種類: ウェブ アプリケーション)。
   - **承認済みの JavaScript オリジン:** `https://family-fujisawa.cloudflareaccess.com`
   - **承認済みのリダイレクト URI:** `https://family-fujisawa.cloudflareaccess.com/cdn-cgi/access/callback`
4. 発行された `クライアント ID` と `クライアント シークレット` を控えている (Bitwarden で管理)

### 2. Cloudflare Zero Trust 設定

#### A. 認証プロバイダ (Identity Provider) の追加

1. Cloudflare Zero Trust ダッシュボード → **Settings** → **Authentication**。
2. Login methods に **Google** を追加し、GCP で取得した ID と シークレット を設定。

#### B. Access Application & Policy の作成

1. **Access** → **Applications** → **Add an application** (Self-hosted)。
2. **Application Configuration:**
   - Domain: `immich-share.hacksaw.work` (任意のスブドメイン)
   - Identity providers: `Google` のみ有効化
3. **Policies:**
   - Action: `Allow`
   - Include: `Emails` → 自分と共有者の Gmail アドレスを追加 (`you@gmail.com`, `mom@gmail.com`)

#### C. Cloudflare Tunnel の作成

1. **Networks** → **Tunnels** → **Create a tunnel** (Cloudflared)。
2. トンネルを作成し、Docker 用の `TUNNEL_TOKEN`（長い文字列）を控える。 (Bitwarden で管理済み)
3. **Public Hostname** の設定:
   - Subdomain / Domain: `immich-share` / `hacksaw.work`
   - Service Type: `HTTP`
   - URL: `immich-server:2283`

### 3. docker-compose.yml の更新

既存の Immich 用 `docker-compose.yml` に `cloudflared` サービスを追加。

設定反映：

```bash
docker compose up -d
```

### 4. Immich サーバーの External Domain 設定

1. Immich 管理画面 → **Administration** → **Settings** → **Server Settings**。
2. **External Domain** に `https://immich-share.hacksaw.work` を設定して保存。

---

## 📌 運用・使用方法

1. **共有リンクの発行:**
   - Immich 上でアルバムまたは写真を選択し、「共有リンク（Public Share Link）」を発行。
   - 発行される URL が `https://immich-share.hacksaw.work/share/xxxx` となっていることを確認して共有相手に送付。
2. **共有相手の体験:**
   - リンクを開くと初回のみ Cloudflare の Google ログイン画面が表示される。
   - 許可された Google アカウントでログインすると、Immich のアルバムが表示される。
