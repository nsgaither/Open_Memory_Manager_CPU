// SPDX-License-Identifier: Apache-2.0
//
// Minimal cocotb-only behavioral model for the GF180 512x8 SRAM.
// Used by chip-top SDF runs because Icarus rejects the PDK SRAM specify paths.

`timescale 1ns/1ps
`default_nettype none

module gf180mcu_fd_ip_sram__sram512x8m8wm1 (
    input  wire       CLK,
    input  wire       CEN,
    input  wire       GWEN,
    input  wire [7:0] WEN,
    input  wire [8:0] A,
    input  wire [7:0] D,
    output logic [7:0] Q

`ifdef USE_POWER_PINS
    ,inout wire VDD,
    inout wire VSS
`endif
);

    logic [7:0] mem [0:511];

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
