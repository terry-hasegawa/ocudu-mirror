# SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
# SPDX-License-Identifier: BSD-3-Clause-Open-MPI

"""Unit tests for stage 1 (input)."""

from __future__ import annotations

import os

import pytest

from ofh_pcap_analyzer.stage_input import (
    InputStats,
    discover_pcap_files,
    stream_packets,
    validate_pcap,
)


def test_discover_lists_only_pcaps(sample_dir):
    directory, _ = sample_dir
    files = discover_pcap_files(directory)
    assert files
    assert all(f.endswith(".pcap") for f in files)


def test_discover_non_directory(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("hi")
    with pytest.raises(NotADirectoryError):
        discover_pcap_files(str(f))


def test_validate_rejects_corrupt(sample_dir):
    directory, _ = sample_dir
    corrupt = os.path.join(directory, "fronthaul_corrupt.pcap")
    assert validate_pcap(corrupt) is False


def test_validate_rejects_missing(tmp_path):
    assert validate_pcap(str(tmp_path / "nope.pcap")) is False


def test_stream_skips_corrupt_and_counts(sample_dir):
    directory, expected = sample_dir
    files = discover_pcap_files(directory)
    stats = InputStats()
    packets = list(stream_packets(files, stats))

    assert stats.files_total == expected["files_total"]
    assert stats.files_skipped == expected["files_corrupt"]
    # Every produced packet carries a timestamp and bytes.
    assert packets
    assert all(p.data and p.timestamp > 0 for p in packets)
