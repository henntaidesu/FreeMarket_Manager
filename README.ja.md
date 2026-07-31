# FreeMarket Manager

フロントエンドとバックエンドを分離したローカル Web アプリケーションです。日本の Mercari（メルカリ）アカウントと連携し、**受注同期 / 出品中商品管理 / ローカル在庫・倉庫管理 / 梱包資材コスト / やることリストと通知 / ワンクリック発送** を一体化しています。バックエンドは Playwright + mitmproxy によりアカウントセッションの維持とリクエストの傍受を行い、フロントエンドは中国語 / 日本語 / 英語の三言語に対応した SPA です。個人または小規模チームがローカル環境やイントラネットでデプロイして使用するのに適しています。

> スクリーンショット内の機微な情報（注文番号・購入者・金額など）はマスク処理済みで、画面の紹介のみを目的としています。

## 画面紹介

### 受注管理

収益サマリーカード（注文件数 / 金額 / 手数料 / 送料 / 梱包資材 / 純収益）＋ 注文明細テーブル。各行を展開して出庫・梱包資材の情報を確認できます。

![受注管理](image/2.png)

### 在庫管理

商品単位の在庫一覧。**バーコード入庫 / バーコードなし入庫 / 画像検索 / 組み合わせ商品** に対応し、倉庫棚・ゲームカテゴリ・商品タイプなど多軸で絞り込めます。

![在庫管理](image/3.png)

### やることリスト

**発送待ち / 返信待ち** の項目を集約し、メルカリからの同期、ワンクリックでの発送確定、ワンクリック評価に対応しています。

![やることリスト](image/1.png)

### 取引詳細とメッセージ

個別の取引内で商品情報を確認し、購入者とアプリ内メッセージでやり取りできます（定型文による返信を含む）。

![取引詳細](image/4.png)

### ワンクリック発送

商品サイズに応じて ゆうパケット / ゆうパック などの発送方法を選択でき（送料対照表付き）、コンビニ（Loppi）発送用の QR コードを生成します。

<p align="center">
  <img src="image/5.png" width="49%" alt="発送サイズ選択" />
  <img src="image/6.png" width="49%" alt="コンビニ発送 QR コード" />
</p>

## 技術スタック

| レイヤー | 技術 |
|------|------|
| フロントエンド | Vue 3、Vite、Vue Router、Pinia、Element Plus、vue-i18n、Axios、ZXing（バーコード） |
| バックエンド | Python 3.11+、FastAPI、Uvicorn |
| データベース | SQLite（デフォルト、`backend/mercariDB.db`、WAL モード）/ MySQL 8.0+；自作 ORM と方言抽象レイヤーを備え、システムページで切り替え可能 |
| 認証 | JWT（Bearer トークン、デフォルト 12 時間） |
| ブラウザ自動化 | Playwright（Edge / Chromium） |
| リクエスト傍受 | mitmproxy（デフォルトでバックエンドと同時に起動、無効化可能） |
| OCR / ビジョン | EasyOCR、OpenCV、Pillow |
| 画像ストレージ | ローカルディレクトリ `backend/imges/`（フロントエンドは `/imges` プロキシ経由でアクセス） |

> 推奨は Python **3.11+**、Node.js **18+**。リポジトリ内の `start.bat` はデフォルトで conda 環境 `mercari` を使用します。

## 主な機能

フロントエンドのルートはすべて [webside/src/router/index.js](webside/src/router/index.js) にあり、対応するバックエンドのブループリントは [backend/src/use_web/API.py](backend/src/use_web/API.py) を参照してください。

| ページ | パス | 説明 |
|------|------|------|
| ダッシュボード | `/dashboard` | 概況とショートカット |
| 在庫管理 | `/inventory` | 商品単位の在庫。バーコード / バーコードなし入庫、画像検索、組み合わせ商品に対応 |
| 受注管理 | `/orders` | メルカリ注文の同期、収益集計、出庫行と梱包資材の管理 |
| 出品中商品 | `/on-sale-items` | 出品中商品の同期と閲覧 |
| やることリスト | `/todos` | 発送待ち / 返信待ちの集約、ワンクリック発送確定 / ワンクリック評価 |
| メルカリ通知 | `/notifications` | メルカリのアプリ内通知（メッセージセンター）の同期 |
| メルカリアカウント | `/mercari-accounts` | アカウント、リクエストヘッダー（JSON）、出品者 ID、自動同期間隔、停止時間帯など |
| メモ | `/memos` | 内蔵のメモ / 付箋 |
| テーブル管理 | `/gotion` | カスタムテーブルデータの管理 |
| システム総覧 | `/system` | ユーザー管理とシステム設定 |
| 在庫記録 | `/system/transactions` | 入出庫の履歴 |
| 梱包資材在庫 | `/system/cost-records` | 梱包資材の在庫 |
| 梱包資材使用記録 | `/system/cost-expenses` | 注文ごとの梱包資材消費 |
| 倉庫管理 | `/system/warehouses` | 倉庫と棚位置 |
| ゲームカテゴリ | `/system/categories` | マスターデータの保守 |
| 商品タイプマッピング | `/system/product-type-category-mappings` | Mercari カテゴリとローカル商品タイプのマッピング |
| 定型文テーブル | `/system/talk-scripts` | 購入者メッセージのデフォルト返信定型文 |
| システムログ | `/system/system-logs` | バックエンド稼働ログの閲覧 |
| データベース管理 | `/system/database` | SQLite / MySQL の切り替え、接続テストとデータ移行 |

