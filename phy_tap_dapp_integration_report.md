---
title: "OCUDU PHY TAP プラグインによる 3rd party dApp 統合調査レポート"
subtitle: "UL PHY レイヤ・データを消費する外部ベンダー dApp の統合点・I/F・制約・難易度評価"
author: "調査: ソースコードベース（gitlab.com/ocudu）"
date: "2026-06-09"
lang: ja
---

# 0. 調査対象と前提

| 項目 | 値 | 根拠 |
|---|---|---|
| 本体 | `gitlab.com/ocudu/ocudu` のミラー（`/home/user/ocudu-mirror`） | `README.md:3` |
| 本体バージョン | **OCUDU 26.04.0**（リリース版） | `cmake/modules/version.cmake:5-8`, `CHANGELOG:9` |
| 本体ライセンス | BSD-3-Clause-Open-MPI | `README.md:7`, `LICENSE:1-2` |
| 由来 | srsRAN 系（Software Radio Systems Limited 著作権） | `LICENSE:1`, 各ファイル SPDX ヘッダ |
| 参考プラグイン | `gitlab.com/ocudu/plugin_examples/phy_tap_plugin_example`（clone 済） | GitLab API（project id 81731466） |
| 参考プラグインの追従先 | OCUDU `dev` ブランチ（既定追従 ref） | `phy_tap_plugin_example/.gitlab-ci.yml:8,12` |
| リリースタグ状況 | 存在するタグは `release_26_04` / `_rc1` / `_rc2` のみ。**26.10 は未リリース**（既定ブランチ `dev` が将来リリースの開発線） | GitLab Tags API（2026-06-09 取得） |

> **重要な前提のずれ**: 本体ミラーは **26.04（リリース版）**、参考プラグインは **`dev`（将来の 26.10 系開発線）** を追従している。後述（項目7）のとおり PHY TAP I/F は 26.04 と `dev` の間で**既に変化**しており、両者をそのまま組み合わせるとビルドが通らない。本レポートは原則 26.04 ミラーの実ソースを根拠とし、`dev` 側は GitLab raw 取得で差分のみ明示する。

PHY TAP は「アップリンク（UL）受信シンボルを外部処理ユニットへ公開する」ためのフック機構であり、本タスクの想定どおり **UL PHY データを消費する dApp の統合点**である（`include/ocudu/phy/upper/phy_tap/phy_tap.h:11-16`）。

---

# 1. 詳細調査結果（項目1〜9）

## 項目1. dApp が実装すべき I/F（抽象クラス・シグネチャ・定義ファイル）

統合点となる純粋仮想クラスは **`ocudu::phy_tap`**。定義ファイルは唯一 `include/ocudu/phy/upper/phy_tap/phy_tap.h`（このディレクトリには本ヘッダ1本のみ）。

26.04 ミラーでの `phy_tap`（`phy_tap.h:17-71`）：

```cpp
class phy_tap {
public:
  virtual ~phy_tap() = default;                                   // :21
  virtual void handle_ul_symbol(resource_grid_writer&  grid_writer,            // :50-57
                                const resource_grid_reader& grid_reader,
                                slot_point slot, unsigned symbol,
                                span<const uplink_pdu_slot_repository::pusch_pdu>         pusch_pdus,
                                span<const uplink_pdu_slot_repository::pucch_pdu>         pucch_pdus,
                                span<const pucch_processor::format1_common_configuration> pucch_f1_pdus,
                                span<const uplink_pdu_slot_repository::srs_pdu>           srs_pdus) = 0;
  virtual void handle_quiet_grid(const resource_grid_reader& grid_reader, slot_point slot) = 0; // :70
};
```

- `handle_ul_symbol`：UL シンボル受信ごとに呼ばれ、当該スロットの「現在シンボルまで」の受信 RE と、当該シンボルでアロケーションが終了する PHY PDU 群（PUSCH/PUCCH/PUCCH-F1/SRS）を渡す（`phy_tap.h:23-57`）。
- `handle_quiet_grid`：受信要求の無いスロットの最終シンボルで、グリッド全体を渡す（`phy_tap.h:59-70`）。

