---
title: "OCUDU PHY TAP 公開データ／UL KPI カタログと dApp 適合性評価"
subtitle: "UL PHY データを消費する 3rd party dApp の入力要件に対する OCUDU 供給データの過不足判定"
author: "調査: 実ソースベース（gitlab.com/ocudu, OCUDU 26.04）"
date: "2026-06-09"
lang: ja
---

# 0. 前提

| 項目 | 値 | 根拠 |
|---|---|---|
| 本体 | OCUDU **26.04.0**（ミラー `/home/user/ocudu-mirror`） | `cmake/modules/version.cmake:5-8` |
| 統合点 | PHY TAP プラグイン I/F `ocudu::phy_tap` | `include/ocudu/phy/upper/phy_tap/phy_tap.h:17-71` |
| TAP 呼出位置 | UL シンボル受信ごと、PHY が RE を消費する直前（RU UL 実行コンテキスト） | `lib/phy/upper/uplink_processor_impl.cpp:200-208`, `phy_tap.h:39-49` |
| 参考実装 | `plugin_examples/phy_tap_plugin_example`（clone 済） | GitLab（id 81731466） |

本レポートは「TAP から dApp に**実際に届く**データ」と「OCUDU が算出する UL KPI（TAP 経由か否か）」をカタログ化し、UL PHY dApp の一般的入力要件に対する過不足を判定する。統合機構（登録・ビルド・RT 制約）は別レポート（PHY TAP 統合調査）を参照。

> **一文要約**: TAP は「**等化前・FFT 後（周波数領域）のリソースグリッド IQ＋豊富なスケジューリング/参照信号メタデータ**」を渡すが、「**測定値（SINR/RSRP/EPRE/TA/CFO/チャネル行列）・絶対時刻・位相基準・時間領域(FFT前)IQ**」は渡さない。波形は OFDM 固定で差し替え不可。動的制御 I/F（E3/dApp）は無い。

---

# 1. 詳細調査結果

## 1.1 UL で dApp に届くデータの種別と TAP ポイント（項目1）

`phy_tap::handle_ul_symbol(...)`（`phy_tap.h:50-57`）が渡す引数＝**TAP から届く全データ**：

| データ | 型 | 内容 | 根拠 |
|---|---|---|---|
| リソースグリッド（読） | `const resource_grid_reader&` | 受信 RE（**FFT 後・等化前**の周波数領域 IQ） | `phy_tap.h:51`, `resource_grid_reader.h:108` |
| リソースグリッド（書） | `resource_grid_writer&` | RE を改変し書き戻し可能 | `phy_tap.h:50`, `resource_grid_writer.h:90` |
| スロット | `slot_point` | numerology(SCS)・SFN・slot index | `phy_tap.h:52`, `slot_point.h:90-100` |
| シンボル index | `unsigned` | スロット内 OFDM シンボル番号 | `phy_tap.h:53` |
| PUSCH PDU 群 | `span<const ...::pusch_pdu>` | RNTI・PRB・DMRS・ポート・MCS 等 | `phy_tap.h:54`, `pusch_processor.h:100-150` |
| PUCCH PDU 群 | `span<const ...::pucch_pdu>` | F0–F4 設定・コンテキスト | `phy_tap.h:55`, `pucch_processor.h:28-378` |
| PUCCH F1 共通 | `span<const ...::format1_common_configuration>` | F1 共通パラメータ | `phy_tap.h:56`, `pucch_processor.h:117-146` |
| SRS PDU 群 | `span<const ...::srs_pdu>` | SRS リソース設定一式 | `phy_tap.h:57`, `srs_estimator_configuration.h:17-26` |

`handle_quiet_grid(grid_reader, slot)`（`phy_tap.h:70`）は受信要求の無いスロットでグリッド全体を渡す。

### 参照信号・メタデータの再構成可否

