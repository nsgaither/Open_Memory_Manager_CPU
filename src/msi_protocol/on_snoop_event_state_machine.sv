`timescale 1ns/1ps
`default_nettype none

module on_snoop_event_state_machine
(
  // input interface
  input  logic [1:0]   current_state_i,
  input  logic [2:0]   snoop_event_i,

  // output interface     
  output logic [1:0] next_state_o,
  output logic [0:0] flush_o
);

  // types
  typedef enum logic [1:0] {
    INVALID  = 2'b00, 
    SHARED   = 2'b01,  
    MODIFIED = 2'b10
  } msi_state;

  typedef enum logic [2:0] {
    BUS_RD   = 3'b1, 
    BUS_RDX  = 3'b10,
    BUS_UPGR = 3'b100  
  } snoop_event;


    // state handling
  msi_state state_q, state_d;
  assign state_q = msi_state'(current_state_i);
  assign next_state_o = state_d;

  // event handling
  snoop_event snoop_event_x;
  assign snoop_event_x = snoop_event'(snoop_event_i);
  // assign proc_event = (wstrb_i == 4'd0) ? READ : WRITE;

  // bus_transactions handling
  logic flush_flag;
  assign flush_o = flush_flag; 

  always_comb begin
    state_d = state_q;
    flush_flag = 1'b0;

    case(state_q)

      INVALID: begin
        state_d = INVALID;
        flush_flag = 1'b0;
      end

      SHARED: begin
        if(snoop_event_x == BUS_RD) begin
          state_d = SHARED;
          flush_flag = 1'b0;
        end
        else begin
          state_d = INVALID;
          flush_flag = 1'b0;
        end

      end
      MODIFIED: begin
        if(snoop_event_x == BUS_RD) begin
          state_d = SHARED;
          flush_flag = 1'b1;
        end
        else if(snoop_event_x == BUS_RDX) begin
          state_d = INVALID;
          flush_flag = 1'b1;
        end
        else begin
          state_d = MODIFIED;
          flush_flag = 1'b0;
        end
      end

      default: begin
        state_d = INVALID;
        flush_flag = 1'b0;
      end
    endcase
  end

endmodule






