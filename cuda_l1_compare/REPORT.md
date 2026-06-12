# Aerial CUDA-Accelerated RAN vs CUDA Accelerated OCUDU — L1 (PHY) 技術比較レポート

- 作成日: 2026-06-12
- 比較対象: NVIDIA Aerial CUDA-Accelerated RAN **26.1.1** / CUDA Accelerated OCUDU **preview (commit ccdf4e6)**
- 本文中のパスは `aerial/...` = Aerial リポジトリ、`ocudu/...` = OCUDU リポジトリからの相対パス。`(推測)` 表記のない記述はコード・ドキュメントで確認済みの事実。

---

## 1. エグゼクティブサマリ

1. **カバレッジ**: Aerial は L1 全チャネル（PDSCH/PDCCH/SSB/CSI-RS/BFW/PUSCH/PUCCH F0-4/PRACH/SRS）を GPU で完結する「フル GPU インライン L1」。OCUDU はスループット支配的なパス（PUSCH/PDSCH/SRS/PRACH 一部/lower-PHY/OFH 圧縮）のみ GPU 化し、PDCCH/PUCCH/SSB/CSI-RS は CPU のままの「選択的オフロード + CPU フォールバック」。
2. **アーキテクチャ思想**: Aerial は GPU を L1 の主体とする専用 SDK（cuPHY）+ 専用制御プレーン（cuphydriver, MPS/green context で SM を静的分割）。OCUDU は既存 CPU PHY の factory/selector 層にベンダ中立な抽象（`phy_acceleration.h`、opaque token）として CUDA を差し込み、`auto/enabled/disabled` の YAML 設定でランタイム選択。
3. **HW 依存**: Aerial は GH200/A100/H100 級 GPU + ConnectX-7/BlueField-3 + DOCA GPUNetIO/GPUDirect + 専用 NVIDIA カーネルが前提のフルスタック垂直統合。OCUDU は sm_89〜121（RTX 40xx〜DGX Spark/Jetson 系 iGPU 含む）で動作し、NIC は通常 NIC（GPUDirect 不使用）、FFT も vkFFT(MIT) で cuFFT 非依存。
4. **成熟度**: Aerial は 2025-2026 に 5 リリース（25.3.x→26.1.x）を重ねた商用グレード（ただし開発履歴は非公開のスカッシュコミット、外部コントリビューション不可）。OCUDU CUDA は DeepSig による 2026-06 の preview（実質 2 コミット、403 ファイル +15.2 万行）で、本家 OCUDU への upstream 統合前段階。
5. **性能の公開度**: OCUDU は再現手順付きの実測値を README に公開（PUSCH 21.2 倍、OFH BFP 26〜72 倍、ただし 20MHz 1 レイヤでは GPU が逆に遅い）。Aerial はリポジトリ内に性能数値を公開していない（ベンチツールのみ同梱）。

**用途別の向き不向き**: 大規模 massive MIMO 商用 DU・AI-RAN 研究（pyAerial/dataLake/E3）には Aerial。オープンガバナンス下での改変・統合・マルチプラットフォーム展開（エッジ/iGPU 含む）、自社 L1 への段階的 GPU 導入の参照実装としては OCUDU が適する。

---

## 2. 調査対象スナップショット

| 項目 | Aerial | OCUDU (CUDA preview) |
|---|---|---|
| リポジトリ | github.com/NVIDIA/aerial-cuda-accelerated-ran | gitlab.com/ocudu/work_groups/wg1_hw_accel/cuda_accelerated_ocudu |
| 調査 commit | `29f5870fd84b0176df48b40667c1b8f1740e6d09` | `ccdf4e681fc93927e1baebd697e8f879de641b38` |
| タグ / バージョン | `26.1.1`（最新タグ、2026-05-27） | タグなし（OCUDU 26.04 ベース、2026-06-08） |
| 取得方法 | `git clone --depth 50`（2026-06-12 実施） | 同左 |
| 直近コミット | "Append -cubb to install script version" ほかリリーススカッシュのみ | `9fd4047` "feat(cuda): add resident CUDA PHY acceleration"（+152,052 行 / 403 ファイル）、`ccdf4e6` README 整備 |
| CUDA 実装の著者 | NVIDIA（コミッタは `aerial` アカウントのみ） | DeepSig Inc（Tim O'Shea / Wan Liu、SPDX: `Copyright (C) 2021-2026 DeepSig Inc`） |

### 2.1 全体構造の棚卸し（Phase 1）

**Aerial トップ構成**（`aerial/README.md:31-49` の構造記述と一致することを確認）:

| ディレクトリ | 役割 |
|---|---|
| `cuPHY/` | CUDA L1 ライブラリ本体（チャネルパイプライン、カーネル、test、examples） |
| `cuPHY-CP/` | 制御プレーン: `cuphycontroller`(設定/起動)、`cuphydriver`(スロットスケジューラ)、`cuphyl2adapter`/`scfl2adapter`(L2-FAPI)、`aerial-fh-driver`(O-RAN FH)、`ru-emulator`、`testMAC`、`data_lake`(+E3 agent)、`container` |
| `cuMAC/`, `cuMAC-CP/` | GPU アクセラレーテッド L2 スケジューラ |
| `pyaerial/` | Python バインディング + ML notebooks |
| `5GModel/` | MATLAB 5G リファレンスモデル（テストベクタ生成） |
| `testBenches/`, `testVectors/`, `cubb_scripts/` | 性能測定、TV、インストール自動化 |

**OCUDU トップ構成**: フル gNB スタック（`lib/` 配下に `cu_cp, cu_up, du, mac, rlc, pdcp, rrc, ngap, e2, fapi_adaptor, ofh, phy, ru, scheduler` 等）。CUDA 追加分は以下に集約:

| 場所 | 役割 |
|---|---|
| `ocudu/lib/phy/cuda/` | in-tree CUDA カーネルライブラリ `ocudu_phy_cuda`（C API: `include/ocudu_phy_cuda.h`、`ocudu/lib/phy/cuda/README.md:3-10`） |
| `ocudu/lib/phy/upper/channel_coding/ldpc/cuda/` | OCUDU 抽象への C++ アダプタ層（LDPC/変調/PDSCH grid writer 等） |
| `ocudu/lib/phy/upper/`, `ocudu/lib/phy/lower/`(経由), `ocudu/lib/ofh/` | resident PUSCH、CUDA-visible grid、OFH GPU 圧縮の統合 |
| `ocudu/scripts/cuda_accel/` | ベンチ/回帰スクリプト群（12 本） |
| `ocudu/docs/doxygen/phy_acceleration.dox` | アクセラレーション設計ドキュメント（162 行） |

