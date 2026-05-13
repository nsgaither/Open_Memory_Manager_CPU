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

    // Serial Interface
    localparam NUM_TPINS = 9;
    localparam NUM_RPINS = 9;

    // io pad indexes
    localparam DEBUG_ID = 0;
    localparam TRAP_ID = 22;
    localparam REQ_I_ID = 11;
    localparam REQ_O_ID = 21;
    localparam SERIAL_I_START_ID = 2;
    localparam SERIAL_O_START_ID = 12;
    localparam GPIO_START_ID = 23;
    
    // For cache TODO: no idea what these are yet
    localparam NUM_SETS = 64;
    localparam WORDS_PER_LINE = 1;

    // TODO: add DLL and other clock management if needed
    wire clk_i, rst_ni;
    assign clk_i = clk;
    assign rst_ni = rst_n;

    // PicoRV32 memory interface
    wire        mem_valid;
    wire        mem_instr;
    wire        mem_ready;
    
    wire [31:0] mem_addr;
    wire [31:0] mem_wdata;
    wire [3:0]  mem_wstrb;
    wire [31:0] mem_rdata;
    
    // Lookahead interface (can be left unused)
    wire        mem_la_read;
    wire        mem_la_write;
    wire [31:0] mem_la_addr;
    wire [31:0] mem_la_wdata;
    wire [3:0]  mem_la_wstrb;
    
    // Trace/debug (can leave unconnected if unused)
    wire        trace_valid;
    wire [35:0] trace_data;
z
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

    (* keep *) mem128x32 mem_ctrl (
        .clk_i       (clk),
        .rst_ni      (rst_n),
        .mem_valid_i (),
        .mem_ready_o (),
        .mem_addr_i  (),
        .mem_wdata_i (),
        .mem_wstrb_i (),
        .mem_rdata_o (),
        .mem_valid_o (),
        .mem_ready_i ()
    );

    (* keep *) mem128x4 tag (
        .clk_i       (clk),
        .rst_ni      (rst_n),
        .mem_valid_i (),
        .mem_ready_o (),
        .mem_addr_i  (),
        .mem_wdata_i (),
        .mem_rdata_o (),
        .mem_valid_o (),
        .mem_ready_i ()
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
        .clk         (clk_i),
        .resetn      (rst_ni),

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

    // special address handler
    // core -> this -> cache controller
    // outputs
    wire pass_mem_valid;
    wire pass_mem_ready;
    wire [31:0] pass_mem_addr;
    wire [31:0] pass_mem_wdata;
    wire [3:0] pass_mem_wstrb;
    wire [31:0] pass_mem_rdata;

    wire flush_ready;
    wire [31:0] flush_addr;
    wire flush_valid;

    wire gpio_pins_o;
    wire gpio_pins_i;
    wire gpio_dir;

    wire cpu_id;

    sp_addr_handler u_sp_addr_handler (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),

    // Interface from CPU (native picorv32)
    .mem_valid       (mem_valid),
    .mem_ready       (mem_ready),
    .mem_addr        (mem_addr),
    .mem_wdata       (mem_wdata),
    .mem_wstrb       (mem_wstrb),
    .mem_rdata       (mem_rdata),

    // Downstream passthrough interface
    .pass_mem_valid  (pass_mem_valid),
    .pass_mem_ready  (pass_mem_ready),
    .pass_mem_addr   (pass_mem_addr),
    .pass_mem_wdata  (pass_mem_wdata),
    .pass_mem_wstrb  (pass_mem_wstrb),
    .pass_mem_rdata  (pass_mem_rdata),

    // Flush special instruction
    .flush_ready_i   (flush_ready),
    .flush_addr_o    (flush_addr),
    .flush_valid_o   (flush_valid),

    // GPIO pin connections
    .gpio_pins_o     (gpio_pins_o),
    .gpio_pins_i     (gpio_pins_i),
    .gpio_dir_o      (gpio_dir),

    // CPU ID
    .cpu_id_i        (cpu_id)
);

// Cache Controller
// sp addr handler -> this -> cache interposer
//                     |
//                     v
//                   Cache
wire        cache_valid;
wire [31:0] cache_addr;
wire [31:0] cache_data;
wire [ 8:0] cache_cmd;
wire        cache_ready;

wire        bus_valid;
wire [31:0] bus_data;
wire [ 2:0] bus_dircmd;
wire        bus_ready;

wire        snoop_valid;
wire [31:0] snoop_data;
wire [ 2:0] snoop_dircmd;
wire        snoop_ready;

