# SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
# SPDX-License-Identifier: BSD-3-Clause-Open-MPI

"""Stage 3 - analyze: CRC verification, TA anomaly detection and BFP decode.

The analyzer is stateful: timing-advance (TA) detection correlates each
U-Plane frame with the most recent C-Plane (control) message for the same
flow/slot, so the analyzer keeps a small per-slot timestamp map. The map is
naturally bounded (keyed by eAxC + frame + subframe + slot, all small ranges).
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from typing import Iterator, Optional

from . import oran_format as fmt
from .logging_config import get_logger
from .models import AnalyzedFrame, ParsedFrame, Plane, SectionStats

_log = get_logger("analyze")

# Compression methods that carry a per-PRB udCompParam byte (e.g. BFP exponent).
_PARAM_PRESENT = {1, 5}  # BFP, bfp_selective


@dataclass
class AnalyzeConfig:
    """Tunables for the analyze stage."""

    # Expected TA window (microseconds). U-Plane frames whose measured TA falls
    # outside [min, max] are flagged as anomalies.
    ta_min_us: float = 0.0
    ta_max_us: float = 500.0
    decode_iq: bool = True


def verify_crc(frame: ParsedFrame) -> tuple[bool, Optional[bool]]:
    """Verifies the Ethernet FCS when present.

    Returns ``(crc_present, crc_ok)``. ``crc_ok`` is ``None`` when no FCS is
    present in the capture (NICs commonly strip it).
    """
    if not frame.has_fcs or len(frame.raw) <= fmt.FCS_LEN:
        return (False, None)
    body = frame.raw[: -fmt.FCS_LEN]
    trailer = frame.raw[-fmt.FCS_LEN :]
    computed = zlib.crc32(body) & 0xFFFFFFFF
    received = int.from_bytes(trailer, "little")
    return (True, computed == received)


def decode_bfp_sections(frame: ParsedFrame) -> tuple[list[SectionStats], Optional[str]]:
    """Decodes U-Plane IQ sections, returning per-section statistics.

    Supports the dynamic-compression header layout used by OCUDU. BFP sections
    carry a per-PRB exponent (udCompParam) followed by ``width``-bit packed I/Q
    samples. Returns ``(sections, error)``; ``error`` is set when decoding had
    to stop early (e.g. truncated IQ data).
    """
    payload = frame.payload
    off = fmt.ORAN_RADIO_HEADER_LEN
    sections: list[SectionStats] = []

    while off + fmt.ORAN_SECTION_HEADER_LEN <= len(payload):
        b0, b1, b2, nof_prb = payload[off : off + 4]
        section_id = (b0 << 4) | (b1 >> 4)
        start_prb = ((b1 & 0x03) << 8) | b2
        off += fmt.ORAN_SECTION_HEADER_LEN

        if nof_prb == 0:
            # 0 means "all PRBs"; without RU carrier config we cannot size the
            # section, so stop decoding here.
            return sections, "nof_prb=0 (all PRBs) not decodable without carrier config"

        if off + fmt.ORAN_DYNAMIC_COMP_HDR_LEN > len(payload):
            return sections, "truncated compression header"
        comp_byte = payload[off]
        comp_method = comp_byte & 0x0F
        width = comp_byte >> 4
        if width == 0:
            width = fmt.MAX_IQ_WIDTH
        off += fmt.ORAN_DYNAMIC_COMP_HDR_LEN  # incl. reserved byte.

        comp_name = fmt.COMPRESSION_NAMES.get(comp_method, "reserved")
        param_present = comp_method in _PARAM_PRESENT
        prb_bytes = fmt.prb_iq_byte_size(width)
        stride = prb_bytes + (1 if param_present else 0)

        if off + stride * nof_prb > len(payload):
            return sections, "truncated IQ data"

        # Decode the section's resource elements and compute mean power.
        sum_power = 0.0
        nof_re = 0
        for _ in range(nof_prb):
            exponent = 0
            if param_present:
                exponent = payload[off]
                off += 1
            samples = fmt.unpack_signed_samples(
                payload[off : off + prb_bytes], width, fmt.NOF_SUBCARRIERS_PER_RB * 2
            )
            off += prb_bytes
            scale = float(1 << exponent)
            for k in range(0, len(samples), 2):
                i = samples[k] * scale
                q = samples[k + 1] * scale
                sum_power += i * i + q * q
                nof_re += 1

        mean_power = (sum_power / nof_re) if nof_re else 0.0
        sections.append(
            SectionStats(
                section_id=section_id,
                start_prb=start_prb,
                nof_prbs=nof_prb,
                compression=comp_name,
                iq_width=width,
                mean_power=mean_power,
            )
        )

    return sections, None


class Analyzer:
    """Stateful analyzer correlating C-Plane and U-Plane for TA detection."""

    def __init__(self, config: Optional[AnalyzeConfig] = None) -> None:
        self.config = config or AnalyzeConfig()
        # slot_key -> most recent C-Plane arrival timestamp.
        self._cplane_ts: dict[tuple, float] = {}

    def analyze(self, frame: ParsedFrame) -> AnalyzedFrame:
        result = AnalyzedFrame(frame=frame)

        # CRC / FCS verification works regardless of plane.
        result.crc_present, result.crc_ok = verify_crc(frame)
        if result.crc_present and result.crc_ok is False:
            _log.info(
                "CRC error",
                extra={
                    "extra_fields": {
                        "file": frame.source_file,
                        "index": frame.index,
                        "eaxc": frame.eaxc_id,
                    }
                },
            )

        if frame.malformed:
            return result

        if frame.plane is Plane.C_PLANE:
            # Record control arrival time for later U-Plane correlation.
            self._cplane_ts[frame.slot_key()] = frame.timestamp
            return result

        if frame.plane is Plane.U_PLANE:
            self._match_timing(frame, result)
            if self.config.decode_iq:
                result.sections, result.analyze_error = decode_bfp_sections(frame)

        return result

    def _match_timing(self, frame: ParsedFrame, result: AnalyzedFrame) -> None:
        c_ts = self._cplane_ts.get(frame.slot_key())
        if c_ts is None:
            return
        ta_us = (frame.timestamp - c_ts) * 1e6
        result.ta_us = ta_us
        if not (self.config.ta_min_us <= ta_us <= self.config.ta_max_us):
            result.ta_anomaly = True
            _log.info(
                "TA anomaly",
                extra={
                    "extra_fields": {
                        "eaxc": frame.eaxc_id,
                        "ta_us": round(ta_us, 3),
                        "window_us": [self.config.ta_min_us, self.config.ta_max_us],
                    }
                },
            )

    def analyze_stream(
        self, frames: Iterator[ParsedFrame]
    ) -> Iterator[AnalyzedFrame]:
        for frame in frames:
            yield self.analyze(frame)
