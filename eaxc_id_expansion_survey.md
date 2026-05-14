# eAxC ID Expansion Survey (Phase 1 — Investigation Only)

Reference spec: O-RAN.WG4.CUS-Spec. The eAxC ID is a 16-bit transport identifier
composed of four configurable-width sub-fields (`O-DU_Port_ID`, `BandSector_ID`,
`CC_ID`, `RU_Port_ID`) whose widths sum to 16 bits.

**No code changes have been made.** This document is the deliverable for Phase 1.

---

## 1 & 2. Symbol Inventory

### 1a. Core constants (`include/ocudu/ofh/ofh_constants.h`)

| Symbol | File:Line | Current value | Surrounding comment |
|---|---|---|---|
| `MAX_NOF_SUPPORTED_EAXC` | `include/ocudu/ofh/ofh_constants.h:15` | `4` | "Maximum number of supported eAxC. Implementation defined." |
| `MAX_SUPPORTED_EAXC_ID_VALUE` | `include/ocudu/ofh/ofh_constants.h:18` | `32` | "Maximum allowed value for eAxC ID." |

These are the only two macros/constants in the repository that bound the eAxC ID
domain. **There are no `*_BITS`, `*_MASK`, `*_WIDTH`, or `*_NUM_*` macros for the
eAxC ID or any of its sub-fields.**

### 1b. Sub-field symbols (`DU_Port` / `BandSector` / `CC_ID` / `RU_Port`)

A repo-wide search for `DU_Port`, `BandSector` / `band_sector`, `CC_ID`, and
`RU_Port` found **no symbols in the OFH stack**. The matches that exist
(`cc_id` in `lib/asn1/...`, `lib/scheduler/...`, FAPI PUCCH builders) are
unrelated 3GPP "component carrier" identifiers, not the O-RAN eAxC `CC_ID`
sub-field.

**Conclusion:** the codebase does not model the eAxC ID as four sub-fields at
all. It treats the eAxC ID as a single opaque integer end-to-end. See section 3.

### 1c. eAxC ID type/variable inventory (OFH stack)

| Symbol | File:Line | Type / value | Notes |
|---|---|---|---|
| `data_flow_uplane_resource_grid_context::eaxc` | `lib/ofh/transmitter/ofh_data_flow_uplane_downlink_data.h:28` | `uint8_t` | **Truncation risk** — only 8 of 16 bits. Comment: "eAxC." |
| `cplane_section_type1_parameters::eaxc` etc. | `lib/ofh/transmitter/ofh_data_flow_cplane_scheduling_commands.h:23,47` | `unsigned` | OK width. |
| `uplane_message_decoder_results::eaxc` | `include/ocudu/ofh/serdes/ofh_message_decoder_properties.h:14` | `unsigned` | OK width. |
| `ecpri::realtime_control_parameters::rtc_id` | `include/ocudu/ofh/ecpri/ecpri_packet_properties.h:29` | `uint16_t` | Wire field — already full 16-bit. |
| `ecpri::iq_data_parameters::pc_id` | `include/ocudu/ofh/ecpri/ecpri_packet_properties.h:37` | `uint16_t` | Wire field — already full 16-bit. |
| `generate_ecpri_control_parameters(uint16_t seq_id, uint16_t eaxc)` | `lib/ofh/transmitter/ofh_data_flow_cplane_scheduling_commands_impl.cpp:107` | `uint16_t` param | OK width. |
| `generate_ecpri_data_parameters(uint16_t seq_id, uint16_t eaxc)` | `lib/ofh/transmitter/ofh_data_flow_uplane_downlink_data_impl.cpp:40` | `uint16_t` param | OK width. |
| `prach_eaxc` / `dl_eaxc` / `ul_eaxc` | `include/ocudu/ofh/ofh_sector_config.h:67-71`; `ofh_transmitter_configuration.h:34-38`; `ofh_receiver_configuration.h:27-29`; plus impl mirrors in `ofh_downlink_handler_impl.h:27,86`, `ofh_uplink_request_handler_impl.h:28-30,87-88`, `ofh_message_receiver_impl.h:39-41,106-107`, `ofh_data_flow_uplane_uplink_data_impl.h:26`, `ofh_data_flow_uplane_uplink_prach_impl.h:29`, `ofh_data_flow_uplane_downlink_data_impl.h:35`, `ofh_uplane_rx_symbol_data_flow_writer.h:38`, `ofh_uplane_prach_symbol_data_flow_writer.h:36` | `static_vector<unsigned, MAX_NOF_SUPPORTED_EAXC>` | Element type `unsigned` OK; container **capacity** bounded by `MAX_NOF_SUPPORTED_EAXC` (count, not ID range). |
| `ru_*_port_id` config fields | `apps/units/flexible_o_du/split_7_2/helpers/ru_ofh_config.h:147,149,151` | `std::vector<unsigned>` | User-facing config; element type OK. |