**言語別規模**（third_party/external 除外、`find`+`wc` による実測）:

| 種別 | Aerial | OCUDU |
|---|---|---|
| `.cu` | 611 ファイル / 176,381 行 | 57 ファイル / 63,418 行 |
| `.cuh` | 92 / 65,855 行 | 2 / 585 行 |
| `.cpp` | 433 / 311,426 行 | 1,885 / 1,196,187 行（フル CU/DU スタック含む） |
| `.h/.hpp` | 474 / 347,007 行 | 3,025 / 515,688 行 |
| `.py` | 278 / 78,239 行（pyAerial 等） | 9 / 1,105 行 |
| MATLAB `.m` | 549 / 121,243 行（5GModel） | 0 |

ビルドは両者 CMake。Aerial は cuPHY のデフォルトアーキが `80-real 90-real`（`aerial/cuPHY/CMakeLists.txt:124-126`）、OCUDU は未指定時 `native`（`ocudu/lib/phy/cuda/CMakeLists.txt:108-111`）で `-DENABLE_CUDA=ON` のオプトイン（`ocudu/CMakeLists.txt` の `option(ENABLE_CUDA ... OFF)`）。

---

## 3. 比較マトリクス

凡例: ✅=対応/充実、△=部分対応/制約あり、❌=非対応/なし、❓=リポジトリからは不明

### A. アーキテクチャ / 全体設計

| 観点 | Aerial | OCUDU |
|---|---|---|
| L1 レイヤ分割 | ✅ inline High-PHY(7.2x split、FH 直結) | ✅ split 7.2(OFH) と split 8(SDR) の両対応、High/Low PHY とも部分 GPU 化 |
| SDK 階層構造 | ✅ cuPHY(ライブラリ) / cuPHY-CP(制御) の明確な 2 層 + チャネル毎パイプラインオブジェクト | ✅ 既存 OCUDU PHY 抽象に factory/selector で挿入、カーネルは単一静的ライブラリ |
| ホスト/GPU 責務分担 | ✅ GPU 主体(L2 メッセージ→GPU パイプライン直行) | △ CPU 主体 + ブロック単位オフロード(resident 化で往復削減) |
| スロットパイプライン | ✅ DL/UL 専用 SlotMap リング + チャネル aggregator | △ 既存 executor 上で非同期 stream 実行 |
| 設定駆動 | ✅ YAML(cuphycontroller) 全面 | ✅ YAML `auto/enabled/disabled` セレクタ + env hooks |

### B. CUDA 実装

| 観点 | Aerial | OCUDU |
|---|---|---|
| CUDA Graphs | ✅ 全面採用(conditional node, device graph 含む) | △ lower-PHY TX/RX の graph キャッシュ(env でオプトイン) |
| Streams/優先度 | ✅ セル毎複数 stream + MPS SM 分割 + green contexts | ✅ greatest-priority stream + H2D/D2H/scrambler 専用 stream |
| Fused/persistent kernel | ✅ fused 多数、order kernel(GDR 同期) | ✅ fused(scramble+mod, PUSCH E2E)、persistent なし |
| メモリ管理 | ✅ pinned/GDR pinned、フットプリント追跡 | ✅ managed(iGPU)/pinned(dGPU)・memAdvise・mem pool・トリプルバッファ |
| ライブラリ依存 | cuFFTDx(mathdx)、TensorRT(chEst)、cuBLAS/cuSOLVER 不使用 | vkFFT(MIT 同梱)のみ、cuFFT 不使用 |
| Tensor Core/混合精度 | △ FP16 LLR(`LLR_FP16`)、WMMA/MMA なし | △ FP16 LLR、WMMA/MMA なし |
| マルチ GPU / GPUDirect | ✅ マルチ GPU、GPUDirect RDMA + GDRCopy + DOCA GPUNetIO | ❌ 単一デバイス前提、GPUDirect なし |
| 対象 GPU アーキ | sm_80/90 デフォルト(+121 インストーラ)。Ampere/Hopper/(Blackwell) | sm_89/90/100/103/120/121、Tegra/iGPU 自動検出 |

### C. PHY チャネル処理カバレッジ（GPU 化の範囲）

| チャネル/機能 | Aerial (GPU) | OCUDU (GPU) |
|---|---|---|
| PDSCH | ✅ フル(CRC/LDPC/RM/変調/DMRS/プリコーディング) | ✅ LDPC enc + RM + fused scramble/変調 + direct grid write |
| PDCCH | ✅ | ❌ CPU |
| PBCH/SSB | ✅(セル/スロット 3 SSB) | ❌ CPU |
| CSI-RS | ✅ TX/RX 両実装あり | ❌ CPU |
| PUSCH | ✅ フル(chEst 多方式/等化/LDPC/early-HARQ) | ✅ E2E resident(LS chEst, ZF/MMSE/MMSE-IRC, FP16 LLR, LDPC, UCI 一部) |
| PUCCH | ✅ F0–F4 | ❌ CPU(F0–F4 とも) |
| PRACH | ✅ | △ lower-PHY 復調は GPU、検出は CPU 既定(CUDA 検出器は実装あり) |
| SRS | ✅ RX/TX + BFW 計算 | ✅ 推定(LSE、TA 推定付き) |
| LDPC enc/dec | ✅ SM 世代別特化実装、早期終了、FP16 | ✅ layered min-sum/boxplus、早期終了、codeword pairing |
| Polar enc/dec | ✅ (PBCH/PDCCH/PUCCH F2-4) | △ カーネルあり、PUSCH 内 UCI 復号のみ結線 |
| ビームフォーミング | ✅ BFW Tx(SRS ベース、32 構成) | ❌ |
| 変調次数 | 〜256QAM(1024QAM なし) | 〜256QAM |
| 最大 PRB / アンテナ / レイヤ | 273 PRB / 64 ant / UL 8L・DL 4L per TB(セル 32L) | 273 PRB / RX 8 port / UL 4L(GPU 路) |

### D. 機能分割 & インターフェース

