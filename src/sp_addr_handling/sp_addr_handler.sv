`timescale 1ns/1ps

module sp_addr_handler (
    input         clk_i,
    input         rst_ni,

    // DFT scan interface. debug_mode_i is the scan/functional mux select.
    input         debug_mode_i,
    input         scan_in_i,
    output        scan_out_o,

    //interface from cpu (native picorv32)
    input         mem_valid,
    output        mem_ready,

    input  [31:0] mem_addr,
    input  [31:0] mem_wdata,
    input  [ 3:0] mem_wstrb,
    output [31:0] mem_rdata,

    // picorv32 instruction-fetch flag (high on an instruction fetch).
    input         mem_instr,

    //downstream passthrough interface
    output        pass_mem_valid,
    input         pass_mem_ready,

    output [31:0] pass_mem_addr,
    output [31:0] pass_mem_wdata,
    output [ 3:0] pass_mem_wstrb,
    input  [31:0] pass_mem_rdata,

    // flush special instruction
    input         flush_ready_i,
    output [31:0] flush_addr_o,
    output        flush_valid_o,

    //gpio pin connections
    output [ 7:0] gpio_pins_o,
    input  [ 7:0] gpio_pins_i,
    output [ 7:0] gpio_dir_o,

    // Private instruction-fetch sideband to cache_interface (bypasses the cache
    // controller + directory coherence, served straight from main memory).
    output        instr_valid_o,
    output [31:0] instr_addr_o,
    input         instr_ready_i,
    input         instr_rvalid_i,
    input  [31:0] instr_rdata_i,

    //cpu_id
    input  [ 7:0] cpu_id_i,

    // Boot-size status register (words), delivered via whoami. Static; used to
    // normalize data addresses to a 0-based data space and read back (read-only
    // to the core) at 0x8000_0004.
    input  [31:0] boot_len_i
);

    //addr decoding
    //check if addr starts with 0x8000
    logic is_mmio;
    logic is_flush;
    logic is_whoami;
    logic is_bootlen;
    logic is_special_addr;
    logic is_instr;
    always_comb begin
        is_mmio = ((mem_addr & 32'hFFFF_FFF0) == 32'h8000_0010);
        is_flush = (mem_addr == 32'h8000_0020);
        is_whoami = (mem_addr == 32'h8000_0000);
        is_bootlen = (mem_addr == 32'h8000_0004);
        is_special_addr = is_mmio | is_flush | is_whoami | is_bootlen;
        // Instruction fetch to a normal (non-special) address: routed on the
        // private sideband, never into the cache path.
        is_instr = mem_instr & mem_valid & ~is_special_addr;
    end

    //rdata logic
    logic [31:0] mmio_rd_data;
    logic [31:0] mem_rdata_l;
    assign mem_rdata = mem_rdata_l;
    always_comb begin
        if (is_whoami) begin
            mem_rdata_l = {24'b0, cpu_id_i}; // return chips unique ID
        end else if (is_bootlen) begin
            mem_rdata_l = boot_len_i;        // read-only boot-size status register
        end else if (is_flush) begin
            mem_rdata_l = '0;
        end else if (is_mmio) begin
            mem_rdata_l = mmio_rd_data; //return data from the mmio regs
        end else if (is_instr) begin
            mem_rdata_l = instr_rdata_i;     // fetched word from main memory (sideband)
        end else begin
            mem_rdata_l = pass_mem_rdata;
        end
    end

    logic mmio_wr_en;
    assign mmio_wr_en = |mem_wstrb & is_mmio & mem_valid;

    // flush logic
    logic [31:0] flush_addr_r;
    logic        flush_valid_r;

    // instruction-fetch sideband busy flag (declared here: it heads this module's
    // DFT scan chain, referenced in flush_reg below).
    logic instr_busy_r;

    logic [32:0] scan_state;
    wire scan_after_handler_regs;
    wire scan_after_mmio;

    assign scan_state = {flush_addr_r, flush_valid_r};
    assign scan_after_handler_regs = scan_state[32];
    assign scan_out_o = scan_after_mmio;

    mmio mmio_inst (
        .clk_i(clk_i),
        .rst_ni(rst_ni),
        .debug_mode_i(debug_mode_i),
        .scan_in_i(scan_after_handler_regs),
        .scan_out_o(scan_after_mmio),
        .addr_i(mem_addr),
        .wr_data_i(mem_wdata),
        .wstrb_i(mem_wstrb), //byte-lane select (native bus word-aligns mem_addr)
        .wr_en_i(mmio_wr_en), //only write if its a special addr
        .rd_data_o(mmio_rd_data),
        .gpio_pins_o(gpio_pins_o),
        .gpio_pins_i(gpio_pins_i),
        .gpio_dir_o(gpio_dir_o)
    );

    always_ff @( posedge clk_i ) begin : flush_reg
        if (!rst_ni) begin
            flush_addr_r <= '0;
            flush_valid_r <= '0;
        end else if (debug_mode_i) begin
            // DFT: chained after instr_busy_r (scan_in_i -> instr_busy_r -> here).
            {flush_addr_r, flush_valid_r} <= {scan_state[31:0], instr_busy_r};
        end else if (is_flush & mem_valid) begin
            // mem_addr is always the fixed 0x8000_0020 trigger address --
            // the line to flush is the value the CPU stores there, same
            // convention as every other MMIO write in this module.
            // Firmware supplies a byte address; shift to a word index to match
            // the now word-indexed cache (same translation as pass_mem_addr).
            flush_addr_r <= {2'b00, mem_wdata[31:2]};
            flush_valid_r <= '1;
        end else if (flush_ready_i) begin
                flush_valid_r <= '0;
        end else begin
            flush_valid_r <= flush_valid_r;
            flush_addr_r <= flush_addr_r;
        end
    end
    assign flush_valid_o = flush_valid_r;
    assign flush_addr_o = flush_addr_r;

    // Private instruction-fetch sideband sequencing. picorv32 holds mem_valid
    // until mem_ready, so gate the request with a busy flag: assert the request
    // until cache_interface accepts it, then wait for the response pulse. Exactly
    // one fetch is outstanding (picorv32 is single-outstanding).
    // (instr_busy_r declared above with the flush regs -- heads the scan chain.)
    assign instr_valid_o = is_instr & ~instr_busy_r;
    assign instr_addr_o  = {2'b00, mem_addr[31:2]};  // raw word index -- no offset

    always_ff @(posedge clk_i) begin : instr_fsm
        if (!rst_ni) begin
            instr_busy_r <= 1'b0;
        end else if (debug_mode_i) begin
            // DFT: instr_busy_r sits at the HEAD of this module's scan chain
            // (scan_in_i -> instr_busy_r -> flush regs -> mmio -> scan_out_o).
            instr_busy_r <= scan_in_i;
        end else if (~instr_busy_r) begin
            if (instr_valid_o & instr_ready_i) instr_busy_r <= 1'b1; // request accepted
        end else begin
            if (instr_rvalid_i)                instr_busy_r <= 1'b0; // response received
        end
    end

    // passthrough but only validate if not sp addr.
    // PicoRV32 drives word-aligned byte addresses (addr[1:0]==0, the accessed
    // byte lane is carried in mem_wstrb), but the cache / coherence / shared-
    // memory path is word-indexed. Translate byte address -> word index here,
    // the single CPU-side choke point, so the special-address decode above
    // stays on the raw byte address while everything downstream sees a proper
    // word index. Must be paired with the boot loader writing image word i at
    // word index i (boot_fsm sram_addr stride of 1).
    // Data accesses are normalized to a 0-based data space: subtract boot_len
    // (words) so the first data word (physical index boot_len) maps to index 0.
    // The OMM directory re-adds boot_len to reach physical memory. boot_len is
    // static, so this is a constant-operand subtract (not a timing-critical path).
    // Instruction fetches take the sideband above, never this path.
    assign pass_mem_addr = {2'b00, mem_addr[31:2]} - boot_len_i;
    assign pass_mem_wdata = mem_wdata;
    assign pass_mem_wstrb = mem_wstrb;
    assign pass_mem_valid = ~is_special_addr & ~is_instr & mem_valid;

    logic mem_ready_l;
    assign mem_ready = mem_ready_l;
    always_comb begin : mem_ready_comb
        if (is_instr) begin
            mem_ready_l = instr_busy_r & instr_rvalid_i; // fetch response arrived
        end else if (~is_special_addr) begin
            mem_ready_l = pass_mem_ready;
        end else if (is_mmio) begin
            mem_ready_l = '1; //mmio is always ready
        end else if (is_flush) begin
            mem_ready_l = flush_ready_i;
        end else if (is_whoami) begin
            mem_ready_l = '1; //whoami is always ready
        end else if (is_bootlen) begin
            mem_ready_l = '1; //read-only status, single-cycle
        end else begin
            mem_ready_l = '0;
        end
    end

endmodule
