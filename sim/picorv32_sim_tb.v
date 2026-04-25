// SPDX-FileCopyrightText: © 2025 Project Template Contributors
// SPDX-License-Identifier: Apache-2.0

`timescale 1ns/1ps

`default_nettype none

module picorv32_sim_tb;

reg clk;
reg rst_n;
wire trap;

wire [31:0] mem_addr;
wire [31:0] mem_wdata;
wire [3:0] mem_wstrb;
wire [31:0] mem_rdata;
wire mem_valid;
wire mem_instr;
wire mem_ready;

wire pcpi_valid, pcpi_wr, pcpi_wait, pcpi_ready;
wire [31:0] pcpi_insn, pcpi_rs1, pcpi_rs2, pcpi_rd;
wire mem_la_read, mem_la_write;
wire [31:0] mem_la_addr, mem_la_wdata;
wire [3:0] mem_la_wstrb;
wire [31:0] irq, eoi;
wire trace_valid;
wire [35:0] trace_data;

assign pcpi_valid = 0;
assign pcpi_insn = 0;
assign pcpi_rs1 = 0;
assign pcpi_rs2 = 0;
assign pcpi_wr = 0;
assign pcpi_rd = 0;
assign pcpi_wait = 0;
assign pcpi_ready = 0;
assign irq = 0;

reg [31:0] ram [0:511];
integer ram_idx;
reg mem_ready_reg;
reg [31:0] mem_rdata_reg;
reg mem_init_done;

initial begin
    for (ram_idx = 0; ram_idx < 512; ram_idx = ram_idx + 1)
        ram[ram_idx] = 32'h00000000;
    mem_init_done = 1;
end

always @(posedge clk) begin
    if (!rst_n) begin
        mem_ready_reg <= 0;
        mem_rdata_reg <= 0;
    end else if (mem_valid && mem_init_done) begin
        mem_ready_reg <= 1;
        mem_rdata_reg <= (mem_addr[11:0] < 12'h800) ? ram[mem_addr[10:2]] : 32'h0;
    end else begin
        mem_ready_reg <= 0;
    end
end

assign mem_ready = mem_ready_reg;
assign mem_rdata = mem_rdata_reg;

always @(posedge clk) begin
    if (mem_valid && mem_ready && |mem_wstrb && mem_addr[11:0] < 12'h800) begin
        if (mem_wstrb[0]) ram[mem_addr[10:2]][7:0] <= mem_wdata[7:0];
        if (mem_wstrb[1]) ram[mem_addr[10:2]][15:8] <= mem_wdata[15:8];
        if (mem_wstrb[2]) ram[mem_addr[10:2]][23:16] <= mem_wdata[23:16];
        if (mem_wstrb[3]) ram[mem_addr[10:2]][31:24] <= mem_wdata[31:24];
    end
end

picorv32 #(
    .ENABLE_COUNTERS(1), .ENABLE_COUNTERS64(0), .ENABLE_REGS_16_31(1),
    .ENABLE_REGS_DUALPORT(1), .LATCHED_MEM_RDATA(0), .TWO_STAGE_SHIFT(1),
    .COMPRESSED_ISA(0), .CATCH_MISALIGN(1), .CATCH_ILLINSN(0),
    .ENABLE_PCPI(0), .ENABLE_MUL(1), .ENABLE_FAST_MUL(0), .ENABLE_DIV(1),
    .ENABLE_IRQ(0), .ENABLE_TRACE(0), .REGS_INIT_ZERO(0),
    .PROGADDR_RESET(32'h00000000), .STACKADDR(32'h00002000)
) u_cpu (
    .clk(clk), .resetn(rst_n), .trap(trap),
    .mem_valid(mem_valid), .mem_instr(mem_instr), .mem_ready(mem_ready),
    .mem_addr(mem_addr), .mem_wdata(mem_wdata), .mem_wstrb(mem_wstrb), .mem_rdata(mem_rdata),
    .mem_la_read(mem_la_read), .mem_la_write(mem_la_write),
    .mem_la_addr(mem_la_addr), .mem_la_wdata(mem_la_wdata), .mem_la_wstrb(mem_la_wstrb),
    .pcpi_valid(pcpi_valid), .pcpi_insn(pcpi_insn), .pcpi_rs1(pcpi_rs1), .pcpi_rs2(pcpi_rs2),
    .pcpi_wr(pcpi_wr), .pcpi_rd(pcpi_rd), .pcpi_wait(pcpi_wait), .pcpi_ready(pcpi_ready),
    .irq(irq), .eoi(eoi), .trace_valid(trace_valid), .trace_data(trace_data)
);

always #5 clk = ~clk;

reg [31:0] cycle_count;
initial cycle_count = 0;
always @(posedge clk) cycle_count <= cycle_count + 1;

initial begin
    $dumpfile("picorv32_sim.vcd");
    $dumpvars(0, picorv32_sim_tb);

    $display("=================================================");
    $display("  picorv32 CPU Simulation Test");
    $display("=================================================");
    $display("");

    // Load program: x1 = 1, x1 = x1 * 2, loop
    ram[0] = 32'h00100113;  // addi x1, x0, 1
    ram[1] = 32'h00118133;  // add x1, x1, x1
    ram[2] = 32'hfe010e13;  // addi x1, x0, -4
    ram[3] = 32'h0001e67f;  // jal x0, -16

    $display("Program loaded:");
    $display("  0x00: lui x1, 0x0; addi x1, x1, 1  [x1 = 1]");
    $display("  0x04: add x1, x1, x1              [x1 = x1 * 2]");
    $display("  0x08: addi x1, x0, -4");
    $display("  0x0C: jal x0, -16                 [loop]");
    $display("");
    $display("Running simulation...");
    $display("");

    clk = 0;
    rst_n = 0;
    #10 rst_n = 1;

    // Run for 500 cycles
    #5000;

    $display("-------------------------------------------------");
    if (trap) begin
        $display("RESULT: TRAP DETECTED at cycle %0d", cycle_count);
        $display("STATUS: FAILED");
    end else begin
        $display("RESULT: No trap after %0d cycles", cycle_count);
        $display("STATUS: PASSED");
    end
    $display("-------------------------------------------------");
    $display("");

    $finish;
end

// Monitor instruction fetches
reg [31:0] last_instr;
always @(posedge clk) begin
    if (mem_valid && mem_instr && mem_ready) begin
        last_instr <= mem_rdata;
    end
end

endmodule

`default_nettype wire