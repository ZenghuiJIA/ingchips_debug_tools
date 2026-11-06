# Retained RAM port contract

Place the caller-owned crash buffer in a board-specific NOLOAD/UNINIT section.
Exclude that section from startup zeroing and verify the bootloader/SRAM power
domain before claiming reset retention. The SDK never assigns an address.

The entire fault path, constants, stack and write buffer must be accessible when
flash is unavailable. Audit the link map and disassembly; moving only the entry
symbol to RAM is insufficient. The platform supplies cache clean and data/instruction
barriers in commit_barrier. HardFault never calls the normal ring or transmit API.

Capture commits HCR1 last, after payload CRC. An occupied slot is not overwritten.
hil_crash_read is read-only and duplicate reads must agree. A transport adapter
must persist and verify the full record on the host before offering explicit
hil_crash_clear(record_id); a UART write completion is not acknowledgement.

This port does not guarantee power-loss retention, a usable stack in lockup,
TrustZone state, or nonvolatile flash writes. Those require board-specific ports.
