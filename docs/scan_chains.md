# Debug scan chains

## External interface

The eight GPIO pads beginning at `DEBUG_START_ID` are shared with four debug
scan chains. `bidir[DEBUG_ID]` is the mux selector.

| Debug mode | Pads `DEBUG_START_ID + 0` through `+3` | Pads `DEBUG_START_ID + 4` through `+7` |
|---|---|---|
| `0` | GPIO `[3:0]`, using the programmed GPIO directions | GPIO `[7:4]`, using the programmed GPIO directions |
| `1` | Scan inputs for chains 0 through 3 | Scan outputs for chains 0 through 3 |

For the current pinout, `DEBUG_ID` is 0 and `DEBUG_START_ID` is 23. Thus the
scan inputs are `bidir[23:26]` and the corresponding outputs are
`bidir[27:30]`.

With global reset deasserted, each rising clock edge in debug mode shifts one
bit into every chain. The tables below list registers from scan input toward
scan output; each vector is traversed least-significant bit first. To load a
specific complete state, transmit the desired values in the reverse of the
listed order. Deasserting debug mode leaves the inserted values in the real
functional registers, and the next rising edge resumes their original update
logic.

PicoRV32 is intentionally not part of DFT. The SRAM bitcell arrays are also not
scan elements; their controller state, address, and data registers are part of
the chains. SRAM chip/write enables are held inactive while shifting so an
arbitrary intermediate scan state cannot corrupt an array.

## Chain 0: startup, address/GPIO, and receive pipes

Input: `bidir[23]`  
Output: `bidir[27]`  
Length: 139 bits

| Order | Instance | Registers | Bits |
|---:|---|---|---:|
| 1 | `i_chip_core` | `mem_init_count[0:9]` | 10 |
| 2 | `u_sp_addr_handler` | `flush_valid_r`, `flush_addr_r[0:31]` | 33 |
| 3 | `u_sp_addr_handler.mmio_inst` | `data_reg[0:7]`, `csr_reg[0:7]` | 16 |
| 4 | `u_cache_interface.bus_ack_pipe` | `valid_o_r`, `data_r[0:34]` | 36 |
| 5 | `u_cache_interface.snoop_pipe` | `valid_o_r`, `data_r[0:34]` | 36 |
| 6 | `u_cache_interface` | `cpu_id_r[0:7]` | 8 |

## Chain 1: cache-controller state

Input: `bidir[24]`  
Output: `bidir[28]`  
Length: 198 bits

All entries are in `u_cache_controller`.

| Order | Registers | Bits |
|---:|---|---:|
| 1 | `cpu_state_q[0:3]` | 4 |
| 2 | `snp_state_q[0:2]` | 3 |
| 3 | `cpu_addr_q[0:31]` | 32 |
| 4 | `cpu_wdata_q[0:31]` | 32 |
| 5 | `cpu_wstrb_q[0:3]` | 4 |
| 6 | `cpu_next_state_q[0:1]` | 2 |
| 7 | `cpu_issue_cmd_q[0:8]` | 9 |
| 8 | `cpu_cmd_valid_q` | 1 |
| 9 | `cpu_line_data_q[0:31]` | 32 |
| 10 | `cpu_line_tag_q[0:1]` | 2 |
| 11 | `cpu_line_state_q[0:1]` | 2 |
| 12 | `tag_match_cpu_q` | 1 |
| 13 | `snp_addr_q[0:31]` | 32 |
| 14 | `snp_dircmd_q[0:2]` | 3 |
| 15 | `snp_next_state_q[0:1]` | 2 |
| 16 | `snp_tag_q[0:1]` | 2 |
| 17 | `snp_flush_q` | 1 |
| 18 | `snp_flush_data_q[0:31]` | 32 |
| 19 | `snp_line_state_q[0:1]` | 2 |

## Chain 2: cache memory controls and outbound arbiter

Input: `bidir[25]`  
Output: `bidir[29]`  
Length: 214 bits

| Order | Instance | Registers | Bits |
|---:|---|---|---:|
| 1 | `u_cache_controller.cache_mem` | `busy`, `active_port`, `last_grant` | 3 |
| 2 | `u_cache_controller.cache_mem.u_cache_mem.tag` | `state_q[0:2]`, `reset_addr_q[0:5]`, `addr_q[0:5]`, `nibble_sel_q`, `wdata_q[0:3]`, `data_read_q[0:7]`, `data_to_write_q[0:7]` | 36 |
| 3 | `u_cache_controller.cache_mem.u_cache_mem.data` | `state_q[0:3]`, `reset_addr_q[0:8]`, `addr_q[0:8]`, `wdata_q[0:31]`, `mode_q[0:3]`, `data_read_q[0:31]`, `data_to_write_q[0:7]` | 98 |
| 4 | `u_cache_controller.outbound_ctrl` | `state_q[0:1]`, `rr_q`, `cache_valid_q`, `cache_addr_q[0:31]`, `cache_data_q[0:31]`, `cache_cmd_q[0:8]` | 77 |

## Chain 3: serializers

Input: `bidir[26]`  
Output: `bidir[30]`  
Length: 119 bits

| Order | Instance | Registers | Bits |
|---:|---|---|---:|
| 1 | `u_cache_interface.u_tserializer` | `current_state`, `curr_msg_len[0:3]`, `count[0:3]`, flattened `shift_arr[0][0]` through `shift_arr[7][8]` | 81 |
| 2 | `u_cache_interface.u_rserializer` | `current_state`, flattened `shift_arr[0][0]` through `shift_arr[3][8]`, `valid_o` | 38 |

## Functional-mode isolation

Every modified sequential block retains its original reset and functional
branches. The only added state-update branch is selected by `debug_mode_i`.
When `bidir[DEBUG_ID]` is low, the GPIO pad directions/data and all register
updates follow their original logic; the scan outputs are not enabled onto the
shared pads.