- **PUSCH-DMRS**：`dmrs_symbol_mask`（DMRS シンボル位置, `pusch_processor.h:130`）、`dmrs_type`（TYPE1/TYPE2, `dmrs_mapping.h`）、`scrambling_id`/`n_scid`/`nof_cdm_groups_without_data`（`pusch_processor.h:67-85`）→ DMRS 系列・位置を**完全再構成可能**。
- **PUCCH-DMRS**：F2 の `n_id_0`（DMRS スクランブル, `pucch_processor.h:246`）、F3/F4 の `n_id_hopping`/`additional_dmrs`/`occ_*`、F0/F1 の `initial_cyclic_shift`/`time_domain_occ` → 各フォーマットの参照系列再構成に必要な ID を提供。
- **SRS**：`srs_resource_configuration`（`srs_resource_configuration.h:17-133`）に `sequence_id`・`comb_size`/`comb_offset`・`cyclic_shift`・`freq_position`/`freq_shift`/`freq_hopping`・`bandwidth_index`・`configuration_index`・`start_symbol`/`nof_symbols`・`nof_antenna_ports`・`periodicity` を**フル提供**→ SRS 系列・配置を完全再構成可能。
- **識別子・割当**：RNTI（`pusch_processor.h:106`, `ul_pucch_context.rnti`, `ul_srs_context.rnti`）、PRB（`freq_alloc`/`starting_prb`/`bwp_*`）、RX ポート（`rx_ports`/`ports`）、時間割当（`start_symbol_index`/`nof_symbols`）。
- **センシング示唆フラグ**：`ul_srs_context` に `is_normalized_channel_iq_matrix_report_requested` / `is_positioning_report_requested`（`uplink_processor_context.h:38-40`）。ただしこれは「上位層が要求したか」の**フラグのみ**で、SRS チャネル行列の**結果は TAP に届かない**（後述 1.5）。

### TAP に届かないもの（重要）

- **測定値／CSI**：SINR・RSRP・EPRE・EVM・CFO・TA・チャネル行列は TAP 後段で算出され、TAP には渡らない（1.5 参照）。TAP は `process_pusch/pucch/srs` の**前**に呼ばれる（`uplink_processor_impl.cpp:201` → `:212-226`）。
- **時間領域（FFT 前）IQ**：TAP は周波数領域グリッドのみ（1.2/B 参照）。
- **絶対時刻・位相基準**：`upper_phy_rx_symbol_context` は `{sector, slot, symbol}` のみで**タイムスタンプ無し**（`upper_phy_rx_symbol_handler.h:19-26`）。
- **PRACH 時間窓**：26.04 の `phy_tap` には PRACH 用メソッドが**無い**（dev では `handle_prach_window` が追加。別レポート項目7）。

## 1.2 データ形式・型、データレート、メモリ（項目2）

- **RE 型**：`cbf16_t`（複素 brain-float16 = 2×16bit = **4 byte/RE**）。`get_view(port, l)` が `span<const cbf16_t>`（`resource_grid_reader.h:108`）。`cf_t`（複素 float）でのコピー取得も可（`:56,91`）。
- **次元**：`get_nof_ports()` × `get_nof_symbols()` × `get_nof_subc()`（`resource_grid_base.h:19,22,25`）。
- **メモリ**：CPU/ホストメモリ上。GPU メモリ上のバッファや GPU コンテキストは TAP に無い（別レポート項目6）。**時間領域サンプリングレートは非公開**（時間領域サンプルを渡さないため）。
- **データレート（パラメトリック概算, ソース非記載の導出値）**：フルグリッド＝`nof_ports × nof_subc × 14 symbols × 4 byte / slot`。例）100 MHz・30 kHz・273 PRB(=3276 subc)・4 ポート → 約 **733 KB/slot**、slot=0.5 ms → 約 **1.47 GB/s**（全 RE をコピーする最悪値）。実用上は対象 PRB/シンボルに限定して削減する。

## 1.3 周期性とタイミング（項目3）