| 観点 | Aerial | OCUDU |
|---|---|---|
| FAPI | ✅ SCF FAPI v10.04 + ベンダ拡張、nvIPC(shm) | ✅ 自前 FAPI 層(lib/fapi)、CUDA は FAPI の下で透過 |
| O-RAN FH | ✅ O-RAN.WG4.CUS.0-v05.00 サブセット、eCPRI、BFP9/14、C/U-plane(M-plane なし) | ✅ 既存 lib/ofh(eCPRI、C/U-plane)、GPU は BFP8-16/無圧縮の圧縮処理のみ |
| L2/DU 接続 | ✅ scfl2adapter + testMAC(外部 L2 接続前提) | ✅ 同一リポジトリ内 MAC/DU(完結) |
| タイミング | ✅ PTP 前提(エラーコード/監視)、T1a 等パラメータ | △ OFH 一般要件(CUDA 固有変更なし) |

### E. パフォーマンス / 最適化

| 観点 | Aerial | OCUDU |
|---|---|---|
| レイテンシ目標記述 | △ パラメータは存在(t1a_*, slot_advance=3)、明示予算ドキュメントなし | △ ベンチ実測のみ |
| 公開性能数値 | ❌ リポジトリ内になし | ✅ README に実測+再現コマンド |
| ベンチツール | ✅ cubb_gpu_test_bench、nsys 連携、容量自動判定 | ✅ scripts/cuda_accel 12 本 + ctest ベンチ |
| リアルタイム機構 | ✅ isolcpus/nohz_full/idle=poll、専用カーネル、コアピン留め YAML | △ governor/バッファ調整スクリプト、OCUDU 標準 affinity |

### F. 標準準拠 / G. テスト

| 観点 | Aerial | OCUDU |
|---|---|---|
| 3GPP 対応 | Rel-15 基本 + Rel-16/17 相当機能(明示タグなし)(推測) | 同(OCUDU 本体は 3GPP/O-RAN 準拠を標榜) |
| テストベクタ | ✅ MATLAB 5GModel→HDF5 TV、コンフォーマンス試験セット | △ 自己生成スイープ(GPU/CPU パリティ、BLER)、3GPP 公式 TV なし |
| CI | ❌ 公開 CI なし | ✅ GitLab CI(ただし CUDA ジョブなし(推測)) |

### H. ハードウェア / I. ソフトウェア依存

| 観点 | Aerial | OCUDU |
|---|---|---|
| 要求 GPU | A100/H100/GH200/DGX Spark(リファレンス) | 任意の CUDA GPU(iGPU 含む、native ビルド可) |
| NIC/DPU | ConnectX-5〜7 / BlueField-3 + DOCA 必須(FH 経路) | 通常 NIC(DPDK は任意、既定 OFF) |
| ベンダーロック | 強(NVIDIA 垂直統合) | 弱(CUDA は backend の 1 つという建付け、vkFFT) |
| CUDA/driver | CUDA 13.1.1 / driver 590.48.01 / GDRCopy 2.5.1 / DOCA 3.2.1(インストーラ固定) | CUDA 13.0.88 / driver 580.95.05 で実測(最小版数の強制なし) |
| OS/カーネル | Ubuntu 22.04/24.04 + NVIDIA 専用カーネル(6.17.0-1014-nvidia 等) | Ubuntu 24.04 ほか(汎用、専用カーネル不要) |
| コンテナ | ✅ NGC コンテナ + HPCCM レシピ | △ 汎用 Docker のみ(CUDA プリセットなし) |

### J. ライセンス / K. 拡張性 / L. ドキュメント / M. 成熟度

| 観点 | Aerial | OCUDU |
|---|---|---|
| ライセンス | Apache 2.0(2025 オープンソース化) | BSD-3-Clause Open MPI variant |
| ソース公開範囲 | ✅ フルソース(バイナリ blob なし) | ✅ フルソース |
| コントリビューション | ❌ 受け付けない | ✅ 受け付け(LF ガバナンス、TSC) |
| dApp/xApp・AI 連携 | ✅ data_lake(ClickHouse)+E3 agent、pyAerial+TensorRT chEst | ❌ なし(E2 は本体にあるが CUDA 非連動) |
| カスタムカーネル追加性 | △ cuPHY C API はあるが巨大・密結合(推測) | ✅ factory/selector + opaque token 設計で追加容易 |
| ドキュメント | ✅ NVIDIA Docs Hub + コンポーネント README | ✅ README(527 行) + phy_acceleration.dox + lib README |
| 成熟度 | 商用グレード、5 リリース、開発履歴非公開 | preview(実質 2 コミット)、upstream 統合中 |

---

## 4. 観点別 詳細所見

### A. アーキテクチャ / 全体設計

**A-1. レイヤ分割と split の扱い**

- Aerial は O-RAN 7.2x split の DU 側 L1（High-PHY）を GPU 上にインライン実装し、フロントホールから GPU メモリへ直接データを引き込む構成。`aerial/cuPHY-CP/aerial-fh-driver/README.md:4` に「O-RAN Fronthaul CUS Specification 5.0 (O-RAN.WG4.CUS.0-v05.00) のサブセットを実装」と明記。FH 受信は DOCA GPUNetIO（`aerial/cuPHY-CP/aerial-fh-driver/lib/gpu_comm_doca.cu:18-21` で `doca_gpunetio.h` を include）で GPU が直接パケットを処理する。
- OCUDU は split 7.2（`ru_ofh`）と split 8（`ru_sdr`、UHD/ZMQ）の両方を持ち、CUDA 化は両経路に挿入されている。split 8 用 lower-PHY の OFDM 変調/復調 GPU 化（`ocudu/lib/phy/cuda/src/low_phy_tx.cu`, `low_phy_puxch_rx.cu`）と、split 7.2 用 OFH IQ 圧縮 GPU 化（`ocudu/lib/phy/cuda/src/ofh_compression.cu`）が併存する（`ocudu/README.md:59-79`）。

**A-2. SDK 階層構造**

- Aerial: cuPHY が 11 種のチャネルパイプラインクラス（`PdschTx`/`PuschRx`/`PdcchTx`/`SsbTx`/`CsirsTx`/`CsirsRx`/`BfwTx`/`PucchRx`/`PrachRx`/`SrsRx`/`SrsTx`、`aerial/cuPHY/src/cuphy_channels/` 配下）を公開し、cuPHY-CP の `cuphydriver` がスロット単位で起動する 2 層構造。
- OCUDU: カーネルは C API（`ocudu/lib/phy/cuda/include/ocudu_phy_cuda.h`）を持つ単一静的ライブラリ `ocudu_phy_cuda` に集約し、「CUDA カーネル/ランタイムコードを 1 箇所に保ち、上位 factory/selector は既存 OCUDU 抽象を使い続ける」方針が明文化されている（`ocudu/lib/phy/cuda/README.md:7-10`）。設計原則は `ocudu/docs/doxygen/phy_acceleration.dox:12-23` に「汎用 PUSCH/PDSCH/PRACH/SRS/lower-PHY/OFH オーケストレーションは OCUDU インターフェースに依存し、具象アクセラレータクラスに依存してはならない」「モード解析・可用性チェック・フォールバック選択は factory/strategy モジュールに置く」と規定。

