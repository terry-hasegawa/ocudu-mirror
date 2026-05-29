# SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
# SPDX-License-Identifier: BSD-3-Clause-Open-MPI

"""O-RAN / eCPRI wire-format constants and low level codecs.

The constants mirror the OCUDU C++ implementation (``lib/ofh``) so that the
analyzer parses exactly what the stack produces:

* eCPRI common header layout: ``lib/ofh/ecpri/ecpri_packet_decoder_impl.cpp``
* O-RAN radio header layout:  ``lib/ofh/serdes/ofh_uplane_message_decoder_impl.cpp``
* compression header layout:  ``lib/ofh/serdes/ofh_uplane_message_decoder_dynamic_compression_impl.cpp``
"""

from __future__ import annotations

# --- Ethernet ---------------------------------------------------------------
ETHERTYPE_ECPRI = 0xAEFE
VLAN_TPID = 0x8100  # lib/ofh/ethernet/ethernet_constants.h
ETH_HEADER_LEN = 14  # dst(6) + src(6) + ethertype(2)
VLAN_TAG_LEN = 4  # TPID(2) + TCI(2)
FCS_LEN = 4

# --- eCPRI ------------------------------------------------------------------
ECPRI_PROTOCOL_REVISION = 1  # ecpri_constants.h
ECPRI_COMMON_HEADER_LEN = 4
ECPRI_TYPE_PARAMS_LEN = 4

ECPRI_MSG_TYPE_IQ_DATA = 0x00  # -> U-Plane
ECPRI_MSG_TYPE_RT_CONTROL = 0x02  # -> C-Plane

# --- O-RAN U/C-Plane --------------------------------------------------------
OFH_PAYLOAD_VERSION = 1  # ofh_cuplane_constants.h
ORAN_RADIO_HEADER_LEN = 4
ORAN_SECTION_HEADER_LEN = 4
ORAN_DYNAMIC_COMP_HDR_LEN = 2
NOF_SUBCARRIERS_PER_RB = 12

# Compression methods (compression_params.h, compression_type enum).
COMPRESSION_NAMES = {
    0: "none",
    1: "BFP",
    2: "block_scaling",
    3: "mu_law",
    4: "modulation",
    5: "bfp_selective",
    6: "mod_selective",
}
MAX_IQ_WIDTH = 16


def to_signed(value: int, width: int) -> int:
    """Interprets ``width``-bit ``value`` as a two's-complement signed int."""
    sign_bit = 1 << (width - 1)
    return (value & (sign_bit - 1)) - (value & sign_bit)


def pack_signed_samples(samples: list[int], width: int) -> bytes:
    """Packs signed integers MSB-first into ``width``-bit fields.

    Used by the sample-data generator; the layout matches
    :func:`unpack_signed_samples` exactly.
    """
    acc = 0
    nbits = 0
    out = bytearray()
    mask = (1 << width) - 1
    for s in samples:
        acc = (acc << width) | (s & mask)
        nbits += width
        while nbits >= 8:
            nbits -= 8
            out.append((acc >> nbits) & 0xFF)
    if nbits:
        out.append((acc << (8 - nbits)) & 0xFF)
    return bytes(out)


def unpack_signed_samples(data: bytes, width: int, count: int) -> list[int]:
    """Unpacks ``count`` signed ``width``-bit samples packed MSB-first."""
    acc = 0
    nbits = 0
    out: list[int] = []
    idx = 0
    for _ in range(count):
        while nbits < width:
            acc = (acc << 8) | data[idx]
            idx += 1
            nbits += 8
        nbits -= width
        raw = (acc >> nbits) & ((1 << width) - 1)
        out.append(to_signed(raw, width))
    return out


def prb_iq_byte_size(width: int) -> int:
    """Bytes of packed IQ data for one PRB (12 subcarriers, I+Q)."""
    bits = NOF_SUBCARRIERS_PER_RB * 2 * width
    return (bits + 7) // 8
