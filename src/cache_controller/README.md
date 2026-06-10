# Cache Controller RTL + Cocotb Verification

This directory contains the cache-controller RTL and the MSI transition helpers
used by `cache_controller.sv`.

## RTL Files

- `cache_controller.sv`
  Top-level cache controller integration.

- `on_processor_event_state_machine.sv`
  Combinational MSI transition helper for local processor reads and writes. It
  maps `current_state_i` and `wstrb_i` to `next_state_o`, `issue_cmd_o`, and
  `issue_cmd_valid_o`.

- `on_snoop_event_state_machine.sv`
  Combinational MSI transition helper for snoop traffic from the directory. It
  maps `current_state_i` and `snoop_event_i` to `next_state_o` and `flush_o`.

- `outbound_arbiter.sv`
  Arbitration logic for outbound cache-controller traffic.

- `apply_wstrb.sv`
  Byte-strobe merge helper for partial writes.

## MSI Encodings

### States

| Name | Value |
| --- | --- |
| `INVALID` | `2'b00` |
| `SHARED` | `2'b01` |
| `MODIFIED` | `2'b10` |

### Processor Events

`on_processor_event_state_machine.sv` derives the processor event from
`wstrb_i`:

| Condition | Event |
| --- | --- |
| `wstrb_i == 4'd0` | read |
| `wstrb_i != 4'd0` | write |

### Snoop Events

| Name | Value |
| --- | --- |
| `BUS_RD` | `3'b001` |
| `BUS_RDX` | `3'b010` |
| `BUS_UPGR` | `3'b100` |

### Directory Commands

| Name | Value |
| --- | --- |
| `BUS_RD` | `9'b000000001` |
| `BUS_RDX` | `9'b000000010` |
| `BUS_UPGR` | `9'b000000100` |
| `EVICT_CLEAN` | `9'b000001000` |
| `EVICT_DIRTY` | `9'b000010000` |
| `NONE` | `9'b000000000` |

## Verification

The state-machine cocotb tests compare the RTL against the Python MSI reference
model in `cocotb/emulation/msi.py`.

From the repository root:

```bash
make test-on-processor-event-state-machine
make test-on-snoop-event-state-machine
make test-cache-controller
make test-cache-mem
make test-all
```

Waveforms are written under `cocotb/sim_build*/`.
