`timescale 1ns/1ps

// test wrapper that instantiates chip_core and exposes boot status signals.
// The 48-bidir pinout no longer routes SPI flash pins to top-level pads.

module chip_core_flash_tb #(
    parameter NUM_BIDIR_PADS = 48
)(
    input logic clk,
    input logic rst_n,
    input logic [NUM_BIDIR_PADS-1:0] bidir_in,
    output logic boot_done_o,
    output logic cores_en_o
);

    //wires for chip_core pad interface
    logic [NUM_BIDIR_PADS-1:0] bidir_out;
    logic [NUM_BIDIR_PADS-1:0] bidir_oe;
    logic [NUM_BIDIR_PADS-1:0] bidir_cs;
    logic [NUM_BIDIR_PADS-1:0] bidir_sl;
    logic [NUM_BIDIR_PADS-1:0] bidir_ie;
    logic [NUM_BIDIR_PADS-1:0] bidir_pu;
    logic [NUM_BIDIR_PADS-1:0] bidir_pd;

    chip_core #(
        .NUM_BIDIR_PADS  (NUM_BIDIR_PADS)
    ) dut (
        .clk       (clk),
        .rst_n     (rst_n),
        .bidir_in  (bidir_in),
        .bidir_out (bidir_out),
        .bidir_oe  (bidir_oe),
        .bidir_cs  (bidir_cs),
        .bidir_sl  (bidir_sl),
        .bidir_ie  (bidir_ie),
        .bidir_pu  (bidir_pu),
        .bidir_pd  (bidir_pd)
    );

    //expose boot status signals for cocotb
    assign boot_done_o = dut.i_housekeeping.boot_done_o;
    assign cores_en_o = dut.i_housekeeping.cores_en_o;

endmodule
