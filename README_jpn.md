<p align="center">
  <img src="images/HYDRA_UMC_BANNER.svg" alt="HYDRA-UMC-DEV-SERVER バナー" width="100%">
</p>

# 🖥️ HYDRA-UMC-DEV-SERVER

<p align="center"><a href="README.md">🇺🇸 English</a> | <a href="README_spa.md">🇪🇸 Español</a> | <a href="README_fra.md">🇫🇷 Français</a> | <a href="README_ita.md">🇮🇹 Italiano</a> | <a href="README_deu.md">🇩🇪 Deutsch</a> | <a href="README_zho.md">🇨🇳 简体中文</a> | 🇯🇵 <b>日本語</b></p>

### 🏗️ エコシステム全体のための再現可能な開発サーバー

<p align="center">
  <img src="https://img.shields.io/badge/ライセンス-GPL%203.0-blue.svg" alt="GPL 3.0">
  <img src="https://img.shields.io/badge/言語-Python%203.11%2B-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/コア-stdlibのみ-brightgreen.svg" alt="stdlibのみのコア">
  <img src="https://img.shields.io/badge/デリバリー-DS02%2F10-367BF5.svg" alt="DS02/10">
</p>

> **状態: v0.0.2、スキャフォールディング - 全10回中のDS02（契約・制約・検証可能な骨格）。**
> 実在してテスト済みの設定スキーマ(`config validate`)は、デフォルトポリシーで
> **どのタスクにもデプロイ権限を与えない**。また読み取り専用のマニフェスト発見機能
> (`inventory scan`)は、このエコシステム自身の `hydra-umc.project.json` を
> 発見できる - この本リポジトリ自身のものも含めて。DS02は、検証済みの
> リモートステーションプロファイル(`station validate`)、ホストが準備できて
> いるかを報告するだけの**読み取り専用**の事前チェック(`station preflight`、
> 何も変更しない)、および**ドライラン**のプロビジョニング計画(`station plan`、
> 一切のステップを実行しない)を追加する。まだワークスペース、タスクランナー、
> 永続キュー、AIプロバイダー連携は存在しない - それらはDS04、DS05、DS06という
> 今後の提供物である。
> 今日存在する正確なコマンド面については
> [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) を参照。

---

## 1. 🛠️ 技術概要

HYDRA-UMC-DEV-SERVERはHYDRA-UMC/URTCエコシステムのための開発インフラである。
再現可能なホスト（対象: NVMeから起動するRaspberry Pi 5またはCompute Module 5、
8GB）が、このエコシステム自身のソースコードをホストし、境界が明確で
ポリシーによって制御されたプログラミング/ビルド/テストのタスクを実行する -
人間とAIアシスタントの両方にとって。これは訓練すべき新しいAIでは**なく**、
代替オペレーティングシステムでも**なく**、あるマシンが変更しても安全だと
自らが判断することも決してない。

DS01は、それぞれ独立して有用な2つの実物をもたらした:

1. **設定スキーマ**(`config validate`) - 3つのJSON文書
   (`HostProfile`、`ToolchainPolicy`、`TaskPolicy`)、それぞれに実際の
   検証と、拒否されるべき各形状に対する実際の否定的テストがある。
   初日から最も重要な不変条件: `TaskPolicy.allow_deploy` はデフォルトで
   `False` であり、文書がJSONのリテラルなブール値 `true` を設定した場合にのみ、
   その権限を持つポリシーが生成され得る。
2. **マニフェスト発見**(`inventory scan`) - HYDRA-UMC-OPS-AGENT自身のedge
   役割がすでに `hydra-umc.project.json` の発見と検証に使っているのと
   同じ実物でテスト済みのパターンを、書き直さずここで再利用している。

DS02はさらに3つを追加する。すべて `station` サブコマンドの下にあり、
すべて依然として「検証し記述するだけで、決して実行しない」:

3. **リモートステーションプロファイル**(`station validate`) - 1つのJSON文書
   (`RemoteIdentity` + `RemoteAccess` + 必要なツールチェーン)で、
   同じくエラーを蓄積する検証を行う。初日の不変条件: リモート編集の
   エンドポイントはループバック/プライベートにバインドし、ルーティング可能な
   アドレスは、文書がリテラルなブール値 `allow_public_bind: true` を
   設定しない限り拒否される。アイデンティティは専用のシステムアカウントであり、
   決して `root` やログインユーザーではない。