**A-3. ホスト側オーケストレーション**

- Aerial: `cuphydriver` が 8 スロット分の `SlotMapUl/SlotMapDl` リングを保持し（`aerial/cuPHY-CP/cuphydriver/src/common/context.cpp:103-107`）、UL/DL ワーカースレッドを YAML 指定の CPU コアへピン留め（`aerial/cuPHY-CP/cuphycontroller/config/cuphycontroller_F08.yaml:69-75` の `workers_ul: [2,3]` / `workers_dl: [4,5,6]`）。L2 からは 3 スロット先行で要求が届く（`l2_adapter_config_F08.yaml` の `slot_advance: 3`）。
- OCUDU: 既存の upper PHY executor 上で非同期 CUDA stream に投げ、完了は CUDA event（`kernel_complete_[buffer_index]`、`ocudu/lib/phy/upper/channel_processors/pusch/pusch_demodulator_gpu_impl.h:307`）で追跡。SINR 報告を遅延同期させる `report_deferred_sinr()`（同 `:156`）など、同期点を後ろへ寄せる設計。

**A-4. 設定・パラメータ駆動**

- Aerial: セル構成・MPS SM 割当・ワーカーコア・圧縮等を cuphycontroller YAML で指定。例: `mps_sm_pusch: 108`, `mps_sm_pdsch: 82`, `mps_sm_pdcch: 36`, `mps_sm_prach: 2`（`cuphycontroller_F08.yaml:38-44`、チャネル毎に SM 数を予算化）。
- OCUDU: 全セレクタが `auto/enabled/disabled` の 3 値で統一（`ocudu/README.md:198-256`）。upper-PHY 6 項目（`pusch/srs/pdsch/prach_acceleration_mode`, `pdsch_acceleration_nof_lanes`, `ldpc_decoder_algorithm`）、split-8 lower-PHY 3 項目、OFH 1 項目（`compression_acceleration_mode`）。バリデーション実装は `ocudu/apps/units/flexible_o_du/o_du_low/du_low_config_validator.cpp:85-90`。

### B. CUDA 実装

**B-1. CUDA Graphs**

- Aerial: PUSCH RX は CUDA 12.4+ の **conditional graph node** を用いた 3 段条件分岐グラフ（`aerial/cuPHY/src/cuphy_channels/pusch_rx.hpp:73-74` の `CUgraphConditionalHandle m_conditional_node_C0/C1/C2_handle`、`#if CUDA_VERSION >= 12040`）。チャネル推定はグラフマネージャ（`aerial/cuPHY/src/cuphy/ch_est/ch_est_graph_mgr.cpp:24-38` の `cuGraphAddKernelNode`）。処理モードに `PUSCH_PROC_MODE_FULL_SLOT_GRAPHS` と device graph 起動が存在（`aerial/cuPHY/src/cuphy/cuphy_api.h:112-117,164` 付近）。
- OCUDU: lower-PHY TX/RX で graph 構成キャッシュ（TX 64 / RX 256 構成、`ocudu/lib/phy/cuda/src/low_phy_tx.cu:26`, `low_phy_puxch_rx.cu:27` の `DEVICE_GRAPH_CACHE_LIMIT`）。`OCUDU_LOWPHY_TX/RX_CUDA_GRAPHS` 環境変数でオプトイン。upper-PHY 側は graph 不使用（stream + event ベース）(推測: コード検索で upper 側に cudaGraph API が見つからないことに基づく)。

**B-2. ストリームと SM 資源管理**

- Aerial: セル毎に UL/順序制御/DL の複数 stream（`aerial/cuPHY-CP/cuphydriver/include/cell.hpp`）。さらに **MPS による SM 静的分割**（B-A-4 の `mps_sm_*`）と **green contexts**（`aerial/cuPHY-CP/cuphydriver/src/common/context.cpp:143` の `use_green_contexts`、`mps.cpp` の `CU_DEV_RESOURCE_TYPE_SM`）でチャネル間干渉を制御。
- OCUDU: `cudaStreamCreateWithPriority(..., greatest_priority)` を試行し失敗時は non-blocking にフォールバック（`ocudu/lib/phy/cuda/src/low_phy_puxch_rx.cu:34-48`）。PUSCH 復調器はメイン/スクランブラ/H2D/D2H の 4 stream（`pusch_demodulator_gpu_impl.h:217-305`）。SM 分割機構はなし。

**B-3. カーネル設計**

- Aerial: LDPC は SM 世代別の特化実装群（`ldpc2_reg_index_fp_desc_dyn_sm80/86/90.cu`、`aerial/cuPHY/src/cuphy/CMakeLists.txt:403-408`）。UL パケット順序制御は GDR-pinned フラグで GPU カーネルと NIC を同期させる order kernel（`aerial/cuPHY-CP/cuphydriver/src/uplink/order_entity.cpp:52-74`）。`--use_fast_math` を受信系カーネルに適用（`aerial/cuPHY/src/cuphy/CMakeLists.txt:364-373`）。
- OCUDU: PUSCH は chEst→等化→復調→デスクランブル→rate-dematch→LDPC を GPU 内で連結する E2E resident 設計（`ocudu/lib/phy/cuda/include/pusch_e2e.h`）。PDSCH はスクランブル+変調の fused kernel（`ocudu/lib/phy/cuda/src/pdsch_fused.cu`）。LDPC は layered min-sum で、**正規化係数を Aerial cuPHY の実測値由来と明記**: 「Per-Row Min-Sum Normalization Factors (Aerial SDK style)」「Values derived from Aerial g_min_sum_norm_BG1_Z384[]」「Rate-adaptive normalization tables (from cuPHY reference)」（`ocudu/lib/phy/cuda/src/ldpc_decoder_flexible.cu:49,55,105,649`）。2 codeword 同時処理（pairing）と早期終了も実装（同 `:8-9` コメント）。

**B-4. メモリ管理**

