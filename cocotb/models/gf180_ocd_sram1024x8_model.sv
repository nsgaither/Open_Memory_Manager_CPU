// SPDX-License-Identifier: Apache-2.0
//
// Minimal cocotb-only behavioral model for the GF180 3.3V ocd 1024x8 SRAM.
// Mirrors gf180_sram512x8_model.sv (synchronous read/write, active-low CEN,
// GWEN and per-bit WEN); depth 1024 -> 10-bit address. Portable across
// Icarus and Verilator (no PDK specify/timing blocks).

`timescale 1ns/1ps
`default_nettype none

module gf180mcu_ocd_ip_sram__sram1024x8m8wm1 (
    input  wire        CLK,
    input  wire        CEN,
    input  wire        GWEN,
    input  wire [7:0]  WEN,
    input  wire [9:0]  A,
    input  wire [7:0]  D,
    output logic [7:0] Q

`ifdef USE_POWER_PINS
    ,inout wire VDD,
    inout wire VSS
`endif
);

    logic [7:0] mem [0:1023];

    always_ff @(posedge CLK) begin
        if (!CEN) begin
            if (!GWEN) begin
                for (int i = 0; i < 8; i++) begin
                    if (!WEN[i]) begin
                        mem[A][i] <= D[i];
                    end
                end
            end

            Q <= mem[A];
        end
    end

endmodule

`default_nettype wire
