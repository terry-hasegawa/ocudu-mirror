# SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
# SPDX-License-Identifier: BSD-3-Clause-Open-MPI

"""End-to-end test for the full pipeline against generated sample data."""

from __future__ import annotations

import json
import os

import pandas as pd

from ofh_pcap_analyzer.pipeline import PipelineConfig, run_pipeline


def test_pipeline_end_to_end(sample_dir, tmp_path):
    directory, expected = sample_dir
    out = tmp_path / "out"

    report = run_pipeline(
        PipelineConfig(
            input_dir=directory,
            output_dir=str(out),
            has_fcs=True,
            ta_max_us=500.0,
        )
    )

    # Counts match the generator's ground truth.
    assert report.files_total == expected["files_total"]
    assert report.files_skipped == expected["files_corrupt"]
    assert report.c_plane_frames == expected["c_plane"]
    assert report.u_plane_frames == expected["u_plane"]
    assert report.crc_errors == expected["crc_errors"]
    assert report.ta_anomalies == expected["ta_anomalies"]

    # All three report artifacts exist.
    frames_json = out / "frames.json"
    kpi_csv = out / "kpi_summary.csv"
    metrics = out / "metrics.prom"
    assert frames_json.exists() and kpi_csv.exists() and metrics.exists()

    # Frame JSON is valid and has BFP-decoded U-Plane sections.
    frames = json.loads(frames_json.read_text())
    assert len(frames) == report.frames_total
    u_with_iq = [
        f for f in frames if f["plane"] == "U" and f["sections"]
    ]
    assert u_with_iq
    assert u_with_iq[0]["sections"][0]["iq_width"] == 9

    # CSV parses and contains per-flow rows.
    df = pd.read_csv(kpi_csv)
    assert not df.empty
    assert set(df["plane"]) <= {"C", "U"}

    # Prometheus file has the expected metric.
    assert "ofh_crc_errors_total" in metrics.read_text()


def test_pipeline_without_fcs_skips_crc(sample_dir, tmp_path):
    directory, _ = sample_dir
    out = tmp_path / "out2"
    report = run_pipeline(
        PipelineConfig(input_dir=directory, output_dir=str(out), has_fcs=False)
    )
    # Without FCS, no CRC checks are performed.
    assert report.crc_checked == 0
    assert report.crc_errors == 0
    assert os.path.exists(out / "frames.json")