- Aerial: pinned/GDR-pinned バッファ抽象（`newGDRbuf`、`aerial/cuPHY-CP/aerial-fh-driver/app/fh_generator/src/gpudevice.cpp:74-77`）、GDRCopy で NIC→GPU 書き込みをフラッシュ（同 `:48-50`）、メモリフットプリント計測（`aerial/cuPHY-CP/cuphydriver/src/common/context.cpp:94-97`）。
- OCUDU: **iGPU では managed memory、dGPU では pinned へ自動フォールバック**するリソースグリッド（`ocudu/lib/phy/upper/resource_grid_cuda_visible_impl.h:91` の `cudaMallocManaged`、`:596-676` のフォールバック、`cudaDevAttrIntegrated` 判定）。`cudaMemAdvise`/`cudaMemPrefetchAsync`(CUDA13+) のチューニングフック（同 `:521-573`）、`cudaMemPool_t`（`pusch_demodulator_gpu_impl.h:223-224`）、トリプルバッファ（`NUM_BUFFERS=3`、同 `:291`）。

**B-5. ライブラリ依存・精度**

- Aerial: FFT は **cuFFTDx**（mathdx 25.06、`aerial/cuPHY/src/cuphy/CMakeLists.txt:25,386`）。TensorRT(NVINFER) を ML チャネル推定に使用（`ch_est/trtengine_chest.cpp`）。cuBLAS/cuSOLVER/NVSHMEM はリンクなし（cuMAC の SVD も自前カーネル `aerial/cuMAC/src/4T4R/svdPrecoding.cu`）。LLR は FP16（`aerial/cuPHY/src/cuphy_channels/pusch_rx.hpp:37` の `#define LLR_FP16`）。WMMA/MMA（Tensor Core）使用は両者とも検出されず — 混合精度は帯域削減目的(推測)。
- OCUDU: FFT は **vkFFT（MIT、同梱）** で cuFFT を使わない（`ocudu/lib/phy/cuda/CMakeLists.txt:154-171` で `vkFFT.h` 必須、リポジトリ内に cufft 参照ゼロ）。vkFFT はマルチバックエンド（CUDA/HIP/OpenCL/Vulkan）ライブラリであり、マルチベンダ方針（`ocudu/README.md:32-41`）と整合する(推測: 選定理由の明文は無し)。INT8 量子化は両者とも未使用。

**B-6. マルチ GPU / ネットワーク直結**

- Aerial: GPUDirect RDMA サポートチェック（`gpudevice.cpp:34` の `cudaDevAttrGPUDirectRDMASupported`）、DOCA GPUNetIO による GPU 発のパケット TX（`gpu_comm_doca.cu` の `doca_gpu_eth_txq`）。マルチ GPU は `GpuDevice` クラスでデバイス毎管理。
- OCUDU: 単一デバイス前提（`cudaGetDevice` ベース、`ocudu/lib/phy/upper/phy_acceleration_resource_grid_factory.cpp:19-31`）。GPUDirect は不使用で、OFH は GPU→ホスト→NIC 経路（pinned staging 4 slot、`ocudu/lib/phy/cuda/src/ofh_compression.cu:10-25`）。

### C. PHY チャネル処理カバレッジ

**C-1. Aerial のカバレッジ（全チャネル GPU）**

- DL: `PdschTx`（`pdsch_tx.hpp:38`、セルあたり最大 64UE: `aerial/cuPHY/src/cuphy/cuphy.h:96`、セルグループ 64 セル: 同 `:99`）、`PdcchTx`、`SsbTx`（スロットあたり 3 SSB: `cuphy.h:58` 付近）、`CsirsTx`（32 パラメータ: `cuphy.h:57` 付近）、BFW 計算 `BfwTx`（`bfw_tx.hpp:29-132`）。
- UL: `PuschRx`（early-HARQ サブスロット処理: `cuphy_api.h:112-117,273`）、`PucchRx`（F0-F4、`scf_5g_fapi.h:155-160` の enum と `cuphy_api.h:975-976` で確認）、`PrachRx`、`SrsRx`。
- 上限値（`aerial/cuPHY/src/cuphy/cuphy.h` で直接確認）: アンテナ 64（`:53`）、273 PRB（`:69`）、PUSCH 8 layers/UE group（`:72`）、DL 4 layers/TB・セル合計 32 layers（`:1116,1119`）、BBU 32 layers（`:49`）、256QAM まで（`:1104`、`CUPHY_QAM_1024` は存在せず）、最大 TB 159,749+24 byte（`:56`）。
- チャネル推定は MMSE/multi-stage MMSE/RKHS/LS の選択式（`cuphy_api.h:231` の `chEstAlgo`）+ TensorRT ベース ML 推定。LDPC 早期終了（`cuphy_api.h:217`）、FP16（`:218`）。

**C-2. OCUDU のカバレッジ（選択的 GPU 化）**

- GPU 化済み: PUSCH E2E（LS chEst + ZF/MMSE/MMSE-IRC 等化: `ocudu/lib/phy/cuda/include/pusch_e2e.h:26-30`、transform precoding は 1 レイヤ MSG3 相当のみ: 同 `:235-258`）、LDPC enc/dec、CRC、rate matching、scrambling、変調（QPSK〜256QAM: `modulation.h:21-27`）、PDSCH fused TX、SRS 推定（4 port、TA 推定: `srs_estimator.h:46-79`）、PRACH（lower 復調 GPU / upper 検出は CPU 既定: `ocudu/README.md:70-72`。CUDA 検出器自体は `prach_detector_cuda_impl.cpp` に存在）、lower-PHY TX/RX、OFH BFP 8/9/10/12/14/16-bit + 無圧縮（`ofh_compression.cu` の switch 文で全幅確認）。
- 非 GPU（CPU のみ）: PDCCH、PBCH/SSB、PUCCH F0-F4、CSI-RS、UCI エンコード（`ocudu/lib/phy/cuda/src/` に該当カーネルなし、CPU factory のみ: `ocudu/lib/phy/upper/channel_processors/{pdcch,ssb,pucch}/factories.cpp`）。Polar カーネル（`polar.cu`、最大 1024 bit payload: `polar.h:18-22`）は PUSCH 内 UCI 復号にのみ結線（`pusch_demodulator_gpu_impl.cpp:218-287`、UCI codeblock ≤2 等の制約付き）。
- GPU 経路の制約（`ocudu/lib/phy/upper/channel_processors/pusch/demodulator_factories.cpp:152-161` の `supports_accelerated_demod()`）: 1-4 レイヤ、RX port {1,2,4,8}、レイヤ数 ≤ port 数、multi-layer transform precoding 不可。条件外は CPU へ自動フォールバック。
- 本体上限の拡張: CUDA コミットが `MAX_NOF_RX_PORTS` を 4→8、`MAX_NRE_PER_RB` を 156→164 に拡張（`ocudu/include/ocudu/ran/pusch/pusch_constants.h`、`git show 9fd4047` で差分確認）— massive MIMO 方向への布石。

