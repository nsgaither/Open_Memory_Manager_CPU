// SPDX-FileCopyrightText: © 2025 Albert Felix
// SPDX-License-Identifier: Apache-2.0

`timescale 1ns/1ps
`default_nettype none

module cache_controller
(
  input  logic        clk_i,
  input  logic        rst_ni,

  // ── Processor → Cache ────────────────────────────────────────────
  input  logic        mem_valid,
  input  logic        mem_instr,
  input  logic [31:0] mem_addr,
  input  logic [31:0] mem_wdata,
  input  logic [3:0]  mem_wstrb,
  output logic        mem_ready,
  output logic [31:0] mem_rdata,

  // ── Cache → Directory (outbound coherence request) ────────────────
  output logic        cache_valid_o,
  output logic [31:0] cache_addr_o,
  output logic [31:0] cache_data_o,
  output logic [8:0]  cache_cmd_o,
  input  logic        cache_ready_i,

  // ── Directory → Cache (inbound coherence response) ────────────────
  input  logic        bus_valid_i,
  input  logic [31:0] bus_data_i,
  input  logic [2:0]  bus_dircmd_i,
  output logic        bus_ready_o,

  // ── Snoop Request (Directory → Cache) ─────────────────────────────
  input  logic        snoop_valid_i,
  input  logic [31:0] snoop_addr_i,
  input  logic [2:0]  snoop_dircmd_i,
  output logic [31:0] flushed_data_o,
  output logic        flushed_valid_o,
  output logic        snoop_ready_o
);

endmodule

`default_nettype wire
