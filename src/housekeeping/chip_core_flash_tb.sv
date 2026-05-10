`timescale 1ns/1ps

// test wrapper that instantiates chip_core with the cypress flash model connected through pad indices
// pad assignments: () match localparams in chip_core.sv)
//   input_in[0] = pass_thru_en
//   input_in[1] = MISO (flash SO)
//   bidir_out[8] = SCK (flash SI clock)
//   bidir_out[9] = MOSI (flash SI data)
//   bidir_out[10]= CSB (flash chip select)

module chip_core_flash_tb #(
    parameter NUM_INPUT_PADS = 12,
    parameter NUM_BIDIR_PADS = 40,
    parameter NUM_ANALOG_PADS = 2
)(
    input logic clk,
    input logic rst_n,
    input logic [NUM_INPUT_PADS-1:0] input_in,
    input logic [NUM_BIDIR_PADS-1:0] bidir_in,
    output logic boot_done_o,
    output logic cores_en_o
);

    //wires for chip_core pad interface
    logic [NUM_INPUT_PADS-1:0] input_pu;
    logic [NUM_INPUT_PADS-1:0] input_pd;
    logic [NUM_BIDIR_PADS-1:0] bidir_out;
    logic [NUM_BIDIR_PADS-1:0] bidir_oe;
    logic [NUM_BIDIR_PADS-1:0] bidir_cs;
    logic [NUM_BIDIR_PADS-1:0] bidir_sl;
    logic [NUM_BIDIR_PADS-1:0] bidir_ie;
    logic [NUM_BIDIR_PADS-1:0] bidir_pu;
    logic [NUM_BIDIR_PADS-1:0] bidir_pd;
    wire [NUM_ANALOG_PADS-1:0] analog;

    chip_core #(
        .NUM_INPUT_PADS  (NUM_INPUT_PADS),
        .NUM_BIDIR_PADS  (NUM_BIDIR_PADS),
        .NUM_ANALOG_PADS (NUM_ANALOG_PADS)
    ) dut (
        .clk       (clk),
        .rst_n     (rst_n),
        .input_in  (input_in),
        .input_pu  (input_pu),
        .input_pd  (input_pd),
        .bidir_in  (bidir_in),
        .bidir_out (bidir_out),
        .bidir_oe  (bidir_oe),
        .bidir_cs  (bidir_cs),
        .bidir_sl  (bidir_sl),
        .bidir_ie  (bidir_ie),
        .bidir_pu  (bidir_pu),
        .bidir_pd  (bidir_pd),
        .analog    (analog)
    );

    //get spi signals from the bidir pad outputs
    //bidir_out[8]=SCK, bidir_out[9]=MOSI, bidir_out[10]=CSB
    wire flash_sck = bidir_out[8];
    wire flash_mosi = bidir_out[9];
    wire flash_csb = bidir_out[10];

    //MISO comes from input_in[1]— driven by cocotb or flash model
    wire flash_miso = input_in[1];

    //flash model tie-off wires (inout ports)
    wire wp_tie;
    wire io3_tie;
    assign wp_tie = 1'b1;
    assign io3_tie = 1'b1;

    //cypress flash model
    s25fl128l #(
        .UserPreload   (1),
        .mem_file_name ("boot_image.mem"),
        .TimingModel   ("S25fl128LAGMFI010")
    ) u_flash (
        .SI           (flash_mosi),
        .SO           (flash_miso),
        .SCK          (flash_sck),
        .CSNeg        (flash_csb),
        .RESETNeg     (1'b1),
        .WPNeg        (wp_tie),
        .IO3_RESETNeg (io3_tie)
    );

    //expose boot status signals for cocotb
    assign boot_done_o = dut.i_housekeeping.boot_done_o;
    assign cores_en_o = dut.i_housekeeping.cores_en_o;

endmodule