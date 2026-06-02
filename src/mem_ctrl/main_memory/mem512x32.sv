// SPDX-FileCopyrightText: © 2025 Albert Felix
// SPDX-License-Identifier: Apache-2.0

`default_nettype none

module mem_ctrl_512x32
(
	input wire         clk_i,
	input wire         rst_ni,	

	input wire [0:0]   mem_valid_i,
	input wire [0:0]   mem_instr_i,

	input wire [31:0]  mem_addr_i,
	input wire [31:0]  mem_wdata_i,
	input wire [3:0]   mem_wstrb_i,

	output wire [31:0] mem_rdata_o,
	output wire [0:0]  mem_ready_o
);

	wire sram_enable_n;
	wire [3:0] sram_write_en_n;
	wire [7:0] sram_write_bit_mask_n;
	wire [8:0] sram_addr;
	wire [31:0] data_to_write;
	wire [31:0] data_read;
	// wire vdd, vss;


	// interal states are retained during disable
	// must be high before 1st running cycle
	assign sram_enable_n = !mem_valid_i;
	// 0 == write and 1 == read
	assign sram_write_en_n = mem_wstrb_i;
	// write bit mask, when bit 6 is 0 then the 6 bit in btye gets updated
	assign sram_write_bit_mask_n = 8'b00000000;
	// addr written to or read from
	assign sram_addr = mem_addr_i[8:0];
	// data to be written 
	assign data_to_write = mem_wdata_i;

	// power signals
	// assign vdd = 1;
	// assign vss = 0;

	gf180mcu_fd_ip_sram__sram512x8m8wm1 sram0 (
		.CLK(clk_i),
		.CEN(sram_enable_n), 
		.GWEN(~sram_write_en_n[0]),
		.WEN(sram_write_bit_mask_n),
		.A(sram_addr),
		.D(data_to_write[7:0]),
		.Q(data_read[7:0]),
		.VDD(),
		.VSS()
	);

	gf180mcu_fd_ip_sram__sram512x8m8wm1 sram1 (
		.CLK(clk_i),
		.CEN(sram_enable_n), 
		.GWEN(~sram_write_en_n[1]),
		.WEN(sram_write_bit_mask_n),
		.A(sram_addr),
		.D(data_to_write[15:8]),
		.Q(data_read[15:8]),
		.VDD(),
		.VSS()
	);

	gf180mcu_fd_ip_sram__sram512x8m8wm1 sram2 (
		.CLK(clk_i),
		.CEN(sram_enable_n), 
		.GWEN(~sram_write_en_n[2]),
		.WEN(sram_write_bit_mask_n),
		.A(sram_addr),
		.D(data_to_write[23:16]),
		.Q(data_read[23:16]),
		.VDD(),
		.VSS()
	);

	
	gf180mcu_fd_ip_sram__sram512x8m8wm1 sram3 (
		.CLK(clk_i),
		.CEN(sram_enable_n), 
		.GWEN(~sram_write_en_n[3]),
		.WEN(sram_write_bit_mask_n),
		.A(sram_addr),
		.D(data_to_write[31:24]),
		.Q(data_read[31:24]),
		.VDD(),
		.VSS()
	);	

	assign mem_rdata_o = data_read;
	assign mem_ready_o = 1'b1;

endmodule

`default_nettype wire





	// genvar i;

	// generate 
	// 	for (i = 0; i < 4; i++) begin
	// 		gf180mcu_fd_ip_sram__sram512x8m8wm1 sram1 (
	// 			.CLK(clk_i),
	// 			.CEN(sram_enable_n), 
	// 			.GWEN(~sram_write_en_n[i]),
	// 			.WEN(sram_write_bit_mask_n),
	// 			.A(sram_addr),
	// 			.D(data_to_write[(7+8*i):(8*i)]),
	// 			.Q(data_read[(7+8*i):(8*i)]),
	// 			.VDD(vdd),
	// 			.VSS(vss)
	// 		);
	// 	end
	// endgenerate
