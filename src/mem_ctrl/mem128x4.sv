// SPDX-FileCopyrightText: © 2025 Albert Felix
// SPDX-License-Identifier: Apache-2.0

// this is sram used to store state bits
// we use a 64 address 8 bit sram to store 128 4-bit values

`default_nettype none

module mem_ctrl_128x4
(
  input  wire        clk_i,
  input  wire        rst_ni,

  // input interface
  input  wire        mem_valid_i,
  output wire        mem_ready_o,
  input  wire [31:0] mem_addr_i,
  input  wire [3:0]  mem_wdata_i,

  // output interface
  output wire [3:0]  mem_rdata_o,
  output wire        mem_valid_o,
  input  wire        mem_ready_i
);

  typedef enum logic [2:0] {
    RESET_SRAMS = 3'b000,
    RESET_DATA  = 3'b001,
    IDLE        = 3'b010,
    MEM_REQ     = 3'b011,
    MEM_RESP    = 3'b100
  } state_t;

  state_t state_q, state_d;

  logic [5:0] reset_addr_q, reset_addr_d;
  logic [5:0] addr_q, addr_d;

  logic       nibble_sel_q, nibble_sel_d;

  logic [3:0] wdata_q, wdata_d;

  logic [7:0] data_read_q, data_read_d;
  logic [7:0] data_to_write_q, data_to_write_d;
  logic [7:0] data_to_write;

  // SRAM interface vars
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
    end
    else begin
      state_q         <= state_d;
      reset_addr_q    <= reset_addr_d;
      addr_q          <= addr_d;
      nibble_sel_q    <= nibble_sel_d;
      wdata_q         <= wdata_d;
      data_read_q     <= data_read_d;
      data_to_write_q <= data_to_write_d;
    end
  end

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

        if (reset_addr_q == 6'd63) begin
          state_d = IDLE;
        end
        else begin
          reset_addr_d = reset_addr_q + 1'b1;
        end
      end

      IDLE: begin
        if (mem_valid_i && mem_ready_o) begin

          addr_d       = mem_addr_i[6:1];
          nibble_sel_d = mem_addr_i[0];
          wdata_d      = mem_wdata_i;

          // issue SRAM access
          sram_enable_n = 1'b0;

          // write upper nibble
          if (mem_addr_i[0]) begin
            sram_gwen     = 1'b0;
            sram_bit_mask = 8'b00001111;
            data_to_write_d = {mem_wdata_i, 4'b0000};
          end

          // write lower nibble
          else begin
            sram_gwen     = 1'b0;
            sram_bit_mask = 8'b11110000;
            data_to_write_d = {4'b0000, mem_wdata_i};
          end

          state_d = MEM_REQ;
        end
      end

      MEM_REQ: begin
        sram_enable_n = 1'b0;
        data_read_d   = data_read_from_sram;
        state_d       = MEM_RESP;
      end

      MEM_RESP: begin
        if (mem_valid_o && mem_ready_i)
          state_d = IDLE;
      end

      default: begin
        state_d = IDLE;
      end

    endcase
  end

  // ready/valid logic
  assign mem_ready_o = (state_q == IDLE);
  assign mem_valid_o = (state_q == MEM_RESP);

  // mux out correct nibble
  logic [3:0] rdata;

  always_comb begin
    if (nibble_sel_q)
      rdata = data_read_q[7:4];
    else
      rdata = data_read_q[3:0];
  end

  assign mem_rdata_o = rdata;

  // mux reset/data path into SRAM
  always_comb begin
    sram_addr    = addr_q;
    data_to_write = data_to_write_q;

    if (state_q == RESET_DATA) begin
      sram_addr     = reset_addr_q;
      data_to_write = 8'h00;
    end
  end

  gf180mcu_fd_ip_sram__sram64x8m8wm1 sram0 (
    .CLK (clk_i),
    .CEN (sram_enable_n),
    .GWEN(sram_gwen),
    .WEN (sram_bit_mask),
    .A   (sram_addr),
    .D   (data_to_write),
    .Q   (data_read_from_sram),
    .VDD (),
    .VSS ()
  );

endmodule

`default_nettype wire