- **TAP 呼出周期**：`handle_ul_symbol` は**受信 UL シンボルごと**（最大 14 回/slot の割当経路）に同期呼出。締切は事実上 1 OFDM シンボル周期（概算 30 kHz≈35.7 µs / 15 kHz≈71.4 µs）。`handle_quiet_grid` はスロット最終シンボル（`uplink_slot_processor_alt_impl.h:41-42`）。
- **タイミング基準**：`slot_point` の SFN(0–1023)・slot index・numerology のみ（`slot_point.h:90-100`）。**絶対時刻は無い**（1.5/C）。
- **信号別の出現周期**（dApp が観測できる UL 参照信号の発生頻度＝下記 config で決まる）：
  - SRS：周期 1–2560 ms（または slots `sl1…sl2560`）（`srs_properties.h` periodicity, `du_high_config.h:513`）
  - PUSCH/PUCCH-DMRS：割当スロットの DMRS シンボル（`dmrs_add_pos` 0–3 で追加位置）
  - PRACH：`prach_config_index`（0–255）で SFN 周期・slot 配置決定（`prach_configuration.h:32-63`）
  - CSI-RS（DL, 参考）：10/20/40/80 ms（`du_high_config.h:876`）

## 1.4 有効化できる信号・周期の config ノブ（項目4）

| 信号 | 有効化ノブ | 周期ノブ | 根拠（file:line） |
|---|---|---|---|
| SRS | `--type_enabled`（disabled/periodic/aperiodic） | `--period_ms`（1–2560 ms） | `du_high_config.h:506,513` |
| CSI-RS（DL） | `--csi_rs_enabled` | `--csi_rs_period`（10/20/40/80 ms） | `du_high_config.h:874,876` |
| CSI レポート | `--report_type`（periodic/aperiodic） | `csi_report_periodicity`（slots4–320） | `csi_report_config.h:33-44` |
| PUSCH/PUCCH DMRS | （PUSCH に内蔵） | `--dmrs_add_pos`（0–3）、type/length | `du_high_config.h:320`, `dmrs_uplink_config.h:59-69` |
| PRACH | （常時） | `--prach_config_index`（0–255） | `du_high_config.h:946`, `prach_configuration.h:32-63` |
| **PHY TAP（live）** | `enable_phy_tap`（bool） | `phy_tap_arguments`（不透明文字列） | `du_low_config.h:69,71` |
| **RX グリッド file dump（offline）** | `phy_rx_symbols_filename` | `phy_rx_symbols_port` / `phy_rx_symbols_prach` | `du_low_config.h:85-89` |

> 補足：`phy_rx_symbols_*` は受信周波数領域シンボルを**ファイルへダンプ**する本体内蔵機能（オフライン解析用）であり、live TAP とは別経路の UL データ公開。

## 1.5 E2/KPM/E3 と制御方向（項目5）

- **E3 / dApp リアルタイム I/F：存在しない**。`\bE3\b`/`dApp`/`near-RT RIC`/`xApp` の該当は RLC-AM PDU の拡張ビットや README 等の無関係箇所のみ（全文 grep）。
- **E2：存在する**（near-RT RIC 向け）。`lib/e2/e2sm/` に **KPM（測定報告）・RC（RAN制御）・CCC（セル設定制御）** サービスモデル。
  - **KPM の UL 測定項目**は RLC/PDCP/RRU 層中心：`DRB.AirIfDelayUl`・`DRB.RlcDelayUl`・`RRU.PrbTotUl`・`RRU.PrbUsedUl`・`DRB.UEThpUl` 等（`lib/e2/e2sm/e2sm_kpm/e2sm_kpm_metric_defs.h`）。**PHY 層の SINR/EPRE/RSRP/EVM/TA は KPM に無い**（26.04）。
  - **RC の制御対象**は MAC/RLC/RRC/モビリティ/ビーム等で、**PHY アルゴリズム（等化・復調・波形・TAP）を制御する style は無い**（`lib/e2/e2sm/e2sm_rc/e2sm_rc_control_service_impl.h`）。
