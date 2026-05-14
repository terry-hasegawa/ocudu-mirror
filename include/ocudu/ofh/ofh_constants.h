// SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
// SPDX-License-Identifier: BSD-3-Clause-Open-MPI

#pragma once

#include <cstddef>

namespace ocudu {
namespace ofh {

/// Open Fronthaul message type.
enum class message_type { control_plane, user_plane, num_ofh_types };

/// Maximum number of supported eAxC. Implementation defined.
constexpr unsigned MAX_NOF_SUPPORTED_EAXC = 4;

/// \brief Maximum allowed value for eAxC ID (exclusive upper bound).
///
/// Per O-RAN.WG4.CUS-Spec section 3.1.3.1.6, the eAxC ID (ecpriRtcid/ecpriPcid) is a 16-bit identifier composed of the
/// O-DU_Port_ID, BandSector_ID, CC_ID and RU_Port_ID sub-fields, whose configurable widths sum to 16 bits. Any
/// allocation permitted by the spec must therefore be supported, so the full 16-bit range [0x0000, 0xFFFF] is valid.
constexpr size_t MAX_SUPPORTED_EAXC_ID_VALUE = 65536;

} // namespace ofh
} // namespace ocudu
