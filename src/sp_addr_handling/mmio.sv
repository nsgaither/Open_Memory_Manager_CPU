`timescale 1ns/1ps

module mmio (
    input logic clk_i,
    input logic rst_ni,

    // DFT scan interface. debug_mode_i is the scan/functional mux select.
    input  logic debug_mode_i,
    input  logic scan_in_i,
    output logic scan_out_o,

    // interface from the addr decoder
    input logic [31:0] addr_i,
    input logic [31:0] wr_data_i, /* verilator lint_off UNUSEDSIGNAL */
    input logic wr_en_i, // write enable
    output logic [31:0] rd_data_o,     // read data back to cpu
    /* verilator lint_on UNUSEDSIGNAL */

    // physical connections to the serializer/pins
    output logic [7:0] gpio_pins_o, // data going out
    input logic [7:0] gpio_pins_i, // data coming in
    output logic [7:0] gpio_dir_o   // 1 = output, 0 = input
);

    // registers
    logic [7:0] data_reg; // holds pin vals
    logic [7:0] csr_reg;  // holds direction (out/in)

    logic [15:0] scan_state;
    assign scan_state = {csr_reg, data_reg};
    assign scan_out_o = scan_state[15];

    // addr constants
    //localparam ADDR_DATA = 32'h8000_0010;
    //localparam ADDR_CSR = 32'h8000_0018;

    //to find which pin index (0-7) the addr refers to
    // addr 0x8000_0010 ->index 0, 0x8000_0017 -> index 7
    logic [2:0] pin_sel;
    assign pin_sel = addr_i[2:0];

    // write
    always_ff @(posedge clk_i) begin
        if(!rst_ni) begin
            data_reg <= 8'h00;
            csr_reg <= 8'h00; // default all to inputs
        end else if (debug_mode_i) begin
            {csr_reg, data_reg} <= {scan_state[14:0], scan_in_i};
        end else if(wr_en_i) begin
            //case where we write to csr (all 8 bits at once)
            if(addr_i == 32'h8000_0018) begin
                csr_reg <= wr_data_i[7:0];
            //case where we write to specici data pin
            end else if((addr_i & 32'hFFFF_FFF8) == 32'h8000_0010) begin
                //only write if csr says this pin is output
                if(csr_reg[pin_sel]) begin
                    data_reg[pin_sel] <= wr_data_i[0]; //only care about lsb
                end
            end
        end
    end

    // Two-flop synchronizer for the asynchronous GPIO input pins before they
    // are sampled into the CPU read datapath. These flops are deliberately
    // kept off the scan chain so scan-mux insertion cannot weaken the
    // metastability hardening; they reset to 0 to avoid X-propagation.
    logic [7:0] gpio_pins_meta, gpio_pins_sync;
    always_ff @(posedge clk_i) begin
        if (!rst_ni) begin
            gpio_pins_meta <= 8'h00;
            gpio_pins_sync <= 8'h00;
        end else begin
            gpio_pins_meta <= gpio_pins_i;
            gpio_pins_sync <= gpio_pins_meta;
        end
    end

    //read
    always_comb begin
        if(addr_i == 32'h8000_0018) begin
            rd_data_o = {24'h0, csr_reg};
        end else if((addr_i & 32'hFFFF_FFF8) == 32'h8000_0010) begin
            //if output then read what we wrote, if input then read the pin
            if(csr_reg[pin_sel]) begin
                rd_data_o = {31'h0, data_reg[pin_sel]};
            end else begin
                rd_data_o = {31'h0, gpio_pins_sync[pin_sel]};
            end
        end else begin
            rd_data_o = 32'h0;
        end
    end

    assign gpio_pins_o = data_reg;
    assign gpio_dir_o = csr_reg;

endmodule
