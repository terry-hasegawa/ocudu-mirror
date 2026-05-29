# SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
# SPDX-License-Identifier: BSD-3-Clause-Open-MPI

"""Unit tests for stage 2 (parse)."""

from __future__ import annotations

import struct

from ofh_pcap_analyzer import oran_format as fmt
from ofh_pcap_analyzer.models import Plane, RawPacket
from ofh_pcap_analyzer.stage_parse import parse_packet


def _make_eth_ecpri(msg_type, eaxc, seq, oran_payload, vlan_id=2):
    hdr = bytes.fromhex("0a0b0c0d0e0f101112131415")
    hdr += struct.pack("!HH", fmt.VLAN_TPID, vlan_id)
    hdr += struct.pack("!H", fmt.ETHERTYPE_ECPRI)
    common = bytes([(1 << 4), msg_type]) + struct.pack("!H", 4 + len(oran_payload))
    params = struct.pack("!HH", eaxc, seq)
    return hdr + common + params + oran_payload


def _radio_header(direction, frame, subframe, slot, symbol):
    b0 = (direction << 7) | (1 << 4) | 0x01
    b1 = frame & 0xFF
    b2 = ((subframe & 0x0F) << 4) | ((slot >> 2) & 0x0F)
    b3 = ((slot & 0x03) << 6) | (symbol & 0x3F)
    return bytes([b0, b1, b2, b3])


def _pkt(data):
    return RawPacket(source_file="t", index=0, timestamp=1.0, data=data, orig_len=len(data))


def test_parse_u_plane_classification_and_fields():
    radio = _radio_header(1, 7, 3, 5, 9)
    data = _make_eth_ecpri(fmt.ECPRI_MSG_TYPE_IQ_DATA, 0x1234, 0x000A, radio)
    pf = parse_packet(_pkt(data))

    assert not pf.malformed
    assert pf.plane is Plane.U_PLANE
    assert pf.eaxc_id == 0x1234
    assert pf.seq_id == 0x000A
    assert pf.vlan_id == 2
    assert pf.frame_id == 7
    assert pf.subframe_id == 3
    assert pf.slot_id == 5
    assert pf.symbol_id == 9
    assert pf.direction == 1


def test_parse_c_plane_classification():
    radio = _radio_header(0, 1, 2, 0, 0)
    data = _make_eth_ecpri(fmt.ECPRI_MSG_TYPE_RT_CONTROL, 0x0001, 0, radio)
    pf = parse_packet(_pkt(data))
    assert pf.plane is Plane.C_PLANE
    assert pf.eaxc_id == 0x0001


def test_parse_non_ecpri_is_malformed():
    data = bytes.fromhex("0a0b0c0d0e0f101112131415") + struct.pack("!H", 0x0800) + b"\x00" * 20
    pf = parse_packet(_pkt(data))
    assert pf.malformed
    assert "ethertype" in pf.parse_error


def test_parse_truncated_is_malformed():
    pf = parse_packet(_pkt(b"\x00" * 8))
    assert pf.malformed


def test_parse_strips_fcs():
    radio = _radio_header(1, 0, 0, 0, 0)
    data = _make_eth_ecpri(fmt.ECPRI_MSG_TYPE_IQ_DATA, 0x1, 0, radio)
    with_fcs = data + b"\xde\xad\xbe\xef"
    pf = parse_packet(_pkt(with_fcs), has_fcs=True)
    # The 4-byte FCS must not leak into the O-RAN payload.
    assert pf.payload == radio
    assert pf.has_fcs is True