ファクトリ I/F は `include/ocudu/phy/upper/upper_phy_factories.h`：

- `class phy_tap_factory` … `virtual std::unique_ptr<phy_tap> create() = 0;`（`upper_phy_factories.h:410-418`）
- 生成関数 `create_phy_tap_factory(unsigned nof_rb, unsigned nof_ports, const std::string& processor_arguments)`（`upper_phy_factories.h:421-422`）。コメントに「このファクトリは PHY tap プラグイン側で定義しなければならない」と明記（`upper_phy_factories.h:408-409`）。

> 参考プラグインは I/F をさらに2段に分け、本体非依存の `external_ul_processor`（`process` / `process_quiet` / `process_prach`）を vendor 実装面として提供する（`phy_tap_plugin_example/include/external_ul_processor.h:19-69`）。`phy_tap_impl` がアダプタとして本体 `phy_tap` を実装し `external_ul_processor` へ委譲する（`phy_tap_plugin_example/lib/phy_tap_impl.h:11-51`）。

## 項目2. 登録・ロード方法（リンク時ファクトリ上書き）

**ランタイム共有ライブラリ（dlopen）ではなく、コンパイル/リンク時のシンボル上書き**で登録する。

- 本体は弱い既定実装を持つ：`OCUDU_HAS_PHY_TAP` 未定義時、`create_phy_tap_factory(...)` は `nullptr` を返す（`lib/phy/upper/upper_phy_factories.cpp:1331-1337`）。
- プラグインは `OCUDU_HAS_PHY_TAP` を定義してこの既定を無効化し、`ocudu::create_phy_tap_factory(...)` の実体を提供する（`phy_tap_plugin_example/lib/phy_tap_factories.cpp:49-55`、`phy_tap_plugin_example/lib/CMakeLists.txt:12`）。
- 生成は設定駆動：`config.phy_tap_arguments` が値を持つときのみファクトリを生成（`upper_phy_factories.cpp:905-909`）。生成された `phy_tap` は `uplink_processor_impl` に `std::unique_ptr<phy_tap>` で渡される（`upper_phy_factories.cpp:101-105,113` / `uplink_processor_impl.h:171,266`）。

> 比較：本体には **RF ラジオ用**の汎用ランタイム・プラグイン機構（`dlopen`/`dlsym` で `libocudu_radio_*.so` を読む）が存在する（`lib/radio/plugin_radio_factory.cpp:102-144`）。**PHY TAP はこの方式を使わず**、静的リンク（in-process）である。

## 項目3. ビルドへの組み込み（CMake / 依存 / ABI）

- 本体は `plugins/` 配下を自動探索：`ENABLE_PLUGINS`（既定 **ON**、`CMakeLists.txt:74`）が有効なら `${CMAKE_SOURCE_DIR}/plugins/*` の各サブディレクトリで `CMakeLists.txt` を持つものを `add_subdirectory` する（`CMakeLists.txt:659-671`）。
- **26.04 ミラーに `plugins/` ディレクトリは存在しない**（`ls plugins` が失敗）。統合者がプラグインをここに配置する必要がある。
- プラグイン側 CMake は**本体のコアターゲットへ直接リンク**する：
  - `add_library(ocudu_upper_phy_tap OBJECT phy_tap_factories.cpp)`（`phy_tap_plugin_example/lib/CMakeLists.txt:6`）
  - `target_link_libraries(ocudu_upper_phy ocudu_upper_phy_tap)`（同 `:9`）← コア `ocudu_upper_phy` に取り込む
  - `target_compile_definitions(ocudu_upper_phy PRIVATE -DOCUDU_HAS_PHY_TAP)`（同 `:12`）
  - 例実装は外部依存 `zmq` と本体 `ocudu_support` にリンク（`phy_tap_plugin_example/lib/external_processors/CMakeLists.txt:12-15`）
