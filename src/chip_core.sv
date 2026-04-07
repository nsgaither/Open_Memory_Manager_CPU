// SPDX-FileCopyrightText: © 2025 XXX Authors
// SPDX-License-Identifier: Apache-2.0

`default_nettype none

module chip_core #(
    parameter NUM_INPUT_PADS,
    parameter NUM_BIDIR_PADS,
    parameter NUM_ANALOG_PADS
    )(
    `ifdef USE_POWER_PINS
    inout  wire VDD,
    inout  wire VSS,
    `endif
    
    input  wire clk,       // clock
    input  wire rst_n,     // reset (active low)
    
    input  wire [NUM_INPUT_PADS-1:0] input_in,   // Input value
    output wire [NUM_INPUT_PADS-1:0] input_pu,   // Pull-up
    output wire [NUM_INPUT_PADS-1:0] input_pd,   // Pull-down

    input  wire [NUM_BIDIR_PADS-1:0] bidir_in,   // Input value
    output wire [NUM_BIDIR_PADS-1:0] bidir_out,  // Output value
    output wire [NUM_BIDIR_PADS-1:0] bidir_oe,   // Output enable
    output wire [NUM_BIDIR_PADS-1:0] bidir_cs,   // Input type (0=CMOS Buffer, 1=Schmitt Trigger)
    output wire [NUM_BIDIR_PADS-1:0] bidir_sl,   // Slew rate (0=fast, 1=slow)
    output wire [NUM_BIDIR_PADS-1:0] bidir_ie,   // Input enable
    output wire [NUM_BIDIR_PADS-1:0] bidir_pu,   // Pull-up
    output wire [NUM_BIDIR_PADS-1:0] bidir_pd,   // Pull-down

    inout  wire [NUM_ANALOG_PADS-1:0] analog  // Analog
);
    
    // PicoRV32 memory interface
    logic        mem_valid;
    logic        mem_instr;
    logic        mem_ready;
    
    logic [31:0] mem_addr;
    logic [31:0] mem_wdata;
    logic [3:0]  mem_wstrb;
    logic [31:0] mem_rdata;
    
    // Lookahead interface (can be left unused)
    logic        mem_la_read;
    logic        mem_la_write;
    logic [31:0] mem_la_addr;
    logic [31:0] mem_la_wdata;
    logic [3:0]  mem_la_wstrb;
    
    // IRQ interface
    logic [31:0] irq;
    logic [31:0] eoi;
    
    // Trace/debug (can leave unconnected if unused)
    logic        trace_valid;
    logic [35:0] trace_data;


    assign mem_ready = 1'b0;       // stall CPU (no memory yet)
    assign mem_rdata = 32'h00000000;

    assign irq = 32'b0;            // no interrupts



    picorv32 #(
        .ENABLE_COUNTERS      (1),
        .ENABLE_COUNTERS64    (0),
        .ENABLE_REGS_16_31    (1),
        .ENABLE_REGS_DUALPORT (1),
    
        .LATCHED_MEM_RDATA    (0),
    
        .TWO_STAGE_SHIFT      (1),
        .BARREL_SHIFTER       (0),
        .TWO_CYCLE_COMPARE    (0),
        .TWO_CYCLE_ALU        (0),
    
        .COMPRESSED_ISA       (0),
    
        .CATCH_MISALIGN       (1),
        .CATCH_ILLINSN        (1),
    
        .ENABLE_MUL           (1),
        .ENABLE_FAST_MUL      (0),
        .ENABLE_DIV           (1),
    
        .ENABLE_IRQ           (0),
        .ENABLE_IRQ_QREGS     (0),
    
        .PROGADDR_RESET       (32'h0000_0000),
        .PROGADDR_IRQ         (32'h0000_0010),
        .STACKADDR            (32'h0000_2000)
    ) pico_rv32_cpu (
        .clk         (clk),
        .resetn      (rst_n),
    
        // Memory interface
        .mem_valid   (mem_valid),
        .mem_instr   (mem_instr),
        .mem_ready   (mem_ready),
    
        .mem_addr    (mem_addr),
        .mem_wdata   (mem_wdata),
        .mem_wstrb   (mem_wstrb),
        .mem_rdata   (mem_rdata),
    
        // Lookahead (optional)
        .mem_la_read   (mem_la_read),
        .mem_la_write  (mem_la_write),
        .mem_la_addr   (mem_la_addr),
        .mem_la_wdata  (mem_la_wdata),
        .mem_la_wstrb  (mem_la_wstrb),
    
        // Interrupts
        .irq         (irq),
        .eoi         (eoi),
    
        // Trace/debug
        .trace_valid (trace_valid),
        .trace_data  (trace_data)
    );



    
    // See here for usage: https://gf180mcu-pdk.readthedocs.io/en/latest/IPs/IO/gf180mcu_fd_io/digital.html
    
    // Disable pull-up and pull-down for input
    assign input_pu = '0;
    assign input_pd = '0;

    // Set the bidir as output
    assign bidir_oe = '1;
    assign bidir_cs = '0;
    assign bidir_sl = '0;
    assign bidir_ie = ~bidir_oe;
    assign bidir_pu = '0;
    assign bidir_pd = '0;
    
    logic _unused;
    assign _unused = &bidir_in;

    logic [NUM_BIDIR_PADS-1:0] count;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            count <= '0;
        end else begin
            if (&input_in) begin
                count <= count + 1;
            end
        end
    end

    logic [7:0] sram_0_out;

    gf180mcu_fd_ip_sram__sram512x8m8wm1 sram_0 (
        `ifdef USE_POWER_PINS
        .VDD  (VDD),
        .VSS  (VSS),
        `endif

        .CLK  (clk),
        .CEN  (1'b1),
        .GWEN (1'b0),
        .WEN  (8'b0),
        .A    ('0),
        .D    ('0),
        .Q    (sram_0_out)
    );

    logic [7:0] sram_1_out;

    gf180mcu_fd_ip_sram__sram512x8m8wm1 sram_1 (
        `ifdef USE_POWER_PINS
        .VDD  (VDD),
        .VSS  (VSS),
        `endif

        .CLK  (clk),
        .CEN  (1'b1),
        .GWEN (1'b0),
        .WEN  (8'b0),
        .A    ('0),
        .D    ('0),
        .Q    (sram_1_out)
    );

    assign bidir_out = count ^ {24'd0, sram_0_out, sram_1_out};

endmodule

`default_nettype wire
