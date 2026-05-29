# SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
# SPDX-License-Identifier: BSD-3-Clause-Open-MPI

"""Command line entry point for the O-RAN fronthaul PCAP analyzer.

Example::

    python -m ofh_pcap_analyzer --input ./captures --output ./out --has-fcs
"""

from __future__ import annotations

import argparse
import logging
import sys

from .logging_config import configure_logging
from .pipeline import PipelineConfig, run_pipeline


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ofh_pcap_analyzer",
        description="O-RAN fronthaul PCAP analysis pipeline (C/U-Plane, TA, CRC, BFP).",
    )
    p.add_argument("-i", "--input", required=True, help="Directory with .pcap files.")
    p.add_argument("-o", "--output", required=True, help="Directory for the reports.")
    p.add_argument(
        "--has-fcs",
        action="store_true",
        help="Captures include the trailing Ethernet FCS (enables CRC checking).",
    )
    p.add_argument(
        "--no-iq",
        action="store_true",
        help="Skip BFP/IQ decoding (faster; only structural + timing analysis).",
    )
    p.add_argument("--ta-min-us", type=float, default=0.0, help="Lower TA window bound.")
    p.add_argument("--ta-max-us", type=float, default=500.0, help="Upper TA window bound.")
    p.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity.",
    )
    p.add_argument(
        "--log-text",
        action="store_true",
        help="Emit human readable logs instead of structured JSON.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(
        level=getattr(logging, args.log_level), json_format=not args.log_text
    )

    config = PipelineConfig(
        input_dir=args.input,
        output_dir=args.output,
        has_fcs=args.has_fcs,
        decode_iq=not args.no_iq,
        ta_min_us=args.ta_min_us,
        ta_max_us=args.ta_max_us,
    )

    try:
        report = run_pipeline(config)
    except (NotADirectoryError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(
        f"Processed {report.frames_total} frames "
        f"({report.c_plane_frames} C-Plane, {report.u_plane_frames} U-Plane) "
        f"from {report.files_total - report.files_skipped}/{report.files_total} files; "
        f"CRC errors={report.crc_errors}, TA anomalies={report.ta_anomalies}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
