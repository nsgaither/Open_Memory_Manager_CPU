`timescale 1ns/1ps

module housekeeping_top #(
   parameter BOOT_SIZE = 32,
   parameter SRAM_BASE_ADDR = 32'h0000_0000
)(
   input logic clk_i,
   input logic reset_ni,
    
   // spi Flash pins
   output logic spi_sck_o,
   output logic spi_mosi_o,
   input logic spi_miso_i,
   output logic flash_csb_o,

   input logic pass_thru_en_i,   // switch: 0 = boot, 1 = pass thru
    
   // output writing
   output logic        mem_valid_o,
   output logic [31:0] mem_addr_o,
   output logic [31:0] mem_wdata_o,
   output logic [3:0]  mem_wstrb_o,
   output logic        mem_instr_o,
    
   // Core control
   output logic cores_en_o,
   output logic boot_done_o
);
   // wires between spi and fsm
   logic spi_start;
   logic spi_done;
   logic spi_busy;
   logic [7:0] spi_data_out;
   logic [7:0] spi_data_in;

   // internal wires from boot_fsm to mem controller adapter
    logic boot_wr_en;
    logic [31:0] boot_addr;
    logic [31:0] boot_data;

    //boot_fsm signals to memory controller interface
    assign mem_valid_o = boot_wr_en;
    assign mem_addr_o = boot_addr;
    assign mem_wdata_o = boot_data;
    assign mem_wstrb_o = boot_wr_en ? 4'b1111 : 4'b0000;
    assign mem_instr_o = 1'b0;
      
   // spi Engine
   spi_engine spi_master (
      .clk_i(clk_i),
      .reset_ni(reset_ni && !pass_thru_en_i),   //keep spi idle during pass thur
      .start_i(spi_start),
      .data_in_i(spi_data_out),
      .data_out_o(spi_data_in),
      .done_o(spi_done),
      .busy_o(spi_busy),
      .spi_sck_o(spi_sck_o), 
      .spi_mosi_o(spi_mosi_o),
      .spi_miso_i(spi_miso_i)
   );
   
   // boot fsm
   boot_fsm #(
      .BOOT_SIZE      (BOOT_SIZE),
      .SRAM_BASE_ADDR (SRAM_BASE_ADDR)
   ) boot_controller (
      .clk_i(clk_i),
      .reset_ni(reset_ni && !pass_thru_en_i),   //fsm idle during pass thru
      .spi_start_o(spi_start),
      .spi_out_o(spi_data_out),
      .spi_in_i(spi_data_in),
      .spi_done_i(spi_done),
      .spi_busy_i(spi_busy),
      .flash_csb_o(flash_csb_o),
      .sram_wr_en_o(boot_wr_en),
      .sram_addr_o(boot_addr),
      .sram_data_o(boot_data),
      .cores_en_o(cores_en_o),
      .boot_done_o(boot_done_o)
   );

endmodule