4. **ホスト事前チェック**(`station preflight`) - プロファイルを読み取り、
   注入可能なインスペクタ・インターフェースを通じて、*この*ホストが
   実際にそのステーションになる準備ができているかを報告する（Pythonの
   バージョン、空きディスク、ワークスペースの書き込み可否、`PATH` 上の
   ツール、ポートの空き、アイデンティティが実在のシステムアカウントか）。
   ホストを決して変更しない。
5. **ドライランのプロビジョニング計画**(`station plan`) - 実際のインストーラが
   *行うであろう*内容（各ステップのargvをデータとして記録）と、systemd
   unitの完全なテキストを提示し、事前チェックに失敗したホストでは計画の
   構築自体を拒否する。何も実行されない。

```
$ hydra-umc-dev-server config validate configs/task-policy.example.json --kind task-policy
VALID: configs/task-policy.example.json (task-policy)
{
  "allow_deploy": false,
  "max_concurrent_tasks": 2,
  "allowed_commands": ["pytest", "build.sh", "build-test.sh"]
}

$ hydra-umc-dev-server inventory scan --root ..
{
  "root": "..",
  "projects": [
    {"name": "HYDRA-UMC-DEV-SERVER", "version": "0.0.2", "maturity": "scaffolding", "manifest_path": "../HYDRA-UMC-DEV-SERVER/hydra-umc.project.json"},
    ...
  ],
  "issues": []
}
```

`run.sh` が実行するデモ以外に引数なしのデフォルト起動は存在せず、この
提供物にはGUIもない - 完全で実際のコマンド面については
[docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) を参照。

## 2. 🧱 アーキテクチャと設計判断

- **デフォルトでデプロイ権限を持つタスクは一つもない。** これはDS01の
  文字通りの受け入れ基準であり、`TaskPolicy` データクラス自身の
  デフォルト値によって強制されている - 単なる文章上の主張ではない -
  そして文書がこの権限をこっそり紛れ込ませようとし得るあらゆる方法
  （欠落したフィールド、誤記、非ブール値）それぞれに専用のテストがある。
- **収集器は実際で正直な失敗を報告する - 決して推測しない。**
  `scan_project_manifests()` が、存在するが壊れているマニフェストに対して
  静かに破棄するのではなく `ManifestScanIssue` を返すのは、この
  エコシステムですでに確立されたパターンである（HYDRA-UMC-OPS-AGENT自身の
  `inventory.py` を参照）- ここでは再発明ではなく再利用されている。
- **状態の所有権とプロジェクト間の関係を再決定するのはこのリポジトリの
  役目ではない。** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) と
  [docs/OPS_INTEGRATION.md](docs/OPS_INTEGRATION.md) は、この
  リポジトリ自身の状態所有権表と、17のプロジェクト間関係を
  必須/任意/開発専用に分類したものを記載している。
- **この提供物ではstdlibのみを使用する。** `config validate` と
  `inventory scan` はサードパーティ依存を一切必要としない - 将来の提供物は、
  その提供物自身のコードが本当に必要とした時にのみ依存を追加する
  （DS05向けの永続キュードライバ、DS06向けのAIプロバイダーSDK）、
  決して先回りして追加することはない。
- **この提供物は検証と発見のみを行う - まだ何も実行しない。**
  このリポジトリにはまだワークスペースも、タスク実行も、キューも、
  いかなるネットワーク呼び出しも存在しない。

## 📂 ディレクトリ構造

