# OMM/OMM_CPU Stress Programs

Small RV32IM assembly programs for bring-up and stress testing with two
OMM_CPU chips connected through an OMM interposer.

These programs are intentionally tiny so they fit in the 512-byte boot image
used by the current flash boot flow.

## Build

Use a RISC-V bare-metal GCC toolchain. The script tries
`riscv32-unknown-elf-` first, then `riscv64-unknown-elf-`. Override with
`CROSS_PREFIX` if your tools use another prefix.

```sh
./build.sh alive_gpio_stress.S
./build.sh pingpong_coherence_stress.S
```

Outputs are written under `build/`:

- `*.elf` - linked ELF
- `*.bin` - raw binary
- `*.mem` - Cypress flash-model style byte-per-line image with `@000000`

For the existing cocotb flash model, use the generated `.mem` as
`boot_image.mem`. For hardware, program the corresponding raw bytes at flash
offset `0x000000`.

## Programs

`alive_gpio_stress.S`

- Safe first bring-up test.
- Reads `whoami` from `0x80000000`.
- Configures GPIO pins as outputs through `0x80000018`.
- Continuously toggles GPIO pins with a CPU-ID-dependent pattern.
- Exercises instruction fetch, branches, ALU ops, multiply, and divide.
- Does not intentionally write normal shared memory.

`pingpong_coherence_stress.S`

- Full two-OMM_CPU-plus-OMM interposer stress test.
- Same binary can run on both CPU chips; each chip chooses a role from
  `whoami[0]`.
- Repeatedly reads and writes a small set of shared external addresses.
- Uses addresses with matching low index bits and different tag bits to create
  cache misses, ownership transfers, snoops, and dirty evictions with little
  code.
- Also drives GPIO heartbeat/status patterns.

If `pingpong_coherence_stress.S` stalls, that is useful data: normal memory
traffic depends on the OMM directory/interposer path responding correctly.

## MMIO Used

- `0x80000000` - `whoami` read, low byte is the OMM-assigned CPU ID.
- `0x80000010..0x80000017` - one GPIO data bit per address.
- `0x80000018` - GPIO direction register, `1` means output.
- `0x80000020` - flush trigger in the current RTL. These tests avoid relying
  on it for correctness because the present address handler triggers a fixed
  flush address.