## ディレクトリ構成（抜粋）

```
mercari/
├── backend/
│   ├── main.py                       # FastAPI エントリ（MITM・自動同期・Playwright を起動）
│   ├── requirements.txt
│   ├── mercariDB.db                  # 実行時 SQLite（業務データ）
│   ├── system.db                     # ブートストラップ設定（DB バックエンド選択など、常に SQLite）
│   ├── imges/                        # 商品 / 梱包資材の画像
│   └── src/
│       ├── API.py                    # /mercariV2 ルートルーター
│       ├── auth.py                   # JWT の発行と検証
│       ├── app_paths.py              # 開発 / PyInstaller のパス
│       ├── mercari_auto_fetch_loop.py # 起動後の周期的な取得
│       ├── system_service.py
│       ├── db_manage/                # 自作 ORM レイヤー
│       │   ├── base_model.py
│       │   ├── database.py           # コネクションプール（シングルトン、SQLite WAL）
│       │   ├── db_manager.py         # テーブル登録・初期化・移行
│       │   ├── db_settings.py        # バックエンド選択と接続パラメータ（system.db へ書き込み）
│       │   ├── migrate.py            # SQLite ↔ MySQL データ移行
│       │   ├── dialects/             # 方言抽象（sqlite / mysql / 翻訳レイヤー）
│       │   └── models/               # 各テーブルモデル（inventory / order / on_sale_item / …）
│       ├── use_web/                  # フロントページに対応する REST ルート
│       │   ├── login/  inventory/  orders/  on_sale_items/
│       │   ├── mercari_accounts/  mercari_image/  notifications/
│       │   ├── todos/  product_types/  system/  web_drive/
│       │   └── image_storage.py
│       ├── use_mercari/              # メルカリ API 呼び出し / 同期のオーケストレーション
│       ├── web_drive/                # Playwright 自動化（マネージャー、直列キュー、MITM セッション）
│       └── ssl_mitm_proxy/           # mitmproxy の起動停止とキャプチャ addon
├── webside/
│   ├── package.json
│   ├── vite.config.js                # ポート 9600、自己署名 HTTPS、/api と /imges のプロキシ
│   └── src/
│       ├── api/                      # Axios ラッパーと JWT インターセプター
│       ├── components/
│       ├── composables/  stores/  utils/  constants/
│       ├── i18n/locales/             # zh-CN / ja / en
│       ├── router/
│       └── views/                    # Dashboard、Inventory、Orders、… および system/*
├── image/                            # README 用の画面スクリーンショット
├── start.bat                         # バックエンド + フロントエンドを一括起動
├── restart.bat
├── pyinstaller.bat                   # バックエンドの PyInstaller パッケージ化
└── CLAUDE.md
```

## API パスの規約

バックエンド V2 のルートはすべて **`/mercariV2`** 配下にあり、「ページ / モジュール」の 2 階層で集約されています。

```
/mercariV2/health
/mercariV2/src/use_web/<page>/<endpoint>     # フロントページ専用インターフェース
/mercariV2/src/use_mercari/<module>/<endpoint> # メルカリ業務のオーケストレーション（要ログイン）
```

互換用のヘルスチェックも引き続き利用可能です：`/api/health`。完全なインターフェース一覧は `http://localhost:9601/docs` を参照してください。

## データベースバックエンド（SQLite / MySQL）

デフォルトでは SQLite（`backend/mercariDB.db`、WAL モード、すぐに使用可能）を使用します。データベースレイヤーは方言抽象化（`src/db_manage/dialects/`）されており、すべての呼び出し箇所は SQLite 形式の SQL（`?` プレースホルダ、`[識別子]` の角括弧）で記述され、MySQL 方言は実行時に翻訳されます。バックエンドを切り替えても**呼び出しコードの変更は不要**です。