```
HYDRA-UMC-DEV-SERVER/
├── src/hydra_umc_dev_server/
│   ├── config.py          # HostProfile/ToolchainPolicy/TaskPolicyのスキーマと検証（DS01）
│   ├── inventory.py       # hydra-umc.project.jsonの実際の読み取り専用発見（DS01）
│   ├── remote_station.py  # RemoteStationProfile: アイデンティティ + リモートアクセス + ツール（DS02）
│   ├── preflight.py       # 注入可能なインスペクタ経由のホストの読み取り専用チェック（DS02）
│   ├── provision.py       # ドライランのプロビジョニング計画 + unitテキスト、決して実行しない（DS02）
│   └── cli.py             # config / inventory / station サブコマンドのエントリポイント
├── configs/
│   ├── host-profile.example.json
│   ├── toolchains.example.json
│   ├── task-policy.example.json      # allow_deploy: false、この形で公開・テスト済み
│   └── remote-station.example.json   # 127.0.0.1 にバインド、この形で公開・テスト済み
├── tests/                # 上記各モジュールの実際のテスト、公開されているサンプル設定を含む
├── docs/
│   ├── CLI_REFERENCE.md    # 各サブコマンド、そのフラグ、終了コード契約
│   ├── CONFIG_SCHEMA.md    # 3つの設定文書の実際のJSON形状
│   ├── REMOTE_STATION.md   # DS02のリモートステーションプロファイル、事前チェック、ドライラン計画
│   ├── ARCHITECTURE.md     # 目的、作業モード、初期範囲、ディスク
│   └── OPS_INTEGRATION.md  # 17関係マップ＋所有権表
├── images/                # メディアとアプリアイコン
├── tools/
│   ├── build_test.py      # バージョン変更を伴わないビルド/コンパイルチェック
│   └── ci_validate.py     # CIが使用するマニフェスト/CHANGELOG/ドキュメント検証
├── build.sh / build.bat   # venv + 編集可能インストール + チェック + テスト
├── build-test.sh / .bat   # 変更を伴わないビルド検証のみ
├── run.sh / run.bat       # 引数なしの場合は実際のinventory scan + config validateデモ、それ以外は実際のCLIコマンドを転送
├── bump_version.py        # エコシステム全体の「オドメーター式」バージョン増加（pyproject.toml + __init__.py）
└── bump_manifest_version.py # hydra-umc.project.jsonのバージョンをネイティブのものと同期（--sync）
```

## ⚙️ ビルドと実行ガイド

```bash
chmod +x build.sh   # 一度だけ
./build.sh          # .venvを作成し、pip install -e ".[dev]"、チェック + テストを実行
./run.sh                                  # 実際のデモ: このGitHubワークスペースに対して
                                           # inventory scanを実行し、次にconfig validate
./run.sh inventory scan --root DIR
./run.sh config validate configs/task-policy.example.json --kind task-policy
```

Windowsでは: `build.bat`、次に `run.bat`（引数なしの場合は同じデモ）/
`run.bat inventory scan ...` / `run.bat config validate ...`。
`build-test.sh`/`.bat` は、プロジェクト自身のCIワークフローが行うのと同じ、
変更を伴わないPython構文チェックを実行し、プロジェクトのバージョンや
CHANGELOGには一切触れない - これ自体はテストスイートを実行**しない**。
完全なローカルテストスイートには `./build.sh`/`build.bat`
（または直接 `pytest tests/`）を実行すること。

**トラブルシューティング**

- `config validate` が終了コード `1` で `INVALID: ...` を返す:
  メッセージを読むこと - 最初のものだけでなく、失敗したすべての
  フィールドが列挙されている。期待される正確な形状については
  [docs/CONFIG_SCHEMA.md](docs/CONFIG_SCHEMA.md) を参照。
- `inventory scan` が、問題ないと思っていたディレクトリで問題を報告する:
  そのディレクトリには存在するが読み取り不能、形式不正、または必須
  フィールドが欠落した `hydra-umc.project.json` がある - マニフェストが
  全く存在しないディレクトリが問題として報告されることは決してない。

## 🚀 ロードマップ

このバージョンはDS01とDS02を提供する。提供順に、残っているのは:

- **DS02 - 再現可能なリモートステーション。** ✅ 提供済み: 検証済みの
  リモートステーションプロファイル、読み取り専用のホスト事前チェック、
  ドライランのプロビジョニング計画（`station` サブコマンド）。ホストは
  変更されず、ステップも実行されない。
- **DS03 - 保守的な移行。** ユーザーのPCからのハッシュ・ローカル変更・
  プライバシーを明示的に扱った棚卸しとバッチコピー。
- **DS04 - ワークスペースと境界付きランナー。** タスクごとの実際の分離:
  2つのタスクが決して衝突せず、ワークスペース外へのパスは拒否される。
