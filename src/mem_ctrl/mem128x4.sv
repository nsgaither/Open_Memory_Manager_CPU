`default_nettype none

module mem128x4
(
  input  logic        clk_i,
  input  logic        rst_ni,

  // DFT scan interface. debug_mode_i is the scan/functional mux select.
  input  logic        debug_mode_i,
  input  logic        scan_in_i,
  output logic        scan_out_o,

  input  logic        mem_valid_i,
  output logic        mem_ready_o,
  input  logic [31:0] mem_addr_i, /* verilator lint_off UNUSEDSIGNAL */
  input  logic [3:0]  mem_wdata_i, /* verilator lint_on UNUSEDSIGNAL */
  input  logic        mem_read_en_i,

  output logic [3:0]  mem_rdata_o,
  output logic        mem_valid_o,
  input  logic        mem_ready_i

  `ifdef USE_POWER_PINS
	    ,input wire VDD //adding these for librelane
	    ,input wire VSS
  `endif
);

  typedef enum logic [2:0] {
    RESET_SRAMS  = 3'b000,
    RESET_DATA   = 3'b001,
    IDLE         = 3'b010,
    MEM_REQ      = 3'b011,
    MEM_REQ_WAIT = 3'b101,
    MEM_RESP     = 3'b100
  } state_t;

  state_t state_q, state_d;

  logic [5:0] reset_addr_q, reset_addr_d;
  logic [5:0] addr_q, addr_d;
  logic       nibble_sel_q, nibble_sel_d;
  logic [3:0] wdata_q, wdata_d;
  logic [7:0] data_read_q, data_read_d;
  logic [7:0] data_to_write_q, data_to_write_d;
  logic [7:0] data_to_write;

  logic [35:0] scan_state;
  assign scan_state = {
    data_to_write_q, data_read_q, wdata_q, nibble_sel_q,
    addr_q, reset_addr_q, state_q
  };
  assign scan_out_o = scan_state[35];

  logic       sram_enable_n;
  logic [5:0] sram_addr;
  logic [7:0] data_read_from_sram;
  logic [7:0] sram_bit_mask;
  logic       sram_gwen;

  always_ff @(posedge clk_i) begin
    if (!rst_ni) begin
      state_q         <= RESET_SRAMS;
      reset_addr_q    <= '0;
      addr_q          <= '0;
      nibble_sel_q    <= 1'b0;
      wdata_q         <= '0;
      data_read_q     <= '0;
      data_to_write_q <= '0;
    end else if (debug_mode_i) begin
      {
        data_to_write_q, data_read_q, wdata_q, nibble_sel_q,
        addr_q, reset_addr_q, state_q
      } <= {scan_state[34:0], scan_in_i};
    end else begin
      state_q         <= state_d;
      reset_addr_q    <= reset_addr_d;
      addr_q          <= addr_d;
      nibble_sel_q    <= nibble_sel_d;
      wdata_q         <= wdata_d;
      data_read_q     <= data_read_d;
      data_to_write_q <= data_to_write_d;
    end
  end

  // pre sliced wires
  logic [5:0] mem_addr_slice;
  logic       mem_addr_bit0;
  assign mem_addr_slice = mem_addr_i[6:1];
  assign mem_addr_bit0  = mem_addr_i[0];


  always_comb begin
    state_d         = state_q;
    reset_addr_d    = reset_addr_q;
    addr_d          = addr_q;
    nibble_sel_d    = nibble_sel_q;
    wdata_d         = wdata_q;
    data_read_d     = data_read_q;
    data_to_write_d = data_to_write_q;

    sram_enable_n = 1'b1;
    sram_gwen     = 1'b1;
    sram_bit_mask = 8'hFF;

    case (state_q)

      RESET_SRAMS: begin
        state_d = RESET_DATA;
      end

      RESET_DATA: begin
        sram_enable_n = 1'b0;
        sram_gwen     = 1'b0;
        sram_bit_mask = 8'h00;
        if (reset_addr_q == 6'd63)
          state_d = IDLE;
        else
          reset_addr_d = reset_addr_q + 1'b1;
      end

      IDLE: begin
        if (mem_valid_i && mem_ready_o) begin
          addr_d       = mem_addr_slice;
          nibble_sel_d = mem_addr_bit0;
          wdata_d      = mem_wdata_i;
          state_d      = MEM_REQ;

          if (!mem_read_en_i) begin
            sram_enable_n = 1'b0;
            sram_gwen     = 1'b0;
            if (mem_addr_bit0) begin
              sram_bit_mask   = 8'b00001111;
              data_to_write_d = {mem_wdata_i, 4'b0000};
            end else begin
              sram_bit_mask   = 8'b11110000;
              data_to_write_d = {4'b0000, mem_wdata_i};
            end
          end
        end
      end

      MEM_REQ: begin
        sram_enable_n = 1'b0;
        sram_gwen     = 1'b1;     // read only
        state_d       = MEM_REQ_WAIT;
      end

      // FIX: addr_q (used for sram_addr below) only becomes valid on the
      // same edge that enters MEM_REQ, which races the SRAM macro's own
      // (blocking-assignment) address latch on that identical edge and
      // loses -- the macro ends up sampling the *previous* transaction's
      // address. Holding the read request one extra cycle before
      // capturing data_read_from_sram gives that latch a full cycle to
      // settle on the correct address (mirrors mem128x32's REQ_0/REQ_1
      // split, which never hit this because it already defers capture).
      MEM_REQ_WAIT: begin
        sram_enable_n = 1'b0;
        sram_gwen     = 1'b1;     // read only
        data_read_d   = data_read_from_sram;
        state_d       = MEM_RESP;
      end

      MEM_RESP: begin
        if (mem_valid_o && mem_ready_i)
          state_d = IDLE;
      end

      default: state_d = IDLE;

    endcase

    // Scan-shifted controller states must not accidentally write the SRAM
    // macro. The inserted state takes effect after debug mode is released.
    if (debug_mode_i) begin
      sram_enable_n = 1'b1;
      sram_gwen     = 1'b1;
      sram_bit_mask = 8'hFF;
    end
  end

  assign mem_ready_o = (state_q == IDLE);
  assign mem_valid_o = (state_q == MEM_RESP);


  logic [3:0] read_top, read_bot;
  assign read_top = data_read_q[7:4];
  assign read_bot = data_read_q[3:0];
  always_comb begin
    if (nibble_sel_q)
      mem_rdata_o = read_top;
    else
      mem_rdata_o = read_bot;
  end

  always_comb begin
    sram_addr     = addr_q;
    data_to_write = data_to_write_q;

    if (state_q == RESET_DATA) begin
      sram_addr     = reset_addr_q;
      data_to_write = 8'h00;
    end else if (state_q == IDLE && mem_valid_i && mem_ready_o && !mem_read_en_i) begin
      sram_addr = mem_addr_slice;
      if (mem_addr_bit0)
        data_to_write = {mem_wdata_i, 4'b0000};
      else
        data_to_write = {4'b0000, mem_wdata_i};
    end
  end

  gf180mcu_fd_ip_sram__sram64x8m8wm1 sram0 (
    .CLK (clk_i),
    .CEN (sram_enable_n),
    .GWEN(sram_gwen),
    .WEN (sram_bit_mask),
    .A   (sram_addr),
    .D   (data_to_write),
    .Q   (data_read_from_sram)
    `ifdef USE_POWER_PINS
       // verilator lint_off ASSIGNIN
    ,.VDD(VDD)
    ,.VSS(VSS)
       // verilator lint_on ASSIGNIN
    `endif
  );

endmodule

`default_nettype wire
