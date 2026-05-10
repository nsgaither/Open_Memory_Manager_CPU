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

    //pad index definitions
    localparam PAD_PASS_THRU_EN = 0;   // input_in[0] — pass_thru_en from PCB
    localparam PAD_MISO         = 1;   // input_in[1] — flash MISO (always input)
 
    localparam PAD_SCK          = 8;   // bidir[8]  — flash SCK
    localparam PAD_MOSI         = 9;   // bidir[9]  — flash MOSI
    localparam PAD_CSB          = 10;  // bidir[10] — flash CSB
 
    // boot ctrl pad signals
    wire pass_thru_en;
    wire boot_sck;
    wire boot_mosi;
    wire boot_miso;
    wire boot_csb;
 
    assign pass_thru_en = input_in[PAD_PASS_THRU_EN];
    assign boot_miso    = input_in[PAD_MISO];
 
    // boot ctrl memory bus outputs
    wire        boot_mem_valid;
    wire [31:0] boot_mem_addr;
    wire [31:0] boot_mem_wdata;
    wire [3:0]  boot_mem_wstrb;
    wire        boot_mem_instr;
    wire        boot_done;
    wire        cores_en;


    housekeeping_top #(
        .BOOT_SIZE      (512),
        .SRAM_BASE_ADDR (32'h0000_0000)
    ) i_housekeeping (
        .clk_i          (clk),
        .reset_ni       (rst_n),
        .pass_thru_en_i (pass_thru_en),
        .spi_sck_o      (boot_sck),
        .spi_mosi_o     (boot_mosi),
        .spi_miso_i     (boot_miso),
        .flash_csb_o    (boot_csb),
        .mem_valid_o    (boot_mem_valid),
        .mem_addr_o     (boot_mem_addr),
        .mem_wdata_o    (boot_mem_wdata),
        .mem_wstrb_o    (boot_mem_wstrb),
        .mem_instr_o    (boot_mem_instr),
        .cores_en_o     (cores_en),
        .boot_done_o    (boot_done)
    );

    // CPU is held in reset until boot_done via cpu_resetn.
    // Its mem_* outputs will be 0/idle while in reset, so the mux below safely passes boot controller traffic during that window.
    wire cpu_resetn;
    assign cpu_resetn = rst_n && cores_en;


    
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
    
    // Trace/debug (can leave unconnected if unused)
    logic        trace_valid;
    logic [35:0] trace_data;

    // PCPI interface (tied off - not using external coprocessor)
    logic        pcpi_valid;
    logic [31:0] pcpi_insn;
    logic [31:0] pcpi_rs1;
    logic [31:0] pcpi_rs2;
    logic        pcpi_wr;
    logic [31:0] pcpi_rd;
    logic        pcpi_wait;
    logic        pcpi_ready;

    logic        trap;



    // Boot mux — boot controller owns bus until boot_done, then CPU takes over
    wire        muxed_mem_valid;
    wire [31:0] muxed_mem_addr;
    wire [31:0] muxed_mem_wdata;
    wire [3:0]  muxed_mem_wstrb;
    wire        muxed_mem_instr;
 
    assign muxed_mem_valid = boot_done ? mem_valid       : boot_mem_valid;
    assign muxed_mem_addr  = boot_done ? mem_addr        : boot_mem_addr;
    assign muxed_mem_wdata = boot_done ? mem_wdata       : boot_mem_wdata;
    assign muxed_mem_wstrb = boot_done ? mem_wstrb       : boot_mem_wstrb;
    assign muxed_mem_instr = boot_done ? mem_instr       : boot_mem_instr;



    

    (* keep *) mem_ctrl_128x32 #(
    ) mem_ctrl (
        .clk_i       (clk),
        .rst_ni      (rst_n),
        .mem_valid_i (muxed_mem_valid),
        .mem_instr_i (muxed_mem_instr),
        .mem_addr_i  (muxed_mem_addr),
        .mem_wdata_i (muxed_mem_wdata),
        .mem_wstrb_i (muxed_mem_wstrb),
        .mem_rdata_o (mem_rdata),
        .mem_ready_o (mem_ready)
		`ifdef USE_POWER_PINS
		// verilator lint_off ASSIGNIN
		,.VDD(VDD)
		,.VSS(VSS)
		// verilator lint_on ASSIGNIN
		`endif
    );


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

        .ENABLE_PCPI          (0),
        .ENABLE_MUL           (1),
        .ENABLE_FAST_MUL      (0),
        .ENABLE_DIV           (1),

        .ENABLE_IRQ           (0),
        .ENABLE_IRQ_QREGS     (0),
        .ENABLE_IRQ_TIMER     (0),

        .ENABLE_TRACE         (0),
        .REGS_INIT_ZERO       (0),

        .MASKED_IRQ           (32'h0000_0000),
        .LATCHED_IRQ          (32'hffff_ffff),
        .PROGADDR_RESET       (32'h0000_0000),
        .PROGADDR_IRQ         (32'h0000_0010),
        .STACKADDR            (32'h0000_2000)
    ) pico_rv32_cpu (
        .clk         (clk),
        .resetn      (cpu_resetn),

        .trap        (trap),

        // Memory interface
        .mem_valid   (mem_valid),
        .mem_instr   (mem_instr),
        .mem_ready   (mem_ready),

        .mem_addr    (mem_addr),
        .mem_wdata   (mem_wdata),
        .mem_wstrb   (mem_wstrb),
        .mem_rdata   (mem_rdata),

        // Lookahead (optional)
        .mem_la_read  (mem_la_read),
        .mem_la_write (mem_la_write),
        .mem_la_addr  (mem_la_addr),
        .mem_la_wdata (mem_la_wdata),
        .mem_la_wstrb (mem_la_wstrb),

        // PCPI (external coprocessor port - tied off)
        .pcpi_valid  (pcpi_valid),
        .pcpi_insn   (pcpi_insn),
        .pcpi_rs1    (pcpi_rs1),
        .pcpi_rs2    (pcpi_rs2),
        .pcpi_wr     (1'b0),
        .pcpi_rd     (32'h0),
        .pcpi_wait   (1'b0),
        .pcpi_ready  (1'b0),

        // Interrupts
        .irq         (32'b0),
        .eoi         (),

        // Trace/debug
        .trace_valid (trace_valid),
        .trace_data  (trace_data)
    );

    
    // See here for usage: https://gf180mcu-pdk.readthedocs.io/en/latest/IPs/IO/gf180mcu_fd_io/digital.html
    
    // Pad ring assignments
    // Use logic intermediates so we can do per-bit overrides
    logic [NUM_INPUT_PADS-1:0] input_pu_r, input_pd_r;
    logic [NUM_BIDIR_PADS-1:0] bidir_out_r, bidir_oe_r, bidir_cs_r;
    logic [NUM_BIDIR_PADS-1:0] bidir_sl_r,  bidir_ie_r, bidir_pu_r, bidir_pd_r;
 
    assign input_pu = input_pu_r;
    assign input_pd = input_pd_r;
    assign bidir_out = bidir_out_r;
    assign bidir_oe  = bidir_oe_r;
    assign bidir_cs  = bidir_cs_r;
    assign bidir_sl  = bidir_sl_r;
    assign bidir_ie  = bidir_ie_r;
    assign bidir_pu  = bidir_pu_r;
    assign bidir_pd  = bidir_pd_r;
    
    always_comb begin
        // Input pads: no pull-up or pull-down
        input_pu_r = '0;
        input_pd_r = '0;
 
        // Bidir defaults: all driven low, output enabled, no pull
        bidir_out_r = '0;
        bidir_oe_r  = '1;
        bidir_cs_r  = '0;
        bidir_sl_r  = '0;
        bidir_pu_r  = '0;
        bidir_pd_r  = '0;
        bidir_ie_r  = ~bidir_oe_r;
 
        // Flash SPI pins — driven by boot controller.
        // When pass_thru_en=1 the programmer drives them directly,
        // so we tri-state our outputs.
        bidir_out_r[PAD_SCK]  = boot_sck;
        bidir_out_r[PAD_MOSI] = boot_mosi;
        bidir_out_r[PAD_CSB]  = boot_csb;
 
        bidir_oe_r[PAD_SCK]   = ~pass_thru_en;
        bidir_oe_r[PAD_MOSI]  = ~pass_thru_en;
        bidir_oe_r[PAD_CSB]   = ~pass_thru_en;
 
        bidir_ie_r[PAD_SCK]   = pass_thru_en;
        bidir_ie_r[PAD_MOSI]  = pass_thru_en;
        bidir_ie_r[PAD_CSB]   = pass_thru_en;
    end


    // Disable pull-up and pull-down for input
    // assign input_pu = '0;
    // assign input_pd = '0;

    // // Set the bidir as output
    // assign bidir_oe = '1;
    // assign bidir_cs = '0;
    // assign bidir_sl = '0;
    // assign bidir_ie = ~bidir_oe;
    // assign bidir_pu = '0;
    // assign bidir_pd = '0;
    
    logic _unused;

    assign _unused = &{analog, bidir_in, mem_la_read, mem_la_write, mem_la_addr,
                       mem_la_wdata, mem_la_wstrb, trace_valid, trace_data, trap,
                       cores_en, cpu_resetn};

    //assign _unused = &bidir_in;

    //assign bidir_out = {NUM_BIDIR_PADS{1'b0}};

endmodule

`default_nettype wire
