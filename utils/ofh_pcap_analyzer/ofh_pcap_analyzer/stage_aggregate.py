# SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
# SPDX-License-Identifier: BSD-3-Clause-Open-MPI

"""Stage 4 - aggregate: compute KPIs from the stream of analyzed frames.

To keep memory bounded for large captures the aggregator never stores every
frame. Instead it keeps:
* per-flow running counters (count, errors, TA sum / sum-of-squares / min / max);
* a capped reservoir of TA samples for percentile estimation.

The final KPI tables are assembled with pandas from these compact summaries.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from .logging_config import get_logger
from .models import AnalyzedFrame, FlowKpi, KpiReport, Plane

_log = get_logger("aggregate")

_RESERVOIR_CAP = 100_000  # Upper bound on retained TA samples.


@dataclass
class _FlowAcc:
    eaxc_id: int
    plane: str
    frames: int = 0
    malformed: int = 0
    crc_checked: int = 0
    crc_errors: int = 0
    ta_count: int = 0
    ta_sum: float = 0.0
    ta_sumsq: float = 0.0
    ta_min: float = math.inf
    ta_max: float = -math.inf
    ta_anomalies: int = 0


@dataclass
class Aggregator:
    """Accumulates KPI statistics from a stream of analyzed frames."""

    flows: dict[tuple, _FlowAcc] = field(default_factory=dict)
    frames_total: int = 0
    frames_malformed: int = 0
    c_plane_frames: int = 0
    u_plane_frames: int = 0
    crc_checked: int = 0
    crc_errors: int = 0
    ta_anomalies: int = 0
    _ta_reservoir: list[float] = field(default_factory=list)
    _ta_seen: int = 0
    _rng: random.Random = field(default_factory=lambda: random.Random(0))

    def update(self, af: AnalyzedFrame) -> None:
        f = af.frame
        self.frames_total += 1
        if f.malformed:
            self.frames_malformed += 1
        if f.plane is Plane.C_PLANE:
            self.c_plane_frames += 1
        elif f.plane is Plane.U_PLANE:
            self.u_plane_frames += 1

        if af.crc_present:
            self.crc_checked += 1
            if af.crc_ok is False:
                self.crc_errors += 1

        # Per-flow accounting only makes sense for classified flows.
        if f.eaxc_id is not None and f.plane in (Plane.C_PLANE, Plane.U_PLANE):
            key = (f.eaxc_id, f.plane.value)
            acc = self.flows.get(key)
            if acc is None:
                acc = _FlowAcc(eaxc_id=f.eaxc_id, plane=f.plane.value)
                self.flows[key] = acc
            acc.frames += 1
            if f.malformed:
                acc.malformed += 1
            if af.crc_present:
                acc.crc_checked += 1
                if af.crc_ok is False:
                    acc.crc_errors += 1
            if af.ta_us is not None:
                acc.ta_count += 1
                acc.ta_sum += af.ta_us
                acc.ta_sumsq += af.ta_us * af.ta_us
                acc.ta_min = min(acc.ta_min, af.ta_us)
                acc.ta_max = max(acc.ta_max, af.ta_us)
                if af.ta_anomaly:
                    acc.ta_anomalies += 1
                self._reservoir_add(af.ta_us)

        if af.ta_anomaly:
            self.ta_anomalies += 1

    def _reservoir_add(self, value: float) -> None:
        self._ta_seen += 1
        if len(self._ta_reservoir) < _RESERVOIR_CAP:
            self._ta_reservoir.append(value)
        else:
            j = self._rng.randint(0, self._ta_seen - 1)
            if j < _RESERVOIR_CAP:
                self._ta_reservoir[j] = value

    @staticmethod
    def _mean_std(acc: _FlowAcc) -> tuple[Optional[float], Optional[float]]:
        if acc.ta_count == 0:
            return (None, None)
        mean = acc.ta_sum / acc.ta_count
        var = max(acc.ta_sumsq / acc.ta_count - mean * mean, 0.0)
        return (mean, math.sqrt(var))

    def build_report(
        self, *, files_total: int = 0, files_skipped: int = 0
    ) -> KpiReport:
        """Assembles the final :class:`KpiReport` using pandas for percentiles."""
        report = KpiReport(
            files_total=files_total,
            files_skipped=files_skipped,
            frames_total=self.frames_total,
            frames_malformed=self.frames_malformed,
            c_plane_frames=self.c_plane_frames,
            u_plane_frames=self.u_plane_frames,
            crc_checked=self.crc_checked,
            crc_errors=self.crc_errors,
            ta_anomalies=self.ta_anomalies,
            ta_samples=self._ta_seen,
        )

        if self._ta_reservoir:
            series = pd.Series(self._ta_reservoir, dtype="float64")
            report.ta_mean_us = float(series.mean())
            report.ta_std_us = float(series.std(ddof=0))
            report.ta_p50_us = float(series.quantile(0.50))
            report.ta_p99_us = float(series.quantile(0.99))

        for acc in sorted(self.flows.values(), key=lambda a: (a.plane, a.eaxc_id)):
            mean, std = self._mean_std(acc)
            report.flows.append(
                FlowKpi(
                    eaxc_id=acc.eaxc_id,
                    plane=acc.plane,
                    frames=acc.frames,
                    malformed=acc.malformed,
                    crc_checked=acc.crc_checked,
                    crc_errors=acc.crc_errors,
                    ta_count=acc.ta_count,
                    ta_mean_us=mean,
                    ta_std_us=std,
                    ta_min_us=(acc.ta_min if acc.ta_count else None),
                    ta_max_us=(acc.ta_max if acc.ta_count else None),
                    ta_anomalies=acc.ta_anomalies,
                )
            )

        _log.info(
            "aggregation complete",
            extra={
                "extra_fields": {
                    "frames": report.frames_total,
                    "flows": len(report.flows),
                    "crc_error_rate": round(report.crc_error_rate, 6),
                    "ta_anomalies": report.ta_anomalies,
                }
            },
        )
        return report


def flows_to_dataframe(report: KpiReport) -> pd.DataFrame:
    """Builds a per-flow KPI DataFrame (used by the CSV output stage)."""
    rows = []
    for flow in report.flows:
        rows.append(
            {
                "eaxc_id": flow.eaxc_id,
                "plane": flow.plane,
                "frames": flow.frames,
                "malformed": flow.malformed,
                "malformed_rate": flow.malformed_rate,
                "crc_checked": flow.crc_checked,
                "crc_errors": flow.crc_errors,
                "crc_error_rate": flow.crc_error_rate,
                "ta_count": flow.ta_count,
                "ta_mean_us": flow.ta_mean_us,
                "ta_std_us": flow.ta_std_us,
                "ta_min_us": flow.ta_min_us,
                "ta_max_us": flow.ta_max_us,
                "ta_anomalies": flow.ta_anomalies,
            }
        )
    columns = [
        "eaxc_id", "plane", "frames", "malformed", "malformed_rate",
        "crc_checked", "crc_errors", "crc_error_rate", "ta_count",
        "ta_mean_us", "ta_std_us", "ta_min_us", "ta_max_us", "ta_anomalies",
    ]
    return pd.DataFrame(rows, columns=columns)
