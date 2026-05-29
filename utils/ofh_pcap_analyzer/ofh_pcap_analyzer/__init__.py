# SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
# SPDX-License-Identifier: BSD-3-Clause-Open-MPI

"""O-RAN fronthaul PCAP analysis pipeline.

A small, streaming pipeline that extracts C-Plane/U-Plane frames from eCPRI
captures, detects timing (TA) anomalies and CRC (FCS) errors, decodes BFP IQ
data and emits KPI reports in JSON, CSV and Prometheus formats.
"""

__version__ = "1.0.0"
