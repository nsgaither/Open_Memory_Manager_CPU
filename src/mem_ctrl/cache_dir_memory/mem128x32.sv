`default_nettype none

module mem_ctrl_128x32
(
  input  wire         clk_i,
  input  wire         rst_ni,

  input  wire [0:0]   mem_valid_i,
  output wire [0:0]   mem_ready_o,
  input  wire [31:0]  mem_addr_i,
  input  wire [31:0]  mem_wdata_i,
  input  wire [3:0]   mem_wstrb_i,

  output wire [31:0]  mem_rdata_o,
  output wire [0:0]   mem_valid_o,
  input  wire [0:0]   mem_ready_i
);

  typedef enum logic [3:0] {
    RESET_SRAMS = 4'd0,
    RESET_DATA  = 4'd1,
    IDLE        = 4'd2,
    MEM_REQ_0   = 4'd3,
    MEM_REQ_1   = 4'd4,
    MEM_REQ_2   = 4'd5,
    MEM_REQ_3   = 4'd6,
    MEM_REQ_4   = 4'd7,
    MEM_RESP    = 4'd8
  } state_t;

  state_t state_q, state_d;

  logic [8:0]  reset_addr_q, reset_addr_d;
  logic [8:0]  addr_q, addr_d;
  logic [31:0] wdata_q, wdata_d;
  logic [3:0]  mode_q, mode_d;
  logic [31:0] data_read_q, data_read_d;
  logic [7:0]  data_to_write_q, data_to_write_d;

  logic        sram_enable_n;
  logic [8:0]  sram_addr;
  logic [7:0]  data_read_from_sram;
  logic        sram_gwen;

  wire [6:0] mem_word_addr = mem_addr_i[6:0];

  wire [7:0] w0 = mem_wdata_i[7:0];
  wire [7:0] w1 = mem_wdata_i[15:8];
  wire [7:0] w2 = mem_wdata_i[23:16];
  wire [7:0] w3 = mem_wdata_i[31:24];

  wire mode0 = mode_q[0];
  wire mode1 = mode_q[1];
  wire mode2 = mode_q[2];
  wire mode3 = mode_q[3];

  always_ff @(posedge clk_i) begin
    if (!rst_ni) begin
      state_q         <= RESET_SRAMS;
      reset_addr_q    <= '0;
      addr_q          <= '0;
      wdata_q         <= '0;
      mode_q          <= '0;
      data_read_q     <= '0;
      data_to_write_q <= '0;
    end else begin
      state_q         <= state_d;
      reset_addr_q    <= reset_addr_d;
      addr_q          <= addr_d;
      wdata_q         <= wdata_d;
      mode_q          <= mode_d;
      data_read_q     <= data_read_d;
      data_to_write_q <= data_to_write_d;
    end
  end

  logic [23:0] data_read_q_slice;
  assign data_read_q_slice = data_read_q[31:8];

  always_comb begin
    state_d         = state_q;
    reset_addr_d    = reset_addr_q;
    addr_d          = addr_q;
    wdata_d         = wdata_q;
    mode_d          = mode_q;
    data_read_d     = data_read_q;
    data_to_write_d = data_to_write_q;

    case (state_q)

      RESET_SRAMS: begin
        state_d = RESET_DATA;
      end

      RESET_DATA: begin
        reset_addr_d = reset_addr_q + 1;
        if (reset_addr_q == 9'd511)
          state_d = IDLE;
      end

      IDLE: begin
        if (mem_valid_i && mem_ready_o) begin
          state_d         = MEM_REQ_0;
          wdata_d         = mem_wdata_i;
          mode_d          = mem_wstrb_i;
          addr_d          = {mem_word_addr, 2'b00};
          data_to_write_d = w0;
          data_read_d     = 32'd0;
        end
      end

      MEM_REQ_0: begin
        addr_d          = addr_q + 1;
        data_to_write_d = w1;
        state_d         = MEM_REQ_1;
      end

      MEM_REQ_1: begin
        addr_d          = addr_q + 1;
        data_to_write_d = w2;
        data_read_d     = {data_read_from_sram, data_read_q_slice};
        state_d         = MEM_REQ_2;
      end

      MEM_REQ_2: begin
        addr_d          = addr_q + 1;
        data_to_write_d = w3;
        data_read_d     = {data_read_from_sram, data_read_q_slice};
        state_d         = MEM_REQ_3;
      end

      MEM_REQ_3: begin
        data_read_d = {data_read_from_sram, data_read_q_slice};
        state_d     = MEM_REQ_4;
      end

      MEM_REQ_4: begin
        data_read_d = {data_read_from_sram, data_read_q_slice};
        state_d     = MEM_RESP;
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
  assign mem_rdata_o = data_read_q;

  always_comb begin
    sram_enable_n = 1'b1;
    sram_addr     = addr_q;
    sram_gwen     = 1'b1;

    if (state_q == RESET_DATA) begin
      sram_enable_n = 1'b0;
      sram_addr     = reset_addr_q;
      sram_gwen     = 1'b0;
    end
    else begin
      if (state_q == MEM_REQ_0) begin
        sram_enable_n = 1'b0;
        sram_gwen     = ~mode0;
      end
      else if (state_q == MEM_REQ_1) begin
        sram_enable_n = 1'b0;
        sram_gwen     = ~mode1;
      end
      else if (state_q == MEM_REQ_2) begin
        sram_enable_n = 1'b0;
        sram_gwen     = ~mode2;
      end
      else if (state_q == MEM_REQ_3) begin
        sram_enable_n = 1'b0;
        sram_gwen     = ~mode3;
      end
      else if (state_q == MEM_REQ_4) begin
        sram_enable_n = 1'b0;
        sram_gwen     = 1'b1;
      end
    end
  end

  gf180mcu_fd_ip_sram__sram512x8m8wm1 sram0 (
    .CLK(clk_i),
    .CEN(sram_enable_n),
    .GWEN(sram_gwen),
    .WEN(8'b0),
    .A(sram_addr),
    .D(data_to_write_q),
    .Q(data_read_from_sram),
    .VDD(),
    .VSS()
  );

endmodule

`default_nettype wire