- **画面で切り替え**：システム管理 → データベース管理（`/system/database`）で SQLite / MySQL を選択し、MySQL 接続のテストや切り替えを実行できます。切り替え時は現在のバックエンドのデータを対象バックエンドへ一括移行し（`src/db_manage/migrate.py`）、選択と接続パラメータをブートストラップ用ストア `backend/system.db` に永続化した後、バックエンドを自動再起動します。
- **バックエンド選択の優先順位**：画面 / `system.db` の設定 > `DB_BACKEND` 環境変数 > デフォルト `sqlite`。
- **MySQL モード**：`system.db`（SQLite）はブートストラップ設定のみを保持し、業務データはすべて MySQL に保存されます。対象データベースは起動時に権限が許す範囲で自動作成されます（`PyMySQL` が必要）。
- **コマンドラインでの移行**：`python -m tools.sqlite_to_mysql`（詳細はスクリプト冒頭の説明を参照）。

## 環境変数

### バックエンド

| 変数 | デフォルト | 説明 |
|------|------|------|
| `DB_BACKEND` | `sqlite` | データベースバックエンド：`sqlite` または `mysql`；画面 / `system.db` の設定の方が優先度が高い |
| `MYSQL_HOST` / `MYSQL_PORT` / `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DATABASE` / `MYSQL_POOL_SIZE` | — | MySQL 接続のフォールバック設定（画面で設定しない場合に使用、`PyMySQL` が必要） |
| `JWT_SECRET` | `CHANGE_ME_IN_PRODUCTION` | JWT 署名キー。**本番環境では必ず変更すること** |
| `JWT_EXPIRE_HOURS` | `12` | トークンの有効時間（時間） |
| `SSL_MITM_AUTO_START` | `1` | `0` にすると mitmproxy の自動起動を無効化 |
| `INTERACTIVE_BROWSER_AUTO_START` | `0` | `1` にすると起動時に有効な全アカウントでヘッドフルブラウザを開く |
| `WEB_DRIVE_AUTOMATION_HEADLESS` | `1` | すべての自動化ブラウザを headless で実行；`0` でヘッドフル + 最小化（デバッグ用）；アカウントページの「ブラウザを開く」ボタンには影響しない |
| `WEB_DRIVE_MITM_MINIMIZED` | `1` | MITM 自動化ウィンドウをタスクバーに最小化；`0` で前面のまま；headless 時は無効 |
| `MERCARI_WEBSIDE_DIST` | — | フロントエンドのビルド成果物ディレクトリをカスタマイズ（FastAPI 内蔵の SPA マウント用） |
| `MERCARI_NO_STATIC` | — | `1` にするとバックエンドが `webside/dist` をマウントしない |

### フロントエンド（`webside/.env.development`）

| 変数 | デフォルト | 説明 |
|------|------|------|
| `MERCARI_DEV_HTTP` | `0` | `1` にすると純粋な HTTP で起動 |
| `MERCARI_DEV_PUBLIC_HOST` | — | リモート / カスタムドメインでアクセスする際の HMR WebSocket ホスト |
| `MERCARI_DEV_HMR_CLIENT_PORT` | `9600` | HMR クライアントポート |

## クイックスタート

### 一括起動（Windows）

リポジトリのルートで実行：

```powershell
start.bat
```

このスクリプトは conda 環境 `mercari` を有効化し、バックエンドの Uvicorn を起動し、`webside` ディレクトリで `npm install && npm run dev` を実行します。

### 一括起動（Mac / Linux）

リポジトリのルートで実行：

```bash
chmod +x start.sh   # 初回のみ必要
./start.sh
```

conda 環境 `mercari` を優先して使用します。conda がない場合は `backend/.venv` を自動作成し `backend/requirements.txt` をインストールします。ブラウザ自動化機能が必要な場合は、別途 `python -m playwright install msedge` を実行して Edge をインストールしてください。

### 手動 — バックエンド

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn main:app --reload --host 0.0.0.0 --port 9601
```

初回起動時に自動でデータベースを作成し、デフォルト管理者を作成します（`users` テーブルが空の場合のみ）：

- ユーザー名：`admin`
- パスワード：`admin`

> ログイン後は速やかに「システム総覧」でパスワードを変更し、強力なランダム値の `JWT_SECRET` を設定してください。

mitmproxy / 自動ブラウザが不要な場合は、重い起動項目を無効化して高速化できます：

```powershell
$env:SSL_MITM_AUTO_START="0"; $env:INTERACTIVE_BROWSER_AUTO_START="0"; python -m uvicorn main:app --reload --host 0.0.0.0 --port 9601
```

### 手動 — フロントエンド

```powershell
cd webside
npm install
npm run dev
```

開発サーバーはデフォルトで **https://localhost:9600**（自己署名証明書。ブラウザの警告は「詳細 → アクセスを続行」でよい）です。純粋な HTTP が必要な場合：

```powershell
$env:MERCARI_DEV_HTTP="1"; npm run dev
```

`/api`、`/imges` は Vite がバックエンド `http://localhost:9601` へリバースプロキシします。

