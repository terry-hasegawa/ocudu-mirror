# SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
# SPDX-License-Identifier: BSD-3-Clause-Open-MPI

"""Unit tests for the low-level O-RAN codecs."""

from __future__ import annotations

import pytest

from ofh_pcap_analyzer import oran_format as fmt


@pytest.mark.parametrize("width", [8, 9, 12, 16])
def test_pack_unpack_roundtrip(width):
    lo = -(1 << (width - 1))
    hi = (1 << (width - 1)) - 1
    samples = [lo, hi, 0, 1, -1, hi - 1, lo + 1] * 4
    packed = fmt.pack_signed_samples(samples, width)
    out = fmt.unpack_signed_samples(packed, width, len(samples))
    assert out == samples


def test_to_signed():
    assert fmt.to_signed(0b0_1111_1111, 9) == 255
    assert fmt.to_signed(0b1_0000_0000, 9) == -256
    assert fmt.to_signed(0xFF, 8) == -1


def test_prb_iq_byte_size_bfp9():
    # 12 subcarriers * 2 * 9 bits = 216 bits = 27 bytes.
    assert fmt.prb_iq_byte_size(9) == 27
    assert fmt.prb_iq_byte_size(16) == 48
