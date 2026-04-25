// SPDX-FileCopyrightText: © 2026 Nicholas Gaither
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

    // -------------------------------------------------------------------------
    // Initialization FSM
    // -------------------------------------------------------------------------
    typedef enum logic [1:0] {
        S_INIT,
        S_DONE
    } state_t;

    state_t   state;
    logic [8:0] init_addr;

    always_ff @(posedge clk_i) begin
        if (!rst_ni) begin
            state     <= S_INIT;
            init_addr <= 9'd0;
        end else if (state == S_INIT) begin
            init_addr <= init_addr + 1;
            if (init_addr == 9'd511)
                state <= S_DONE;
        end
    end

    wire init_busy = (state == S_INIT);

    logic sram_enable_reg;
	wire sram_enable_n;
	wire [3:0] sram_write_en_n;
	wire [7:0] sram_write_bit_mask_n;
	wire [8:0] sram_addr;
	wire [31:0] data_to_write;
	wire [31:0] data_read;
	// wire vdd, vss;


    always_ff @(posedge clk_i) begin
        if (!rst_ni) begin
            sram_enable_reg <= 1'b1;
        end else begin
            sram_enable_reg <= init_busy ? 1'b0 : !mem_valid_i;
        end
    end
    assign sram_enable_n = sram_enable_reg;

    // During init: GWEN=0 (write all bytes). During normal op: CPU controls.
    assign sram_write_en_n =
        init_busy ? 4'b0000        // all bytes write-enabled
                  : mem_wstrb_i;

    assign sram_write_bit_mask_n = 8'b0000_0000; // all bits always writable

    assign sram_addr =
        init_busy ? init_addr      // walk all 512 addresses
                  : mem_addr_i[8:0];

    assign data_to_write =
        init_busy ? 32'h0000_0000  // write zeros (change pattern here if needed)
                  : mem_wdata_i;

	// power signals
	// assign vdd = 1;
	// assign vss = 0;

    gf180mcu_fd_ip_sram__sram512x8m8wm1 sram0 (
        .CLK  (clk_i),
        .CEN  (sram_enable_n),
        .GWEN (~sram_write_en_n[0]),
        .WEN  (sram_write_bit_mask_n),
        .A    (sram_addr),
        .D    (data_to_write[7:0]),
        .Q    (data_read[7:0]),
        .VDD  (),
        .VSS  ()
    );
    gf180mcu_fd_ip_sram__sram512x8m8wm1 sram1 (
        .CLK  (clk_i),
        .CEN  (sram_enable_n),
        .GWEN (~sram_write_en_n[1]),
        .WEN  (sram_write_bit_mask_n),
        .A    (sram_addr),
        .D    (data_to_write[15:8]),
        .Q    (data_read[15:8]),
        .VDD  (),
        .VSS  ()
    );
    gf180mcu_fd_ip_sram__sram512x8m8wm1 sram2 (
        .CLK  (clk_i),
        .CEN  (sram_enable_n),
        .GWEN (~sram_write_en_n[2]),
        .WEN  (sram_write_bit_mask_n),
        .A    (sram_addr),
        .D    (data_to_write[23:16]),
        .Q    (data_read[23:16]),
        .VDD  (),
        .VSS  ()
    );
    gf180mcu_fd_ip_sram__sram512x8m8wm1 sram3 (
        .CLK  (clk_i),
        .CEN  (sram_enable_n),
        .GWEN (~sram_write_en_n[3]),
        .WEN  (sram_write_bit_mask_n),
        .A    (sram_addr),
        .D    (data_to_write[31:24]),
        .Q    (data_read[31:24]),
        .VDD  (),
        .VSS  ()
    );

	assign mem_rdata_o = data_read;
	assign mem_ready_o = init_busy ? 1'b0 : 1'b1;

endmodule

`default_nettype wire
