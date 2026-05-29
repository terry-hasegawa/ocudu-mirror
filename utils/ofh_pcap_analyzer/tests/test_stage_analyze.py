# SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
# SPDX-License-Identifier: BSD-3-Clause-Open-MPI

"""Unit tests for stage 3 (analyze)."""

from __future__ import annotations

import struct
import zlib

from ofh_pcap_analyzer import oran_format as fmt
from ofh_pcap_analyzer.models import ParsedFrame, Plane
from ofh_pcap_analyzer.stage_analyze import (
    AnalyzeConfig,
    Analyzer,
    decode_bfp_sections,
    verify_crc,
)


def _bfp9_section(nof_prb=2, width=9):
    b = bytearray([0x00, 0x10, 0x00, nof_prb])  # section_id=1, start_prb=0
    b += bytes([(width << 4) | 0x01, 0x00])  # udCompHdr: BFP, width.
    for _ in range(nof_prb):
        b.append(3)  # exponent
        samples = [10, -10] * fmt.NOF_SUBCARRIERS_PER_RB
        b += fmt.pack_signed_samples(samples, width)
    return bytes(b)


def test_verify_crc_ok():
    body = b"hello world frame"
    fcs = struct.pack("<I", zlib.crc32(body) & 0xFFFFFFFF)
    pf = ParsedFrame("t", 0, 1.0, 0, 0, has_fcs=True, raw=body + fcs)
    present, ok = verify_crc(pf)
    assert present and ok is True


def test_verify_crc_bad():
    body = b"hello world frame"
    pf = ParsedFrame("t", 0, 1.0, 0, 0, has_fcs=True, raw=body + b"\x00\x00\x00\x00")
    present, ok = verify_crc(pf)
    assert present and ok is False


def test_verify_crc_absent_when_no_fcs():
    pf = ParsedFrame("t", 0, 1.0, 0, 0, has_fcs=False, raw=b"abc")
    present, ok = verify_crc(pf)
    assert present is False and ok is None


def test_decode_bfp9_sections():
    radio = bytes([0x91, 0, 0, 0])  # arbitrary valid-looking radio header
    pf = ParsedFrame("t", 0, 1.0, 0, 0, plane=Plane.U_PLANE)
    pf.payload = radio + _bfp9_section(nof_prb=2, width=9)
    sections, err = decode_bfp_sections(pf)
    assert err is None
    assert len(sections) == 1
    s = sections[0]
    assert s.iq_width == 9
    assert s.compression == "BFP"
    assert s.nof_prbs == 2
    # samples 10/-10 scaled by 2^3 -> power = (80^2 + 80^2) = 12800.
    assert abs(s.mean_power - 12800.0) < 1e-6


def test_decode_truncated_iq_reports_error():
    radio = bytes([0x91, 0, 0, 0])
    full = radio + _bfp9_section(nof_prb=2, width=9)
    pf = ParsedFrame("t", 0, 1.0, 0, 0, plane=Plane.U_PLANE)
    pf.payload = full[:-5]  # chop the IQ data
    sections, err = decode_bfp_sections(pf)
    assert err is not None


def test_ta_matching_and_anomaly():
    analyzer = Analyzer(AnalyzeConfig(ta_min_us=0.0, ta_max_us=500.0, decode_iq=False))

    def frame(plane, ts):
        pf = ParsedFrame("t", 0, ts, 0, 0, plane=plane)
        pf.eaxc_id, pf.frame_id, pf.subframe_id, pf.slot_id = 1, 0, 0, 0
        return pf

    # Normal TA (100 us).
    analyzer.analyze(frame(Plane.C_PLANE, 1.000_000))
    res = analyzer.analyze(frame(Plane.U_PLANE, 1.000_100))
    assert res.ta_us is not None and abs(res.ta_us - 100.0) < 1e-3
    assert res.ta_anomaly is False

    # Anomalous TA (700 us > window).
    analyzer.analyze(frame(Plane.C_PLANE, 2.000_000))
    res2 = analyzer.analyze(frame(Plane.U_PLANE, 2.000_700))
    assert res2.ta_anomaly is True


def test_ta_no_match_when_no_cplane():
    analyzer = Analyzer(AnalyzeConfig(decode_iq=False))
    pf = ParsedFrame("t", 0, 5.0, 0, 0, plane=Plane.U_PLANE)
    pf.eaxc_id, pf.frame_id, pf.subframe_id, pf.slot_id = 9, 0, 0, 0
    res = analyzer.analyze(pf)
    assert res.ta_us is None
    assert res.ta_anomaly is False
