# O-RAN Fronthaul PCAP Analyzer

A streaming Python pipeline that extracts C-Plane/U-Plane frames from O-RAN
fronthaul captures (eCPRI over Ethernet), detects timing (TA) anomalies and CRC
(FCS) errors, decodes BFP-compressed IQ data and emits KPI reports.

The wire-format parsing mirrors the OCUDU C++ stack (`lib/ofh`): eCPRI common
header, O-RAN U/C-Plane radio headers and the dynamic compression header are
decoded exactly as the RU/DU produce them.

## Requirements

* Python 3.11+
* `scapy`, `pandas` (see `requirements.txt`)

```bash
pip install -r requirements.txt
```

## Pipeline stages

Each stage is an independent, unit-tested module:

| # | Stage | Module | Responsibility |
|---|-------|--------|----------------|
| 1 | Input | `stage_input.py` | Discover + validate PCAPs, stream packets, skip corrupt files |
| 2 | Parse | `stage_parse.py` | Ethernet/VLAN/eCPRI dissection, C/U-Plane classification |
| 3 | Analyze | `stage_analyze.py` | CRC verification, TA anomaly detection, BFP9 IQ decode |
| 4 | Aggregate | `stage_aggregate.py` | KPI computation (error rates, TA distribution) |
| 5 | Output | `stage_output.py` | JSON / CSV / Prometheus writers |

`pipeline.py` wires the stages together in a single streaming pass; `models.py`
holds the dataclasses exchanged between stages, and `oran_format.py` holds the
wire-format constants and BFP bit codecs.

### Memory strategy

Packets are streamed lazily via scapy's `RawPcapReader`. The parse and analyze
stages are generators, the per-frame JSON is written incrementally, and the
aggregate stage keeps only compact per-flow counters plus a capped reservoir of
TA samples. Captures of several hundred MB never need to be fully buffered.

### Error handling

| Stage | Caught | Recovery |
|-------|--------|----------|
| Input | I/O errors, bad magic, truncated capture | Skip file / truncate stream, log a warning, keep going |
| Parse | short frames, unknown ethertype/msg-type | Flag frame `malformed` with `parse_error`, continue |
| Analyze | truncated/oversized IQ, bad width | Skip section, record `analyze_error`, continue |
| Aggregate | empty inputs | Zero/`None` guards (no division by zero) |
| Output | write I/O | Propagated (fatal) |

## Usage

```bash
# Generate a synthetic sample capture set (incl. CRC errors + TA anomalies).
python tools/make_sample_pcap.py -o ./sample_captures

# Run the analyzer.
python -m ofh_pcap_analyzer -i ./sample_captures -o ./reports --has-fcs
```

Outputs written to the report directory:

* `frames.json`   - per-frame statistics (plane, eAxC, slot/symbol, CRC, TA, IQ sections)
* `kpi_summary.csv` / `kpi_summary.json` - per-flow KPIs (CRC error rate, TA spread, ...)
* `metrics.prom`  - Prometheus text-exposition metrics

### CLI options

| Option | Description |
|--------|-------------|
| `-i, --input` | Directory containing `.pcap` files |
| `-o, --output` | Directory for the reports |
| `--has-fcs` | Captures include the trailing Ethernet FCS (enables CRC checking) |
| `--no-iq` | Skip BFP/IQ decoding (structural + timing analysis only) |
| `--ta-min-us` / `--ta-max-us` | Expected TA window; frames outside it are anomalies |
| `--log-level` / `--log-text` | Logging verbosity / human-readable logs |

## Timing-advance (TA) model

The analyzer correlates each U-Plane (IQ data) frame with the most recent
C-Plane (control) message for the same flow/slot (eAxC + frame + subframe +
slot) and reports `TA = arrival(U) - arrival(C)` in microseconds. Frames whose
TA falls outside `[ta_min_us, ta_max_us]` are flagged as anomalies, and the KPI
report includes mean/std/p50/p99 of the TA distribution.

## Tests

```bash
python -m pytest
```

Each stage has its own `tests/test_stage_*.py`, plus `test_pipeline.py` runs the
full pipeline against generated sample data and asserts on the known ground
truth (frame counts, injected CRC errors and TA anomalies).
