# SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
# SPDX-License-Identifier: BSD-3-Clause-Open-MPI

"""Pipeline orchestration: wires the five stages together.

The single pass over the analyzed-frame stream both writes the per-frame JSON
and feeds the KPI aggregator, so frames are never materialised as a list.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from .logging_config import get_logger
from .models import KpiReport
from .stage_aggregate import Aggregator
from .stage_analyze import Analyzer, AnalyzeConfig
from .stage_input import InputStats, discover_pcap_files, stream_packets
from .stage_output import (
    FrameJsonWriter,
    write_kpi_csv,
    write_kpi_json,
    write_prometheus,
)
from .stage_parse import parse_stream

_log = get_logger("pipeline")


@dataclass
class PipelineConfig:
    """End-to-end pipeline configuration."""

    input_dir: str
    output_dir: str
    has_fcs: bool = False
    decode_iq: bool = True
    ta_min_us: float = 0.0
    ta_max_us: float = 500.0
    frames_json_name: str = "frames.json"
    kpi_csv_name: str = "kpi_summary.csv"
    kpi_json_name: str = "kpi_summary.json"
    prometheus_name: str = "metrics.prom"


def run_pipeline(config: PipelineConfig) -> KpiReport:
    """Runs the full input -> parse -> analyze -> aggregate -> output pipeline."""
    os.makedirs(config.output_dir, exist_ok=True)

    files = discover_pcap_files(config.input_dir)
    input_stats = InputStats()
    aggregator = Aggregator()
    analyzer = Analyzer(
        AnalyzeConfig(
            ta_min_us=config.ta_min_us,
            ta_max_us=config.ta_max_us,
            decode_iq=config.decode_iq,
        )
    )

    raw = stream_packets(files, input_stats)
    parsed = parse_stream(raw, has_fcs=config.has_fcs)
    analyzed = analyzer.analyze_stream(parsed)

    frames_path = os.path.join(config.output_dir, config.frames_json_name)
    _log.info("pipeline start", extra={"extra_fields": {"input": config.input_dir}})

    with FrameJsonWriter(frames_path) as writer:
        for af in analyzed:
            writer.write(af)
            aggregator.update(af)

    report = aggregator.build_report(
        files_total=input_stats.files_total,
        files_skipped=input_stats.files_skipped,
    )

    write_kpi_csv(report, os.path.join(config.output_dir, config.kpi_csv_name))
    write_kpi_json(report, os.path.join(config.output_dir, config.kpi_json_name))
    write_prometheus(report, os.path.join(config.output_dir, config.prometheus_name))

    _log.info(
        "pipeline complete",
        extra={
            "extra_fields": {
                "files_total": report.files_total,
                "files_skipped": report.files_skipped,
                "frames": report.frames_total,
            }
        },
    )
    return report