- **TAP への測定値供給：無し**。OCUDU は UL 測定値を算出するが**別経路**で配送：
  - PHY メトリクス：`pusch_processor_metrics{sinr_dB, evm}`・`ldpc_decoder_metrics{crc_ok, nof_iterations}`・`time_alignment_estimator_metrics` 等 → `phy_metric_notifier<T>` で通知（`include/ocudu/phy/metrics/phy_metrics_reports.h`, `phy_metrics_notifiers.h`）。
  - 結果通知：`channel_state_information`（SINR 3 種・EVM・EPRE・RSRP/port・CFO・TA）（`include/ocudu/phy/upper/channel_state_information.h`）、`pucch_processor_result.detection_metric`、`srs_estimator_result{srs_channel_matrix, epre, rsrp, noise_variance, time_alignment}`（`signal_processors/srs/srs_estimator_result.h`）。
  - これらは TAP の引数に**含まれない**（`phy_tap.h:50-70` の署名）。dApp が測定値を使うには別途これらの notifier をタップする結線が必要（本体改造）。
- **制御方向まとめ**：KPM＝読み取り（報告）専用、RC/CCC＝MAC/RLC/RRC/セルの制御（PHY 非対象）。TAP＝起動時設定のみ・ランタイム制御 I/F 無し。

## 1.6 波形に関する拡張性（項目6）

- **OFDM 変復調はファクトリ化されているが、プラグイン差し替え不可（コア固定）**。
  - I/F：`ofdm_modulator`/`ofdm_demodulator`（`include/ocudu/phy/lower/modulation/ofdm_*.h`）、ファクトリ `ofdm_modulator_factory`/`ofdm_demodulator_factory`（`modulation_factories.h:15-96`）。
  - 実装：`ofdm_*_factory_generic` が**直接インスタンス化**（`lib/phy/lower/modulation/modulation_factories.cpp:16-136`）。RF ラジオのような `dlopen`/`dlsym` ロード機構は**無い**。
  - 対応波形は **CP-OFDM** と **DFT-s-OFDM（transform precoding）** のみ。波形選択 enum や代替波形フックは**未検出**。
- **時間領域(FFT前)IQ は非公開**：グリッドは FFT/復調**後**に充填される（`ofdm_demodulator_impl.cpp` の `grid.put()`）。OFH split 7.2 では DU は**周波数領域 U-plane IQ** を受領しグリッドへ直接書込（`lib/ofh/receiver/ofh_uplane_rx_symbol_data_flow_writer.cpp`）→ DU 側に時間領域は存在しない。`baseband_gateway`（split 8/lower PHY）の生サンプルもプラグインへは公開されない。
- **帰結（ISAC 多波形の成立性）**：TAP は OFDM 復調済み周波数領域グリッドの read-modify-write のみ可能で、**非 OFDM 波形の送受信をプラグインから追加することはできない**。多波形 ISAC には PHY 本体（lower PHY/波形ファクトリ）の改造が必要。

---

# (a) 公開データ／KPI カタログ表

判定列：TAP=live TAP 経由で届くか。◯=届く / ×=届かない / （別経路）=他 I/F 経由。

