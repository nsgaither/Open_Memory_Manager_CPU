`default_nettype none
`timescale 1ns/1ps

module chip_core #(
    parameter NUM_BIDIR_PADS
    )(
    `ifdef USE_POWER_PINS
    inout  wire VDD,
    inout  wire VSS,
    `endif
    
    input  wire 					  clk,        // clock
    input  wire 					  rst_n,      // reset (active low)

    // Physically buffered scan/functional-mode controls. Separate branches
    // prevent one pad-driven net from spanning every scan mux in the core.
    input  wire  [3:0] debug_mode_i,
    // One branch for request-state logic and one per receive shift word.
    input  wire  [4:0] req_i_branches,
    
    input  wire  [NUM_BIDIR_PADS-1:0] bidir_in,   // Input value
    output logic [NUM_BIDIR_PADS-1:0] bidir_out,  // Output value
    output logic [NUM_BIDIR_PADS-1:0] bidir_oe,   // Output enable
    output logic [NUM_BIDIR_PADS-1:0] bidir_cs,   // Input type (0=CMOS Buffer, 1=Schmitt Trigger)
    output logic [NUM_BIDIR_PADS-1:0] bidir_sl,   // Slew rate (0=fast, 1=slow)
    output logic [NUM_BIDIR_PADS-1:0] bidir_ie,   // Input enable
    output logic [NUM_BIDIR_PADS-1:0] bidir_pu,   // Pull-up
    output logic [NUM_BIDIR_PADS-1:0] bidir_pd    // Pull-down
);

    // Serial Interface
    localparam NUM_TPINS = 9;
    localparam NUM_RPINS = 9;

    // I/O pad indexes for the 0p5x0p5 48-bidir pinout.
    localparam DEBUG_ID          = 0;   // bidir[0]
    localparam BOOT_DONE_ID      = 1;   // bidir[1]
    localparam REQ_I_ID          = 11;  // bidir[11]
    localparam REQ_O_ID          = 21;  // bidir[21]
    localparam TRAP_ID           = 22;  // bidir[22]
    localparam SERIAL_I_START_ID = 2;   // bidir[2]  through bidir[10]
    localparam SERIAL_O_START_ID = 12;  // bidir[12] through bidir[20]
    localparam GPIO_START_ID     = 23;  // bidir[23] through bidir[30]
    localparam DEBUG_START_ID    = 23;  // DFT pins muxed with GPIO[7:0]
    localparam DFT_PINS          = 8;
    localparam DFT_CHAINS        = DFT_PINS / 2;
 
    wire clk_i;
    assign clk_i = clk;

    // The cache SRAM wrappers clear themselves after reset. Hold the CPU in
    // reset until the longest clear sequence, mem512x32, has reached IDLE.
    localparam int MEM_INIT_CYCLES = 1025; // RESET_SRAMS + 1024 RESET_DATA cycles (4x banked data mem, both macros cleared in parallel)
    localparam int MEM_INIT_COUNTER_WIDTH = $clog2(MEM_INIT_CYCLES + 1);
    localparam logic [MEM_INIT_COUNTER_WIDTH-1:0] MEM_INIT_COUNT_MAX = MEM_INIT_CYCLES;

    logic [MEM_INIT_COUNTER_WIDTH-1:0] mem_init_count;
    wire memory_ready;
    wire cores_en;
    wire boot_done;
    logic boot_done_meta, boot_done_sync;
    wire [DFT_CHAINS-1:0] dft_scan_in;
    wire [DFT_CHAINS-1:0] dft_scan_out;
    wire scan_after_mem_init;
    wire scan_after_sp_handler;
    wire [1:0] cache_scan_out;
    wire [1:0] interface_scan_out;

    assign memory_ready = (mem_init_count == MEM_INIT_COUNT_MAX);
    assign cores_en = memory_ready && boot_done_sync;
    assign boot_done = bidir_in[BOOT_DONE_ID];
    assign dft_scan_in = bidir_in[DEBUG_START_ID +: DFT_CHAINS];
    assign scan_after_mem_init = mem_init_count[MEM_INIT_COUNTER_WIDTH-1];

    // Two-flop synchronizer for the asynchronous boot_done pad before it gates
    // release of the CPU reset. rst_n is already reset-synchronized upstream in
    // chip_top (reset_sync_ff -> rst_n_sync), so it is safe to use as the reset
    // here. Excluded from scan (synchronizer hardening); resets to 0.
    // (serial_i / req_i are left unsynchronized on purpose: the link clock is
    // forwarded from the bottom chip, so those pins are already in the clk_i
    // domain.)
    always_ff @(posedge clk_i) begin
        if (!rst_n) begin
            boot_done_meta <= 1'b0;
            boot_done_sync <= 1'b0;
        end else begin
            boot_done_meta <= boot_done;
            boot_done_sync <= boot_done_meta;
        end
    end

    // Four independent chains use the lower half of the shared GPIO/DFT pad
    // range as serial inputs and the upper half as serial outputs.
    assign dft_scan_out[0] = interface_scan_out[0];
    assign dft_scan_out[1] = cache_scan_out[0];
    assign dft_scan_out[2] = cache_scan_out[1];
    assign dft_scan_out[3] = interface_scan_out[1];

    always_ff @(posedge clk_i) begin
        if (!rst_n) begin
            mem_init_count <= '0;
        end else if (debug_mode_i[0]) begin
            mem_init_count <= {
                mem_init_count[MEM_INIT_COUNTER_WIDTH-2:0], dft_scan_in[0]
            };
        end else if (!memory_ready) begin
            mem_init_count <= mem_init_count + 1'b1;
        end
    end

    // CPU mem_* outputs stay idle while reset is held low.
    wire cpu_resetn;
    assign cpu_resetn = rst_n && cores_en;


    // PicoRV32 memory interface
    wire        mem_valid;
    wire        mem_instr;
    wire        mem_ready;
    
    wire [31:0] mem_addr;
    wire [31:0] mem_wdata;
    wire [3:0]  mem_wstrb;
    wire [31:0] mem_rdata;

    // Optional PicoRV32 sideband interfaces are unused, but named here so the
    // core instance has an explicit, complete port map.
    wire        mem_la_read;
    wire        mem_la_write;
    wire [31:0] mem_la_addr;
    wire [31:0] mem_la_wdata;
    wire [3:0]  mem_la_wstrb;
    wire [31:0] irq_eoi;
    wire        trace_valid;
    wire [35:0] trace_data;

    logic        trap;
    logic        pcpi_valid;
    logic [31:0] pcpi_insn;
    logic [31:0] pcpi_rs1;
    logic [31:0] pcpi_rs2;

    picorv32 #(
        .ENABLE_COUNTERS      (1),
        .ENABLE_COUNTERS64    (0),
        .ENABLE_REGS_16_31    (1),
        .ENABLE_REGS_DUALPORT (1),

        .LATCHED_MEM_RDATA    (0),

        .TWO_STAGE_SHIFT      (1),
        .BARREL_SHIFTER       (0),
        .TWO_CYCLE_COMPARE    (1),
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

        // Lookahead interface (unused)
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
        .eoi         (irq_eoi),

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

    wire [7:0] gpio_pins_o;
    logic [7:0] gpio_pins_i;
    wire [7:0] gpio_dir;

    wire [7:0] cpu_id;

    sp_addr_handler u_sp_addr_handler (
        .clk_i           (clk_i),
        .rst_ni          (rst_n),
        .debug_mode_i    (debug_mode_i[1]),
        .scan_in_i       (scan_after_mem_init),
        .scan_out_o      (scan_after_sp_handler),

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
    wire [ 3:0] cache_cmd;
    wire        cache_ready;

    wire        bus_valid;
    wire [31:0] bus_data;
    wire [ 3:0] bus_dircmd;
    wire        bus_ready;

    wire        snoop_valid;
    wire [31:0] snoop_data;
    wire [ 3:0] snoop_dircmd;
    wire        snoop_ready;

    cache_controller u_cache_controller (
        .clk_i                 (clk_i),
        .rst_ni                (rst_n),
        .debug_mode_i          (debug_mode_i[2]),
        .scan_in_i             ({dft_scan_in[2], dft_scan_in[1]}),
        .scan_out_o            (cache_scan_out),

        .mem_valid_i           (pass_mem_valid),
        .mem_instr_i           (mem_instr),
        .mem_ready_o           (pass_mem_ready),
        .mem_addr_i            (pass_mem_addr),
        .mem_wdata_i           (pass_mem_wdata),
        .mem_wstrb_i           (pass_mem_wstrb),
        .mem_rdata_o           (pass_mem_rdata),

        .flush_valid_i         (flush_valid),
        .flush_addr_i          (flush_addr),
        .flush_ready_o         (flush_ready),

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
        .snoop_addr_i          (snoop_data),
        .snoop_dircmd_i        (snoop_dircmd)
        `ifdef USE_POWER_PINS
        ,.VDD(VDD)
        ,.VSS(VSS)
        `endif
    );

    // cache_interposer_interface
    // cache controller -> this -> IO pins
    wire                 rbusy;
    wire                 req_o;
    wire [NUM_TPINS-1:0] serial_o;
    logic [NUM_RPINS-1:0] serial_i;

    cache_interface #(
        .NUM_TPINS (NUM_TPINS),
        .NUM_RPINS (NUM_RPINS)
    ) u_cache_interface (
        .clk_i          (clk_i),
        .rst_ni         (rst_n),
        .debug_mode_i   (debug_mode_i[3]),
        .scan_in_i      ({dft_scan_in[3], scan_after_sp_handler}),
        .scan_out_o     (interface_scan_out),

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
        .req_i_branches (req_i_branches),
        .serial_i       (serial_i),
        .req_o          (req_o),
        .serial_o       (serial_o)
    );

    // bidirectional pad control
    always_comb begin : bidir_control
        // defaults
        bidir_oe = '0;
        bidir_cs = '0;
        bidir_sl = '0;
        bidir_pu = '0;
        bidir_pd = '0;

        // IO control
        if (debug_mode_i[0]) begin
            bidir_oe[DEBUG_START_ID +: DFT_CHAINS] = '0;
            bidir_oe[DEBUG_START_ID + DFT_CHAINS +: DFT_CHAINS] = '1;
        end else begin
            bidir_oe[GPIO_START_ID +: 8] = gpio_dir;
        end
        bidir_oe[DEBUG_ID] = 1'b0;                     // debug pin is input only
        bidir_oe[TRAP_ID] = 1'b1;                      // trap pin is output only
        bidir_oe[REQ_I_ID] = 1'b0;                     // req_i is input only
        bidir_oe[REQ_O_ID] = 1'b1;                     // req_o is output only
        bidir_oe[SERIAL_I_START_ID +: NUM_RPINS] = '0; // serial_i is input only
        bidir_oe[SERIAL_O_START_ID +: NUM_TPINS] = '1; // serial_o is output only
        bidir_ie = ~bidir_oe;
    end

    // bidirectional pad data routing
    logic [NUM_BIDIR_PADS-1:0] bidir_data_i;
    always_comb begin : bidir_data
        // defaults
        bidir_data_i = bidir_in;
        bidir_out = {NUM_BIDIR_PADS{1'b0}};

        // trap
        bidir_out[TRAP_ID] = trap;

        // serial
        serial_i = bidir_data_i[SERIAL_I_START_ID +: NUM_RPINS];
        bidir_out[REQ_O_ID] = req_o;
        bidir_out[SERIAL_O_START_ID +: NUM_TPINS] = serial_o;

        // GPIO
        bidir_out[GPIO_START_ID +: 8] = gpio_pins_o;
        gpio_pins_i = bidir_data_i[GPIO_START_ID +: 8];

        // In debug mode, GPIO[3:0] are scan inputs and GPIO[7:4] are the
        // corresponding scan outputs.
        if (debug_mode_i[0]) begin
            bidir_out[DEBUG_START_ID + DFT_CHAINS +: DFT_CHAINS] = dft_scan_out;
        end
    end

endmodule

`default_nettype wire