- 言語/ABI 要件（本体 `CMakeLists.txt`）：`CMAKE_CXX_STANDARD 17` / `REQUIRED ON`（`:18-19`）、x86 は `-march=native`（既定）/ aarch64 は `-mcpu=native`（`:554-577`）、`-fno-rtti`（`:197`）、Release で `-fno-trapping-math -fno-math-errno`（`:203-205`）。RTSAN（`-fsanitize=realtime`）オプションあり。
- 結論：プラグインは**本体ビルドツリー内で同一コンパイラ・同一フラグでビルドし、コアライブラリへ静的リンクする**前提。スタンドアロン SDK や安定 C ABI 境界は提供されない。

## 項目4. PHY パイプライン上の TAP フック位置と呼び出し元・スレッド

UL 受信チェーンの呼び出し系列（26.04）：

1. RU → `upper_phy_rx_symbol_handler_impl::handle_rx_symbol(context, grid, is_valid)`（`lib/phy/upper/upper_phy_rx_symbol_handler_impl.cpp:24`）
2. → `ul_proc.handle_rx_symbol(context.symbol, is_valid)`（同 `:32`）
3. → `uplink_processor_impl::handle_rx_symbol(end_symbol_index, is_valid)`（`uplink_processor_impl.cpp:111`）→ シンボルループで `process_symbol_pdus(...)`（同 `:179`）
4. → `process_symbol_pdus()` 内で `ul_tap->handle_ul_symbol(...)` を呼ぶ（`uplink_processor_impl.cpp:200-208`）

- フック位置は **PHY が当該 RE を消費する直前**：`process_symbol_pdus` は先に tap を呼び（`:201`）、その後に `process_pucch/pusch/srs`（`:212-226`）を実行する。この順序保証は I/F で明文化（`phy_tap.h:39-42`）。
- 静かな（受信要求の無い）スロットでは `uplink_slot_processor_alt_impl::handle_rx_symbol` が最終シンボルで `tap->handle_quiet_grid(grid, *slot)` を呼ぶ（`uplink_slot_processor_alt_impl.h:39-43`）。
- **スレッド = 「RU UL 実行コンテキスト」**（`phy_tap.h:48`）。さらに呼び出し中は slot processor の FSM ロックを保持（`uplink_processor_impl.cpp:115` `start_handle_rx_symbol()` / `:120` scope-exit `finish_handle_rx_symbol()`、コメント `:113-114`「異スレッドからの同時処理を防ぐ」）。→ tap 内ブロッキングは slot processor 全体を停止させる。

## 項目5. 渡されるデータ構造と所有権・ライフタイム

- **リソースグリッド**：`resource_grid_writer&` / `const resource_grid_reader&` を**参照で**受領。実体は `uplink_processor_impl` 保有（`grid->get_writer()/get_reader()` を渡す、`uplink_processor_impl.cpp:201-202`）。
  - RE データは (port, symbol) ごとに `span<const cbf16_t>`（**複素 brain-float16 の IQ**）：`resource_grid_reader::get_view(port, l)`（`resource_grid_reader.h:108`）、書込は `resource_grid_writer::get_view`（`resource_grid_writer.h:90`）。次元は `get_nof_ports/get_nof_subc/get_nof_symbols`（`resource_grid_base.h:19,22,25`）。
- **PDU 群**は `span<const ...>`（**非所有ビュー**、repository が所有）：
  - `pusch_pdu`：`harq_id`, `tb_size`(units::bytes), `pdu`(=`pusch_processor::pdu_t`：rnti, start_symbol_index, nof_symbols 等)（`uplink_pdu_slot_repository.h:23-30`）
  - `pucch_pdu`：`context`(`ul_pucch_context`：rnti, format), `config`(format0..4 の variant)（同 `:33-43`）
  - `srs_pdu`：`context`(`ul_srs_context`), `config`(`srs_estimator_configuration`)（同 `:46-51`）
  - `pucch_processor::format1_common_configuration`：slot, bwp_size_rb, bwp_start_rb, cp, starting_prb 等（`pucch_processor.h:117-129`）
- **所有権・ライフタイム規約**（`phy_tap.h`）：
  - PHY は PUSCH/PUCCH/SRS アロケーションの RE を「最終シンボル受信かつ本メソッド呼出後」まで消費しない（`:39-42`）。→ 当該呼出内で処理し書き戻せる。
  - 「PDU に属するグリッド内容は、その PDU を渡した呼出が return した後は変更してはならない」（`:44-46`）。→ **span/参照は呼出中のみ有効**、保持・遅延書込は未定義動作。
