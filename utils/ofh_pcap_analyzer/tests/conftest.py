# SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
# SPDX-License-Identifier: BSD-3-Clause-Open-MPI

"""Shared pytest fixtures and import-path setup."""

from __future__ import annotations

import os
import sys

import pytest

# Make the package and the tools/ generator importable without installation.
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for path in (_ROOT, os.path.join(_ROOT, "tools")):
    if path not in sys.path:
        sys.path.insert(0, path)


@pytest.fixture
def sample_dir(tmp_path):
    """Generates a small sample capture set and returns its directory + truth."""
    from make_sample_pcap import generate_sample

    out = tmp_path / "captures"
    expected = generate_sample(str(out), nof_slots=20, has_fcs=True, seed=7)
    return str(out), expected
