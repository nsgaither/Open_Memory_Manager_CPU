# MSI Protocol RTL + Cocotb Verification

This folder contains a synthesizable Verilog implementation of an MSI coherence finite state machine and a cocotb testbench that exhaustively verifies its behavior against a golden Python reference model.

## What this module is

`msi_protocol` implements the **MSI cache line coherence policy** for a single line. It models three coherence states:

- `I` (Invalid)
- `S` (Shared)
- `M` (Modified)

It reacts to two classes of events:

1. **Processor events** (local cache access)
2. **Snoop events** (observed coherence traffic from other agents)

The module is written as a classic **Mealy style FSM**:

- The registered state is `CS`
- Combinational logic computes `NS` and outputs from `CS + inputs`
- Outputs are meaningful in the cycle the inputs are asserted (before the next clock edge)

This is why the cocotb testbench samples outputs **before** the rising edge.

## Interface

### Inputs

- `clk_i`  
  Clock.

- `reset_i`  
  Active high reset. Resets internal state to `I`.

- `current_state [1:0]`  
  Present in the interface for integration, but **not used** by this implementation. The internal state register `CS` is the state source of truth.

- `proc_valid`  
  When high, a processor event is present this cycle.

- `proc_event`  
  Processor event encoding:
  - `PR_RD` (0): processor read
  - `PR_WR` (1): processor write

- `snoop_valid`  
  When high, a snoop event is present this cycle.

- `snoop_event [1:0]`  
  Snoop event encoding:
  - `BUS_RD` (0): another cache is reading
  - `BUS_RDX` (1): another cache requests exclusive ownership
  - `BUS_UPGR` (2): another cache upgrades from shared to modified

### Outputs

- `next_state [1:0]`  
  Combinational next state `NS`.

- `cmd_valid`  
  Indicates the module is issuing a cache initiated coherence request during a **processor event**.

- `issue_cmd [2:0]`  
  Coherence command encoding. Only meaningful when `cmd_valid=1`.

- `flush`  
  Indicates the cache must flush or supply dirty data on a snoop (only asserted when current state is `M` and snoop requires it).

## Encodings

### States

| Name | Value |
| --- | --- |
| `I` | `2'b00` |
| `S` | `2'b01` |
| `M` | `2'b10` |

### Processor Events

| Name | Value |
| --- | --- |
| `PR_RD` | `1'b0` |
| `PR_WR` | `1'b1` |

### Snoop Events

| Name | Value |
| --- | --- |
| `BUS_RD` | `2'b00` |
| `BUS_RDX` | `2'b01` |
| `BUS_UPGR` | `2'b10` |

### Coherence Commands (`issue_cmd`)

This implementation defines eight possible command values even though not all are produced in the current RTL.

| Name | Value |
| --- | --- |
| `CMD_BUS_RD` | `3'd0` |
| `CMD_BUS_RDX` | `3'd1` |
| `CMD_BUS_UPGR` | `3'd2` |
| `CMD_EVICT_CLEAN` | `3'd3` |
| `CMD_EVICT_DIRTY` | `3'd4` |
| `CMD_SNOOP_BUS_RD` | `3'd5` |
| `CMD_SNOOP_BUS_RDX` | `3'd6` |
| `CMD_SNOOP_BUS_UPGR` | `3'd7` |

Important behavior conventions used by this design:

- `cmd_valid` is only asserted on **processor initiated** transitions that require a bus transaction.
- On snoop events, `cmd_valid` must remain `0`.
- On processor events, `flush` must remain `0`.

## FSM behavior summary

### Processor events (`proc_valid=1`)

| Current | Event | Next | cmd_valid | issue_cmd |
| --- | --- | --- | --- | --- |
| I | PR_RD | S | 1 | BUS_RD |
| I | PR_WR | M | 1 | BUS_RDX |
| S | PR_RD | S | 0 | none |
| S | PR_WR | M | 1 | BUS_UPGR |
| M | PR_RD | M | 0 | none |
| M | PR_WR | M | 0 | none |

### Snoop events (`snoop_valid=1`, and `proc_valid=0`)

| Current | Snoop | Next | flush |
| --- | --- | --- | --- |
| I | any | I | 0 |
| S | BUS_RD | S | 0 |
| S | BUS_RDX | I | 0 |
| S | BUS_UPGR | I | 0 |
| M | BUS_RD | S | 1 |
| M | BUS_RDX | I | 1 |
| M | BUS_UPGR | M | 0 |

`M + BUS_UPGR` is treated as a protocol violation and handled gracefully by holding `M` and not flushing.

### Arbitration between proc and snoop

If both `proc_valid` and `snoop_valid` are asserted in the same cycle, **processor events take priority** because the RTL uses:

- `if (proc_valid) ... else if (snoop_valid) ...`

The testbench includes an explicit illegal input test that ensures `flush` and `cmd_valid` are never asserted simultaneously.

## Cocotb verification

The cocotb testbench drives the RTL and compares results against a golden Python reference model in `msi_v2.py`.

### Golden model

The reference model provides:

- `on_processor_event(state, event) -> TransitionResult`
- `on_snoop_event(state, event) -> TransitionResult`

Each `TransitionResult` includes at least:

- `next_state`
- `issue_cmd` (or None)
- `flush`

The testbench maps Python command enum values into the Verilog 3 bit encoding via `PYTHON_TO_V_CMD`.

### Sampling rule

All transition outputs are sampled **before** the rising clock edge:

- The FSM uses a registered state `CS`
- Inputs are applied while `CS` is stable
- `NS`, `cmd_valid`, `issue_cmd`, and `flush` are combinational
- The testbench waits `Timer(1, ns)` to settle combinational logic, then samples outputs
- Only after sampling does it clock the design to advance `CS`

### Tests included

1. `test_reset`  
   Checks outputs are idle after reset and `next_state=INVALID`.

2. `test_all_processor_transitions`  
   Exhaustively checks all 6 state x processor event combinations.

3. `test_all_snoop_transitions`  
   Exhaustively checks all 9 state x snoop event combinations.

4. `test_idle_no_valid`  
   With both valids low, state must hold and outputs must be idle.

5. `test_both_valid_illegal`  
   Drives both valids high and asserts `flush` and `cmd_valid` are never both 1.

6. `test_sequential_transitions`  
   Runs a realistic sequence:
   - I + PR_RD -> S
   - S + PR_WR -> M
   - M + BUS_RDX -> I

7. `test_modified_busupgr_protocol_violation`  
   Verifies `M + BUS_UPGR` is handled gracefully.

## Running the simulation

From the repository root:

```bash
make test-msi
```

To view waveforms:

```bash
make test-msi-view
```

Waveforms will be written to:

- `cocotb/msi/sim_build/msi_protocol.fst`

## Notes and limitations

- `current_state` is currently unused. The module is self contained and holds coherence state internally in `CS`.
- Eviction behavior is not implemented even though eviction command encodings exist.
- The module models MSI policy for one cache line and does not include tag matching, data arrays, directory sharer tracking, or multi core arbitration.