cache_controller #(
  .NumSets     (NUM_SETS),
  .WordsPerLine (WORDS_PER_LINE)
) u_cache_controller (
  .clk_i                 (clk_i),
  .rst_ni                (rst_ni),

  .mem_valid_i           (pass_mem_valid),
  .mem_ready_o           (pass_mem_ready),
  .mem_addr_i            (pass_mem_addr),
  .mem_wdata_i           (pass_mem_wdata),
  .mem_wstrb_i           (pass_mem_wstrb),
  .mem_rdata_o           (pass_mem_rdata),

  .flush_valid_i         (flush_valid),
  .flush_addr_i          (flush_addr),
  .flush_ready_o         (flush_ready),

  .data_cache_rd_en_o    (),
  .data_cache_rd_set_o   (),
  .data_cache_rd_word_o  (),
  .data_cache_rd_data_i  (),

  .data_cache_wr_en_o    (),
  .data_cache_wr_set_o   (),
  .data_cache_wr_word_o  (),
  .data_cache_wr_data_o  (),
  .data_cache_wr_strb_o  (),
  .data_cache_ready_i    (),

  .cache_valid_o         (cache_valid),
  .cache_ready_i         (cache_ready),
  .cache_addr_o          (cache_addr),
  .cache_data_o          (cache_data),
  .cache_cmd_o           (cache_cmd),

  .bus_valid_i           (bus_valid),
  .bus_ready_o           (bus_ready),
  .bus_data_i            (bus_data),
  .bus_dircmd_i          (bus_dircmd),

  .snoop_valid_i         (snoop_valid),
  .snoop_ready_o         (snoop_ready),
  .snoop_data_i          (snoop_data),
  .snoop_dircmd_i        (snoop_dircmd)
);

// Cache
// Cache controller -> this
cache #(
  .NumSets     (NUM_SETS),
  .WordsPerLine (WORDS_PER_LINE)
) u_cache (
  .clk_i     (clk_i),
  .rst_ni    (rst_ni),

  .rd_en_i   (),
  .rd_set_i  (),
  .rd_word_i (),
  .rd_data_o (),

  .wr_en_i   (),
  .wr_set_i  (),
  .wr_word_i (),
  .wr_data_i (),
  .wr_strb_i (),

  .ready_o   ()
);

// cache_interposer_interface
// cache controller -> this -> IO pins
wire                 rbusy;

wire                 req_o;
wire [NUM_TPINS-1:0] serial_o;
wire                 req_i;
wire [NUM_RPINS-1:0] serial_i;

cache_interface #(
    .NUM_TPINS (NUM_TPINS),
    .NUM_RPINS (NUM_RPINS)
) u_cache_interface (
    .clk_i          (clk_i),
    .rst_ni         (rst_ni),

    // UPSTREAM --------------------------------------
    // Cache Send Ports
    .cache_valid_i  (cache_valid),
    .cache_addr_i   (cache_addr),
    .cache_data_i   (cache_data),
    .cache_cmd_i    (cache_cmd),
    .cache_ready_o  (cache_ready),

    // Bus Ack ports
    .bus_valid_o    (bus_valid),
    .bus_data_o     (bus_data),
    .bus_dircmd_o   (bus_dircmd),
    .bus_ready_i    (bus_ready),

    // Snoop Req ports
    .snoop_valid_o  (snoop_valid),
    .snoop_data_o   (snoop_data),
    .snoop_dircmd_o (snoop_dircmd),
    .snoop_ready_i  (snoop_ready),

    // busy
    .rbusy_o        (rbusy),

    // other
    .cpu_id_o       (cpu_id),

    // DOWNSTREAM ------------------------------------
    // wrapped serializer IO
    .req_i          (req_i),
    .serial_i       (serial_i),
    .req_o          (req_o),
    .serial_o       (serial_o)
);

    
    // See here for usage: https://gf180mcu-pdk.readthedocs.io/en/latest/IPs/IO/gf180mcu_fd_io/digital.html
    
    // Disable pull-up and pull-down for input
    assign input_pu = '0;
    assign input_pd = '0;

    // bidirectional pad control
    always_comb begin : birdir_control
        // defaults
        birdir_oe = '0;
        birdir_cs = '0;
        birdir_sl = '0;
        birdir_ie = ~birdir_oe;
        bidir_pu = '0;
        bidir_pd = '0;

        // IO control
        birdir_oe[GPIO_START_ID +: 8] = gpio_dir;
        birdir_oe[DEBUG_ID] = 1'b0;                     // debug pin is input only
        birdir_oe[TRAP_ID] = 1'b1;                      // trap pin is output only
        birdir_oe[REQ_I_ID] = 1'b0;                     // req_i is input only
        birdir_oe[REQ_O_ID] = 1'b1;                     // req_o is output only
        birdir_oe[SERIAL_I_START_ID +: NUM_RPINS] = '0; // serial_i is input only
        birdir_oe[SERIAL_O_START_ID +: NUM_TPINS] = '1; // serial_o is output only
    end

    // bidirectional pad data routing
    wire [NUM_BIDIR_PADS-1:0] bidir_data_i;
    always_comb begin : bidir_data
        // defaults
        bidir_data_i = bidir_in;
        bidir_out = {NUM_BIDIR_PADS{1'b0}};

        // trap
        bidir_out[TRAP_ID] = trap;

        // debug
        debug = bidir_data_i[DEBUG_ID];

        // serial
        req_i = bidir_data_i[REQ_I_ID];
        serial_i = bidir_data_i[SERIAL_I_START_ID +: NUM_RPINS];
        bidir_out[REQ_O_ID] = req_o;
        bidir_out[SERIAL_O_START_ID +: NUM_TPINS] = serial_o;

        // GPIO
        bidir_out[GPIO_START_ID +: 8] = gpio_pins_o;
        gipio_pins_i = bidir_data_i[GPIO_START_ID +: 8];
    end

endmodule

`default_nettype wire
