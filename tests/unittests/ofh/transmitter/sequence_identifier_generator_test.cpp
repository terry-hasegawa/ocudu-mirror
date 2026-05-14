// SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
// SPDX-License-Identifier: BSD-3-Clause-Open-MPI

#include "../../../../lib/ofh/transmitter/sequence_identifier_generator.h"
#include "ocudu/adt/bounded_bitset.h"
#include <gtest/gtest.h>

using namespace ocudu;
using namespace ofh;

TEST(sequence_identifier_generator, generate_consecutive_sequence_number_for_one_exac)
{
  unsigned eaxc = 0;

  sequence_identifier_generator gen;

  unsigned seq_id = gen.generate(eaxc);
  ASSERT_EQ(++seq_id, gen.generate(eaxc));
}

TEST(sequence_identifier_generator, generate_consecutive_sequence_number_for_different_exac)
{
  static_vector<unsigned, MAX_NOF_SUPPORTED_EAXC> eaxc = {0, 1, 2, 3};

  sequence_identifier_generator gen;

  static_vector<unsigned, MAX_NOF_SUPPORTED_EAXC> seq_id = {0, 0, 0, 0};
  for (unsigned i = 0; i != MAX_NOF_SUPPORTED_EAXC; ++i) {
    for (unsigned eaxc_pos = 0, eaxc_end = eaxc.size(); eaxc_pos != eaxc_end; ++eaxc_pos) {
      if (i == 0) {
        seq_id[eaxc_pos] = gen.generate(eaxc[eaxc_pos]);
        continue;
      }

      ASSERT_EQ(++seq_id[eaxc_pos], gen.generate(eaxc[eaxc_pos]));
    }
  }
}

TEST(sequence_identifier_generator, sequence_id_values_fit_in_one_byte)
{
  unsigned eaxc = 0;

  sequence_identifier_generator gen(255);

  ASSERT_EQ(gen.generate(eaxc), 255);
  ASSERT_EQ(gen.generate(eaxc), 0);
}

TEST(sequence_identifier_generator, supports_full_16_bit_eaxc_id_range)
{
  // Per O-RAN.WG4.CUS-Spec section 3.1.3.1.6 the eAxC ID spans the full 16-bit range [0x0000, 0xFFFF].
  sequence_identifier_generator gen;

  // Upper bound of the eAxC ID range.
  unsigned eaxc_max = MAX_SUPPORTED_EAXC_ID_VALUE - 1;
  ASSERT_EQ(eaxc_max, 0xFFFF);
  ASSERT_EQ(gen.generate(eaxc_max), 0);
  ASSERT_EQ(gen.generate(eaxc_max), 1);

  // eAxC IDs that share a low byte must not collide (e.g. 0x0002 and 0x0102).
  unsigned eaxc_low  = 0x0002;
  unsigned eaxc_high = 0x0102;
  ASSERT_EQ(gen.generate(eaxc_low), 0);
  ASSERT_EQ(gen.generate(eaxc_high), 0);
  ASSERT_EQ(gen.generate(eaxc_low), 1);
}

#ifdef ASSERTS_ENABLED
TEST(sequence_identifier_generator, death_when_eaxc_value_is_not_supported)
{
  unsigned eaxc = MAX_SUPPORTED_EAXC_ID_VALUE;

  sequence_identifier_generator gen;
  ASSERT_DEATH(gen.generate(eaxc), "");
}
#endif