**C-3. 対比のポイント**

- Aerial は制御系チャネル（PDCCH/PBCH/PUCCH）も GPU で処理するため CPU 側 L1 負荷が原理的に小さい。OCUDU は制御系を CPU に残すため、セル数スケール時は CPU 側がボトルネックになり得る(推測)。
- ビームフォーミング/プリコーディング: Aerial は SRS ベース BFW 計算をパイプラインとして持つ（`bfw_tx.cpp`、L2 アダプタの `enable_beam_forming: 1`）。OCUDU の CUDA 範囲にビームフォーミングはない。

### D. 機能分割 & インターフェース

- **FAPI**: Aerial は SCF FAPI v10.04 ベース + ベンダ拡張メッセージ（BFW CVI 要求 0x90/0x91 等、`aerial/cuPHY-CP/scfl2adapter/lib/scf_5g_fapi/scf_5g_fapi.h:35-40,87-160`）。L2-L1 間トランスポートは nvIPC 共有メモリ（`cuphycontroller.yaml` の `transport: shm`）。OCUDU は自前 FAPI 実装（`ocudu/lib/fapi_adaptor/`）を持つが、CUDA アクセラレーションは FAPI より下の upper/lower PHY 内で完全に透過（外部 IF 変更なし）。
- **O-RAN FH**: Aerial は eCPRI v1（`aerial/cuPHY-CP/aerial-fh-driver/include/aerial-fh-driver/oran.hpp:193`）、BFP 9/14-bit 構造体（同 `:339,344`）、CUS v05.00 サブセット。M-plane は FH ドライバ内に記述なし（上位での扱いと推測）。OCUDU は既存 `lib/ofh` の U-plane ビルダ/デコーダに GPU 圧縮をバッチ統合（`ocudu/lib/ofh/serdes/ofh_uplane_message_builder_impl.cpp` +267 行、batched symbol 書き込み: `ofh_uplane_rx_symbol_data_flow_writer.cpp`）。
- **タイミング**: Aerial は PTP 同期状態を FAPI エラーコードで監視（`scf_5g_fapi.h:58-63` の `SCF_ERROR_CODE_PTP_SYNCED` 等）、PTP プロセスの CPU affinity 設定（`cubb_scripts/install/versions.sh:89,126`）。OCUDU の CUDA 変更はタイミング系に手を入れていない。

### E. パフォーマンス / 最適化

- **OCUDU の公開実測値**（`ocudu/README.md:97-110`、DGX Spark GB10、再現スクリプト付き）:
  - PUSCH レイテンシ 100MHz/273PRB/4L/8port/MCS20: CPU 13,122.3µs → GPU 618.9µs（**21.2 倍**）
  - PDSCH p50 同条件 4L/4port: 625.0µs → 186.0µs（**3.36 倍**）
  - OFH BFP 9-bit 圧縮/伸長: **26.7〜72.6 倍**
  - PUSCH 感度: GPU と CPU の差 **-0.1dB**（10% BLER 点） — ビット精度でなく BLER 等価性で検証
  - **注意点として明記**: 20MHz 1 レイヤでは GPU の方が遅い（PUSCH 262.3µs vs 225.8µs、PDSCH 79.9µs vs 29.4µs）— 起動/同期オーバーヘッド未償却
- **Aerial**: リポジトリ内に公表性能数値なし。代わりに GPU 単体性能測定ツール cubb_gpu_test_bench（「特定スロット数にわたり各ワークロードのレイテンシを測定」「TDD パターン F08/F09/F14 のセル容量自動判定」、`aerial/testBenches/README.md:9-12,28,169`）、nsys トレース連携（同 `:195`）。
- **リアルタイム機構**: Aerial はカーネルブートパラメータレベルで規定 — `isolcpus`（DGX Spark で 4-19、GH200 で 4-64: `versions.sh:86,124`）、`nohz_full`/`idle=poll`/`rcu_nocbs`（`aerial/cuPHY/util/cuBB_system_checks/README.md:57-58`）、DPDK スレッドのコア固定（`cuphycontroller_F08.yaml:32`）。OCUDU は `scripts/ocudu_performance`（governor=performance、ネットワークバッファ 33MB 化）と OCUDU 標準の affinity 管理（`ocudu/apps/services/worker_manager/os_sched_affinity_manager.h:11-20`）のみで、専用カーネルや isolcpus の強制はない。
- **トレーシング**: OCUDU は CUDA ヘッダ非依存のランタイム NVTX 連携 `scoped_trace` を新設（`ocudu/include/ocudu/support/tracing/scoped_trace.h:12-63`、`OCUDU_NVTX_TRACE=1` で有効化）。Aerial は NVTX3 + CUPTI を cuphy にリンク（`aerial/cuPHY/src/cuphy/CMakeLists.txt:386`）。

### F. 標準準拠

- 両者とも 3GPP リリースの明示タグはコード内に無い。Aerial は 5GModel が「3GPP 仕様に基づく」TV 生成を行い（`aerial/README.md:19-20`、`aerial/5GModel/nr_matlab/readme.md`: Compliance/TestVector/Performance の 3 テストセット）、PUCCH F2-4・massive MIMO・SRS ビームフォーミング等 Rel-16/17 相当機能を含む(推測)。OCUDU 本体は「3GPP and O-RAN Alliance specifications に準拠」を標榜（`ocudu/README.md:496-500`）。
- numerology: Aerial は µ=0..3（`cuphy_api.h:64`）で FR2 含む。OCUDU CUDA は SCS 15/30/60/120kHz をパラメータとして受ける（`pusch_e2e.h` の `scs_khz`）が、OTA 検証は FR1 (n78) 中心（`ocudu/README.md:178`）(推測: FR2 実機検証の記述なし)。

### G. テスト & 検証

