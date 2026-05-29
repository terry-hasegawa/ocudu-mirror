# SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
# SPDX-License-Identifier: BSD-3-Clause-Open-MPI

"""Unit tests for stage 5 (output)."""

from __future__ import annotations

import json

import pandas as pd

from ofh_pcap_analyzer.models import AnalyzedFrame, KpiReport, ParsedFrame, Plane
from ofh_pcap_analyzer.stage_aggregate import Aggregator
from ofh_pcap_analyzer.stage_output import (
    FrameJsonWriter,
    render_prometheus,
    write_kpi_csv,
    write_kpi_json,
    write_prometheus,
)


def _report():
    agg = Aggregator()
    pf = ParsedFrame("t", 0, 1.0, 0, 0, plane=Plane.U_PLANE)
    pf.eaxc_id = 1
    agg.update(AnalyzedFrame(frame=pf, crc_present=True, crc_ok=False, ta_us=120.0))
    return agg.build_report(files_total=1)


def test_frame_json_writer_streams_valid_json(tmp_path):
    path = tmp_path / "frames.json"
    pf = ParsedFrame("t", 0, 1.0, 10, 10, plane=Plane.U_PLANE)
    pf.eaxc_id = 7
    with FrameJsonWriter(str(path)) as w:
        w.write(AnalyzedFrame(frame=pf, crc_present=True, crc_ok=True))
        w.write(AnalyzedFrame(frame=pf))
    data = json.loads(path.read_text())
    assert isinstance(data, list) and len(data) == 2
    assert data[0]["plane"] == "U"
    assert data[0]["eaxc_id"] == 7
    assert "raw" not in data[0] and "payload" not in data[0]


def test_frame_json_writer_empty(tmp_path):
    path = tmp_path / "empty.json"
    with FrameJsonWriter(str(path)):
        pass
    assert json.loads(path.read_text()) == []


def test_write_kpi_csv(tmp_path):
    path = tmp_path / "kpi.csv"
    write_kpi_csv(_report(), str(path))
    df = pd.read_csv(path)
    assert "crc_error_rate" in df.columns
    assert len(df) == 1


def test_write_kpi_json(tmp_path):
    path = tmp_path / "kpi.json"
    write_kpi_json(_report(), str(path))
    obj = json.loads(path.read_text())
    assert obj["frames_total"] == 1
    assert "crc_error_rate" in obj


def test_render_prometheus_format():
    text = render_prometheus(_report())
    assert "# HELP ofh_frames_total" in text
    assert "# TYPE ofh_crc_error_rate gauge" in text
    assert "ofh_frames_total 1" in text
    assert 'ofh_plane_frames_total{plane="U"} 1' in text
    # Every non-comment, non-empty line must be "name value".
    for line in text.splitlines():
        if line and not line.startswith("#"):
            assert len(line.rsplit(" ", 1)) == 2


def test_write_prometheus_file(tmp_path):
    path = tmp_path / "metrics.prom"
    write_prometheus(_report(), str(path))
    assert "ofh_crc_errors_total 1" in path.read_text()