### 1d. Structures sized/indexed by `MAX_SUPPORTED_EAXC_ID_VALUE`

| Symbol | File:Line | Construct | Comment |
|---|---|---|---|
| `sequence_identifier_generator::counters` | `lib/ofh/transmitter/sequence_identifier_generator.h:17` | `std::array<std::atomic<uint8_t>, MAX_SUPPORTED_EAXC_ID_VALUE>` | indexed directly by eAxC ID |
| loop bound | `lib/ofh/transmitter/sequence_identifier_generator.h:23` | `for (i = 0; i != MAX_SUPPORTED_EAXC_ID_VALUE; ++i)` | init loop |
| assert + msg | `lib/ofh/transmitter/sequence_identifier_generator.h:31-34` | `ocudu_assert(eaxc < MAX_SUPPORTED_EAXC_ID_VALUE, ...)` | range guard |
| `sequence_id_checker_impl::initialized` | `lib/ofh/receiver/ofh_sequence_id_checker_impl.h:20,25` | `bounded_bitset<MAX_SUPPORTED_EAXC_ID_VALUE>` | indexed by eAxC ID |
| `sequence_id_checker_impl::counters` | `lib/ofh/receiver/ofh_sequence_id_checker_impl.h:21` | `static_circular_map<uint8_t, uint8_t, MAX_SUPPORTED_EAXC_ID_VALUE>` | indexed by eAxC ID |
| loop bound | `lib/ofh/receiver/ofh_sequence_id_checker_impl.h:27` | `for (K = 0; K != MAX_SUPPORTED_EAXC_ID_VALUE; ++K)` | init loop |
| assert + msg | `lib/ofh/receiver/ofh_sequence_id_checker_impl.h:35-38` | `ocudu_assert(eaxc < MAX_SUPPORTED_EAXC_ID_VALUE, ...)` | range guard |
| `uplink_cplane_context_repository::repo_entry` | `lib/ofh/support/uplink_cplane_context_repository.h:34` | `std::array<std::atomic<uint64_t>, MAX_SUPPORTED_EAXC_ID_VALUE>` | **one such array per slot** — largest memory multiplier |
| `ofh_uplane_trace_names::trace_names` | `lib/ofh/transmitter/ofh_data_flow_uplane_downlink_data_impl.h:60` | `std::array<std::string, MAX_SUPPORTED_EAXC_ID_VALUE>` | indexed by eAxC ID |
| `check_eaxc_id` | `lib/ru/ofh/ru_ofh_config_validator.cpp:27-36` | `eaxc < MAX_SUPPORTED_EAXC_ID_VALUE` | config validation + user-facing range message |
| `ru_emulator_seq_id_checker::counters` | `apps/examples/ofh/ru_emulator_seq_id_checker.h:22` | `std::array<kpi_counter, MAX_SUPPORTED_EAXC_ID_VALUE>` | indexed by eAxC ID |
| assert | `apps/examples/ofh/ru_emulator_seq_id_checker.h:76-79` | `ocudu_assert(eaxc < MAX_SUPPORTED_EAXC_ID_VALUE, ...)` | range guard |
| `seq_counters` / `prach_seq_counters` | `apps/examples/ofh/ru_emulator.cpp:483-484` | `static_circular_map<uint8_t, uint8_t, MAX_SUPPORTED_EAXC_ID_VALUE>` | indexed by eAxC ID |
| range asserts | `apps/examples/ofh/ru_emulator.cpp:518,523,529` | `ocudu_assert(eaxc <= MAX_SUPPORTED_EAXC_ID_VALUE, ...)` | note: `<=` (off-by-one vs. the `<` used elsewhere) |

