# SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
# SPDX-License-Identifier: BSD-3-Clause-Open-MPI

"""Stage 2 - parse: Ethernet/VLAN/eCPRI dissection and plane classification.

The dissection is implemented with :mod:`struct` rather than scapy layers: the
frames are custom O-RAN payloads, so hand parsing is both faster and avoids
pulling heavyweight scapy dissectors into the hot path. Any malformed frame is
flagged (``malformed=True``) and kept with a ``parse_error`` rather than raising
- the pipeline must survive a few bad packets in a large capture.
"""

from __future__ import annotations

import struct
from typing import Iterator

from . import oran_format as fmt
from .logging_config import get_logger
from .models import ParsedFrame, Plane, RawPacket

_log = get_logger("parse")


def _classify(msg_type: int) -> Plane:
    if msg_type == fmt.ECPRI_MSG_TYPE_IQ_DATA:
        return Plane.U_PLANE
    if msg_type == fmt.ECPRI_MSG_TYPE_RT_CONTROL:
        return Plane.C_PLANE
    return Plane.UNKNOWN


def _parse_radio_header(pf: ParsedFrame, payload: bytes) -> None:
    """Parses the 4-byte O-RAN radio application header.

    Bit layout mirrors ``ofh_uplane_message_decoder_impl::decode_header``:
        byte0: direction(7) | version(6:4) | filterIndex(3:0)
        byte1: frameId
        byte2: subframeId(7:4) | slotId(3:0) -> slotId bits [5:2]
        byte3: slotId(7:6) -> slotId bits [1:0] | symbolId(5:0)
    """
    if len(payload) < fmt.ORAN_RADIO_HEADER_LEN:
        return
    b0, frame, sf_slot, slot_sym = payload[:4]
    pf.direction = b0 >> 7
    pf.filter_index = b0 & 0x0F
    pf.frame_id = frame
    pf.subframe_id = sf_slot >> 4
    slot_id = (sf_slot & 0x0F) << 2
    slot_id |= slot_sym >> 6
    pf.slot_id = slot_id
    pf.symbol_id = slot_sym & 0x3F


def parse_packet(pkt: RawPacket, *, has_fcs: bool = False) -> ParsedFrame:
    """Parses a single raw packet into a :class:`ParsedFrame`.

    Never raises on malformed input: failures set ``malformed`` and
    ``parse_error`` so the frame can still be counted and reported.
    """
    data = pkt.data
    pf = ParsedFrame(
        source_file=pkt.source_file,
        index=pkt.index,
        timestamp=pkt.timestamp,
        captured_len=len(data),
        orig_len=pkt.orig_len,
        raw=data,
        has_fcs=has_fcs,
    )

    body = data[: -fmt.FCS_LEN] if (has_fcs and len(data) > fmt.FCS_LEN) else data

    try:
        if len(body) < fmt.ETH_HEADER_LEN:
            raise ValueError("frame shorter than Ethernet header")

        offset = 12  # skip dst+src MAC.
        (ethertype,) = struct.unpack_from("!H", body, offset)
        offset += 2
        if ethertype == fmt.VLAN_TPID:
            (tci,) = struct.unpack_from("!H", body, offset)
            pf.vlan_id = tci & 0x0FFF
            offset += 2
            (ethertype,) = struct.unpack_from("!H", body, offset)
            offset += 2
        pf.ethertype = ethertype

        if ethertype != fmt.ETHERTYPE_ECPRI:
            raise ValueError(f"non-eCPRI ethertype 0x{ethertype:04x}")

        if len(body) - offset < fmt.ECPRI_COMMON_HEADER_LEN + fmt.ECPRI_TYPE_PARAMS_LEN:
            raise ValueError("frame too short for eCPRI headers")

        # eCPRI common header (ecpri_packet_decoder_impl.cpp).
        b0 = body[offset]
        pf.ecpri_revision = b0 >> 4
        pf.ecpri_msg_type = body[offset + 1]
        (pf.ecpri_payload_size,) = struct.unpack_from("!H", body, offset + 2)
        offset += fmt.ECPRI_COMMON_HEADER_LEN

        pf.plane = _classify(pf.ecpri_msg_type)
        if pf.plane is Plane.UNKNOWN:
            raise ValueError(f"unsupported eCPRI msg type {pf.ecpri_msg_type}")

        # eCPRI type parameters: {pc_id|rtc_id, seq_id}.
        eaxc, seq = struct.unpack_from("!HH", body, offset)
        pf.eaxc_id = eaxc
        pf.seq_id = seq
        offset += fmt.ECPRI_TYPE_PARAMS_LEN

        pf.payload = body[offset:]
        _parse_radio_header(pf, pf.payload)
        return pf

    except (ValueError, struct.error, IndexError) as exc:
        pf.malformed = True
        pf.parse_error = str(exc)
        _log.debug(
            "malformed frame",
            extra={
                "extra_fields": {
                    "file": pkt.source_file,
                    "index": pkt.index,
                    "error": str(exc),
                }
            },
        )
        return pf


def parse_stream(
    packets: Iterator[RawPacket], *, has_fcs: bool = False
) -> Iterator[ParsedFrame]:
    """Lazily parses a stream of raw packets."""
    for pkt in packets:
        yield parse_packet(pkt, has_fcs=has_fcs)