### アクセス

| 説明 | アドレス |
|------|------|
| フロントエンド（HTTPS） | https://localhost:9600 |
| フロントエンド（HTTP） | http://localhost:9600（`MERCARI_DEV_HTTP=1` の場合のみ） |
| バックエンドのヘルスチェック | http://localhost:9601/api/health または `/mercariV2/health` |
| OpenAPI / Swagger | http://localhost:9601/docs |

Vite と Uvicorn はいずれも `0.0.0.0` をリッスンするため、同一 LAN 内の他のデバイスから `https://<自機の IP>:9600` でアクセスできます。

## メルカリ連携について

1. フロントエンドの **メルカリアカウント** ページで新規アカウントを作成し、出品者 ID、自動同期間隔、任意の停止時間帯などを入力します。
2. 「ブラウザを開く」ボタンは、Playwright 経由でそのアカウント専用の Edge インスタンスを起動します（永続化 profile は `backend/data/web_drive_profiles/mercari_<id>/` に保存）。初回は cookies を取得するため手動でメルカリにログインする必要があります。
3. バックエンドは mitmproxy でそのセッションのリクエストを傍受し、当該アカウントのリクエストヘッダーを自動で書き戻します（`mercari_accounts.value` フィールドに JSON 形式で保存）。
4. 設定完了後、`mercari_auto_fetch_loop` がアカウント設定の間隔に従って注文・出品中商品・通知などのデータを自動取得します。フロントエンドから手動で同期 / 検証をトリガーすることもできます。
5. 同期に失敗した場合は、まず Uvicorn のコンソールログとインターフェースが返す `detail` を確認してください。

> 公式・非公式インターフェースの呼び出しは Mercari の規約やリスク管理の影響を受ける可能性があります。コンプライアンスとアカウントの安全性については各自でご判断ください。

## 本番デプロイ

### フロントエンドのビルド

```powershell
cd webside
npm run build
```

成果物は `webside/dist` に出力されます。バックエンドは起動時にこのディレクトリを SPA 静的ファイルとして自動マウントします（`MERCARI_WEBSIDE_DIST` でパスをカスタマイズ、または `MERCARI_NO_STATIC=1` で無効化）。

### バックエンドのパッケージ化

リポジトリには、バックエンドを単一の実行ファイルにパッケージ化するための `pyinstaller.bat` が用意されています（EasyOCR などの重い依存を含むためサイズが大きくなります。初回パッケージ化の前に Playwright ブラウザがインストール済みであることを確認してください：`playwright install msedge`）。

## 新機能の追加

### 新しい API ルートの追加

1. `backend/src/use_web/<page>/API.py` で `router = APIRouter()` を定義し、具体的なエンドポイントを実装します。
2. [backend/src/use_web/API.py](backend/src/use_web/API.py) で `include_router(...)` により登録します。必要に応じて `dependencies=_AUTH` を付与して認証を有効化します。
3. フロントエンドは [webside/src/api](webside/src/api) に対応するラッパーを追加し、[webside/src/router/index.js](webside/src/router/index.js) にルートを追加します。

### 新しいデータテーブルの追加

1. `backend/src/db_manage/models/` に新しいモデルを作成し、`BaseModel` を継承して `get_table_name()` / `get_fields()` を実装します（`get_indexes()` は任意）。
2. [backend/src/db_manage/db_manager.py](backend/src/db_manage/db_manager.py) で登録します。バックエンド起動時に `init_database()` が自動でテーブル作成と移行を実行します。

## 依存関係と注意事項

- `requirements.txt` には **EasyOCR**、**Playwright**、**mitmproxy** などの重い依存が含まれ、初回インストール時にモデルやブラウザのバイナリをダウンロードします。OCR / ブラウザ自動化が不要な場合は依存を削減し、対応するルートを無効化できます。
- Playwright は Windows ではデフォルトで Edge を使用します。他のブラウザを使う場合は事前に `playwright install <browser>` を実行してください。
- mitmproxy を初めて実行する際はルート証明書を信頼する必要があります。Windows ユーザーは [backend/src/ssl_mitm_proxy/windows_trust.py](backend/src/ssl_mitm_proxy/windows_trust.py) を参考にしてください。
- データベースファイルは `backend/mercariDB.db` にあり、定期的なバックアップを推奨します。WAL モードでは `.db-wal` / `.db-shm` の付随ファイルもあります。MySQL 使用時は業務データが MySQL にあり、`backend/system.db` にはブートストラップ設定のみが保存されます。
