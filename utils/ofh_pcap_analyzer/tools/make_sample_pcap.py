# SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
# SPDX-License-Identifier: BSD-3-Clause-Open-MPI

"""Synthetic O-RAN fronthaul capture generator.

Produces small PCAP files whose byte layout matches what the analyzer parses
(see :mod:`ofh_pcap_analyzer.oran_format`). The data deliberately contains:
* paired C-Plane and U-Plane frames per slot,
* BFP9-compressed IQ U-Plane sections,
* a few TA anomalies (U-Plane arriving outside the timing window),
* a few CRC (FCS) errors,
* a deliberately corrupted file (to exercise input validation/skip).

Can be used as a library (``generate_sample``) or run as a script.
"""

from __future__ import annotations

import os
import random
import struct
import sys
import zlib

# Allow running both as ``python tools/make_sample_pcap.py`` and as a module.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ofh_pcap_analyzer import oran_format as fmt  # noqa: E402
from scapy.utils import PcapWriter  # noqa: E402

_DST = bytes.fromhex("0a0b0c0d0e0f")
_SRC = bytes.fromhex("101112131415")


def _write_frame(writer: PcapWriter, frame: bytes, ts: float) -> None:
    """Writes raw frame bytes at timestamp ``ts`` honouring the writer linktype."""
    # write_packet() does not emit the global pcap header; ensure it exists.
    if not getattr(writer, "header_present", False):
        writer.write_header(frame)
    sec = int(ts)
    usec = int(round((ts - sec) * 1_000_000))
    writer.write_packet(frame, sec=sec, usec=usec, caplen=len(frame), wirelen=len(frame))


def _eth_ecpri_header(vlan_id: int) -> bytes:
    hdr = _DST + _SRC
    if vlan_id is not None:
        hdr += struct.pack("!HH", fmt.VLAN_TPID, vlan_id & 0x0FFF)
    hdr += struct.pack("!H", fmt.ETHERTYPE_ECPRI)
    return hdr


def _ecpri_common(msg_type: int, payload_size: int) -> bytes:
    # revision=1, bit0=0 -> is_last_packet=True.
    b0 = (fmt.ECPRI_PROTOCOL_REVISION << 4) & 0xF0
    return bytes([b0, msg_type]) + struct.pack("!H", payload_size)


def _radio_header(direction: int, frame: int, subframe: int, slot: int, symbol: int) -> bytes:
    b0 = (direction << 7) | (fmt.OFH_PAYLOAD_VERSION << 4) | 0x01  # filterIndex=1
    b1 = frame & 0xFF
    b2 = ((subframe & 0x0F) << 4) | ((slot >> 2) & 0x0F)
    b3 = ((slot & 0x03) << 6) | (symbol & 0x3F)
    return bytes([b0, b1, b2, b3])


def _u_plane_section(section_id: int, start_prb: int, nof_prb: int, width: int, rng: random.Random) -> bytes:
    b0 = (section_id >> 4) & 0xFF
    b1 = ((section_id & 0x0F) << 4) | ((start_prb >> 8) & 0x03)  # rb=0, symInc=0
    b2 = start_prb & 0xFF
    b3 = nof_prb & 0xFF
    out = bytearray([b0, b1, b2, b3])
    # Dynamic udCompHdr: width<<4 | method(BFP=1), then reserved byte.
    out += bytes([((width & 0x0F) << 4) | 0x01, 0x00])
    for _ in range(nof_prb):
        out.append(rng.randint(0, 6))  # exponent (udCompParam).
        samples = [
            fmt.to_signed(rng.randint(0, (1 << width) - 1), width)
            for _ in range(fmt.NOF_SUBCARRIERS_PER_RB * 2)
        ]
        out += fmt.pack_signed_samples(samples, width)
    return bytes(out)


def _finalize(frame: bytes, has_fcs: bool, corrupt_crc: bool) -> bytes:
    if not has_fcs:
        return frame
    fcs = zlib.crc32(frame) & 0xFFFFFFFF
    if corrupt_crc:
        fcs ^= 0xDEADBEEF
    return frame + struct.pack("<I", fcs)