- 例：`grid_reader.get(temp_buffer, i_port, symbol, 0)` → DSP → `grid_writer.put(i_port, symbol, 0, temp_buffer)` の read-modify-write（`external_ul_processor_example_impl.cpp:57,62,67`）。

## 項目6. 実行コンテキストの制約（RT / スレッド / メモリ / CPU・GPU / in/out-of-process）

- **ハード・リアルタイム**：UL シンボル受信ごとに同期呼出（`phy_tap.h:23-24`）。I/F に「RU UL 実行コンテキストで呼ばれる。重い処理を同期実行すると realtime error を招く」と2箇所で警告（`phy_tap.h:48-49,68-69`）。FSM ロック保持中（項目4）。
- **レイテンシ・バジェット**：締切は事実上「1 OFDM シンボル周期」（ソース上は「シンボル単位の同期呼出」＋上記警告が根拠。秒数は数値としてはソースに無く、numerology からの**概算導出**：15 kHz ≈ 71.4 µs、30 kHz ≈ 35.7 µs/シンボル）。
- **CPU コンテキスト**：グリッドはホストメモリ上の `cbf16_t` span（項目5）。この経路に GPU は無い。ハードウェアアクセラレータは LDPC 用 DPDK BBDEV のみ（`CHANGELOG:20`）で tap には公開されない → **tap からの GPU/アクセラレータ・オフロードは未提供（未確認）**。
- **in-process（同一プロセス・静的リンク）**。out-of-process 連携は ZMQ 参考実装が手本：重い I/O を専用ワーカへ退避してから送出する。
  - 専用ワーカ `general_task_worker`「ULPhyTap」（キュー長 2048）と executor を保持（`tap_ul_resource_grid_epre_zmq.h:35-58`）。
  - コールバック内では軽量計算（EPRE=モジュラス二乗の累積）だけ行い、`deps->get_executor().defer([...]{ backend.send_buffer(...); })` で**ワーカスレッドへ退避**（`tap_ul_resource_grid_epre_zmq.cpp:33-34`）。
  - 退避先で ZMQ PUSH 送出（`zmq_server_backend.h:30,57`）→ 外部 dApp は ZMQ_PULL で別プロセス受信（`zmq_server_backend.h:13-15`）。
  - ホットパスのバッファは `bounded_object_pool` でプール化（`tap_ul_resource_grid_epre_zmq.h:106`）。
- 推奨アーキテクチャ：**tap 内は最小限の抽出/変換のみ、vendor の重い DSP/ML は別スレッド or 別プロセス（低レイテンシ IPC）で実行**。

## 項目7. API 安定性（26.04 ⇄ dev／将来 26.10）

**I/F は既に変化している（ソース/ABI 破壊あり）。** 上流 `dev`（GitLab raw 取得）と 26.04 ミラーの差分：

| 要素 | 26.04（ミラー） | dev（将来 26.10 系） |
|---|---|---|
| `phy_tap` 純粋仮想メソッド | 2個：`handle_ul_symbol`, `handle_quiet_grid`（`phy_tap.h:50,70`） | **3個**：＋`handle_prach_window(prach_buffer&, const prach_buffer_context&)`（dev `phy_tap.h:81`） |
| `create_phy_tap_factory` 引数 | 3個（nof_rb, nof_ports, args）（`upper_phy_factories.h:422`） | **4個**：＋`std::optional<tdd_ul_dl_config_common> tdd_pattern`（dev `upper_phy_factories.h:426`） |
| upper-phy 設定フィールド | `phy_tap_arguments` のみ（`upper_phy_factories.h:285`） | ＋`phy_tap_tdd_pattern`（dev `upper_phy_factories.h:288`） |