### 1e. Structures sized by `MAX_NOF_SUPPORTED_EAXC` (count, not ID range)

`lib/ofh/support/uplink_context_repository.h:55,122`,
`lib/ofh/support/prach_context_repository.h:38`,
`include/ocudu/ofh/ethernet/ethernet_frame_pool.h:373`, plus all the
`static_vector` configs in 1c. These bound the *number of antenna streams*, which
the spec leaves implementation-defined — out of scope for ID-range expansion, but
listed for completeness.

### 1f. Wire-level parsing

| Site | File:Line | Current behaviour |
|---|---|---|
| eCPRI control decode | `lib/ofh/ecpri/ecpri_packet_decoder_impl.cpp:58` | `params.rtc_id = deserializer.read<uint16_t>()` — full 16-bit |
| eCPRI IQ decode | `lib/ofh/ecpri/ecpri_packet_decoder_impl.cpp:47` | `params.pc_id = deserializer.read<uint16_t>()` — full 16-bit |
| eCPRI control build | `lib/ofh/ecpri/ecpri_packet_builder_impl.cpp:56` | `serializer.write(msg_params.rtc_id)` — full 16-bit |
| eCPRI IQ build | `lib/ofh/ecpri/ecpri_packet_builder_impl.cpp:79` | `serializer.write(msg_params.pc_id)` — full 16-bit |
| message receiver | `lib/ofh/receiver/ofh_message_receiver_impl.cpp:74` | `eaxc = ecpri_iq_params.pc_id` — full 16-bit |
| RU emulator peek | `apps/examples/ofh/ru_emulator.cpp:437` | `message_info.eaxc = packet[19]` — **single byte only**; reads RU_Port byte, drops the high byte |

---

## 3. Current Bit Allocation Per Sub-field (inferred)

**The code does not decompose the eAxC ID into sub-fields.** It is handled as a
flat integer everywhere. Consequently:

- There is no per-sub-field bit allocation defined anywhere in the source — no
  `O-DU_Port_ID` / `BandSector_ID` / `CC_ID` / `RU_Port_ID` widths, masks, or
  shifts exist.
- The *effective* usable eAxC ID range today is `[0, 31]` (5 bits), imposed
  solely by `MAX_SUPPORTED_EAXC_ID_VALUE = 32` — far below the spec's 16-bit
  (`0x0000`–`0xFFFF`) maximum.
- The eCPRI transport layer (`rtc_id` / `pc_id`) already carries the full 16-bit
  value; the artificial narrowing is entirely in the OFH application layer
  (`ofh_constants.h`) plus the `uint8_t` field in 1c and the single-byte peek in
  1f.

Because no sub-field split exists in code, "expand each sub-field to its maximum
allowed width" reduces, for this codebase, to: **support the full flat 16-bit
eAxC ID range.** If the intent is to additionally *introduce* explicit sub-field
modelling (configurable widths summing to 16), that is a new feature and its spec
basis (default widths) needs confirmation — see Open Questions.

---

## 4. Prioritized Change List (proposal — not yet applied)

