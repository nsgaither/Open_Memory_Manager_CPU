// SPDX-FileCopyrightText: © 2025 Albert Felix
// SPDX-License-Identifier: Apache-2.0

// This is not ideall design
// due to space constraits we cant use multiple srams and thus
// need to rely on multi cycle r/w

`default_nettype none

module mem_ctrl_128x32
(
  input wire         clk_i,
  input wire         rst_ni,    

  // input interface
  input  wire [0:0]   mem_valid_i,
  input  wire [0:0]   mem_instr_i,
  input  wire [31:0]  mem_addr_i,
  input  wire [31:0]  mem_wdata_i,
  input  wire [3:0]   mem_wstrb_i,   

  // output interface     
  output wire [31:0] mem_rdata_o,
  output wire [0:0]  mem_ready_o

  `ifdef USE_POWER_PINS
	    ,input wire VDD //adding these for librelane
	    ,input wire VSS
  `endif
  
);

  typedef enum logic [3:0] {
    RESET_SRAMS = 4'b0000, 
    RESET_DATA  = 4'b0001,
    IDLE        = 4'b0010,
    MEM_REQ_0   = 4'b0011,
    MEM_REQ_0_READ = 4'b0100,
    MEM_REQ_1   = 4'b0101,
    MEM_REQ_1_READ = 4'b0110,
    MEM_REQ_2   = 4'b0111,
    MEM_REQ_2_READ = 4'b1000,
    MEM_REQ_3   = 4'b1001,
    MEM_REQ_3_READ = 4'b1010,
    MEM_REQ_4   = 4'b1011
  } state_t;

  state_t state_q, state_d;
  logic [8:0]  reset_addr_q, reset_addr_d;
  logic [8:0]  addr_q, addr_d;
  logic [31:0] wdata_q, wdata_d;
  logic [3:0]  mode_q, mode_d;
  logic [31:0] data_read_q, data_read_d;
  logic [7:0]  data_to_write_q, data_to_write_d;
  logic [7:0]  data_to_write;

  // SRAM interface vars
  logic [0:0]  sram_enable_n;
  logic [8:0]  sram_addr;
  logic [7:0]  data_read_from_sram;
  logic sram_gwen;
  logic [7:0] sram_wen; // per-byte write enable (active low)

  always_ff @(posedge clk_i) begin
   	if (!rst_ni) begin
   	  state_q <= RESET_SRAMS;
   	  reset_addr_q <= '0;
   	  addr_q <= '0;
   	  wdata_q <= '0;
   	  mode_q <= '0;
		  data_read_q <= '0;
			data_to_write_q <= '0;
   	end else begin
   	  state_q <= state_d;
   	  reset_addr_q <= reset_addr_d;
   	  addr_q <= addr_d;
   	  wdata_q <= wdata_d;
   	  mode_q <= mode_d;
		  data_read_q <= data_read_d;
   		data_to_write_q <= data_to_write_d;
   	end
  end

  always_comb begin
	  state_d = state_q;
	  reset_addr_d = reset_addr_q;
	  addr_d = addr_q;
	  wdata_d = wdata_q;
	  mode_d = mode_q;
		data_read_d = data_read_q;  
		data_to_write_d = data_to_write_q;

	  case (state_q)
	    RESET_SRAMS: begin
        state_d = RESET_DATA;
	    end
	    
      RESET_DATA: begin
        if (reset_addr_q == 9'd511) state_d = IDLE;
        reset_addr_d = reset_addr_q + 1;
      end
         
      IDLE: begin
        if (mem_valid_i) begin
          state_d = MEM_REQ_0;
          wdata_d = mem_wdata_i;
          mode_d = mem_wstrb_i;
          addr_d = {mem_addr_i[6:0], 2'b00};  // word addr × 4
          data_to_write_d = mem_wdata_i[7:0];
          data_read_d     = 32'd0;
        end
      end
      
      // Read byte 0 (addr+0)
      MEM_REQ_0: begin
        state_d = MEM_REQ_0_READ;
      end
      
      MEM_REQ_0_READ: begin
        // Data from SRAM available now (1 cycle latency)
        data_read_d = {data_read_from_sram, data_read_q[31:8]};
        addr_d = addr_q + 1;
        data_to_write_d = wdata_q[15:8];
        state_d = MEM_REQ_1;
      end
      
      // Read byte 1 (addr+1)
      MEM_REQ_1: begin
        state_d = MEM_REQ_1_READ;
      end
      
      MEM_REQ_1_READ: begin
        data_read_d = {data_read_from_sram, data_read_q[31:8]};
        addr_d = addr_q + 1;
        data_to_write_d = wdata_q[23:16];
        state_d = MEM_REQ_2;
      end
      
      // Read byte 2 (addr+2)
      MEM_REQ_2: begin
        state_d = MEM_REQ_2_READ;
      end
      
      MEM_REQ_2_READ: begin
        data_read_d = {data_read_from_sram, data_read_q[31:8]};
        addr_d = addr_q + 1;
        data_to_write_d = wdata_q[31:24];
        state_d = MEM_REQ_3;
      end
      
      // Read byte 3 (addr+3)
      MEM_REQ_3: begin
        state_d = MEM_REQ_3_READ;
      end
      
      MEM_REQ_3_READ: begin
        data_read_d = {data_read_from_sram, data_read_q[31:8]};
        state_d = MEM_REQ_4;
      end
      
      // Done - signal ready and go back to IDLE
      MEM_REQ_4: begin
        state_d = IDLE;
      end
      
      default: state_d = IDLE;
	  endcase
  end

  // ready valid logic - PicoRV32 expects mem_ready when transaction completes
  // MEM_REQ_4 is the last state, data is valid after this
  assign mem_ready_o = (state_q == MEM_REQ_4);

  // data outputs
  assign mem_rdata_o = data_read_q;

  always_comb begin
      sram_enable_n = 1'b1;
      sram_addr     = addr_q;
      data_to_write = data_to_write_q;
      sram_gwen     = 1'b1;

      if (state_q == RESET_DATA) begin
          sram_enable_n = 1'b0;
          sram_addr     = reset_addr_q;
          data_to_write = 8'd0;
          sram_gwen     = 1'b0;
      end
      else begin
          case (state_q)
              MEM_REQ_0, MEM_REQ_1, MEM_REQ_2, MEM_REQ_3: begin
                  sram_enable_n = 1'b0;
                  sram_gwen = 1'b0; // Will be overridden by mode
              end
              MEM_REQ_0_READ, MEM_REQ_1_READ, MEM_REQ_2_READ, MEM_REQ_3_READ: begin
                  sram_enable_n = 1'b0;
                  sram_gwen = 1'b1; // Read mode
              end
              MEM_REQ_4: begin
                  sram_enable_n = 1'b0;
                  sram_gwen = 1'b1;
              end
              default: ;
          endcase
      end
  end

  // WEN: active-low per-byte write enable (SRAM is 8-bit wide, so only WEN[0] matters)
  // sram_gwen=0 (write mode) -> WEN=8'hFE (byte 0 write enabled)
  // sram_gwen=1 (read mode)  -> WEN=8'hFF (all write disabled)
  assign sram_wen = sram_gwen ? 8'hFF : (mode_q & 8'h0F);

  (* keep *) gf180mcu_fd_ip_sram__sram512x8m8wm1 sram_0 (
      .CLK(clk_i),
      .CEN(sram_enable_n), 
      .GWEN(sram_gwen),
      .WEN(sram_wen),
      .A(sram_addr),
      .D(data_to_write[7:0]),
      .Q(data_read_from_sram)
      `ifdef USE_POWER_PINS
      ,.VDD(VDD)
      ,.VSS(VSS)
      `endif
  );
  
endmodule

`default_nettype wire