- ミラー側に `handle_prach_window` / `tdd_pattern`（phy_tap 文脈）は**存在しない**（リポジトリ全文 grep で未検出）。
- 参考プラグインは 3メソッド＋4引数ファクトリ＋`process_prach` を実装（`phy_tap_impl.h:35`, `phy_tap_factories.cpp:49-52`, `external_ul_processor.h:68`）。→ **26.04 に対してはそのままコンパイル不可**（抽象メソッド未実装＝インスタンス化不可、ファクトリ署名不一致）。逆に 26.04 向け実装は dev で抽象メソッド不足になる。
- 密結合度：I/F 署名は内部型（`resource_grid_reader/writer`, `uplink_pdu_slot_repository::*`, `pucch_processor::format1_common_configuration`, `prach_buffer`, `slot_point`, `cbf16_t`, `tdd_ul_dl_config_common`）に直接依存。**安定 C ABI 無し・C++ vtable/STL 型をまたぐ**ため、コンパイラ/フラグ一致のリビルドが必須。
- 補足：`dev` の `version.cmake` も現状 26.04.0 のまま（版数は**リリース時にのみ更新**）。26.10 タグは未作成（2026-06-09）。

## 項目8. ライセンスとリンク形態（事実のみ。解釈は行わない）

- 本体ライセンス：**BSD-3-Clause-Open-MPI**（`README.md:7`、`LICENSE:1-2` Software Radio Systems Limited、各ファイル SPDX）。
- `LICENSES/` 同梱：`Apache-2.0` / `BSD-2-Clause` / `BSD-3-Clause` / `BSD-3-Clause-Open-MPI` / `CC0-1.0` / `MIT`（各 `.txt`）。
- PHY TAP 関連ファイルの SPDX ヘッダ（全て行2が `SPDX-License-Identifier: BSD-3-Clause-Open-MPI`）：`phy_tap.h:2`, `uplink_processor_impl.cpp:2`, `upper_phy_factories.cpp:2`, `upper_phy_factories.h:2`。加えて行3に「本ファイルは 3GPP 仕様の一部を実装し追加のライセンス要件の対象となりうる」旨の注記（`phy_tap.h:3` ほか）。
- 参考プラグイン：全ファイル `BSD-3-Clause-Open-MPI`（例 `phy_tap_factories.cpp:2`）、`REUSE.toml` / `LICENSES/BSD-3-Clause-Open-MPI.txt` 同梱。
- **リンク形態（事実）**：プラグイン（tap 本体）はコア `ocudu_upper_phy` へ**静的リンク（同一プロセス・同一アドレス空間、プロセス分離なし）**（`phy_tap_plugin_example/lib/CMakeLists.txt:9`）。ZMQ 例は**消費側 dApp** のみを別プロセス化し得る（tap コード自体は in-process）。

## 項目9. 制御・設定（起動時設定 / 動的制御 I/F）

- 有効化・設定（アプリ設定構造体 `du_low_unit_expert_upper_phy_config`）：
  - 設定フィールド：`bool enable_phy_tap=false;` / `std::string phy_tap_arguments="";`（`apps/units/flexible_o_du/o_du_low/du_low_config.h`、`enable_phy_tap`/`phy_tap_arguments`）
  - CLI11：`--enable_phy_tap` / `--phy_tap_arguments`（`du_low_config_cli11_schema.cpp:245-254`）
  - YAML：`enable_phy_tap` / `phy_tap_arguments`（`du_low_config_yaml_writer.cpp:62-63`、`expert_phy:` セクション、README 例参照）
  - 反映：`if (enable_phy_tap) upper_phy_factory_config.phy_tap_arguments = phy_tap_arguments;`（`du_low_config_translator.cpp:60-62`）→ `upper_phy_factories.cpp:905-909` で生成
- `processor_arguments` の形式：**OCUDU 本体は中身を解釈せず**プラグインへ不透明に渡す。解釈はプラグイン側（例：正規表現 `tap_ul_epre=([^,]*)` で ZMQ バインドアドレス抽出、`external_processor_factories.cpp:110`）。書式はカンマ区切り `key=value`（README 例 `enable_quiet_processing=true,log_level=warning`）。
- **動的制御 I/F（E2/E3/dApp/RIC）は PHY TAP に対して存在しない**。tap は起動時に一度だけ生成され `std::unique_ptr<phy_tap>` として `uplink_processor_impl` へ渡る不変オブジェクトで、再構成パスは無い（`uplink_processor_impl.h:171,266`）。E2/RIC から phy_tap を制御する結線も無し（全文調査で未検出）。→ **起動時設定のみ。ランタイム動的制御は未実装（未確認）**。

