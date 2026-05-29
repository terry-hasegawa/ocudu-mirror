# SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
# SPDX-License-Identifier: BSD-3-Clause-Open-MPI

"""Stage 5 - output: write frame JSON, KPI CSV and Prometheus metrics.

The frame JSON is written incrementally (streamed array) so the full set of
frame records never needs to live in memory at once. CSV and Prometheus outputs
operate on the compact KPI report produced by the aggregate stage.
"""

from __future__ import annotations

import json
from typing import TextIO

from .logging_config import get_logger
from .models import AnalyzedFrame, KpiReport
from .stage_aggregate import flows_to_dataframe

_log = get_logger("output")


class FrameJsonWriter:
    """Incrementally writes analyzed frames as a JSON array.

    Usage::

        with FrameJsonWriter(path) as w:
            for af in frames:
                w.write(af)
    """

    def __init__(self, path: str) -> None:
        self._path = path
        self._fh: TextIO | None = None
        self._count = 0

    def __enter__(self) -> "FrameJsonWriter":
        self._fh = open(self._path, "w", encoding="utf-8")
        self._fh.write("[")
        return self

    def write(self, frame: AnalyzedFrame) -> None:
        assert self._fh is not None
        if self._count:
            self._fh.write(",")
        self._fh.write("\n  ")
        json.dump(frame.to_record(), self._fh, ensure_ascii=False, default=str)
        self._count += 1

    def __exit__(self, *exc) -> None:
        if self._fh is not None:
            self._fh.write("\n]\n" if self._count else "]\n")
            self._fh.close()
            _log.info(
                "wrote frame JSON",
                extra={"extra_fields": {"file": self._path, "frames": self._count}},
            )


def write_kpi_csv(report: KpiReport, path: str) -> None:
    """Writes the per-flow KPI summary as CSV using pandas."""
    df = flows_to_dataframe(report)
    df.to_csv(path, index=False)
    _log.info(
        "wrote KPI CSV",
        extra={"extra_fields": {"file": path, "rows": len(df)}},
    )


def _metric(lines: list[str], name: str, help_text: str, mtype: str) -> None:
    lines.append(f"# HELP {name} {help_text}")
    lines.append(f"# TYPE {name} {mtype}")


def render_prometheus(report: KpiReport) -> str:
    """Renders the KPI report in the Prometheus text exposition format."""
    lines: list[str] = []

    _metric(lines, "ofh_frames_total", "Total fronthaul frames processed.", "counter")
    lines.append(f"ofh_frames_total {report.frames_total}")

    _metric(lines, "ofh_frames_malformed_total", "Malformed frames.", "counter")
    lines.append(f"ofh_frames_malformed_total {report.frames_malformed}")

    _metric(lines, "ofh_plane_frames_total", "Frames per plane.", "counter")
    lines.append(f'ofh_plane_frames_total{{plane="C"}} {report.c_plane_frames}')
    lines.append(f'ofh_plane_frames_total{{plane="U"}} {report.u_plane_frames}')

    _metric(lines, "ofh_crc_checked_total", "Frames with an FCS checked.", "counter")
    lines.append(f"ofh_crc_checked_total {report.crc_checked}")

    _metric(lines, "ofh_crc_errors_total", "Frames failing FCS verification.", "counter")
    lines.append(f"ofh_crc_errors_total {report.crc_errors}")

    _metric(lines, "ofh_crc_error_rate", "CRC error rate (errors/checked).", "gauge")
    lines.append(f"ofh_crc_error_rate {report.crc_error_rate:.9g}")

    _metric(lines, "ofh_ta_anomalies_total", "Timing-advance anomalies detected.", "counter")
    lines.append(f"ofh_ta_anomalies_total {report.ta_anomalies}")

    _metric(lines, "ofh_ta_us", "Timing-advance distribution (microseconds).", "gauge")
    for stat, value in (
        ("mean", report.ta_mean_us),
        ("std", report.ta_std_us),
        ("p50", report.ta_p50_us),
        ("p99", report.ta_p99_us),
    ):
        if value is not None:
            lines.append(f'ofh_ta_us{{stat="{stat}"}} {value:.9g}')

    # Per-flow gauges.
    _metric(lines, "ofh_flow_crc_error_rate", "Per-flow CRC error rate.", "gauge")
    for flow in report.flows:
        lines.append(
            f'ofh_flow_crc_error_rate{{eaxc="{flow.eaxc_id}",plane="{flow.plane}"}} '
            f"{flow.crc_error_rate:.9g}"
        )

    _metric(lines, "ofh_flow_ta_mean_us", "Per-flow mean TA (microseconds).", "gauge")
    for flow in report.flows:
        if flow.ta_mean_us is not None:
            lines.append(
                f'ofh_flow_ta_mean_us{{eaxc="{flow.eaxc_id}",plane="{flow.plane}"}} '
                f"{flow.ta_mean_us:.9g}"
            )

    return "\n".join(lines) + "\n"


def write_prometheus(report: KpiReport, path: str) -> None:
    """Writes the Prometheus metrics file."""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render_prometheus(report))
    _log.info("wrote Prometheus metrics", extra={"extra_fields": {"file": path}})


def write_kpi_json(report: KpiReport, path: str) -> None:
    """Writes the KPI summary as a JSON object (companion to the CSV)."""
    from dataclasses import asdict

    payload = asdict(report)
    payload["crc_error_rate"] = report.crc_error_rate
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, default=str)
    _log.info("wrote KPI JSON", extra={"extra_fields": {"file": path}})