| # | データ/KPI 項目 | 型・形式 | TAP | 算出/配送経路 | 周期 | 根拠（file:line） |
|---|---|---|---|---|---|---|
| 1 | 受信リソースグリッド（FFT後・等化前 IQ） | `cbf16_t`/`cf_t`（複素, 4B/RE）, CPU mem | ◯（R/W） | grid 参照を直接受領 | per-symbol | `resource_grid_reader.h:108`, `phy_tap.h:50-51` |
| 2 | slot/SFN/numerology(SCS) | `slot_point` | ◯ | 引数 | per-symbol | `slot_point.h:90-100`, `phy_tap.h:52` |
| 3 | symbol index | `unsigned` | ◯ | 引数 | per-symbol | `phy_tap.h:53` |
| 4 | PUSCH 割当・RNTI・MCS・層・ポート | `pusch_processor::pdu_t` | ◯ | 引数 span | 割当スロット | `pusch_processor.h:100-150` |
| 5 | PUSCH-DMRS（位置/型/スクランブル） | `dmrs_symbol_mask`+`dmrs`変種 | ◯ | 引数 span | DMRS シンボル | `pusch_processor.h:130-132` |
| 6 | PUCCH F0–F4 設定（PRB/hopping/スクランブル/DMRS-ID） | variant `format0..4_configuration` | ◯ | 引数 span | 割当スロット | `pucch_processor.h:28-378` |
| 7 | PUCCH F1 共通 | `format1_common_configuration` | ◯ | 引数 span | 割当スロット | `pucch_processor.h:117-146` |
| 8 | SRS リソース設定（系列/comb/hopping/帯域/周期） | `srs_estimator_configuration`+`srs_resource_configuration` | ◯ | 引数 span | SRS periodicity | `srs_resource_configuration.h:17-133` |
| 9 | UE 識別子（RNTI）/SR 機会/SRS 要求フラグ | `ul_pucch_context`/`ul_srs_context` | ◯ | 引数（context） | 割当スロット | `uplink_processor_context.h:20-41` |
| 10 | SINR（推定器/等化後/EVM 由来） | `channel_state_information` | ×（別経路） | result notifier | post-proc | `channel_state_information.h` |
| 11 | RSRP / EPRE（port 別含む） | `channel_state_information` | ×（別経路） | result notifier | post-proc | 同上 |
| 12 | EVM（合計/シンボル別） | `channel_state_information` | ×（別経路） | result notifier | post-proc | 同上 |
| 13 | CFO（Hz） | `channel_state_information` | ×（別経路） | result notifier | post-proc | 同上 |
| 14 | TA（time alignment） | `channel_state_information` / `srs_estimator_result` | ×（別経路） | result notifier | post-proc | `srs_estimator_result.h` |
| 15 | SRS チャネル行列（正規化 IQ 行列） | `srs_channel_matrix` | ×（別経路） | `srs_estimator_result` | SRS 機会 | `srs_estimator_result.h` |
| 16 | noise variance | `srs_estimator_result` | ×（別経路） | result notifier | post-proc | 同上 |
| 17 | CRC / LDPC 反復回数 | `ldpc_decoder_metrics`/`pusch_decoder_result` | ×（別経路） | metric notifier | post-proc | `phy_metrics_reports.h` |
| 18 | PUCCH 検出メトリック | `pucch_processor_result.detection_metric` | ×（別経路） | result | post-proc | `pucch_processor_result.h` |
| 19 | E2 KPM UL 項目（PrbUl/AirIfDelayUl/UEThpUl 等） | E2SM-KPM | ×（別 I/F=E2） | E2 報告 | 報告周期 | `e2sm_kpm_metric_defs.h` |
| 20 | 絶対時刻（PTP/GPS, wall-clock） | `baseband_gateway_timestamp`（入口のみ） | ×（消失） | baseband 入口で破棄 | — | `baseband_gateway_receiver.h:18-21`, `upper_phy_rx_symbol_handler.h:19-26` |
| 21 | 位相基準/コヒーレンス情報 | — | ×（未確認） | 公開なし | — | （未検出） |
| 22 | 時間領域 / FFT 前 IQ サンプル | — | ×（非公開） | lower PHY/OFH 内で消費 | — | `ofh_uplane_rx_symbol_data_flow_writer.cpp` |
| 23 | PRACH 時間窓（buffer/context） | `prach_buffer`/`prach_buffer_context` | ×（26.04 は未） | dev で `handle_prach_window` | PRACH 機会 | 別レポート項目7 |
| 24 | RX グリッド file dump（offline） | ファイル出力 | （別経路） | 本体内蔵ダンプ | 設定次第 | `du_low_config.h:85-89` |

## UL KPI（OCUDU が算出する主な UL PHY KPI、TAP 非経由）

| KPI | 構造体/フィールド | 配送 | 根拠 |
|---|---|---|---|
| PUSCH SINR / EVM | `pusch_processor_metrics{sinr_dB, evm}` | metric notifier | `phy_metrics_reports.h` |
| CSI（SINR×3/RSRP/EPRE/CFO/TA/EVM） | `channel_state_information` | PUSCH/PUCCH result | `channel_state_information.h` |
| SRS（チャネル行列/EPRE/RSRP/noise/TA） | `srs_estimator_result` | SRS result | `srs_estimator_result.h` |
| 復号（CRC/反復） | `ldpc_decoder_metrics`,`pusch_decoder_result` | metric/result | `phy_metrics_reports.h` |
| UL リソース/遅延/スループット | E2SM-KPM（RRU.PrbUl, DRB.*Ul） | E2 | `e2sm_kpm_metric_defs.h` |