def generate_sample(
    out_dir: str,
    *,
    nof_slots: int = 20,
    eaxc_ids: tuple[int, ...] = (0x0001, 0x0002),
    has_fcs: bool = True,
    seed: int = 1234,
) -> dict[str, object]:
    """Generates sample captures under ``out_dir``.

    Returns a dict describing the expected ground truth (frame counts, number of
    injected CRC errors and TA anomalies) so tests can assert on it.
    """
    os.makedirs(out_dir, exist_ok=True)
    rng = random.Random(seed)

    width = 9  # BFP9.
    ta_window_max_us = 500.0
    normal_ta_us = 100.0
    anomaly_ta_us = 700.0

    expected = {
        "c_plane": 0,
        "u_plane": 0,
        "crc_errors": 0,
        "ta_anomalies": 0,
        "files_valid": 0,
        "files_corrupt": 0,
    }

    base_ts = 1_700_000_000.0
    slot_period = 500e-6  # 0.5 ms slot.

    good_path = os.path.join(out_dir, "fronthaul_capture_0.pcap")
    writer = PcapWriter(good_path, linktype=1, sync=True)  # DLT_EN10MB

    for slot in range(nof_slots):
        frame_id = (slot // 10) & 0xFF
        subframe = slot % 10
        slot_in_sf = 0
        for eaxc in eaxc_ids:
            t_c = base_ts + slot * slot_period
            # Inject a TA anomaly on a few slots.
            is_anomaly = (slot % 7 == 0)
            ta_us = anomaly_ta_us if is_anomaly else normal_ta_us
            t_u = t_c + ta_us * 1e-6

            # --- C-Plane frame (eCPRI RT control) ---
            c_body = _radio_header(0, frame_id, subframe, slot_in_sf, 0)
            c_body += bytes([0x10, 0x00, 0x00, 0x01])  # minimal section bytes (not parsed)
            c_params = struct.pack("!HH", eaxc, slot & 0xFFFF)
            c_payload = c_params + c_body
            c_frame = (
                _eth_ecpri_header(vlan_id=2)
                + _ecpri_common(fmt.ECPRI_MSG_TYPE_RT_CONTROL, len(c_payload))
                + c_payload
            )
            # Inject a CRC error on a couple of C-Plane frames.
            corrupt = has_fcs and (slot % 11 == 3) and eaxc == eaxc_ids[0]
            _write_frame(writer, _finalize(c_frame, has_fcs, corrupt), t_c)
            expected["c_plane"] += 1
            if corrupt:
                expected["crc_errors"] += 1

            # --- U-Plane frame (eCPRI IQ data, BFP9) ---
            section = _u_plane_section(section_id=1, start_prb=0, nof_prb=4, width=width, rng=rng)
            u_body = _radio_header(1, frame_id, subframe, slot_in_sf, slot % 14) + section
            u_params = struct.pack("!HH", eaxc, slot & 0xFFFF)
            u_payload = u_params + u_body
            u_frame = (
                _eth_ecpri_header(vlan_id=2)
                + _ecpri_common(fmt.ECPRI_MSG_TYPE_IQ_DATA, len(u_payload))
                + u_payload
            )
            corrupt_u = has_fcs and (slot % 13 == 5) and eaxc == eaxc_ids[1]
            _write_frame(writer, _finalize(u_frame, has_fcs, corrupt_u), t_u)
            expected["u_plane"] += 1
            if corrupt_u:
                expected["crc_errors"] += 1
            if is_anomaly and ta_us > ta_window_max_us:
                expected["ta_anomalies"] += 1

    writer.close()
    expected["files_valid"] += 1

    # A second small valid file to prove multi-file handling (same FCS policy).
    second_path = os.path.join(out_dir, "fronthaul_capture_1.pcap")
    writer2 = PcapWriter(second_path, linktype=1, sync=True)
    for slot in range(3):
        eaxc = eaxc_ids[0]
        c_payload = struct.pack("!HH", eaxc, slot) + _radio_header(0, 0, slot, 0, 0) + b"\x10\x00\x00\x01"
        c_frame = _eth_ecpri_header(2) + _ecpri_common(fmt.ECPRI_MSG_TYPE_RT_CONTROL, len(c_payload)) + c_payload
        _write_frame(writer2, _finalize(c_frame, has_fcs, corrupt_crc=False), base_ts + 100 + slot * slot_period)
        expected["c_plane"] += 1
    writer2.close()
    expected["files_valid"] += 1

    # A deliberately corrupted file (bad magic) -> must be skipped.
    corrupt_path = os.path.join(out_dir, "fronthaul_corrupt.pcap")
    with open(corrupt_path, "wb") as fh:
        fh.write(b"NOTAPCAPFILE" + os.urandom(64))
    expected["files_corrupt"] += 1

    expected["files_total"] = expected["files_valid"] + expected["files_corrupt"]
    return expected


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(description="Generate sample O-RAN fronthaul PCAPs.")
    p.add_argument("-o", "--output", default="./sample_captures", help="Output directory.")
    p.add_argument("--slots", type=int, default=20)
    p.add_argument("--no-fcs", action="store_true", help="Do not append Ethernet FCS.")
    args = p.parse_args()

    info = generate_sample(args.output, nof_slots=args.slots, has_fcs=not args.no_fcs)
    print(f"Generated sample captures in {args.output}: {info}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
