module two_port_cache_mem #(
  parameter ADDR_W  = 32,
  parameter DATA_W  = 32,
  parameter STRB_W  = DATA_W/8,
  parameter STATE_W = 2,
  parameter TAG_W   = 2
)(
  input  logic clk_i,
  input  logic rst_ni,

  // =========================
  // PORT 0
  // =========================
  input  logic                  p0_valid_i,
  output logic                  p0_ready_o,
  input  logic [ADDR_W-1:0]     p0_addr_i,
  input  logic [DATA_W-1:0]     p0_wdata_i,
  input  logic [STRB_W-1:0]     p0_wstrb_i,
  input  logic [STATE_W-1:0]    p0_wstate_i,
  input  logic [TAG_W-1:0]      p0_wtag_i,

  output logic [DATA_W-1:0]     p0_rdata_o,
  output logic [TAG_W-1:0]      p0_rtag_o,
  output logic [STATE_W-1:0]    p0_rstate_o,
  output logic                  p0_valid_o,
  input  logic                  p0_ready_i,

  // =========================
  // PORT 1
  // =========================
  input  logic                  p1_valid_i,
  output logic                  p1_ready_o,
  input  logic [ADDR_W-1:0]     p1_addr_i,
  input  logic [DATA_W-1:0]     p1_wdata_i,
  input  logic [STRB_W-1:0]     p1_wstrb_i,
  input  logic [STATE_W-1:0]    p1_wstate_i,
  input  logic [TAG_W-1:0]      p1_wtag_i,

  output logic [DATA_W-1:0]     p1_rdata_o,
  output logic [TAG_W-1:0]      p1_rtag_o,
  output logic [STATE_W-1:0]    p1_rstate_o,
  output logic                  p1_valid_o,
  input  logic                  p1_ready_i
);

  // ============================================================
  // cache_mem signals
  // ============================================================

  logic                  cm_valid_i;
  logic                  cm_ready_o;
  logic [ADDR_W-1:0]     cm_addr_i;
  logic [DATA_W-1:0]     cm_wdata_i;
  logic [STRB_W-1:0]     cm_wstrb_i;
  logic [STATE_W-1:0]    cm_wstate_i;
  logic [TAG_W-1:0]      cm_wtag_i;

  logic [DATA_W-1:0]     cm_rdata_o;
  logic [TAG_W-1:0]      cm_rtag_o;
  logic [STATE_W-1:0]    cm_rstate_o;
  logic                  cm_valid_o;
  logic                  cm_ready_i;

  // ============================================================
  // Arbitration state (IMPORTANT FIX)
  // ============================================================

  logic busy;
  logic active_port;   // 0 = p0, 1 = p1
  logic last_grant;

  logic grant_p0, grant_p1;

  // ============================================================
  // RR arbitration (ONLY when NOT busy)
  // ============================================================

  always_comb begin
    grant_p0 = 0;
    grant_p1 = 0;

    if (!busy) begin
      case ({p1_valid_i, p0_valid_i})
        2'b01: grant_p0 = 1;
        2'b10: grant_p1 = 1;
        2'b11: begin
          if (last_grant == 0)
            grant_p1 = 1;
          else
            grant_p0 = 1;
        end
      endcase
    end
  end

  // ============================================================
  // Transaction control (FIX FOR DEADLOCK)
  // ============================================================

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      busy        <= 0;
      active_port <= 0;
      last_grant  <= 0;
    end else begin

      // start transaction
      if (!busy && cm_valid_i && cm_ready_o) begin
        busy <= 1;

        if (grant_p1) begin
          active_port <= 1;
          last_grant  <= 1;
        end else if (grant_p0) begin
          active_port <= 0;
          last_grant  <= 0;
        end
      end

      // end transaction
      if (busy && cm_valid_o && cm_ready_i) begin
        busy <= 0;
      end
    end
  end

  // ============================================================
  // Request mux (LOCKED when busy)
  // ============================================================

  always_comb begin
    cm_valid_i  = 0;
    cm_addr_i   = 0;
    cm_wdata_i  = 0;
    cm_wstrb_i  = 0;
    cm_wstate_i = 0;
    cm_wtag_i   = 0;

    if (busy) begin
      if (active_port == 0) begin
        cm_valid_i  = p0_valid_i;
        cm_addr_i   = p0_addr_i;
        cm_wdata_i  = p0_wdata_i;
        cm_wstrb_i  = p0_wstrb_i;
        cm_wstate_i = p0_wstate_i;
        cm_wtag_i   = p0_wtag_i;
      end else begin
        cm_valid_i  = p1_valid_i;
        cm_addr_i   = p1_addr_i;
        cm_wdata_i  = p1_wdata_i;
        cm_wstrb_i  = p1_wstrb_i;
        cm_wstate_i = p1_wstate_i;
        cm_wtag_i   = p1_wtag_i;
      end
    end else begin
      if (grant_p0) begin
        cm_valid_i  = p0_valid_i;
        cm_addr_i   = p0_addr_i;
        cm_wdata_i  = p0_wdata_i;
        cm_wstrb_i  = p0_wstrb_i;
        cm_wstate_i = p0_wstate_i;
        cm_wtag_i   = p0_wtag_i;
      end else if (grant_p1) begin
        cm_valid_i  = p1_valid_i;
        cm_addr_i   = p1_addr_i;
        cm_wdata_i  = p1_wdata_i;
        cm_wstrb_i  = p1_wstrb_i;
        cm_wstate_i = p1_wstate_i;
        cm_wtag_i   = p1_wtag_i;
      end
    end
  end

  // ============================================================
  // Ready routing
  // ============================================================

  assign p0_ready_o = (busy && active_port==0) ? cm_ready_o :
                      (!busy && grant_p0)     ? cm_ready_o : 0;

  assign p1_ready_o = (busy && active_port==1) ? cm_ready_o :
                      (!busy && grant_p1)     ? cm_ready_o : 0;

  // ============================================================
  // Response routing
  // ============================================================

  assign p0_rdata_o  = cm_rdata_o;
  assign p0_rtag_o   = cm_rtag_o;
  assign p0_rstate_o = cm_rstate_o;

  assign p1_rdata_o  = cm_rdata_o;
  assign p1_rtag_o   = cm_rtag_o;
  assign p1_rstate_o = cm_rstate_o;

  assign p0_valid_o = (busy && active_port==0) ? cm_valid_o : 0;
  assign p1_valid_o = (busy && active_port==1) ? cm_valid_o : 0;

  assign cm_ready_i =
      (busy && active_port==0) ? p0_ready_i :
      (busy && active_port==1) ? p1_ready_i :
                                 0;

  // ============================================================
  // cache_mem instance
  // ============================================================

  cache_mem u_cache_mem (
    .clk_i    (clk_i),
    .rst_ni   (rst_ni),

    .valid_i  (cm_valid_i),
    .ready_o  (cm_ready_o),

    .addr_i   (cm_addr_i),
    .wdata_i  (cm_wdata_i),
    .wstrb_i  (cm_wstrb_i),
    .wstate_i (cm_wstate_i),
    .wtag_i   (cm_wtag_i),

    .rdata_o  (cm_rdata_o),
    .rtag_o   (cm_rtag_o),
    .rstate_o (cm_rstate_o),

    .valid_o  (cm_valid_o),
    .ready_i  (cm_ready_i)
  );

endmodule