---

# (a) 統合手順

26.04 を前提とした、UL PHY データを消費する dApp の統合手順（参考プラグインに準拠）：

1. **配置**：本体ツリーに `plugins/` を作成し、その配下へプラグイン一式を置く（`CMakeLists.txt:659-671`、既定 `ENABLE_PLUGINS=ON`）。26.04 ミラーには `plugins/` が無いため新規作成が必要。
2. **ファクトリ実装**：`ocudu::create_phy_tap_factory(nof_rb, nof_ports, processor_arguments)` を実装し、`phy_tap` を生成する `phy_tap_factory` を返す（手本：`phy_tap_factories.cpp:49-55`）。**26.04 の3引数署名に合わせる**（`upper_phy_factories.h:422`）。
3. **tap 実装**：`phy_tap` を継承し `handle_ul_symbol` と `handle_quiet_grid` を実装（26.04 はこの2つ。`dev` では `handle_prach_window` も必須）。
4. **vendor ロジック**：tap 内は最小限に留め、UL データ（`cbf16_t` グリッド＋PDU メタデータ）を抽出。重い処理は (i) 専用ワーカスレッドへ `defer`、または (ii) ZMQ 等の低レイテンシ IPC で別プロセスの dApp へストリーム（手本：`tap_ul_resource_grid_epre_zmq.{h,cpp}` / `zmq_server_backend.h`）。
5. **ビルド結線**：プラグイン CMake で `target_link_libraries(ocudu_upper_phy <plugin_obj>)` と `target_compile_definitions(ocudu_upper_phy PRIVATE -DOCUDU_HAS_PHY_TAP)`（手本：`lib/CMakeLists.txt:9,12`）。外部依存（例 `zmq`）と `ocudu_support` をリンク。**本体と同一コンパイラ・同一フラグ**（C++17, `-march/-mcpu=native`, `-fno-rtti`）でビルド。
6. **本体ビルド**：通常どおり本体を CMake ビルド（`ENABLE_PLUGINS=ON` で自動取り込み）。
7. **実行時有効化**：gNB 設定で `expert_phy.enable_phy_tap: true` と `expert_phy.phy_tap_arguments: <key=value,...>`（または CLI `--enable_phy_tap=true --phy_tap_arguments=...`）。dApp 側の接続先（例 ZMQ エンドポイント）は `phy_tap_arguments` で渡す。

---

# (b) dApp が最低限実装すべき I/F

26.04 でビルドを通すための**最小実装セット**：

| # | 実装対象 | 必須メソッド/関数 | 根拠 |
|---|---|---|---|
| 1 | `class : public ocudu::phy_tap` | `handle_ul_symbol(...)` / `handle_quiet_grid(...)` の2純粋仮想 | `phy_tap.h:50,70` |
| 2 | `class : public ocudu::phy_tap_factory` | `std::unique_ptr<phy_tap> create()` | `upper_phy_factories.h:417` |
| 3 | 自由関数 | `std::shared_ptr<phy_tap_factory> ocudu::create_phy_tap_factory(unsigned nof_rb, unsigned nof_ports, const std::string& processor_arguments)` | `upper_phy_factories.h:421-422` |
| 4 | ビルド定義 | `OCUDU_HAS_PHY_TAP` を `ocudu_upper_phy` に付与 | `lib/CMakeLists.txt:12` |

- 推奨（参考プラグイン流）：本体非依存の vendor 面 `external_ul_processor`（`process` / `process_quiet`、`dev` では `process_prach` も）を切り、`phy_tap` 実装はアダプタに留める（`external_ul_processor.h`, `phy_tap_impl.h`）。
- **`dev`／将来 26.10 へ移行する場合**：`phy_tap::handle_prach_window(prach_buffer&, const prach_buffer_context&)` の追加実装と、`create_phy_tap_factory` の `tdd_pattern` 引数追加が必須（項目7）。