- Aerial: MATLAB 5GModel で生成した HDF5 TV を cuPHY の各チャネル test/example が消費（`aerial/cuPHY/src/cuphy_hdf5/cuphy_hdf5.h`、`TV_PUCCH_F*_gNB_CUPHY_*.h5` 形式: `cuphy_ex_gen_perf_curve_from_file.cpp:275-289`）。E2E は `ru-emulator`（ConnectX-5 100GbE 最適化: `aerial/cuPHY-CP/ru-emulator/README.md`）+ `testMAC`。公開 CI 設定はなし（`.github/workflows` 不在）。
- OCUDU: GPU/CPU パリティテスト（`ldpc_decoder_gpu_cpu_test.cpp`、`pusch_gpu_cpu_result_parity_test.cpp` 等）、BLER 感度スイープ（`pusch_e2e_sensitivity_sweep.cpp`）、E2E パイプライン（`pusch_e2e_pipeline_test.cpp`）、ストレス（`pusch_64qam_stress_test.cpp`）等 25 本の CUDA テストを ctest に統合（`ocudu/README.md:426-465`、DGX Spark で 12+8 本 100% pass のログ付き）。TV は自己生成で 3GPP 公式 TV ではない。`.gitlab-ci.yml` に CUDA 専用ジョブは見当たらない(推測: CI は CPU ビルドのみ)。

### H. ハードウェア依存

- Aerial 実行リファレンス（`aerial/cubb_scripts/install/versions.sh`）: DGX Spark（CUDA arch 121、`:92`）/ Supermicro GH200 480GB（arch 90、`:129`）。NIC は ConnectX-7（install_services.sh コメント）/ BlueField-3（`cuBB_system_checks/README.md:114`）。DOCA 3.2.1 + GDRCopy 2.5.1 必須（`versions.sh:63,78,100,115`）。hugepages 24GB（`:119`）。**FH 経路に NVIDIA NIC + DOCA が事実上必須**。
- OCUDU: `CMAKE_CUDA_ARCHITECTURES` 明示指定で sm_89〜121 をサポート（`ocudu/README.md:134-141`）、未指定なら `native`。**Tegra/Jetson/Orin/Thor/Spark を CMake が自動検出**し（`ocudu/lib/phy/cuda/CMakeLists.txt:27-105`）、iGPU では managed memory 経路を使う第一級サポート。NIC は汎用（OFH は標準ソケット既定、DPDK は `ENABLE_DPDK=OFF` 既定: `ocudu/CMakeLists.txt`）。Split-8 は UHD/ZMQ（`ENABLE_UHD/ENABLE_ZEROMQ` 既定 ON）。

### I. ソフトウェア依存 & エコシステム

- Aerial: CUDA 13.1.1 / GPU driver 590.48.01 / 専用カーネル `6.17.0-1014-nvidia`(DGX Spark)・`6.8.0-1025-nvidia-64k`(GH200) をインストーラが固定（`versions.sh:60,72,74,97,109,111`）。DPDK は DOCA 経由で導入。デプロイは NGC コンテナ + HPCCM レシピ（`aerial/cuPHY-CP/container/README.md`）。
- OCUDU: CUDA toolkit の最小バージョン強制なし（`find_package(CUDAToolkit REQUIRED)` のみ、`ocudu/lib/phy/cuda/CMakeLists.txt:113-116`）。実測環境は CUDA 13.0.88 / driver 580.95.05（`ocudu/README.md:56-57`）。vkFFT は MIT ライセンスで同梱（`ocudu/lib/phy/cuda/third_party/vkfft/LICENSE`）。Docker は汎用 OCUDU 用のみで CUDA プリセットなし（`ocudu/docker/Dockerfile:14-37` に CUDA 層なし）。

### J. ライセンス & 公開性

- Aerial: **Apache License 2.0**（`aerial/LICENSE`, copyright 2025 NVIDIA）。フルソース公開でバイナリ blob は確認されず。ただし「Aerial is not accepting contributions at this time」（`aerial/README.md:71`）で、git 履歴はリリーススカッシュ 5 コミットのみ（`git shortlog`: 著者 `aerial` のみ）— **オープンソースだがオープン開発ではない**。
- OCUDU: **BSD 3-Clause Open MPI variant**（`ocudu/LICENSE`、copyright 2021-2026 Software Radio Systems Limited）。CUDA カーネルの SPDX は `Copyright (C) 2021-2026 DeepSig Inc`（`ocudu/lib/phy/cuda/src/*.cu` ヘッダ）。Linux Foundation ガバナンス + TSC、コントリビューション受け付け（`ocudu/CONTRIBUTING.md`、`ocudu/README.md:509-520`）。本 preview は upstream 統合を TSC と調整中（`ocudu/README.md:467-483`）。
- 注目点: OCUDU の LDPC 正規化テーブルが「Aerial SDK 由来」と明記されている（前掲 B-3）。Aerial の Apache 2.0 化により、こうした実装知見の流用が法的に可能になったことを示す事例(推測: ライセンス上の評価は法務確認が必要)。

### K. 拡張性 / プログラマビリティ

- Aerial:
  - **pyAerial**: cuPHY サブセットの Python API。「ML 研究者向け: モデル検証・ベンチマーク・データセット生成」（`aerial/pyaerial/README.md:1-6`）。neural receiver / LLRNet データセット生成 / dataLake チャネル推定等の Jupyter notebook 9 本以上。TensorRT/Torch 連携（`pyaerial/container/requirements.txt:20-21`）。
  - **data_lake + E3 agent**: FH・PUSCH・チャネル推定データを ClickHouse に収集（`aerial/cuPHY-CP/data_lake/data_lake.cpp:23-37` の `fhInfo/puschInfo/hestInfo`）、E3 インターフェース実装 `e3_agent.cpp` が dApp 連携の受け口。**研究用 AI-RAN ループ（データ収集→学習→推論差し込み）がリポジトリ内で完結**。
  - ML 推論の本番組込みは TensorRT チャネル推定（`trtengine_chest.cpp`）が既に存在。
  - 一方、cuPHY 自体への独自カーネル追加は API が巨大で channel クラスと密結合のため改造コストが高い(推測)。
- OCUDU:
  - **マルチベンダ前提の抽象**: `resident_softbit_buffer` は `void* execution_context` / `void* completion_token` の opaque token 設計で CUDA 型を一切漏らさない（`ocudu/include/ocudu/phy/upper/acceleration/phy_acceleration.h:22-40`）。「CUDA は最初のバックエンドであり、複数ベンダ・複数アーキテクチャを支える枠組みが意図」（`ocudu/README.md:32-41`）。
  - 新規アクセラレータ追加は factory/selector への登録で済む構造（例: `srs_estimator_factory.cpp`、`demodulator_factories.cpp` の layer-select wrapper）。
  - dApp/xApp・AI/ML 連携は CUDA 範囲には存在しない（`lib/e2` は本体機能で CUDA 非連動）。

