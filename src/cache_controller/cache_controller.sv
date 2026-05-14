// SPDX-FileCopyrightText: © 2025 Albert Felix
// SPDX-License-Identifier: Apache-2.0

// MSI Cache Controller

`timescale 1ns/1ps
`default_nettype none

module cache_controller
(
  input  logic        clk_i,
  input  logic        rst_ni,

  // ── Processor → Cache ────────────────────────────────────────────
  input  logic        mem_valid_i,
  input  logic        mem_instr_i,
  input  logic [31:0] mem_addr_i,
  input  logic [31:0] mem_wdata_i,
  input  logic [3:0]  mem_wstrb_i,
  output logic        mem_ready_o,
  output logic [31:0] mem_rdata_o,

  // ── Cache → Directory (outbound coherence request) ────────────────
  output logic        cache_valid_o,
  output logic [31:0] cache_addr_o,
  output logic [31:0] cache_data_o,
  output logic [8:0]  cache_cmd_o,
  input  logic        cache_ready_i,

  // ── Directory → Cache (inbound coherence response) ────────────────
  input  logic        bus_valid_i,
  input  logic [31:0] bus_data_i,
  input  logic [2:0]  bus_dircmd_i,
  output logic        bus_ready_o,

  // ── Snoop Request (Directory → Cache) ─────────────────────────────
  input  logic        snoop_valid_i,
  input  logic [31:0] snoop_addr_i,
  input  logic [2:0]  snoop_dircmd_i,
  output logic        snoop_ready_o
);

  // Local parameters
  localparam logic [1:0] S_INVALID  = 2'b00;
  localparam logic [1:0] S_SHARED   = 2'b01;
  localparam logic [1:0] S_MODIFIED = 2'b10;

  // snoop acks
  localparam logic [8:0] SnoopBusRD_Ack_1h   = 9'b100000;
  localparam logic [8:0] SnoopBusRDX_Ack_1h  = 9'b1000000;
  localparam logic [8:0] SnoopBusUPGR_Ack_1h = 9'b10000000;

  // coherence cmds
  localparam logic [8:0] NULLcc1h            = 9'b0;
  localparam logic [8:0] BusRD_1h            = 9'b1;
  localparam logic [8:0] BusRDX_1h           = 9'b10;
  localparam logic [8:0] BusUPGR_1h          = 9'b100;
  localparam logic [8:0] EvictClean_1h       = 9'b1000;
  localparam logic [8:0] EvictDirty_1h       = 9'b10000;

  // coherence cmd acks
  localparam logic [2:0] BUSRD_ACK   = 3'b001;
  localparam logic [2:0] BUSRDX_ACK  = 3'b010;
  localparam logic [2:0] BUSUPGR_ACK = 3'b100;

  // Address layout: addr[6:0]=index (7 bits), addr[8:7]=tag (2 bits)
  // [8:7]; the params are kept for documentation. Reconcile this before
  // running real software on PicoRV32.
  localparam int OFFSET_W = 0;
  localparam int INDEX_W  = 7;
  localparam int TAG_W    = 2;
  localparam int TAG_HI   = OFFSET_W + INDEX_W + TAG_W - 1;  // 8
  localparam int TAG_LO   = OFFSET_W + INDEX_W;               // 7


  typedef enum logic [2:0] {
    SNP_IDLE             = 3'd0,
    SNP_FETCH_LINE_REQ   = 3'd1,
    SNP_FETCH_LINE_RESP  = 3'd2,
    SNP_ON_SNOOP_EVENT   = 3'd3,
    SNP_FLUSH_HANDLER    = 3'd4,
    SNP_UPDATE_LINE_REQ  = 3'd5,
    SNP_UPDATE_LINE_RESP = 3'd6,
    SNP_DONE             = 3'd7
  } snp_state_t;

  typedef enum logic [3:0] {
      CPU_IDLE                       = 4'd1,
      CPU_FETCH_LINE_REQ             = 4'd2,
      CPU_FETCH_LINE_RESP            = 4'd3,
      CPU_TAG_MISS                   = 4'd4,
      CPU_TAG_MATCH                  = 4'd5,
      CPU_READ_MISS                  = 4'd6,
      CPU_READ_MISS_ACK              = 4'd7,
      CPU_READ_MISS_UPDATE_LINE_REQ  = 4'd8,
      CPU_READ_MISS_UPDATE_LINE_RESP = 4'd9,
      CPU_READ_REQ                   = 4'd10,
      CPU_READ_RESP                  = 4'd11,
      CPU_WRITE_MISS                 = 4'd12,
      CPU_WRITE_MISS_ACK             = 4'd13,
      CPU_WRITE_REQ                  = 4'd14,
      CPU_WRITE_RESP                 = 4'd15
  } cpu_state_t;


  // Registers 
  cpu_state_t cpu_state_q, cpu_state_d;
  snp_state_t snp_state_q, snp_state_d;

  // CPU-side latched info about the current outstanding request
  logic [31:0] cpu_addr_q,       cpu_addr_d;
  logic [31:0] cpu_wdata_q,      cpu_wdata_d;
  logic [3:0]  cpu_wstrb_q,      cpu_wstrb_d;
  logic [1:0]  cpu_next_state_q, cpu_next_state_d;
  logic [8:0]  cpu_issue_cmd_q,  cpu_issue_cmd_d;
  logic        cpu_cmd_valid_q,  cpu_cmd_valid_d;
  logic [31:0] cpu_line_data_q,  cpu_line_data_d;
  logic [1:0]  cpu_line_tag_q,   cpu_line_tag_d;
  logic [1:0]  cpu_line_state_q, cpu_line_state_d;   
  logic        tag_match_cpu_q,  tag_match_cpu_d;

  // Snoop-side latched info about the current snoop
  logic [31:0] snp_addr_q,       snp_addr_d;
  logic [2:0]  snp_dircmd_q,     snp_dircmd_d;
  logic [1:0]  snp_next_state_q, snp_next_state_d;
  logic [1:0]  snp_tag_q,        snp_tag_d;
  logic        snp_flush_q,      snp_flush_d;
  logic [31:0] snp_flush_data_q, snp_flush_data_d;
  logic [1:0]  snp_line_state_q, snp_line_state_d;   


  // cache_mem wires
  // on_cpu_request port
  logic        cm_cpu_valid_i;
  logic        cm_cpu_ready_i;
  logic [31:0] cm_cpu_addr_i;
  logic [31:0] cm_cpu_wdata_i;
  logic [3:0]  cm_cpu_wstrb_i;
  logic [1:0]  cm_cpu_wstate_i;
  logic [1:0]  cm_cpu_wtag_i;
  logic        cm_cpu_ready_o;
  logic        cm_cpu_valid_o;
  logic [31:0] cm_cpu_rdata_o;
  logic [1:0]  cm_cpu_rstate_o;
  logic [1:0]  cm_cpu_rtag_o;

  // on_snoop_request port
  logic        cm_snoop_valid_i;
  logic        cm_snoop_ready_i;
  logic [31:0] cm_snoop_addr_i;
  logic [31:0] cm_snoop_wdata_i;
  logic [3:0]  cm_snoop_wstrb_i;
  logic [1:0]  cm_snoop_wstate_i;
  logic [1:0]  cm_snoop_wtag_i;
  logic        cm_snoop_ready_o;
  logic        cm_snoop_valid_o;
  logic [31:0] cm_snoop_rdata_o;
  logic [1:0]  cm_snoop_rstate_o;
  logic [1:0]  cm_snoop_rtag_o;

  two_port_cache_mem cache_mem
  (
    .clk_i(clk_i),
    .rst_ni(rst_ni),

    // on processor event port
    .p0_valid_i(cm_cpu_valid_i),
    .p0_ready_o(cm_cpu_ready_o),
    .p0_addr_i({25'd0, cm_cpu_addr_i[6:0]}), // take index bits as addr
    .p0_wdata_i(cm_cpu_wdata_i),
    .p0_wstrb_i(cm_cpu_wstrb_i),
    .p0_wstate_i(cm_cpu_wstate_i),
    .p0_wtag_i(cm_cpu_wtag_i),

    .p0_rdata_o(cm_cpu_rdata_o),
    .p0_rtag_o(cm_cpu_rtag_o),
    .p0_rstate_o(cm_cpu_rstate_o),
    .p0_valid_o(cm_cpu_valid_o),
    .p0_ready_i(cm_cpu_ready_i),

    // on snoop event port
    .p1_valid_i(cm_snoop_valid_i),
    .p1_ready_o(cm_snoop_ready_o),
    .p1_addr_i({25'd0, cm_snoop_addr_i[6:0]}),
    .p1_wdata_i(cm_snoop_wdata_i),
    .p1_wstrb_i(cm_snoop_wstrb_i),
    .p1_wstate_i(cm_snoop_wstate_i),
    .p1_wtag_i(cm_snoop_wtag_i),

    .p1_rdata_o(cm_snoop_rdata_o),
    .p1_rtag_o(cm_snoop_rtag_o),
    .p1_rstate_o(cm_snoop_rstate_o),
    .p1_valid_o(cm_snoop_valid_o),
    .p1_ready_i(cm_snoop_ready_i)
  );

  // outbound arbiter
  logic        outbound_cpu_cache_valid_i;
  logic [31:0] outbound_cpu_cache_addr_i;
  logic [31:0] outbound_cpu_cache_data_i;
  logic [8:0]  outbound_cpu_cache_cmd_i;
  logic        outbound_cpu_cache_ready_o;

  logic        outbound_snoop_cache_valid_i;
  logic [31:0] outbound_snoop_cache_addr_i;
  logic [31:0] outbound_snoop_cache_data_i;
  logic [8:0]  outbound_snoop_cache_cmd_i;
  logic        outbound_snoop_cache_ready_o;

  outbound_arbiter outbound_ctrl (
    .clk_i(clk_i),
    .rst_ni(rst_ni),

    .m0_valid_i(outbound_cpu_cache_valid_i),
    .m0_addr_i(outbound_cpu_cache_addr_i),
    .m0_data_i(outbound_cpu_cache_data_i),
    .m0_cmd_i(outbound_cpu_cache_cmd_i),
    .m0_ready_o(outbound_cpu_cache_ready_o),

    .m1_valid_i(outbound_snoop_cache_valid_i),
    .m1_addr_i(outbound_snoop_cache_addr_i),
    .m1_data_i(outbound_snoop_cache_data_i),
    .m1_cmd_i(outbound_snoop_cache_cmd_i),
    .m1_ready_o(outbound_snoop_cache_ready_o),

    .cache_valid_o(cache_valid_o),
    .cache_addr_o(cache_addr_o),
    .cache_data_o(cache_data_o),
    .cache_cmd_o(cache_cmd_o),
    .cache_ready_i(cache_ready_i)
  );


  // ============================================================
  // on_snoop_event_state_machine
  // ============================================================
  logic [1:0] on_snoop_event_state_o;
  logic       on_snnop_event_flush_o;
  on_snoop_event_state_machine u_snoop_sm (
    .current_state_i (snp_line_state_q),
    .snoop_event_i   (snp_dircmd_q),   // one-hot: 001=RD 010=RDX 100=UPGR
    .next_state_o    (on_snoop_event_state_o),
    .flush_o         (on_snnop_event_flush_o)
  );

  // ============================================================
  // on_processor_event_state_machine
  // ============================================================
  logic [1:0] on_processor_event_state_o;
  logic [8:0] on_processor_event_issue_cmd_o;
  logic       on_processor_event_cmd_valid_o;
  on_processor_event_state_machine u_proc_sm (
    .current_state_i   ((tag_match_cpu_q) ? cpu_line_state_q : S_INVALID),
    .wstrb_i           (cpu_wstrb_q),
    .next_state_o      (on_processor_event_state_o),
    .issue_cmd_o       (on_processor_event_issue_cmd_o),
    .issue_cmd_valid_o (on_processor_event_cmd_valid_o)
  );

  // ============================================================
  // apply_wstrb
  // ============================================================
  logic [31:0] data_to_write;
  apply_wstrb u_apply_wstrb_hit (
    .base_data_i (cpu_line_data_q),
    .wdata_i     (cpu_wdata_q),
    .wstrb_i     (cpu_wstrb_q),
    .result_o    (data_to_write)
  );


  // ============================================================
  // Sequential state update
  // ============================================================
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      cpu_state_q      <= CPU_IDLE;
      snp_state_q      <= SNP_IDLE;
      cpu_addr_q       <= 32'b0;
      cpu_wdata_q      <= 32'b0;
      cpu_wstrb_q      <= 4'b0;
      cpu_next_state_q <= S_INVALID;
      cpu_issue_cmd_q  <= 9'b0;
      cpu_cmd_valid_q  <= 1'b0;
      cpu_line_data_q  <= 32'b0;
      cpu_line_tag_q   <= 2'd0;
      cpu_line_state_q <= S_INVALID;    // NEW
      tag_match_cpu_q  <= 1'b1;
      snp_addr_q       <= 32'b0;
      snp_dircmd_q     <= 3'b0;
      snp_next_state_q <= S_INVALID;
      snp_flush_q      <= 1'b0;
      snp_flush_data_q <= 32'b0;
      snp_tag_q        <= 2'b0;
      snp_line_state_q <= S_INVALID;    // NEW
    end else begin
      cpu_state_q      <= cpu_state_d;
      snp_state_q      <= snp_state_d;
      cpu_addr_q       <= cpu_addr_d;
      cpu_wdata_q      <= cpu_wdata_d;
      cpu_wstrb_q      <= cpu_wstrb_d;
      cpu_next_state_q <= cpu_next_state_d;
      cpu_issue_cmd_q  <= cpu_issue_cmd_d;
      cpu_cmd_valid_q  <= cpu_cmd_valid_d;
      cpu_line_data_q  <= cpu_line_data_d;
      cpu_line_tag_q   <= cpu_line_tag_d;
      cpu_line_state_q <= cpu_line_state_d; // NEW
      tag_match_cpu_q  <= tag_match_cpu_d;
      snp_addr_q       <= snp_addr_d;
      snp_dircmd_q     <= snp_dircmd_d;
      snp_next_state_q <= snp_next_state_d;
      snp_flush_q      <= snp_flush_d;
      snp_flush_data_q <= snp_flush_data_d;
      snp_tag_q        <= snp_tag_d;
      snp_line_state_q <= snp_line_state_d; // NEW
    end
  end

  // ============================================================
  // Snoop FSM
  // ============================================================
  // pre slice wires 
  logic [1:0] snp_addr_tag;
  assign snp_addr_tag = snp_addr_q[8:7];
  always_comb begin

    // hold
    snp_state_d      = snp_state_q;
    snp_addr_d       = snp_addr_q;
    snp_dircmd_d     = snp_dircmd_q;
    snp_next_state_d = snp_next_state_q;
    snp_flush_d      = snp_flush_q;
    snp_flush_data_d = snp_flush_data_q;
    snp_tag_d        = snp_tag_q;
    snp_line_state_d = snp_line_state_q;   

    // cache_mem snoop-port controls (default off)
    cm_snoop_valid_i  = '0;
    cm_snoop_ready_i  = '0;
    cm_snoop_addr_i   = '0;
    cm_snoop_wdata_i  = '0;
    cm_snoop_wstrb_i  = '0;
    cm_snoop_wstate_i = '0;
    cm_snoop_wtag_i   = '0;

    // outbound snoop-cmd controls (default off)
    outbound_snoop_cache_valid_i = '0;
    outbound_snoop_cache_addr_i  = '0;
    outbound_snoop_cache_data_i  = '0;
    outbound_snoop_cache_cmd_i   = '0;
    // outbound_snoop_cache_ready_o = '0;

    // incoming bus ack (default off)
    bus_ready_o = 1'b0;

    // snoop ready handshake (default off)
    snoop_ready_o = 1'b0;

    case (snp_state_q)

      SNP_IDLE: begin
        if (snoop_valid_i) begin
          snp_addr_d    = snoop_addr_i;
          snp_dircmd_d  = snoop_dircmd_i;
          snp_state_d   = SNP_FETCH_LINE_REQ;
          snoop_ready_o = 1'b1;
        end
      end

      SNP_FETCH_LINE_REQ: begin
        cm_snoop_valid_i = 1'b1;
        cm_snoop_addr_i  = snp_addr_q;
        cm_snoop_wstrb_i = '0; // read
        if (cm_snoop_ready_o) begin
          snp_state_d = SNP_FETCH_LINE_RESP;
        end
      end

      SNP_FETCH_LINE_RESP: begin
        if (cm_snoop_valid_o) begin
          if (cm_snoop_rtag_o != snp_addr_tag) begin
            // ghost snoop: tag doesn't match, nothing to do, just ack
            snp_state_d = SNP_DONE;
          end
          else begin
            snp_flush_data_d = cm_snoop_rdata_o;
            snp_tag_d        = cm_snoop_rtag_o;
            snp_line_state_d = cm_snoop_rstate_o;   // FIX: latch state now
            snp_state_d      = SNP_ON_SNOOP_EVENT;
          end
          cm_snoop_ready_i = 1'b1;
        end
      end

      SNP_ON_SNOOP_EVENT: begin
        snp_next_state_d = on_snoop_event_state_o;
        snp_flush_d      = on_snnop_event_flush_o;

        if (on_snnop_event_flush_o) begin
          snp_state_d = SNP_FLUSH_HANDLER;
        end else begin
          snp_state_d = SNP_UPDATE_LINE_REQ;
        end
      end

      SNP_FLUSH_HANDLER: begin
        outbound_snoop_cache_valid_i = 1'b1;
        outbound_snoop_cache_addr_i  = snp_addr_q;
        outbound_snoop_cache_data_i  = snp_flush_data_q;
        outbound_snoop_cache_cmd_i   = EvictDirty_1h;

        if (outbound_snoop_cache_ready_o) begin
          // evicts have no ack in this system
          snp_state_d = SNP_UPDATE_LINE_REQ;
        end
      end

      SNP_UPDATE_LINE_REQ: begin
        cm_snoop_valid_i  = 1'b1;
        cm_snoop_addr_i   = snp_addr_q;
        cm_snoop_wstrb_i  = '1; // write
        cm_snoop_wdata_i  = snp_flush_data_q;
        cm_snoop_wtag_i   = snp_tag_q;
        cm_snoop_wstate_i = snp_next_state_q;

        if (cm_snoop_ready_o) begin
          snp_state_d = SNP_UPDATE_LINE_RESP;
        end
      end

      SNP_UPDATE_LINE_RESP: begin
        if (cm_snoop_valid_o) begin
          cm_snoop_ready_i = 1'b1;
          snp_state_d      = SNP_DONE;
        end
      end

      SNP_DONE: begin
        outbound_snoop_cache_valid_i = 1'b1;
        outbound_snoop_cache_addr_i  = snp_addr_q;
        outbound_snoop_cache_data_i  = '0;
        if (snp_dircmd_q == 3'b001) begin
          outbound_snoop_cache_cmd_i = SnoopBusRD_Ack_1h;
        end
        else if (snp_dircmd_q == 3'b010) begin
          outbound_snoop_cache_cmd_i = SnoopBusRDX_Ack_1h;
        end
        else if (snp_dircmd_q == 3'b100) begin
          outbound_snoop_cache_cmd_i = SnoopBusUPGR_Ack_1h;
        end
        else begin
          outbound_snoop_cache_cmd_i = NULLcc1h;
        end

        if (outbound_snoop_cache_ready_o) begin
          snp_state_d = SNP_IDLE;
        end
      end

      default: snp_state_d = SNP_IDLE;
    endcase
  end


  // ============================================================
  // CPU FSM
  // ============================================================
  //
   
  // pre slice wires 
  logic [1:0] cpu_addr_tag;
  assign cpu_addr_tag = cpu_addr_q[8:7];
  always_comb begin

    // hold
    cpu_state_d      = cpu_state_q;
    cpu_addr_d       = cpu_addr_q;
    cpu_wdata_d      = cpu_wdata_q;
    cpu_wstrb_d      = cpu_wstrb_q;
    cpu_next_state_d = cpu_next_state_q;
    cpu_issue_cmd_d  = cpu_issue_cmd_q;
    cpu_cmd_valid_d  = cpu_cmd_valid_q;
    cpu_line_data_d  = cpu_line_data_q;
    cpu_line_tag_d   = cpu_line_tag_q;
    cpu_line_state_d = cpu_line_state_q;   // NEW: hold
    tag_match_cpu_d  = tag_match_cpu_q;

    // cache_mem cpu-port controls (default off)
    cm_cpu_valid_i  = '0;
    cm_cpu_ready_i  = '0;
    cm_cpu_addr_i   = '0;
    cm_cpu_wdata_i  = '0;
    cm_cpu_wstrb_i  = '0;
    cm_cpu_wstate_i = '0;
    cm_cpu_wtag_i   = '0;

    // outbound cpu-cmd controls (default off)
    outbound_cpu_cache_valid_i = '0;
    outbound_cpu_cache_addr_i  = '0;
    outbound_cpu_cache_data_i  = '0;
    outbound_cpu_cache_cmd_i   = '0;
    // outbound_cpu_cache_ready_o = '0;

    // cpu-interface (default off)
    mem_ready_o = 1'b0;
    mem_rdata_o = '0;

    case (cpu_state_q)

      CPU_IDLE: begin
        if (mem_valid_i) begin
          cpu_addr_d  = mem_addr_i;
          cpu_wdata_d = mem_wdata_i;
          cpu_wstrb_d = mem_wstrb_i;
          cpu_state_d = CPU_FETCH_LINE_REQ;
        end
      end

      CPU_FETCH_LINE_REQ: begin
        cm_cpu_valid_i = 1'b1;
        cm_cpu_addr_i  = cpu_addr_q;
        cm_cpu_wstrb_i = '0; // read
        if (cm_cpu_ready_o) begin
          cpu_state_d = CPU_FETCH_LINE_RESP;
        end
      end

      CPU_FETCH_LINE_RESP: begin
        if (cm_cpu_valid_o) begin
          if (cm_cpu_rtag_o != cpu_addr_tag && cm_cpu_rstate_o != S_INVALID) begin
            // tag miss with a valid line -> need to flush before refill.
            tag_match_cpu_d  = 1'b0;
            cpu_line_data_d  = cm_cpu_rdata_o;
            cpu_line_tag_d   = cm_cpu_rtag_o;
            cpu_line_state_d = cm_cpu_rstate_o;
            cpu_state_d      = CPU_TAG_MISS;
          end
          else begin
            // tag hit, or tag miss on an invalid line (nothing to evict)
            cpu_line_data_d  = cm_cpu_rdata_o;
            cpu_line_tag_d   = cm_cpu_rtag_o;
            cpu_line_state_d = cm_cpu_rstate_o;   // FIX: latch state now
            cpu_state_d      = CPU_TAG_MATCH;
          end
          cm_cpu_ready_i = 1'b1;
        end
      end

      CPU_TAG_MISS: begin
        // flush out the wrong tag using LATCHED state (was cm_cpu_rstate_o, racy)
        outbound_cpu_cache_valid_i = 1'b1;
        outbound_cpu_cache_addr_i  = cpu_addr_q;
        outbound_cpu_cache_data_i  = cpu_line_data_q;
        if (cpu_line_state_q == S_SHARED) begin
          outbound_cpu_cache_cmd_i = EvictClean_1h;
        end
        else if (cpu_line_state_q == S_MODIFIED) begin
          outbound_cpu_cache_cmd_i = EvictDirty_1h;
        end
        else begin
          outbound_cpu_cache_cmd_i = NULLcc1h;
        end

        if (outbound_cpu_cache_ready_o) begin
          // evicts have no ack in this system
          cpu_state_d = CPU_TAG_MATCH;
        end
      end


      CPU_TAG_MATCH: begin
        // u_proc_sm reads cpu_line_state_q (latched) gated by tag_match_cpu_q,
        // so its outputs are stable and not affected by snoop port activity.
        cpu_next_state_d = on_processor_event_state_o;
        cpu_issue_cmd_d  = on_processor_event_issue_cmd_o;
        cpu_cmd_valid_d  = on_processor_event_cmd_valid_o;

        // read
        if (cpu_wstrb_q == 4'd0) begin
          if (on_processor_event_cmd_valid_o) begin
            cpu_state_d = CPU_READ_MISS;
          end
          else begin
            cpu_state_d = CPU_READ_REQ;
          end
        end
        // write
        else begin
          if (on_processor_event_cmd_valid_o) begin
            cpu_state_d = CPU_WRITE_MISS;
          end
          else begin
            cpu_state_d = CPU_WRITE_REQ;
          end
        end
      end


      CPU_READ_MISS: begin
        outbound_cpu_cache_valid_i = 1'b1;
        outbound_cpu_cache_addr_i  = cpu_addr_q;
        outbound_cpu_cache_data_i  = cpu_line_data_q;
        outbound_cpu_cache_cmd_i   = cpu_issue_cmd_q;

        if (outbound_cpu_cache_ready_o) begin
          cpu_state_d = CPU_READ_MISS_ACK;
        end
      end


      CPU_READ_MISS_ACK: begin
        if (bus_valid_i) begin
          if (bus_dircmd_i == BUSRD_ACK) begin
            cpu_line_data_d = bus_data_i;
          end
          else if (bus_dircmd_i == BUSRDX_ACK) begin
            cpu_line_data_d = bus_data_i;
          end
          else if (bus_dircmd_i == BUSUPGR_ACK) begin
            // do nothing with data
          end
          else begin
            // error
          end
          bus_ready_o = 1'b1;
          cpu_state_d = CPU_READ_MISS_UPDATE_LINE_REQ;
        end
      end

      CPU_READ_MISS_UPDATE_LINE_REQ: begin
        cm_cpu_valid_i  = 1'b1;
        cm_cpu_addr_i   = cpu_addr_q;
        cm_cpu_wstrb_i  = 4'b1111;
        cm_cpu_wdata_i  = cpu_line_data_q;
        cm_cpu_wtag_i   = cpu_addr_tag;
        cm_cpu_wstate_i = cpu_next_state_q;

        if (cm_cpu_ready_o) begin
          cpu_state_d = CPU_READ_MISS_UPDATE_LINE_RESP;
        end
      end

      CPU_READ_MISS_UPDATE_LINE_RESP: begin
        // FIX: wait on valid_o and ack with ready_i. Previous version polled
        // ready_o (which won't re-assert until ready_i pulses) → deadlock.
        if (cm_cpu_valid_o) begin
          cm_cpu_ready_i = 1'b1;
          cpu_state_d    = CPU_READ_REQ;
        end
      end

      CPU_READ_REQ: begin
        cm_cpu_valid_i = 1'b1;
        cm_cpu_addr_i  = cpu_addr_q;
        cm_cpu_wstrb_i = 4'b0000; // read

        if (cm_cpu_ready_o) begin
          cpu_state_d = CPU_READ_RESP;
        end
      end

      CPU_READ_RESP: begin
        if (cm_cpu_valid_o) begin
          mem_rdata_o    = cm_cpu_rdata_o; // feed data out to cpu
          mem_ready_o    = 1'b1;
          cm_cpu_ready_i = 1'b1;

          tag_match_cpu_d = 1'b1;
          cpu_state_d     = CPU_IDLE;
        end
      end

      CPU_WRITE_MISS: begin
        outbound_cpu_cache_valid_i = 1'b1;
        outbound_cpu_cache_addr_i  = cpu_addr_q;
        outbound_cpu_cache_data_i  = cpu_line_data_q;
        outbound_cpu_cache_cmd_i   = cpu_issue_cmd_q;

        if (outbound_cpu_cache_ready_o) begin
          cpu_state_d = CPU_WRITE_MISS_ACK;
        end
      end

      CPU_WRITE_MISS_ACK: begin
        if (bus_valid_i) begin
          if (bus_dircmd_i == BUSRD_ACK) begin
            cpu_line_data_d = bus_data_i;
          end
          else if (bus_dircmd_i == BUSRDX_ACK) begin
            cpu_line_data_d = bus_data_i;
          end
          else if (bus_dircmd_i == BUSUPGR_ACK) begin
            // we already had the line in S, keep our copy of the data
          end
          else begin
            // error
          end
          bus_ready_o = 1'b1;
          cpu_state_d = CPU_WRITE_REQ;
        end
      end

      CPU_WRITE_REQ: begin
        cm_cpu_valid_i  = 1'b1;
        cm_cpu_addr_i   = cpu_addr_q;
        cm_cpu_wstrb_i  = cpu_wstrb_q;
        cm_cpu_wdata_i  = data_to_write;
        cm_cpu_wtag_i   = cpu_addr_tag;
        cm_cpu_wstate_i = cpu_next_state_q;

        if (cm_cpu_ready_o) begin
          cpu_state_d = CPU_WRITE_RESP;
        end
      end

      CPU_WRITE_RESP: begin
        if (cm_cpu_valid_o) begin
          mem_ready_o    = 1'b1;
          cm_cpu_ready_i = 1'b1;

          tag_match_cpu_d = 1'b1;
          cpu_state_d     = CPU_IDLE;
        end
      end

      default: cpu_state_d = CPU_IDLE;

    endcase
  end
endmodule

`default_nettype wire
