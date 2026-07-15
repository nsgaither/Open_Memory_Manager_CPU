`default_nettype none

module mem512x32
(
  input  wire         clk_i,
  input  wire         rst_ni,

  // DFT scan interface. debug_mode_i is the scan/functional mux select.
  input  wire         debug_mode_i,
  input  wire         scan_in_i,
  output wire         scan_out_o,

  input  wire [0:0]   mem_valid_i,
  output wire [0:0]   mem_ready_o,
  input  wire [31:0]  mem_addr_i, /* verilator lint_off UNUSEDSIGNAL */
  input  wire [31:0]  mem_wdata_i, /* verilator lint_on UNUSEDSIGNAL */
  input  wire [3:0]   mem_wstrb_i,

  output wire [31:0]  mem_rdata_o,
  output wire [0:0]   mem_valid_o,
  input  wire [0:0]   mem_ready_i

  `ifdef USE_POWER_PINS
	    ,input wire VDD //adding these for librelane
	    ,input wire VSS
  `endif
);

  // 4x BANKED data store: 512 words x 32b across TWO 3.3V ocd 1024x8 macros,
  // byte-interleaved for a parallel 2-access read instead of the old
  // byte-serial 4-access walk.
  //   macro0 (sram0) holds bytes {0,1} of every word; macro1 (sram1) holds {2,3}.
  //   For word W, half h in {0,1}: row {W, h}. h=0 -> {b0,b2}, h=1 -> {b1,b3}.
  // Both macros share the address bus and are accessed every cycle, so a word
  // needs only two SRAM accesses (half0 then half1) rather than four. Capacity
  // is unchanged: each macro stores 2 bytes x 512 words = 1024 rows (full
  // 1024x8), and the reset clear walks 1024 rows (both macros in parallel),
  // half the old 2048. mem_addr_i[8:0] is the word index.
  typedef enum logic [2:0] {
    RESET_SRAMS = 3'd0,
    RESET_DATA  = 3'd1,
    IDLE        = 3'd2,
    MEM_REQ_0   = 3'd3,   // present/write half 0 (bytes 0 and 2)
    MEM_REQ_1   = 3'd4,   // present/write half 1 (bytes 1 and 3); capture half 0
    MEM_REQ_2   = 3'd5,   // capture half 1
    MEM_RESP    = 3'd6
  } state_t;

  state_t state_q, state_d;

  logic [9:0]  reset_addr_q, reset_addr_d;   // 0..1023 clear walk
  logic [8:0]  word_addr_q,  word_addr_d;    // latched word index (512 words)
  logic [31:0] wdata_q,      wdata_d;
  logic [3:0]  mode_q,       mode_d;         // latched wstrb (0 => read)
  logic [31:0] rdata_q,      rdata_d;

  wire is_write = |mode_q;

  // Scan chain: functional pass-through of the state registers. Length is
  // intentionally not tuned here (datapath still in flux).
  logic [89:0] scan_state;
  assign scan_state = {
    rdata_q, wdata_q, word_addr_q, reset_addr_q, mode_q, state_q
  };
  assign scan_out_o = scan_state[89];

  // Per-macro read data
  logic [7:0] q0, q1;

  always_ff @(posedge clk_i) begin
    if (!rst_ni) begin
      state_q      <= RESET_SRAMS;
      reset_addr_q <= '0;
      word_addr_q  <= '0;
      wdata_q      <= '0;
      mode_q       <= '0;
      rdata_q      <= '0;
    end else if (debug_mode_i) begin
      {rdata_q, wdata_q, word_addr_q, reset_addr_q, mode_q, state_q}
        <= {scan_state[88:0], scan_in_i};
    end else begin
      state_q      <= state_d;
      reset_addr_q <= reset_addr_d;
      word_addr_q  <= word_addr_d;
      wdata_q      <= wdata_d;
      mode_q       <= mode_d;
      rdata_q      <= rdata_d;
    end
  end

  wire [8:0] mem_word_addr = mem_addr_i[8:0];

  // Next-state + read capture
  always_comb begin
    state_d      = state_q;
    reset_addr_d = reset_addr_q;
    word_addr_d  = word_addr_q;
    wdata_d      = wdata_q;
    mode_d       = mode_q;
    rdata_d      = rdata_q;

    case (state_q)

      RESET_SRAMS: state_d = RESET_DATA;

      RESET_DATA: begin
        reset_addr_d = reset_addr_q + 1'b1;
        if (reset_addr_q == 10'd1023)
          state_d = IDLE;
      end

      IDLE: begin
        if (mem_valid_i && mem_ready_o) begin
          word_addr_d = mem_word_addr;
          wdata_d     = mem_wdata_i;
          mode_d      = mem_wstrb_i;
          rdata_d     = 32'd0;
          state_d     = MEM_REQ_0;
        end
      end

      MEM_REQ_0: state_d = MEM_REQ_1;

      MEM_REQ_1: begin
        // Q reflects half 0 (presented in MEM_REQ_0): b0=q0 (macro0), b2=q1 (macro1)
        rdata_d[7:0]   = q0;
        rdata_d[23:16] = q1;
        state_d        = MEM_REQ_2;
      end

      MEM_REQ_2: begin
        // Q reflects half 1 (presented in MEM_REQ_1): b1=q0 (macro0), b3=q1 (macro1)
        rdata_d[15:8]  = q0;
        rdata_d[31:24] = q1;
        state_d        = MEM_RESP;
      end

      MEM_RESP: begin
        if (mem_valid_o && mem_ready_i)
          state_d = IDLE;
      end

      default: state_d = IDLE;

    endcase
  end

  assign mem_ready_o = (state_q == IDLE);
  assign mem_valid_o = (state_q == MEM_RESP);
  assign mem_rdata_o = rdata_q;

  // SRAM control. Both macros share the address bus and are enabled together;
  // per-macro GWEN selects which byte lanes are written on each half.
  logic [9:0] sram_addr;
  logic       sram_cen;
  logic       gwen0, gwen1;
  logic [7:0] d0, d1;

  always_comb begin
    sram_cen  = 1'b1;
    gwen0     = 1'b1;
    gwen1     = 1'b1;
    sram_addr = {word_addr_q, 1'b0};
    d0        = wdata_q[7:0];
    d1        = wdata_q[23:16];

    case (state_q)
      RESET_DATA: begin
        sram_cen  = 1'b0;
        gwen0     = 1'b0;
        gwen1     = 1'b0;
        sram_addr = reset_addr_q;
        d0        = 8'h00;
        d1        = 8'h00;
      end
      MEM_REQ_0: begin           // half 0: byte0 (macro0), byte2 (macro1)
        sram_cen  = 1'b0;
        sram_addr = {word_addr_q, 1'b0};
        d0        = wdata_q[7:0];    // b0
        d1        = wdata_q[23:16];  // b2
        gwen0     = is_write ? ~mode_q[0] : 1'b1;
        gwen1     = is_write ? ~mode_q[2] : 1'b1;
      end
      MEM_REQ_1: begin           // half 1: byte1 (macro0), byte3 (macro1)
        sram_cen  = 1'b0;
        sram_addr = {word_addr_q, 1'b1};
        d0        = wdata_q[15:8];   // b1
        d1        = wdata_q[31:24];  // b3
        gwen0     = is_write ? ~mode_q[1] : 1'b1;
        gwen1     = is_write ? ~mode_q[3] : 1'b1;
      end
      default: ; // IDLE / MEM_REQ_2 / MEM_RESP: no SRAM access
    endcase

    // Scan-shifted controller states must not accidentally write the SRAM
    // macros. The inserted state takes effect after debug mode is released.
    if (debug_mode_i) begin
      sram_cen = 1'b1;
      gwen0    = 1'b1;
      gwen1    = 1'b1;
    end
  end

  // macro0: byte lanes {0,1}
  (* keep *) gf180mcu_ocd_ip_sram__sram1024x8m8wm1 sram0 (
    .CLK(clk_i),
    .CEN(sram_cen),
    .GWEN(gwen0),
    .WEN(8'b0),
    .A(sram_addr),
    .D(d0),
    .Q(q0)
    `ifdef USE_POWER_PINS
       // verilator lint_off ASSIGNIN
    ,.VDD(VDD)
    ,.VSS(VSS)
       // verilator lint_on ASSIGNIN
    `endif
  );

  // macro1: byte lanes {2,3}
  (* keep *) gf180mcu_ocd_ip_sram__sram1024x8m8wm1 sram1 (
    .CLK(clk_i),
    .CEN(sram_cen),
    .GWEN(gwen1),
    .WEN(8'b0),
    .A(sram_addr),
    .D(d1),
    .Q(q1)
    `ifdef USE_POWER_PINS
       // verilator lint_off ASSIGNIN
    ,.VDD(VDD)
    ,.VSS(VSS)
       // verilator lint_on ASSIGNIN
    `endif
  );

endmodule

`default_nettype wire
