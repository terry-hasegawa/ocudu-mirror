# SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
# SPDX-License-Identifier: BSD-3-Clause-Open-MPI

"""Unit tests for stage 4 (aggregate)."""

from __future__ import annotations

from ofh_pcap_analyzer.models import AnalyzedFrame, ParsedFrame, Plane
from ofh_pcap_analyzer.stage_aggregate import Aggregator, flows_to_dataframe


def _af(plane, eaxc, *, crc_present=False, crc_ok=None, ta_us=None, ta_anomaly=False, malformed=False):
    pf = ParsedFrame("t", 0, 1.0, 0, 0, plane=plane, malformed=malformed)
    pf.eaxc_id = eaxc
    return AnalyzedFrame(
        frame=pf,
        crc_present=crc_present,
        crc_ok=crc_ok,
        ta_us=ta_us,
        ta_anomaly=ta_anomaly,
    )


def test_aggregator_counts_and_rates():
    agg = Aggregator()
    agg.update(_af(Plane.C_PLANE, 1))
    agg.update(_af(Plane.U_PLANE, 1, crc_present=True, crc_ok=True, ta_us=100.0))
    agg.update(_af(Plane.U_PLANE, 1, crc_present=True, crc_ok=False, ta_us=700.0, ta_anomaly=True))
    agg.update(_af(Plane.U_PLANE, 2, malformed=True))

    report = agg.build_report(files_total=2, files_skipped=1)
    assert report.frames_total == 4
    assert report.c_plane_frames == 1
    assert report.u_plane_frames == 3
    assert report.frames_malformed == 1
    assert report.crc_checked == 2
    assert report.crc_errors == 1
    assert abs(report.crc_error_rate - 0.5) < 1e-9
    assert report.ta_anomalies == 1
    assert report.ta_samples == 2
    assert report.files_skipped == 1


def test_flow_kpi_breakdown():
    agg = Aggregator()
    for _ in range(4):
        agg.update(_af(Plane.U_PLANE, 5, crc_present=True, crc_ok=True, ta_us=50.0))
    agg.update(_af(Plane.U_PLANE, 5, crc_present=True, crc_ok=False, ta_us=60.0))
    report = agg.build_report()

    flow = next(f for f in report.flows if f.eaxc_id == 5 and f.plane == "U")
    assert flow.frames == 5
    assert flow.crc_checked == 5
    assert flow.crc_errors == 1
    assert abs(flow.crc_error_rate - 0.2) < 1e-9
    assert flow.ta_count == 5
    assert flow.ta_min_us == 50.0
    assert flow.ta_max_us == 60.0


def test_flows_to_dataframe_columns():
    agg = Aggregator()
    agg.update(_af(Plane.U_PLANE, 1, ta_us=10.0))
    df = flows_to_dataframe(agg.build_report())
    assert "crc_error_rate" in df.columns
    assert "ta_mean_us" in df.columns
    assert len(df) == 1


def test_empty_report_no_division_errors():
    report = Aggregator().build_report()
    assert report.crc_error_rate == 0.0
    assert report.ta_mean_us is None