- **DS05 - 永続キューと追跡可能な結果。** ID、リース、再起動を生き延びる
  実際の実行ジャーナル。
- **DS06 - 交換可能なAIプロバイダー。** まず決定論的な偽プロバイダー、
  その後に実際の承認されたプロバイダー。
- **DS07-DS10** - HYDRA-UMC-OPS-AGENTと連携したインシデント対応、
  完全に制御された最初の修復サイクル、安定した運用/復旧、そして
  正直な成熟度評価を伴う配布パッケージ。

DS03-DS10のいずれも、まだこのリポジトリには存在しない - 各提供物が明示的に
含むもの・除外するものについては [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
を参照。

## 🔗 関連プロジェクト

このプロジェクトは同じ作者（JuanenRac / Electro Hobby 3D）によるHYDRA-UMCロボティクスエコシステムの一部である。ある依頼が実際にはこのリポジトリではなく、これらのいずれかに関するものである可能性があるため、知っておく価値がある。

**直接関連**
- **[HYDRA-UMC-OPS-AGENT](https://github.com/JuanenRac/HYDRA-UMC-OPS-AGENT)** — 保守インシデントのライフサイクル（証拠、診断、人間による承認済み変更、カナリアデプロイ、検証）を所有する；DEV-SERVERはそれを置き換えるのではなく連携し、自身のタスクを承認することは決してない。
- **[HYDRA-UMC-SDK](https://github.com/JuanenRac/HYDRA-UMC-SDK)** — その契約が存在するようになれば、DEV-SERVERとエコシステムの他の部分との間のあらゆるタスク/結果のやり取りが検証されることになる共有JSON Schema契約。
- **[HYDRA-UMC-UPDATER](https://github.com/JuanenRac/HYDRA-UMC-UPDATER)** — DEV-SERVERが構築しOPS-AGENTが承認した候補の実際の消費者；ノードへの配信は常にUPDATER自身の検証優先のアトミックな経路を通り、ランナーからの直接コピーは決してない。
- **[HYDRA-UMC-OS-REBUILDER](https://github.com/JuanenRac/HYDRA-UMC-OS-REBUILDER)** — もう一つの「Ecosystem Operations」の兄弟プロジェクト: 開発作業をホストするのではなく、新しいCM5イメージを構築する。

**エコシステムの他の一部**

*コアハードウェアとプラットフォーム*
- **[HYDRA-UMC](https://github.com/JuanenRac/HYDRA-UMC)** — ロボットアームの物理マザーボード: CM5ホスト＋デュアルコアSTM32H745、CAN-OTA/SPI-OTA経由で最大8本のツールアームを統括。
- **[HYDRA-UMC-OS](https://github.com/JuanenRac/HYDRA-UMC-OS)** — CM5向けの再現可能なRaspberry Pi OS製品層: 読み取り専用エージェント、検証済み設定/プロファイル、WiFi初回接続プロビジョニング。

*コアバックエンドとクライアント*
- **[HYDRA-UMC-SERVER](https://github.com/JuanenRac/HYDRA-UMC-SERVER)** — すべての制御クライアントが実際に通信する実物のヘッドレスバックエンド（REST/WebSocket）。
- **[HYDRA-UMC-STUDIO](https://github.com/JuanenRac/HYDRA-UMC-STUDIO)** — リアルタイムのマルチロボット3D可視化を備えたウェブ制御ダッシュボード。
- **[HYDRA-UMC-SUITE](https://github.com/JuanenRac/HYDRA-UMC-SUITE)** — 複数サーバーを同時に扱うデスクトップ（PySide6）群制御センター。
- **[HYDRA-UMC-ANDROID-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-ANDROID-CONTROL)** — 生体認証ログインとペア設定されたWear OSコンパニオンを備えたネイティブAndroid制御アプリ。
- **[HYDRA-UMC-IOS-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-IOS-CONTROL)** — リアルタイムWebSocket同期を備えたiOS/iPadOS制御アプリ（Flutter）。
- **[HYDRA-UMC-DSI](https://github.com/JuanenRac/HYDRA-UMC-DSI)** — CM5自体に組み込まれた、オンボード7インチDSIタッチスクリーン向けのネイティブタッチUI。
- **[HYDRA-UMC-EDITOR-URDF](https://github.com/JuanenRac/HYDRA-UMC-EDITOR-URDF)** — 完成したモデルをSTUDIO自身のカタログにプッシュするデスクトップグラフィカルURDF作成/編集ツール。
- **[HYDRA-UMC-BRIDGE-AMR](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-AMR)** — 実際のVDA 5050 MQTTパブリッシャーによるAGV/AMR車両群の協調境界。
- **[HYDRA-UMC-BRIDGE-CNC](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-CNC)** — 実際のGRBLステータス/制御バイトアクセスを備えた高レベルCNCセルコーディネーター。
- **[HYDRA-UMC-BRIDGE-DROIDS](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-DROIDS)** — 実際のBoston Dynamics Spotコマンド送信機を備えた、脚式/ヒューマノイド型ドロイドの協調境界。
- **[HYDRA-UMC-BRIDGE-LASER](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-LASER)** — 3つの実際の鍵/筐体/インターロックGPIO保護を読み取るレーザーセル安全コーディネーター。
- **[HYDRA-UMC-BRIDGE-OPENPNP](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-OPENPNP)** — OpenPnPピックアンドプレース向けの安全な高レベル基板フローコーディネーター。
- **[HYDRA-UMC-BRIDGE-PRINTER3D](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-PRINTER3D)** — 実際に制御されたジョブコマンドを備えた、Moonraker/Klipper 3Dプリンター向けの安全な協調境界。
- **[HYDRA-UMC-BRIDGE-ROS2](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-ROS2)** — 実際の遅延インポート方式のrclpy ROS 2トランスポートを備えた安全コーディネーター。
- **[HYDRA-UMC-BRIDGE-UAV](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-UAV)** — 実際のMAVLinkコマンド送信機を備えた、カメラ搭載UAV向けの協調境界。

*URTCツールプラットフォーム*
- **[URTC](https://github.com/JuanenRac/URTC)** — 物理的なUniversal Robot Tool Controller基板のファームウェア、CANバス経由で25以上のツールプロファイル。
- **[URTC-FLASHER](https://github.com/JuanenRac/URTC-FLASHER)** — URTC基板向けのデスクトップGUI書き込みツール、CAN-OTAに加えてフルチップSWD/JTAG。
- **[URTC-TESTER](https://github.com/JuanenRac/URTC-TESTER)** — URTC基板向けのデスクトップライブCANバス診断ツール、ツールプロファイルごとに1パネル。
- **[URTC-WEB-STUDIO](https://github.com/JuanenRac/URTC-WEB-STUDIO)** — Web Serial API経由のブラウザベースのURTC-TESTER代替、ローカルインストール不要。

*ビジョンAIノード（Hailo-8）*
- **[HYDRA-UMC-VISION-NODE](https://github.com/JuanenRac/HYDRA-UMC-VISION-NODE)** — Hailo-8ビジョンパイプラインの統合ハブ、ステージごとの実際のハードウェア準備状況チェックを備える。
- **[HYDRA-UMC-DETECTION-HEF](https://github.com/JuanenRac/HYDRA-UMC-DETECTION-HEF)** — Hailoアーキテクチャ/チェックサムによる安全ロード検証を備えた実際のコンパイル済みモデルレジストリ。
- **[HYDRA-UMC-VISION-STREAMER](https://github.com/JuanenRac/HYDRA-UMC-VISION-STREAMER)** — 実際のHailoRT統合境界を備えた、実際のGStreamerパイプライン＋MediaMTX設定ジェネレーター。
- **[HYDRA-UMC-VISUAL-SERVOING-API](https://github.com/JuanenRac/HYDRA-UMC-VISUAL-SERVOING-API)** — 上流のゾーン状態に基づく安全ゲートを備えた、実際の位置ベース視覚サーボ補正則。
- **[HYDRA-UMC-SAFETY-ZONES](https://github.com/JuanenRac/HYDRA-UMC-SAFETY-ZONES)** — 較正の鮮度を強制する、実際のゾーン侵入チェックとE-STOP要求。

*認知AIノード（Hailo-10）*
- **[HYDRA-UMC-COGNITIVE-NODE](https://github.com/JuanenRac/HYDRA-UMC-COGNITIVE-NODE)** — Hailo-10認知パイプライン（LLM/VLA/音声オーケストレーション）の統合ハブ。
- **[HYDRA-UMC-VLA-ENGINE](https://github.com/JuanenRac/HYDRA-UMC-VLA-ENGINE)** — Vision-Language-Actionモデル向けの実際のアクショントークンのエンコード/デコードと軌道生成。
- **[HYDRA-UMC-VOICE-UI](https://github.com/JuanenRac/HYDRA-UMC-VOICE-UI)** — 境界付きで確認が必要なWatchリレーを備えた、実際の音声フロントエンド（VAD＋意図解析器）。
- **[HYDRA-UMC-SEMANTIC-PLANNER](https://github.com/JuanenRac/HYDRA-UMC-SEMANTIC-PLANNER)** — MCUエラーコードに対する、実際のルールベースのタスク分解と意味的エラー回復。
- **[HYDRA-UMC-DOCS-QA](https://github.com/JuanenRac/HYDRA-UMC-DOCS-QA)** — このエコシステム自身のMarkdownドキュメントに対する、stdlibのみによる実際のTF-IDF文書検索。

*オーケストレーションと群制御*
- **[HYDRA-UMC-ORCHESTRATOR](https://github.com/JuanenRac/HYDRA-UMC-ORCHESTRATOR)** — 実際のgRPC/Protobufヘルスレポート契約とミッションステートマシンを備えた統合ハブ。
- **[HYDRA-UMC-JOB-DISPATCHER](https://github.com/JuanenRac/HYDRA-UMC-JOB-DISPATCHER)** — 実際のHTTP API上での、重複排除機能を備えた実際の優先度ベースのジョブキュー。
- **[HYDRA-UMC-NODE-HEALING](https://github.com/JuanenRac/HYDRA-UMC-NODE-HEALING)** — 独自の再試行/バックオフと識別不一致検出を備えた、実際のgRPCベースの車両群健全性ウォッチドッグ。
- **[HYDRA-UMC-PATH-PLANNER-3D](https://github.com/JuanenRac/HYDRA-UMC-PATH-PLANNER-3D)** — 実際の障害物/作業空間衝突検証を備えた、実際のRRTベースの3D経路プランナー。
- **[HYDRA-UMC-SWARM-SYNC](https://github.com/JuanenRac/HYDRA-UMC-SWARM-SYNC)** — マルチセル収束のためにプロパティテストされた、実際のCRDT LWW-Element-Map状態同期。

*デジタルツインとシミュレーション*
- **[HYDRA-UMC-TWIN](https://github.com/JuanenRac/HYDRA-UMC-TWIN)** — 実際のバージョン互換性同期契約を備えた、デジタルツインエンジンの統合ハブ。
- **[HYDRA-UMC-HIL-BRIDGE](https://github.com/JuanenRac/HYDRA-UMC-HIL-BRIDGE)** — シミュレーションと実際のハードウェアの間でコマンドをルーティングする、実際のハードウェア・イン・ザ・ループ安全インターロック。
- **[HYDRA-UMC-PHYSICS-REPLICA](https://github.com/JuanenRac/HYDRA-UMC-PHYSICS-REPLICA)** — 実際のURDFサブセットに基づく実際の順運動学と関節限界検証。
- **[HYDRA-UMC-SYNTHETIC-DATA-GEN](https://github.com/JuanenRac/HYDRA-UMC-SYNTHETIC-DATA-GEN)** — YOLO/COCOアノテーションエクスポートを備えた、実際の手続き型2Dシーンジェネレーター。

*データと分析*
- **[HYDRA-UMC-DATALAKE](https://github.com/JuanenRac/HYDRA-UMC-DATALAKE)** — 実際の取り込み/クエリHTTP APIを備えた、sqlite3ベースの実際の時系列ストア。
- **[HYDRA-UMC-ANOMALY-DETECTOR](https://github.com/JuanenRac/HYDRA-UMC-ANOMALY-DETECTOR)** — ドリフト監視を備えた、実際のFFT＋統計ベースライン異常検知器。
- **[HYDRA-UMC-PRODUCTION-REPORTS](https://github.com/JuanenRac/HYDRA-UMC-PRODUCTION-REPORTS)** — DATALAKEの履歴に基づく実際のOEE/稼働率計算、再現可能なCSVエクスポートを備える。
- **[HYDRA-UMC-TELEMETRY-COLLECTOR](https://github.com/JuanenRac/HYDRA-UMC-TELEMETRY-COLLECTOR)** — シーケンス重複排除を備えた、DATALAKEへの実際のCAN/WebSocket取り込みパイプライン。

*産業ゲートウェイ*
- **[HYDRA-UMC-GATEWAY-INDUSTRIAL](https://github.com/JuanenRac/HYDRA-UMC-GATEWAY-INDUSTRIAL)** — 実際のコマンドホワイトリスト/バックプレッシャー層を備えた、産業用プロトコルへ中継する統合ハブ。
- **[HYDRA-UMC-OPCUA-SERVER](https://github.com/JuanenRac/HYDRA-UMC-OPCUA-SERVER)** — 実際のバイナリプロトコルクライアントセッションで検証された、実際のOPC-UAアドレス空間。
- **[HYDRA-UMC-MQTT-BROKER](https://github.com/JuanenRac/HYDRA-UMC-MQTT-BROKER)** — クライアントごとの任意認証とトピックACLを備えた実際のMQTTブローカー。
- **[HYDRA-UMC-MTCONNECT-ADAPTER](https://github.com/JuanenRac/HYDRA-UMC-MTCONNECT-ADAPTER)** — 縮退モード出力を備えた、実際のMTConnect `/probe` および `/current` XMLエンドポイント。

*補完ツール*
- **[HYDRA-UMC-DASHBOARD-AI](https://github.com/JuanenRac/HYDRA-UMC-DASHBOARD-AI)** — 正直な統計フォールバックを備えた、DATALAKE/ANOMALY-DETECTOR上のスマートサマリーと異常ハイライトパネル。
- **[HYDRA-UMC-TOOL-CLI](https://github.com/JuanenRac/HYDRA-UMC-TOOL-CLI)** — 実際で安定した終了コード契約を持つ車両群CLI、HYDRA-UMC-SERVER自身のAPIの本物のライブクライアント。
- **[HYDRA-UMC-WATCH](https://github.com/JuanenRac/HYDRA-UMC-WATCH)** — 実際の触覚アラートとペア設定された電話への音声リレーを備えたWearOSコンパニオンアプリ。
- **[HYDRA-UMC-CONNECTOR-HUB](https://github.com/JuanenRac/HYDRA-UMC-CONNECTOR-HUB)** — 設計上GETのみの外部アダプター機能カタログ。
- **[URTC-SMART-RACK](https://github.com/JuanenRac/URTC-SMART-RACK)** — 実際のツールID復号とSmart Idle予熱ロジックを備えた、基板搭載ラック向けファームウェア。
- **[URTC-VISION-TOOL](https://github.com/JuanenRac/URTC-VISION-TOOL)** — 熱/RGB検査ツールヘッド向けの、ファームウェアと実際のPythonビジョンコンパニオン。

---

## 📚 ドキュメントとコミュニティ

- **[docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md)** — 各サブコマンド、そのフラグ、終了コード契約。
- **[docs/CONFIG_SCHEMA.md](docs/CONFIG_SCHEMA.md)** — `HostProfile`/`ToolchainPolicy`/`TaskPolicy`の実際のJSON形状。
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — 目的、2つの作業モード、初期範囲、ディスク構成。
- **[docs/OPS_INTEGRATION.md](docs/OPS_INTEGRATION.md)** — 完全な17関係マップと状態所有権表。
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — プルリクエストのための技術スタックとコーディングガイドライン。
- **[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)** — このコミュニティで期待される行動基準。
- **[SECURITY.md](SECURITY.md)** — 脆弱性の報告方法、およびこのプロジェクトの実際のセキュリティ重点分野。
- **[SUPPORT.md](SUPPORT.md)** — 質問や不具合報告の窓口。

## 👤 作者
**JuanenRac**（Electro Hobby 3D）
📧 electrohobby3d@gmail.com
📺 [youtube.com/@electrohobby3d](https://youtube.com/@electrohobby3d)

## 📜 ライセンス

GPL-3.0（ソフトウェア）／ CC BY-SA 4.0（ドキュメント）- 詳細は [LICENSE.md](LICENSE.md) を参照。