---

# (b) 適合性評価（◯/△/×）

UL PHY dApp が**一般に必要とする入力**に対する OCUDU TAP 供給の判定。dApp 個別の具体要件は別途入力前提で〔要入力〕を置く。

| 一般入力要件 | OCUDU 供給（TAP） | 判定 | 理由（file:line） | dApp 個別要件 |
|---|---|---|---|---|
| 周波数領域 RX IQ（等化前グリッド） | grid R/W（cbf16） | ◯ | `resource_grid_reader.h:108` | 〔要入力〕 |
| 参照信号の位置・系列再構成（DMRS/SRS） | フル設定提供 | ◯ | `pusch_processor.h:130-132`, `srs_resource_configuration.h:17-133` | 〔要入力〕 |
| 対象 PRB/アロケーション（UE・ch 対応） | `freq_alloc`/PRB/ports | ◯ | `pusch_processor.h:128,134` | 〔要入力〕 |
| UE 識別（RNTI） | context.rnti | ◯ | `uplink_processor_context.h:24,36` | 〔要入力〕 |
| numerology/SCS・slot/symbol | `slot_point`+symbol | ◯ | `slot_point.h:90-100` | 〔要入力〕 |
| シンボル書き戻し（grid 改変） | writer 提供 | ◯ | `phy_tap.h:50` | 〔要入力〕 |
| チャネル推定/CSI（SINR/RSRP/TA/行列） | TAP 非経由 | × | `phy_tap.h:50-70`（署名に無し）、別経路 `channel_state_information.h` | 〔要入力〕 |
| 絶対時刻（PTP/GPS, wall-clock） | 入口で消失 | × | `upper_phy_rx_symbol_handler.h:19-26` | 〔要入力〕 |
| 位相基準/コヒーレンス | 公開なし | ×（未確認） | （未検出） | 〔要入力〕 |
| 時間領域 / FFT 前 IQ | 非公開（周波数領域のみ） | × | `ofh_uplane_rx_symbol_data_flow_writer.cpp` | 〔要入力〕 |
| ランタイム制御（有効化/パラメータ） | 起動時 config のみ | △ | `du_low_config.h:69,71`、E3/dApp 無し | 〔要入力〕 |
| マルチ波形/非 OFDM 送受信 | OFDM 固定・差し替え不可 | × | `modulation_factories.cpp:16-136` | 〔要入力〕 |
| PRACH 時間窓アクセス | 26.04 未（dev で追加） | △ | 別レポート項目7 | 〔要入力〕 |

---

# (c) データ供給面から見た統合難易度の所見

dApp の類型ごとに、TAP 供給データで成立するかを判定する。

| dApp 類型 | 必要入力 | TAP 供給での成立性 | 所見・追加作業 |
|---|---|---|---|
| **A. 周波数領域 UL 解析系**（干渉/雑音監視、復調前グリッド解析、UL 占有・スペクトル監視、参照信号ベースの自前チャネル推定） | 等化前グリッド＋RS/PRB/RNTI メタ | **◯ 成立** | TAP の供給で充足。grid＋DMRS/SRS 設定から自前推定可能。RT 退避（別スレッド/IPC）は必要だがデータ供給面の不足は無い。 |
| **B. 測定値消費系**（OCUDU 算出の SINR/RSRP/TA/チャネル行列を入力にする dApp） | 後段測定値・CSI | **△ 限定的** | TAP には届かない。`channel_state_information`/`srs_estimator_result`/metric notifier を**別途タップする本体改造**が必要。E2 KPM は PHY 層 CSI を持たない。 |
| **C. コヒーレント・センシング / ISAC**（時間領域 IQ・絶対時刻・位相基準・非 OFDM 波形が必要） | 時間領域 IQ、PTP/GPS 時刻、位相、波形拡張 | **× 不足** | TAP は周波数領域のみ。絶対時刻は baseband 入口で消失（`baseband_gateway_receiver.h:18-21`→`upper_phy_rx_symbol_handler.h:19-26`）。位相基準は未公開。非 OFDM 波形は本体固定。**lower PHY/OFH の改造（pre-FFT サンプル＋timestamp 公開）と波形ファクトリ拡張**が前提で、TAP の枠を超える。 |