### L. ドキュメント & 開発者体験

- Aerial: NVIDIA Docs Hub（外部）+ コンポーネント README + `make help` 付きインストーラ。コンテナで環境再現性は高いが、専用カーネル・NIC 要件のためオンボーディングの物理的ハードルが高い(推測)。
- OCUDU: README 527 行（ビルド→設定→ベンチ→検証まで再現コマンド付き）、`phy_acceleration.dox` 162 行の設計原則文書、`lib/phy/cuda/README.md` のスタンドアロン開発手順。**カーネル単体を `cmake -S lib/phy/cuda` で独立ビルド可能**（`ocudu/lib/phy/cuda/README.md:33-48`）で、カーネル開発の敷居は低い。

### M. 成熟度 & コミュニティ

- Aerial: タグ 25.3.0/25.3.1/25.3.2/26.1.0/26.1.1 のリリースケイデンス（約四半期 + パッチ）。サポートレベル「Maintained」（`aerial/README.md:78`）。商用採用事例の記述はリポジトリ内になし（NVIDIA の対外発表ベース）。開発はクローズド（履歴 5 コミット、全て `aerial` アカウント）。
- OCUDU: 本体は多数コントリビュータのオープン開発（直近 50 コミットに 10 名以上: Eckermann, Maroszek, Paisana 他）。CUDA 部分は DeepSig 2 名による preview で、「統合後に本リポジトリは削除/アーカイブされ得る」（`ocudu/README.md:14-18`）。直近コミット 2026-06-08 とアクティブ。

---

## 5. OCUDU 視点の示唆（Aerial 設計からの取り込み候補とギャップ)

1. **制御系チャネルの GPU 化余地**: Aerial は PDCCH/SSB/PUCCH/CSI-RS も GPU 化し CPU 負荷を最小化している。OCUDU は polar カーネル（`polar.cu`）を既に持つため、PDCCH/PBCH エンコードの GPU 結線は比較的近距離のギャップ。PUCCH F2-4 受信（polar 復号利用）も同様。
2. **CUDA Graphs の upper-PHY 適用**: Aerial の conditional graph（早期終了・データ依存分岐をグラフ内で処理、`pusch_rx.hpp:73-74`）は、OCUDU の slot 単位 kernel launch オーバーヘッド（20MHz で GPU が CPU に負ける要因）への直接的な対策になる。OCUDU は lower-PHY に graph キャッシュの足場を既に持つ。
3. **SM 資源分割（MPS/green contexts）**: マルチセル・マルチチャネル同時実行時の干渉制御として Aerial の `mps_sm_*` 予算化（`cuphycontroller_F08.yaml:38-44`）は有効。OCUDU の `pdsch_acceleration_nof_lanes` は萌芽的な同等概念であり、green contexts への発展余地がある。
4. **early-HARQ / サブスロット処理**: Aerial の 4 シンボル時点 HARQ 判定（`cuphy_api.h:112-117`）は低レイテンシ要件（URLLC）で重要。OCUDU の resident 設計はシンボル単位処理への拡張に親和的(推測)。
5. **FH 直結（GPUDirect/DOCA）**: OCUDU の OFH GPU 圧縮はホスト経由のため、スケール時は PCIe/メモリ帯域が制約になる。Aerial 型の NIC→GPU 直結は効果が大きいが、NVIDIA NIC + DOCA への依存が生じ、OCUDU のベンダ中立方針とトレードオフ。導入するなら ethernet 層の backend 抽象として隔離するのが OCUDU 流。
6. **テストベクタ戦略**: Aerial の MATLAB 5GModel→HDF5 TV のような仕様準拠リファレンスを OCUDU は持たない（GPU/CPU パリティのみ）。3GPP 38.141 系コンフォーマンスへの接続が今後の品質保証ギャップ。
7. **AI/ML フック**: Aerial の data_lake/E3/pyAerial に相当するものが OCUDU には無い。DeepSig の背景を踏まえると将来的な追加が予想されるが(推測)、現状は「従来型 PHY の高速化」に限定。
8. **逆に OCUDU が優位な点（Aerial から学ぶ必要がない点）**: CPU フォールバックと `auto` モードによる段階的導入、iGPU/エッジ対応、vkFFT による FFT のベンダ非依存、opaque token のバックエンド抽象、公開実測値と再現スクリプト。これらは Aerial に無い OCUDU の差別化要素であり、upstream 統合時にも維持すべき設計。

---

## 6. 未解決事項・要確認リスト

1. **Aerial の実性能数値**: リポジトリに公表値が無いため、セル容量・スループット・レイテンシは NVIDIA 公式ドキュメント（docs.nvidia.com/aerial）または実測での確認が必要。
2. **Aerial の M-plane / nFAPI**: FH ドライバに M-plane 実装は見当たらず、nFAPI への言及も未発見。上位統合（例: OAM、`cuphyoam`）側の確認が必要。
3. **OCUDU CUDA の OTA 実績範囲**: README は B200(UHD) n78 20MHz の設定例と DGX Spark 検証ログのみ。OFH 構成（実 O-RU）での GPU 圧縮の実機検証状況は不明。
4. **OCUDU の PUSCH GPU 経路の上限**: GPU 路は 4 レイヤ/8 port までで、`MAX_NOF_RX_PORTS=8` への拡張はあるが 64TRX 級 massive MIMO への道筋は本 preview からは読めない。
5. **3GPP リリース対応の正確な範囲**: 両者ともリリース番号の明示が無く、機能からの推定に留まる。提案資料に使う場合は各社のリリースノート/仕様書での裏取りを推奨。
6. **Aerial のコード生成系**: cuPHY の一部ヘッダが巨大（25 万行超の `.h`）で、自動生成コードの可能性がある。生成元（社内ツール）は非公開のため改変容易性の評価は限定的。
7. **ライセンス上の相互利用**: OCUDU の LDPC テーブルが Aerial 由来である点（`ldpc_decoder_flexible.cu:55`）は Apache 2.0 → BSD への取り込みとして一般に可能だが、NOTICE 義務等の精査は法務確認が必要。
8. **shallow clone の制約**: 本調査は `--depth 50` で実施。全履歴ベースのコミット統計（総コミット数・全コントリビュータ数）は完全ではない。

---

*本レポートは両リポジトリのソースコード静的調査に基づく。実行・実測は行っていない。*
