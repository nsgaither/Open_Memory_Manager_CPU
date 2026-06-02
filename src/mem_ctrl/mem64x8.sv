// SPDX-FileCopyrightText: © 2025 XXX Authors
// SPDX-License-Identifier: Apache-2.0

`default_nettype none

module mem64x8 (
  input  wire        clk_i,
  input  wire        enable_n_i,
  input  wire [2:0]  gwen_i,
  input  wire [23:0] wen_i,
  input  wire [5:0]  addr_i,
  input  wire [23:0] wdata_i,
  output wire [23:0] rdata_o

  `ifdef USE_POWER_PINS
    ,inout wire VDD,
    inout wire VSS
  `endif
);

    (* keep *) gf180mcu_fd_ip_sram__sram64x8m8wm1 sram0 (
        .CLK  (clk_i),
        .CEN  (enable_n_i),
        .GWEN (gwen_i[0]),
        .WEN  (wen_i[7:0]),
        .A    (addr_i),
        .D    (wdata_i[7:0]),
        .Q    (rdata_o[7:0])
        `ifdef USE_POWER_PINS
        ,.VDD (VDD)
        ,.VSS (VSS)
        `endif
    );

    (* keep *) gf180mcu_fd_ip_sram__sram64x8m8wm1 sram1 (
        .CLK  (clk_i),
        .CEN  (enable_n_i),
        .GWEN (gwen_i[1]),
        .WEN  (wen_i[15:8]),
        .A    (addr_i),
        .D    (wdata_i[15:8]),
        .Q    (rdata_o[15:8])
        `ifdef USE_POWER_PINS
        ,.VDD (VDD)
        ,.VSS (VSS)
        `endif
    );

    (* keep *) gf180mcu_fd_ip_sram__sram64x8m8wm1 sram2 (
        .CLK  (clk_i),
        .CEN  (enable_n_i),
        .GWEN (gwen_i[2]),
        .WEN  (wen_i[23:16]),
        .A    (addr_i),
        .D    (wdata_i[23:16]),
        .Q    (rdata_o[23:16])
        `ifdef USE_POWER_PINS
        ,.VDD (VDD)
        ,.VSS (VSS)
        `endif
    );

endmodule

`default_nettype wire