**総括**

- **充足する用途（A）**：「UL の復調済み周波数領域 IQ＋スケジューリング/参照信号メタデータ」を入力とする dApp には、OCUDU の供給は**十分**（◯）。特に DMRS/SRS の設定が完全提供される点が強み。
- **部分充足（B）**：OCUDU 算出の UL 測定値（SINR/RSRP/TA/チャネル行列等）は**存在するが TAP 非経由**。利用には result/metric notifier への追加結線（本体改造）が必要（△）。
- **不足する用途（C：時刻同期センシング/ISAC）**：**時間領域 IQ・絶対時刻・位相基準が TAP に無く**、かつ**波形が OFDM 固定**のため、現行 TAP のデータ供給では**成立しない**（×）。lower PHY/OFH への時刻付き生サンプル公開と波形拡張という本体側の追加開発が前提。
- **動的制御面**：dApp を実行時に制御する I/F（E3/dApp）は無く、E2 も PHY を制御しない。dApp の有効化・パラメータは**起動時 config（不透明引数）のみ**（△）。
- **センシング示唆**：`ul_srs_context` の positioning/IQ-matrix 要求フラグや NRPPa（CHANGELOG 26.04）は OCUDU 内に測位経路が存在することを示すが、その**データは TAP には届かない**。

> 次段アクション：dApp 個別要件（〔要入力〕欄）が確定すれば、本カタログ表と突き合わせて各行の判定を確定できる。特に「時間領域 IQ / 絶対時刻 / 位相 / 測定値 / 波形拡張」の要否が A/B/C の類型判定と本体改造規模を分ける。

---

# 付録. 主要根拠ファイル

| ファイル | 役割 |
|---|---|
| `include/ocudu/phy/upper/phy_tap/phy_tap.h` | TAP I/F（届くデータの境界） |
| `include/ocudu/phy/support/resource_grid_reader.h` / `resource_grid_writer.h` / `resource_grid_base.h` | グリッド I/O・`cbf16_t`・次元 |
| `include/ocudu/phy/upper/channel_processors/pusch/pusch_processor.h` | PUSCH PDU・DMRS |
| `include/ocudu/phy/upper/channel_processors/pucch/pucch_processor.h` | PUCCH F0–F4 設定 |
| `include/ocudu/phy/upper/signal_processors/srs/srs_estimator_configuration.h` / `ran/srs/srs_resource_configuration.h` | SRS 設定 |
| `include/ocudu/phy/upper/uplink_processor_context.h` | PUCCH/SRS コンテキスト（RNTI・要求フラグ） |
| `include/ocudu/ran/slot_point.h` | slot/SFN/numerology（絶対時刻なし） |
| `include/ocudu/phy/upper/channel_state_information.h` / `signal_processors/srs/srs_estimator_result.h` | CSI・SRS 測定結果（TAP 非経由） |
| `include/ocudu/phy/metrics/phy_metrics_reports.h` / `phy_metrics_notifiers.h` | PHY メトリクス |
| `lib/e2/e2sm/e2sm_kpm/e2sm_kpm_metric_defs.h` / `e2sm_rc/*` | E2 KPM/RC（PHY 制御なし・E3 なし） |
| `include/ocudu/phy/lower/modulation/modulation_factories.h` / `lib/phy/lower/modulation/modulation_factories.cpp` | OFDM 変復調（コア固定・非プラグイン） |
| `include/ocudu/gateways/baseband/baseband_gateway_receiver.h` / `include/ocudu/phy/upper/upper_phy_rx_symbol_handler.h` | 絶対 timestamp の所在と消失点 |
| `lib/ofh/receiver/ofh_uplane_rx_symbol_data_flow_writer.cpp` | OFH split 7.2＝周波数領域 IQ |
| `apps/units/flexible_o_du/o_du_low/du_low_config.h` / `o_du_high/du_high/du_high_config.h` | TAP/grid-dump 有効化・SRS/CSI/DMRS/PRACH config |
