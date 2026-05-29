# SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
# SPDX-License-Identifier: BSD-3-Clause-Open-MPI

"""Dataclasses shared across the pipeline stages.

These types form the contract between stages: the parse stage produces
:class:`ParsedFrame`, the analyze stage enriches it into :class:`AnalyzedFrame`,
and the aggregate stage condenses many frames into a :class:`KpiReport`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


class Plane(str, Enum):
    """eCPRI message plane classification."""

    C_PLANE = "C"  # Real-Time control data (eCPRI msg type 0x02).
    U_PLANE = "U"  # IQ data (eCPRI msg type 0x00).
    UNKNOWN = "?"


@dataclass
class RawPacket:
    """A single packet as produced by the input stage (streaming)."""

    source_file: str
    index: int  # 0-based index within the source file.
    timestamp: float  # Capture timestamp in seconds since the epoch.
    data: bytes  # Raw link-layer bytes (Ethernet frame, optionally incl. FCS).
    orig_len: int  # Original on-wire length reported by the capture.


@dataclass
class ParsedFrame:
    """Result of the parse stage for a single packet."""

    source_file: str
    index: int
    timestamp: float
    captured_len: int
    orig_len: int

    plane: Plane = Plane.UNKNOWN
    malformed: bool = False
    parse_error: Optional[str] = None

    # Ethernet / VLAN.
    vlan_id: Optional[int] = None
    ethertype: Optional[int] = None

    # eCPRI common header.
    ecpri_revision: Optional[int] = None
    ecpri_msg_type: Optional[int] = None
    ecpri_payload_size: Optional[int] = None

    # eCPRI type parameters (IQ data or RT control).
    eaxc_id: Optional[int] = None  # pc_id (U-Plane) or rtc_id (C-Plane).
    seq_id: Optional[int] = None

    # O-RAN radio application header.
    direction: Optional[int] = None
    filter_index: Optional[int] = None
    frame_id: Optional[int] = None
    subframe_id: Optional[int] = None
    slot_id: Optional[int] = None
    symbol_id: Optional[int] = None  # symbolId (U-Plane) / startSymbolId (C-Plane).

    # Raw O-RAN payload (after the eCPRI type parameters), used by the analyze
    # stage to decode IQ sections. Not serialised to JSON.
    payload: bytes = field(default=b"", repr=False)
    # Full link-layer frame bytes (incl. trailing FCS when present), used by the
    # analyze stage for CRC verification. Not serialised to JSON.
    raw: bytes = field(default=b"", repr=False)
    has_fcs: bool = False

    def slot_key(self) -> tuple[Any, ...]:
        """Returns a key identifying the slot a frame belongs to."""
        return (self.eaxc_id, self.frame_id, self.subframe_id, self.slot_id)


@dataclass
class SectionStats:
    """Per-section IQ statistics produced when decoding U-Plane data."""

    section_id: int
    start_prb: int
    nof_prbs: int
    compression: str
    iq_width: int
    mean_power: float  # Mean |IQ|^2 across decoded resource elements.


@dataclass
class AnalyzedFrame:
    """A :class:`ParsedFrame` enriched by the analyze stage."""

    frame: ParsedFrame

    # CRC / FCS.
    crc_present: bool = False
    crc_ok: Optional[bool] = None

    # Timing advance (only meaningful for matched U-Plane frames).
    ta_us: Optional[float] = None  # U-Plane arrival minus matched C-Plane arrival.
    ta_anomaly: bool = False

    # BFP / IQ decode.
    sections: list[SectionStats] = field(default_factory=list)
    analyze_error: Optional[str] = None

    def to_record(self) -> dict[str, Any]:
        """Flattens the frame into a JSON-serialisable record."""
        f = self.frame
        rec = asdict(f)
        rec.pop("payload", None)
        rec.pop("raw", None)
        rec["plane"] = f.plane.value
        rec.update(
            {
                "crc_present": self.crc_present,
                "crc_ok": self.crc_ok,
                "ta_us": self.ta_us,
                "ta_anomaly": self.ta_anomaly,
                "analyze_error": self.analyze_error,
                "sections": [asdict(s) for s in self.sections],
            }
        )
        return rec


@dataclass
class FlowKpi:
    """KPI for a single flow (one eAxC on one plane)."""

    eaxc_id: int
    plane: str
    frames: int = 0
    malformed: int = 0
    crc_checked: int = 0
    crc_errors: int = 0
    ta_count: int = 0
    ta_mean_us: Optional[float] = None
    ta_std_us: Optional[float] = None
    ta_min_us: Optional[float] = None
    ta_max_us: Optional[float] = None
    ta_anomalies: int = 0

    @property
    def crc_error_rate(self) -> float:
        return (self.crc_errors / self.crc_checked) if self.crc_checked else 0.0

    @property
    def malformed_rate(self) -> float:
        return (self.malformed / self.frames) if self.frames else 0.0


@dataclass
class KpiReport:
    """Top-level KPI summary returned by the aggregate stage."""

    files_total: int = 0
    files_skipped: int = 0
    frames_total: int = 0
    frames_malformed: int = 0
    c_plane_frames: int = 0
    u_plane_frames: int = 0

    crc_checked: int = 0
    crc_errors: int = 0

    ta_anomalies: int = 0
    ta_samples: int = 0
    ta_mean_us: Optional[float] = None
    ta_std_us: Optional[float] = None
    ta_p50_us: Optional[float] = None
    ta_p99_us: Optional[float] = None

    flows: list[FlowKpi] = field(default_factory=list)

    @property
    def crc_error_rate(self) -> float:
        return (self.crc_errors / self.crc_checked) if self.crc_checked else 0.0
