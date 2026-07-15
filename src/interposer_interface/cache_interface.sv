`timescale 1ns/1ps

module cache_interface #(
    parameter int NUM_TPINS = 1,
    parameter int NUM_RPINS = 1
)
(
    input  logic                clk_i,
    input  logic                rst_ni,

    // Two DFT lanes: lane 0 covers receive pipes/CPU ID and lane 1 covers
    // the transmit/receive serializers.
    input  logic                debug_mode_i,
    input  logic [1:0]          scan_in_i,
    output logic [1:0]          scan_out_o,
    // UPSTREAM --------------------------------------
    // Cache Send Ports
    input  logic                cache_valid_i,
    input  logic [31:0]         cache_addr_i,
    input  logic [31:0]         cache_data_i,
    input  logic [3:0]          cache_cmd_i,
    output logic                cache_ready_o,

    // Bus Ack ports
    output logic                bus_valid_o,
    output logic [31:0]         bus_data_o,
    output logic [3:0]          bus_dircmd_o,
    input  logic                bus_ready_i,

    // Snoop Req ports
    output logic                snoop_valid_o,
    output logic [31:0]         snoop_data_o,
    output logic [3:0]          snoop_dircmd_o,
    input  logic                snoop_ready_i,

    // Private instruction-fetch sideband (from sp_addr_handler, bypasses the
    // cache controller). Request in, response out.
    input  logic                instr_valid_i,
    input  logic [31:0]         instr_addr_i,
    output logic                instr_ready_o,
    output logic                instr_rvalid_o,
    output logic [31:0]         instr_rdata_o,

    // busy
    output logic                rbusy_o,

    // other
    output logic [7:0]          cpu_id_o,
    // Boot-size status register, delivered inside the widened WhoAmI frame.
    output logic [31:0]         boot_len_o,
    // -----------------------------------------------

    // DOWNSTREAM ------------------------------------
    // wrapped serializer IO
    input  logic [4:0]           req_i_branches,
    input  logic [NUM_RPINS-1:0] serial_i,
    output logic                 req_o,
    output logic [NUM_TPINS-1:0] serial_o
    // -----------------------------------------------
);

    typedef enum logic [3:0] {
        NULL            = 4'b0000,
        BusRD           = 4'b0001,
        BusRDX          = 4'b0010,
        BusUPGR         = 4'b0011,

        // Private instruction fetch: bypasses cache_controller + directory
        // coherence, served straight from main memory. Injected here from the
        // sp_addr_handler sideband, not from cache_controller.
        InstrFetch      = 4'b0100,

        EvictClean      = 4'b0101,
        EvictDirty      = 4'b0110,


        SnoopBusRD      = 4'b1001,
        SnoopBusRDX     = 4'b1010,
        SnoopBusUPGR    = 4'b1011,


        WhoAmI          = 4'b1110,
        ResetDone       = 4'b1111
    } metadata;

    typedef enum logic [1:0] {
        CMDONLY = 2'b00,
        SHORT   = 2'b01,
        MEDIUM  = 2'b10,
        LARGE   = 2'b11
    } msg_types;

    // TRANSMISSION
    logic [69:0] t_packet;
    wire scan_after_tserializer;
    wire scan_after_rserializer;
    wire scan_after_bus_pipe;
    wire scan_after_snoop_pipe;

    // Transmit arbitration: the cache_controller stream has priority over the
    // instruction-fetch sideband. picorv32 is single-outstanding, so a CPU data
    // request and a fetch never coexist; the only overlap is a fetch vs a
    // cache_controller snoop-ack, which the fetch simply waits behind (it cannot
    // deadlock -- a stalled fetch generates no new CPU traffic, snoop-acks drain).
    logic tx_sel_instr;
    assign tx_sel_instr = instr_valid_i & ~cache_valid_i;

    // cache_cmd_i is already the 4-bit binary `metadata` code, so the packet's
    // metadata field is just cache_cmd_i; the case only selects msg length + payload.
    always_comb begin : build_packet
        if (tx_sel_instr) begin
            // Private fetch request: command + address, MEDIUM (36-bit) frame.
            t_packet = {MEDIUM, 32'b0, instr_addr_i, InstrFetch};
        end else begin
            case (cache_cmd_i)
                BusRD, BusRDX, BusUPGR : t_packet = {MEDIUM,  32'b0,        cache_addr_i, cache_cmd_i};
                EvictClean             : t_packet = {MEDIUM,  32'b0,        cache_addr_i, cache_cmd_i};
                EvictDirty             : t_packet = {LARGE,   cache_data_i, cache_addr_i, cache_cmd_i};
                SnoopBusRD, SnoopBusRDX: t_packet = {MEDIUM,  32'b0,        cache_data_i, cache_cmd_i};
                SnoopBusUPGR           : t_packet = {CMDONLY, 32'b0,        32'b0,        cache_cmd_i};
                ResetDone              : t_packet = {CMDONLY, 32'b0,        32'b0,        cache_cmd_i};
                default                : t_packet = '0;
            endcase
        end
    end

    // Single tserializer valid = either source wants to send; ready is routed to
    // whichever source is currently selected.
    logic tser_valid;
    logic tser_ready;
    assign tser_valid    = cache_valid_i | instr_valid_i;
    assign cache_ready_o = tser_ready & ~tx_sel_instr;
    assign instr_ready_o = tser_ready &  tx_sel_instr;

    tserializer #(
        .NUM_PINS    (NUM_TPINS),
        .MAX_MSG_LEN (68),
        .MSG_LEN_0   (4),
        .MSG_LEN_1   (12),
        .MSG_LEN_2   (36),
        .MSG_LEN_3   (68)
    ) u_tserializer (
        .clk_i    (clk_i),
        .rst_ni   (rst_ni),
        .debug_mode_i (debug_mode_i),
        .scan_in_i     (scan_in_i[1]),
        .scan_out_o    (scan_after_tserializer),

        .req_o    (req_o),
        .serial_o (serial_o),

        .valid_i  (tser_valid),
        .data_in  ({4'b0, t_packet[67:0]}),
        .msg_type (t_packet[69:68]),
        .ready_o  (tser_ready)
    );

    // RECEIVING
    // Widened to 68 so the WhoAmI LARGE frame (boot_len + cpu_id) fits. A 36-bit
    // ack still lands in rpacket_full[35:0] identically (the rserializer fills
    // from word 0 upward), so bus/snoop decode is unchanged; only WhoAmI reads
    // the upper bits [67:36].
    wire [(int'($ceil(real'(68) / NUM_RPINS)) * NUM_RPINS)-1:0] rpacket_full;
    wire rvalid_o;
    assign rbusy_o = req_i_branches[0];
    rserializer #(
        .NUM_PINS    (NUM_RPINS),
        .MAX_MSG_LEN (68)
    ) u_rserializer (
        .clk_i    (clk_i),
        .rst_ni   (rst_ni),
        .debug_mode_i (debug_mode_i),
        .scan_in_i     (scan_after_tserializer),
        .scan_out_o    (scan_after_rserializer),
        
        .serial_i (serial_i),
        .req_i_branches (req_i_branches),

        .valid_o  (rvalid_o),
        .data_o   (rpacket_full),
        .ready_i  (1'b1)
    );

    logic [3:0] rmetadata;
    assign rmetadata = rpacket_full[3:0];

    logic           bus_valid_d;
    logic           snoop_valid_d;
    logic           instr_resp_valid_d;

    // No one-hot conversion: rmetadata IS the command code passed downstream.
    // Just route it to the bus vs snoop pipe (or the instruction-fetch response).
    // dir->cache acks echo the request's metadata code (EvictDirty = dirty
    // writeback persisted; InstrFetch = fetched word returned).
    always_comb begin : decode_packet
        bus_valid_d        = 1'b0;
        snoop_valid_d      = 1'b0;
        instr_resp_valid_d = 1'b0;

        case (rmetadata)
            BusRD, BusRDX, BusUPGR, EvictDirty    : bus_valid_d        = rvalid_o;
            SnoopBusRD, SnoopBusRDX, SnoopBusUPGR : snoop_valid_d      = rvalid_o;
            InstrFetch                            : instr_resp_valid_d = rvalid_o;
            default                               : ;
        endcase
    end

    logic [31:0]    receive_data_d;
    assign receive_data_d = rpacket_full[35:4];

    // bus ack data interface
    wire bus_ack_rready_i; /* verilator lint_off UNUSEDSIGNAL */ /* verilator lint_on UNUSEDSIGNAL */
    lossy_pipe_stage #(
        .WIDTH(36)
    ) bus_ack_pipe (
        .clk_i   (clk_i),
        .rst_ni  (rst_ni),
        .debug_mode_i (debug_mode_i),
        .scan_in_i     (scan_in_i[0]),
        .scan_out_o    (scan_after_bus_pipe),

        // Upstream Interface
        .valid_i (bus_valid_d),
        .data_i  ({rmetadata, receive_data_d}),
        .ready_o (bus_ack_rready_i),    // tied to one because it's lossy

        // Downstream Interface
        .valid_o (bus_valid_o),
        .data_o  ({bus_dircmd_o, bus_data_o}),
        .ready_i (bus_ready_i)
    );

    // snoop data interface
    wire snoop_rready_i; /* verilator lint_off UNUSEDSIGNAL */ /* verilator lint_on UNUSEDSIGNAL */
    lossy_pipe_stage #(
        .WIDTH(36)
    ) snoop_pipe (
        .clk_i   (clk_i),
        .rst_ni  (rst_ni),
        .debug_mode_i (debug_mode_i),
        .scan_in_i     (scan_after_bus_pipe),
        .scan_out_o    (scan_after_snoop_pipe),

        // Upstream Interface
        .valid_i (snoop_valid_d),
        .data_i  ({rmetadata, receive_data_d}),
        .ready_o (snoop_rready_i),    // tied to one because it's lossy

        // Downstream Interface
        .valid_o (snoop_valid_o),
        .data_o  ({snoop_dircmd_o, snoop_data_o}),
        .ready_i (snoop_ready_i)
    );

    // hold cpu_id
    logic [31:0] boot_len_r;
    logic        instr_rvalid_r;
    logic [31:0] instr_rdata_r;

    logic [7:0] cpu_id_r;
    assign cpu_id_o = cpu_id_r;
    // DFT scan lane 0 tail: ... -> cpu_id_r -> boot_len_r -> instr_rdata_r ->
    // instr_rvalid_r -> scan_out_o[0]. (Lane 1 stays the serializer chain.)
    assign scan_out_o[0] = instr_rvalid_r;
    assign scan_out_o[1] = scan_after_rserializer;

    always_ff @( posedge clk_i ) begin : cpuid_reg
        if (!rst_ni) begin
            cpu_id_r <= '0;
        end else if (debug_mode_i) begin
            cpu_id_r <= {cpu_id_r[6:0], scan_after_snoop_pipe};
        end else if ((rmetadata == WhoAmI) & (rvalid_o == 1)) begin
            cpu_id_r <= rpacket_full[11:4];
        end
    end

    // hold boot_len: upper 32 bits of the WhoAmI LARGE frame. Static after boot;
    // feeds sp_addr_handler data normalization + the 0x8000_0004 MMIO read.
    assign boot_len_o = boot_len_r;
    always_ff @( posedge clk_i ) begin : bootlen_reg
        if (!rst_ni)
            boot_len_r <= '0;
        else if (debug_mode_i)
            boot_len_r <= {boot_len_r[30:0], cpu_id_r[7]};   // DFT: after cpu_id_r
        else if ((rmetadata == WhoAmI) & (rvalid_o == 1'b1))
            boot_len_r <= rpacket_full[67:36];
    end

    // Private instruction-fetch response: a 1-cycle valid pulse + latched word,
    // consumed by sp_addr_handler (which is waiting -- single-outstanding fetch).
    assign instr_rvalid_o = instr_rvalid_r;
    assign instr_rdata_o  = instr_rdata_r;
    always_ff @( posedge clk_i ) begin : instr_resp_reg
        if (!rst_ni) begin
            instr_rvalid_r <= 1'b0;
            instr_rdata_r  <= '0;
        end else if (debug_mode_i) begin
            // DFT: instr_rdata_r after boot_len_r, then instr_rvalid_r (chain tail).
            instr_rdata_r  <= {instr_rdata_r[30:0], boot_len_r[31]};
            instr_rvalid_r <= instr_rdata_r[31];
        end else begin
            instr_rvalid_r <= instr_resp_valid_d;
            if (instr_resp_valid_d)
                instr_rdata_r <= receive_data_d;   // rpacket_full[35:4] = fetched word
        end
    end

endmodule
