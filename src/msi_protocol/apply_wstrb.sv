`timescale 1ns/1ps
`default_nettype none

module apply_wstrb
(
  input  logic [31:0] base_data_i,
  input  logic [31:0] wdata_i,
  input  logic [3:0]  wstrb_i,
  output logic [31:0] result_o
);

  assign result_o[7:0]   = wstrb_i[0] ? wdata_i[7:0]   : base_data_i[7:0];
  assign result_o[15:8]  = wstrb_i[1] ? wdata_i[15:8]  : base_data_i[15:8];
  assign result_o[23:16] = wstrb_i[2] ? wdata_i[23:16] : base_data_i[23:16];
  assign result_o[31:24] = wstrb_i[3] ? wdata_i[31:24] : base_data_i[31:24];

endmodule