---

# (c) 制約一覧

| 区分 | 制約 | 根拠 |
|---|---|---|
| 実行スレッド | RU UL 実行コンテキストで同期呼出。FSM ロック保持中（ブロッキングで slot processor 停止） | `phy_tap.h:48`, `uplink_processor_impl.cpp:115,120` |
| レイテンシ | シンボル単位の締切（概算：30 kHz ≈ 35.7 µs / 15 kHz ≈ 71.4 µs/シンボル。秒数はソース非記載の導出値） | `phy_tap.h:23-24,48-49` |
| メモリ所有 | グリッド参照・PDU span は**呼出中のみ有効**。PDU 領域は return 後変更不可（保持・遅延書込は UB） | `phy_tap.h:39-46` |
| データ型 | RE は (port, symbol) ごとの `span<const cbf16_t>`（複素 BF16 IQ）。CPU/ホストメモリ | `resource_grid_reader.h:108` |
| プロセス | in-process 静的リンク。out-of-process 化は自前 IPC（ZMQ 例あり） | `lib/CMakeLists.txt:9`, `zmq_server_backend.h` |
| アクセラレータ | GPU/HW アクセラレータは tap に未公開（BBDEV は LDPC 専用） | `CHANGELOG:20` |
| ビルド/ABI | 本体ツリー内・同一コンパイラ/フラグ・C++17・`-march/-mcpu=native`・`-fno-rtti`。安定 C ABI 無し | `CMakeLists.txt:18-19,197,554-577` |
| API 安定性 | 26.04→dev で I/F 変更済（メソッド/署名追加）。リリースごと再移植 | 項目7（dev raw 取得） |
| 制御 | 起動時 CLI/YAML のみ。ランタイム動的制御（E2/E3/RIC）無し | `du_low_config_*`、全文調査 |
| 登録 | dlopen 無し。リンク時ファクトリ上書き（`OCUDU_HAS_PHY_TAP`） | `upper_phy_factories.cpp:1331-1337` |
| ライセンス | 本体・例とも BSD-3-Clause-Open-MPI（許諾系）。3GPP 実装注記あり（解釈は本レポート対象外） | `LICENSE`, `phy_tap.h:2-3` |

---

# (d) 統合難易度の評価

判定凡例：◯=容易/低リスク、△=注意/中、×=困難/高リスク。工数は**概算**（1名想定、設計〜初回動作まで）。

| 項目 | 判定 | 理由（根拠） | 概算工数 |
|---|---|---|---|
| 1. I/F 明確性 | ◯ | 抽象クラス＋ファクトリが文書化され、動作する参考実装あり（`phy_tap.h`, 参考プラグイン） | 2〜3 人日 |
| 2. 登録/ロード | △ | dlopen 不可。`OCUDU_HAS_PHY_TAP` 上書き＋本体ツリー内ビルド前提（`upper_phy_factories.cpp:1331`, `lib/CMakeLists.txt:12`） | 2〜5 人日 |
| 3. ビルド組込 | △ | コア `ocudu_upper_phy` へ静的リンク、同一フラグ必須、外部依存(zmq)導入、`plugins/` 新設（`CMakeLists.txt:74,659-671`） | 3〜5 人日 |
| 4. フック位置/スレッド | △ | UL 受信チェーンの好位置だが RU UL スレッド・FSM ロック下（`uplink_processor_impl.cpp:115-120`） | 設計込 3〜5 人日 |
| 5. データ構造/所有権 | △ | 情報は豊富だが内部型に密結合・非所有 span・呼出内限定・BF16 IQ 理解が必要（`phy_tap.h:39-46`, `resource_grid_reader.h:108`） | 3〜5 人日 |
| 6. RT 制約 | ×（最難関） | サブシンボル締切・同期・in-process。vendor の重処理は同期実行不可、ワーカ/別プロセス退避が必須（`phy_tap.h:48-49`, ZMQ 例） | 1〜3 人週 |
| 7. API 安定性 | × | 26.04→dev で既に破壊的変更。安定 ABI 無し、リリースごと再移植（項目7） | 移植ごと 2〜4 人日（恒常） |
| 8. ライセンス/リンク形態 | ◯（事実） | BSD-3-Clause-Open-MPI（許諾系）、静的 in-process リンク。技術的障壁は小（解釈は対象外） | ほぼ 0 |
| 9. 制御/設定 | △ | 起動時 CLI/YAML の不透明引数のみ。動的制御が必要なら自前側チャネル実装（`du_low_config_*`） | 静的=1〜2 人日／動的=別途中規模 |