| Priority | File / symbol | Proposed change |
|---|---|---|
| P0 | `include/ocudu/ofh/ofh_constants.h:18` `MAX_SUPPORTED_EAXC_ID_VALUE` | Raise to the spec maximum `65536` (`0x1'0000`), i.e. full 16-bit range. **Blocked by P1 memory concern** — see risk analysis. |
| P0 | `lib/ofh/transmitter/ofh_data_flow_uplane_downlink_data.h:28` | Widen `uint8_t eaxc` → `uint16_t` (or `unsigned`) to stop truncation. |
| P1 | `lib/ofh/support/uplink_cplane_context_repository.h:34` | Re-key `repo_entry` from "indexed by eAxC ID" to "indexed by eAxC slot/array index" (0..`MAX_NOF_SUPPORTED_EAXC`), or switch to a small map. Direct expansion is not viable (see risk 5.1). |
| P1 | `lib/ofh/transmitter/sequence_identifier_generator.h:17` | Same: index by stream index or use a map keyed by eAxC ID. |
| P1 | `lib/ofh/receiver/ofh_sequence_id_checker_impl.h:20-21` | Same: `bounded_bitset` / `static_circular_map` must not be sized at 65536. |
| P1 | `lib/ofh/transmitter/ofh_data_flow_uplane_downlink_data_impl.h:60` | `trace_names` array must not be sized at 65536; size by configured eAxC count or use a map. |
| P2 | `lib/ru/ofh/ru_ofh_config_validator.cpp:27-36` `check_eaxc_id` | Update bound + user-facing "Valid range is [0-N]" message to the new max. |
| P2 | `apps/examples/ofh/ru_emulator.cpp:437` | Read eAxC as 16-bit (`packet[18..19]`, byte order per eCPRI) instead of single byte. |
| P2 | `apps/examples/ofh/ru_emulator.cpp:483-484,518-531`, `ru_emulator_seq_id_checker.h:22,76` | Mirror the P1 re-keying; fix `<=` → `<` off-by-one at lines 518/523/529. |
| P3 | `apps/units/flexible_o_du/split_7_2/helpers/ru_ofh_config_cli11_schema.cpp:334-336` | Add explicit `[0, 65535]` range validation on `--prach/dl/ul_port_id`. |
| P3 | Tests (see risk 5.5) | Add upper-bound coverage; adjust `sequence_identifier_generator_test.cpp:53` which uses `MAX_SUPPORTED_EAXC_ID_VALUE` as an out-of-range value. |
| P3 | All changed sites | Add O-RAN.WG4.CUS-Spec section citations in comments (Phase 2 requirement). |

---

## 5. Risk Analysis

### 5.1 Memory impact on arrays / hash tables / lookup structures
This is the dominant risk. Several structures are **sized directly by
`MAX_SUPPORTED_EAXC_ID_VALUE` and indexed by the raw eAxC ID value**:

- `uplink_cplane_context_repository` holds **one `std::array<std::atomic<uint64_t>,
  MAX_SUPPORTED_EAXC_ID_VALUE>` per slot**. At `32` that is 256 B/slot; at `65536`
  it becomes 512 KB/slot, multiplied by the slot-repository depth — easily
  hundreds of MB. Naïve expansion is infeasible.
- `sequence_identifier_generator::counters`, `sequence_id_checker_impl`'s
  `bounded_bitset` + `static_circular_map`, and the `trace_names` string array
  (65536 `std::string`s) have the same problem at smaller multipliers.
- **Mitigation:** decouple "ID range" from "container size." These structures
  only ever hold up to `MAX_NOF_SUPPORTED_EAXC` live entries, so they should be
  indexed by the configured-stream index or use a compact map keyed by eAxC ID.
  This is an architectural change, not a constant bump, and is the bulk of the
  Phase 2 work.

### 5.2 Bitfield boundaries in eCPRI / O-RAN fronthaul header parse/build code
Low risk on the eCPRI layer itself: `rtc_id`/`pc_id` are already `uint16_t` and
read/written as full 16-bit fields (1f). Two concrete defects to fix:
- `data_flow_uplane_resource_grid_context::eaxc` is `uint8_t` — silently truncates
  any eAxC ID > 255 between the DL handler and the U-Plane data flow.
- `ru_emulator.cpp:437` peeks the eAxC from a single byte (`packet[19]`), so the
  emulator would misidentify any ID needing the high byte. Need to confirm eCPRI
  byte order before fixing.

