# SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
# SPDX-License-Identifier: BSD-3-Clause-Open-MPI

"""Stage 1 - input: discover, validate and stream packets from PCAP files.

Design goals:
* Streaming: packets are yielded lazily via :class:`scapy.utils.RawPcapReader`
  so that captures of several hundred MB never need to be fully buffered.
* Robust: a corrupted or unreadable file is skipped with a warning and does
  not abort the run. The number of skipped files is tracked.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Iterator

from scapy.utils import RawPcapReader

from .logging_config import get_logger
from .models import RawPacket

_log = get_logger("input")

# libpcap / pcapng magic numbers (any byte order).
_PCAP_MAGICS = {
    b"\xd4\xc3\xb2\xa1",  # microsecond, little endian
    b"\xa1\xb2\xc3\xd4",  # microsecond, big endian
    b"\x4d\x3c\xb2\xa1",  # nanosecond, little endian
    b"\xa1\xb2\x3c\x4d",  # nanosecond, big endian
    b"\x0a\x0d\x0d\x0a",  # pcapng
}


@dataclass
class InputStats:
    """Counters describing what the input stage processed."""

    files_total: int = 0
    files_skipped: int = 0
    packets_read: int = 0
    skipped_files: list[str] = field(default_factory=list)


def discover_pcap_files(directory: str) -> list[str]:
    """Returns a sorted list of ``*.pcap`` / ``*.pcapng`` files in ``directory``."""
    if not os.path.isdir(directory):
        raise NotADirectoryError(f"input path is not a directory: {directory}")

    files = [
        os.path.join(directory, name)
        for name in sorted(os.listdir(directory))
        if name.lower().endswith((".pcap", ".pcapng"))
    ]
    _log.info(
        "discovered pcap files",
        extra={"extra_fields": {"directory": directory, "count": len(files)}},
    )
    return files


def validate_pcap(path: str) -> bool:
    """Cheaply validates a capture file by checking its magic number.

    Returns ``True`` when the file looks like a pcap/pcapng capture. Any I/O
    error is caught and reported as invalid (the file will be skipped).
    """
    try:
        if os.path.getsize(path) < 4:
            _log.warning("file too small to be a capture", extra={"extra_fields": {"file": path}})
            return False
        with open(path, "rb") as fh:
            magic = fh.read(4)
        if magic not in _PCAP_MAGICS:
            _log.warning(
                "unrecognised capture magic; skipping",
                extra={"extra_fields": {"file": path, "magic": magic.hex()}},
            )
            return False
        return True
    except OSError as exc:
        _log.warning(
            "cannot read capture file; skipping",
            extra={"extra_fields": {"file": path, "error": str(exc)}},
        )
        return False


def _read_one_file(path: str, stats: InputStats) -> Iterator[RawPacket]:
    """Streams packets from a single validated capture file.

    Any error raised mid-file (truncated capture, scapy parse error) is caught
    so that already-read packets are not lost and the run continues.
    """
    try:
        with RawPcapReader(path) as reader:
            for index, (data, meta) in enumerate(reader):
                # meta.sec / meta.usec carry the capture timestamp. Fall back to
                # 0.0 when a reader variant does not expose them.
                sec = getattr(meta, "sec", 0) or 0
                usec = getattr(meta, "usec", 0) or 0
                # tshigh/tsresol handling is abstracted away by scapy; usec is
                # already scaled to the file resolution for RawPcapReader.
                ts = float(sec) + float(usec) / 1_000_000.0
                orig_len = getattr(meta, "wirelen", None) or len(data)
                stats.packets_read += 1
                yield RawPacket(
                    source_file=path,
                    index=index,
                    timestamp=ts,
                    data=bytes(data),
                    orig_len=int(orig_len),
                )
    except Exception as exc:  # noqa: BLE001 - want to keep the pipeline alive.
        _log.warning(
            "error while reading capture; truncating file",
            extra={"extra_fields": {"file": path, "error": str(exc)}},
        )


def stream_packets(paths: list[str], stats: InputStats) -> Iterator[RawPacket]:
    """Validates and streams packets from every file in ``paths``.

    Corrupted files are skipped (and counted in ``stats``); valid files are
    streamed packet by packet.
    """
    for path in paths:
        stats.files_total += 1
        if not validate_pcap(path):
            stats.files_skipped += 1
            stats.skipped_files.append(path)
            continue
        _log.info("reading capture", extra={"extra_fields": {"file": path}})
        yield from _read_one_file(path, stats)
