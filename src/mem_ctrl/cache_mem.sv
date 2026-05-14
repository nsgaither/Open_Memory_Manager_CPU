// SPDX-FileCopyrightText: © 2025 Albert Felix
// SPDX-License-Identifier: Apache-2.0

// wrapper around memory types to make accessing cache data and state
// more clean
 
`default_nettype none

module cache_mem
(
  input  wire        clk_i,
  input  wire        rst_ni,

  // input interface
  input  wire         valid_i,
  output wire         ready_o,
  input  wire [31:0]  addr_i,
  input  wire [31:0]  wdata_i,  // data to write
  input  wire [3:0]   wstrb_i, 
  input  wire [1:0]   wstate_i, // state to write
  input  wire [1:0]   wtag_i, // tag to write

  // output interface
  output wire [31:0]  rdata_o, // data read
  output wire [1:0]   rtag_o, // tag read
  output wire [1:0]   rstate_o, // state read
  output wire         valid_o,
  input  wire         ready_i
);

  // combine tag_i and state_i for easier storage
  logic [3:0] tag_plus_state_i;
  assign tag_plus_state_i = {wtag_i, wstate_i}; 

  // decombine tag_o and state_o from stored 
  logic [3:0] tag_plus_state_o;
  assign rtag_o = tag_plus_state_o[3:2];
  assign rstate_o= tag_plus_state_o[1:0];

  // combine ready_o and valid_o of both modules
  logic tag_mem_ready, data_mem_ready;
  logic tag_mem_valid, data_mem_valid;
  assign ready_o = (tag_mem_ready & data_mem_ready);
  assign valid_o = (tag_mem_valid & data_mem_valid);

  
  mem_ctrl_128x4 tag
  (
    .clk_i(clk_i),
    .rst_ni(rst_ni),
    .mem_valid_i(valid_i),
    .mem_ready_o(tag_mem_ready),
    .mem_addr_i(addr_i),
    .mem_wdata_i(tag_plus_state_i),
    .mem_read_en_i((wstrb_i == 4'b0000) ? 1'b1 : 1'b0),
    .mem_rdata_o(tag_plus_state_o),
    .mem_valid_o(tag_mem_valid),
    .mem_ready_i(ready_i && data_mem_valid)
  );

  mem_ctrl_128x32 data
  (
    .clk_i(clk_i),
    .rst_ni(rst_ni),
    .mem_valid_i(valid_i),
    .mem_ready_o(data_mem_ready),
    .mem_addr_i(addr_i),
    .mem_wdata_i(wdata_i),
    .mem_wstrb_i(wstrb_i),   
    .mem_rdata_o(rdata_o),
    .mem_valid_o(data_mem_valid),
    .mem_ready_i(ready_i)
  );

endmodule

`default_nettype wire
