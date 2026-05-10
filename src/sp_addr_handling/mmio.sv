`timescale 1ns/1ps

module mmio (
    input logic clk_i,
    input logic rst_ni,

    // interface from the addr decoder
    input logic [31:0] addr_i,
    input logic [31:0] wr_data_i,
    input logic wr_en_i, // write enable
    output logic [31:0] rd_data_o,     // read data back to cpu

    // physical connections to the serializer/pins
    output logic [7:0] gpio_pins_o, // data going out
    input logic [7:0] gpio_pins_i, // data coming in
    output logic [7:0] gpio_dir_o   // 1 = output, 0 = input
);

    // registers
    logic [7:0] data_reg; // holds pin vals
    logic [7:0] csr_reg;  // holds direction (out/in)

    // addr constants
    //localparam ADDR_DATA = 32'h8000_0010;
    //localparam ADDR_CSR = 32'h8000_0018;

    //to find which pin index (0-7) the addr refers to
    // addr 0x8000_0010 ->index 0, 0x8000_0017 -> index 7
    logic [2:0] pin_sel;
    assign pin_sel = addr_i[2:0];

    // write
    always_ff @(posedge clk_i or negedge rst_ni) begin
        if(!rst_ni) begin
            data_reg <= 8'h00;
            csr_reg <= 8'h00; // default all to inputs
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

    //read
    always_comb begin
        if(addr_i == 32'h8000_0018) begin
            rd_data_o = {24'h0, csr_reg};
        end else if((addr_i & 32'hFFFF_FFF8) == 32'h8000_0010) begin
            //if output then read what we wrote, if input then read the pin
            if(csr_reg[pin_sel]) begin
                rd_data_o = {31'h0, data_reg[pin_sel]};
            end else begin
                rd_data_o = {31'h0, gpio_pins_i[pin_sel]};
            end
        end else begin
            rd_data_o = 32'h0;
        end
    end

    assign gpio_pins_o = data_reg;
    assign gpio_dir_o = csr_reg;

endmodule