### 5.3 Schema impact on config files (YAML / JSON / NETCONF YANG)
- YAML: `prach_port_id` / `dl_port_id` / `ul_port_id` are emitted/parsed as plain
  integer lists (`ru_ofh_config_yaml_writer.cpp:137-144`); no schema-level max, so
  larger values parse fine. CLI11 options (`ru_ofh_config_cli11_schema.cpp:334-336`)
  currently apply **no range check** — should add `[0, 65535]`.
- No JSON or NETCONF/YANG models for eAxC were found in the repo (`configs/`,
  `docs/` contain none). If YANG models live in the separate `ocudu_docs` repo,
  they are out of scope here but worth flagging to the user.

### 5.4 Log output formatting (printf widths / hex digit counts)
All eAxC logging uses `fmt` `'{}'` with no fixed width or hex specifier (e.g.
`ofh_data_flow_cplane_scheduling_commands_impl.cpp:156`, `ofh_message_receiver_impl.cpp:80`,
`ru_emulator_seq_id_checker.h:45`). Decimal output auto-widens, so no truncation —
but readability is poor for large IDs. Optional: switch eAxC logs to `'{:#06x}'`
for consistent 4-hex-digit display. Low risk, cosmetic.

### 5.5 Hardcoded assumptions in unit/integration tests
- `sequence_identifier_generator_test.cpp:53` uses `MAX_SUPPORTED_EAXC_ID_VALUE`
  itself as the "unsupported" value in a death test — semantics still hold after a
  bump, but if the structure is re-keyed (5.1) this test must be rewritten.
- Many tests hardcode small eAxC values (`= 2`, `{0,1,2,3}`, `{4,5,6,7}`,
  `= 24`, `invalid_eaxc = 4`): `ofh_data_flow_cplane_scheduling_commands_test.cpp`,
  `ofh_data_flow_uplane_downlink_data_impl_test.cpp`, `ofh_downlink_handler_impl_test.cpp:87`,
  `ofh_uplane_rx_symbol_data_flow_writer_test.cpp:21,56`,
  `ofh_uplane_prach_symbol_data_flow_writer_test.cpp:17`,
  `ofh_sequence_id_checker_impl_test.cpp`, `ofh_uplink_request_handler_impl_test.cpp:23-24`,
  `ofh_data_flow_uplane_uplink_prach_impl_test.cpp:38,43`. These keep working but
  give no upper-range coverage — Phase 2 must add tests at `0xFFFF` and at each
  sub-field boundary.
- Test doubles use `eaxc = -1` as a sentinel (`ofh_data_flow_cplane_scheduling_commands_test_doubles.h:19`,
  `ofh_downlink_handler_impl_test.cpp:25`) — fine for `unsigned`, but verify it
  does not collide once `0xFFFF` becomes a valid value.

---

## Open Questions (please confirm before Phase 2)

1. **Sub-field modelling.** The codebase has *no* `O-DU_Port_ID` / `BandSector_ID`
   / `CC_ID` / `RU_Port_ID` decomposition — the eAxC ID is a flat integer. Do you
   want Phase 2 to (a) simply support the full flat 16-bit range, or (b) also
   introduce explicit configurable sub-field widths/masks? Option (b) needs the
   default sub-field widths from the spec, which I will not guess.
2. **Target value of `MAX_SUPPORTED_EAXC_ID_VALUE`.** Confirm it should become
   `65536` (full 16-bit, exclusive bound) — consistent with the existing `eaxc <
   MAX_SUPPORTED_EAXC_ID_VALUE` usage.
3. **Re-keying scope.** The memory-driven re-keying of `uplink_cplane_context_repository`,
   `sequence_identifier_generator`, `sequence_id_checker_impl`, and `trace_names`
   (risk 5.1) is the largest change and touches hot paths. Confirm you want this
   architectural change rather than a capped/smaller intermediate constant.
4. **Branch.** Task says branch `feature/eaxc-id-range-expansion`; this session's
   environment is on `claude/expand-eaxc-id-range-dtsZa`. Please confirm which
   branch Phase 2 commits should target.

---

**Phase 1 complete. Stopping here for your review — no Phase 2 changes will be
made until you approve.**
