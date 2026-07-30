# OMM_CPU

A RISC-V RV32IM SoC targeting the GlobalFoundries 180nm (GF180MCU) process, designed for the wafer.space MPW shuttle program.

The core is a **PicoRV32** CPU with multiply/divide (RV32IM), backed by a custom memory controller with a 512x8 SRAM, a tag SRAM controller, and a cache controller placeholder for future coherent caching. The design is implemented using the [LibreLane](https://librelane.readthedocs.io/) open-source ASIC flow.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      chip_top                               │
│  ┌─────────────────────────────────────────────────────────┐│
│  │  Pad Ring (GF180MCU I/O cells)                          ││
│  └──────────┬──────────────────────────────────────────────┘│
│  ┌──────────▼──────────────────────────────────────────────┐│
│  │                    chip_core                            ││
│  │                                                         ││
│  │  ┌──────────────┐    ┌────────────────────────────┐     ││
│  │  │  PicoRV32    │◄──►│  mem128x32 (memory ctrl)   │     ││
│  │  │  (RV32IM)    │    │  512x8 SRAM → 128x32 words │     ││
│  │  │  25 MHz      │    │  4-cycle access latency    │     ││
│  │  └──────────────┘    └────────────────────────────┘     ││
│  │                          ┌────────────────────────┐     ││
│  │                          │  mem128x4 (tag SRAM)   │     ││
│  │                          │  64x8 SRAM → 128x4     │     ││
│  │                          └────────────────────────┘     ││
│  │  ┌──────────────────────────────────────────────────┐   ││
│  │  │  cache_controller                                │   ││
│  │  └──────────────────────────────────────────────────┘   ││
│  └─────────────────────────────────────────────────────────┘│
│                                                             │
│  ┌──────────────────────┐  ┌──────────────────────┐         │
│  │  wafer.space chip ID │  │  wafer.space logo    │         │
│  └──────────────────────┘  └──────────────────────┘         │
└─────────────────────────────────────────────────────────────┘
```

### Blocks

| Block | Description |
|---|---|
| **PicoRV32** | Size-optimized RISC-V RV32I core with M extension (multiply/divide), native valid/ready memory interface |
| **mem128x32** | Memory controller multiplexing 32-bit CPU accesses across 4 cycles to a single 512x8 SRAM macro (area-constrained) |
| **mem128x4** | Tag SRAM controller backed by a 64x8 SRAM, storing 128 4-bit tag/state entries |
| **cache_controller** | Stub for future coherent cache with directory-based coherence and snoop interface |
| **chip_id / logo** | Hard macros for wafer.space die marking (QR code and logo GDS) |

## Dependencies

Too manage all dependencies, the project template includes a Nix shell with all the required tools.
Install Nix and LibreLane by following the Nix-based installation instructions: https://librelane.readthedocs.io/en/latest/installation/nix_installation/index.html
To activate the shell, simply run `nix-shell` in the root directory of this repository. The subsequent steps assume that you are in the Nix shell of the project template.

## Prerequisites

The project template uses the open_pdks gf180mcuD variant of the PDK.
To clone the latest PDK version via [Ciel](https://github.com/fossi-foundation/ciel), run `make clone-pdk`.

## Usage

Enter the Nix development shell:

```
nix-shell
```

Run a singular command in nix-shell:

```
nix-shell --run "your-cmd"
```

### Implement the Design

```
make librelane
```

View the result in OpenROAD or KLayout:

```
make librelane-openroad
make librelane-klayout
```

| Slot  | Dimensions |
|---|---|
| `0p5x0p5` | 0.5 mm × 0.5 mm |

### Verification

Cocotb-based testbenches using Icarus Verilog:

| Command | Description |
|---|---|
| `make sim` | RTL simulation of the full chip |
| `make sim-gl` | Gate-level simulation (after `final/` populated) |
| `make sim-view` | View waveforms in GTKWave |
| `make test-chip-top` | Top-level pad, scan, and reset-gating tests |
| `make test-mem128x32` | Main data-memory controller tests |
| `make test-mem-ctrl-128x4` | Tag/state memory-controller tests |

### Padring-Only Build

For analog designs that need just the padring without standard cells:

```
make librelane-padring
```

## Simulation Tests

- **chip_top_tb.py** — Full-chip tests: reset/clock, pad I/O, memory controller FSM, CPU instruction fetch, trap on illegal instruction, SRAM interface timing, GPIO, system stress
- **mem128x32_tb.py** — Memory controller timing and byte-level write tests
- **cache_sram_test.py** — 10,000 random transactions against a Python golden model

## Source Files

All RTL sources are in `src/`:

- `chip_top.sv` — Top-level chip with pad ring instantiations
- `chip_core.sv` — Core design instantiating CPU, memory controllers, and cache controller
- `cache_controller/cache_controller.sv` — Coherent cache placeholder
- `mem_ctrl/mem128x32.sv` — Main memory controller (512x8 SRAM)
- `mem_ctrl/mem128x4.sv` — Tag SRAM controller (64x8 SRAM)
- `slot_defines.svh` — Pad counts per slot size

## Precheck

To check whether your design is suitable for manufacturing, run the [gf180mcu-precheck](https://github.com/wafer-space/gf180mcu-precheck) with your layout.

## License

Apache 2.0 — see [LICENSE](https://github.com/nsgaither/Open_Memory_Manager_CPU/blob/main/LICENSE).