## 総合判定：**△〜×（中〜高難度）**

- **実現可能性は高い**：明確な抽象 I/F、動作する参考プラグイン、許諾系ライセンス、UL 受信チェーン上の好位置のフックが揃っており、「UL PHY データを外部へ出す」統合経路は明確に存在し実証済み（項目1,2,4,8）。
- **難しさの本質は3点**：
  1. **ハード RT・in-process 実行**（項目6）。vendor の DSP/ML をコールバックで同期実行することは現実的でなく、**薄い in-process tap＋低レイテンシ IPC で out-of-process dApp へ橋渡し**する設計が事実上必須（ZMQ 例が手本）。
  2. **本体ツリー内・静的リンク・同一フラグ**のビルド制約（項目3）。スタンドアロン SDK や安定 ABI が無い。
  3. **API 不安定**（項目7）。26.04 とリリースタグの無い `dev` で I/F が既に乖離。**26.04 リリース＋現行 plugin_examples をそのまま組み合わせると非互換**。
- **概算総工数（初回の out-of-process dApp ブリッジ実現まで）：約 3〜6 人週**。加えてリリース更新ごとに 2〜4 人日程度の再移植が恒常的に発生。
- **推奨**：(i) 対象リビジョンを **26.04 リリースで固定**するか **dev で固定**するかを先に決め I/F 署名を一致させる、(ii) tap は抽出/転送に限定し vendor 処理は別プロセス化、(iii) `phy_tap_arguments` で dApp 接続先を渡す、(iv) 動的制御が必要なら自前制御チャネルを別途設計（本体に E2/E3 連携は無い）。

---

# 付録. 主要根拠ファイル一覧

| ファイル | 役割 |
|---|---|
| `include/ocudu/phy/upper/phy_tap/phy_tap.h` | 統合 I/F（抽象クラス）定義 |
| `include/ocudu/phy/upper/upper_phy_factories.h` | `phy_tap_factory` / `create_phy_tap_factory` 宣言・設定フィールド |
| `lib/phy/upper/upper_phy_factories.cpp` | 弱い既定実装（`#ifndef OCUDU_HAS_PHY_TAP`）・ファクトリ生成（設定駆動） |
| `lib/phy/upper/uplink_processor_impl.{h,cpp}` | フック呼出（`handle_ul_symbol`）・FSM ロック・データ取得 |
| `lib/phy/upper/uplink_slot_processor_alt_impl.h` | 静かなスロットの `handle_quiet_grid` 呼出 |
| `lib/phy/upper/upper_phy_rx_symbol_handler_impl.cpp` | RU→UL 受信ハンドラ（呼び出し元） |
| `include/ocudu/phy/upper/uplink_pdu_slot_repository.h` | PUSCH/PUCCH/SRS PDU 構造体 |
| `include/ocudu/phy/support/resource_grid_reader.h` / `resource_grid_writer.h` / `resource_grid_base.h` | グリッド I/O・`cbf16_t`・次元 |
| `apps/units/flexible_o_du/o_du_low/du_low_config*.{h,cpp}` | CLI/YAML 設定・反映 |
| `CMakeLists.txt` | `ENABLE_PLUGINS` / `plugins/` 取り込み・コンパイラ/ABI フラグ |
| `cmake/modules/version.cmake` / `CHANGELOG` / `LICENSE` / `LICENSES/` | 版数・ライセンス事実 |
| `phy_tap_plugin_example/`（外部・clone） | 参考実装：ファクトリ上書き・ZMQ out-of-process・ビルド結線 |
| OCUDU `dev`（GitLab raw 取得） | 26.04 との I/F 差分（`handle_prach_window`, `tdd_pattern`） |
