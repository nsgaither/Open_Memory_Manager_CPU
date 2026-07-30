`timescale 1ns/1ps

module rserializer #(
    parameter int NUM_PINS = 1,
    parameter int MAX_MSG_LEN = 68
)(

    input  logic                  clk_i,
    input  logic                  rst_ni,

    // DFT scan interface. debug_mode_i is the scan/functional mux select.
    input  logic                  debug_mode_i,
    input  logic                  scan_in_i,
    output logic                  scan_out_o,

    input  logic [NUM_PINS-1 : 0] serial_i,
    // Branch 0 controls the receive state. The four remaining physical
    // branches enable shift words round-robin; a 36-bit, 9-pin receiver has
    // one branch per word, while longer receivers reuse them round-robin.
    input  logic [4:0]            req_i_branches,

    output logic                  valid_o,
    output logic [int'($ceil(real'(MAX_MSG_LEN) / NUM_PINS) * NUM_PINS) - 1:0] data_o,
    input  logic                  ready_i

);

    localparam int shift_width = NUM_PINS;
    localparam int shift_depth = int'($ceil(real'(MAX_MSG_LEN) / NUM_PINS));

    typedef enum logic { 
        IDLE    = 1'b0,
        RECEIVE = 1'b1
    } state;

    state current_state, next_state;
    logic [shift_depth-1:0][shift_width-1:0] shift_arr;
    logic [shift_depth*shift_width-1:0] scan_shift_state;
    wire scan_after_state;
    wire scan_after_shift;

    assign scan_after_state = current_state;
    assign scan_shift_state = shift_arr;
    assign scan_after_shift = shift_arr[shift_depth-1][shift_width-1];
    assign scan_out_o = valid_o;

    always_ff @( posedge clk_i ) begin : state_reg
        if (!rst_ni)
            current_state <= IDLE;
        else if (debug_mode_i)
            current_state <= state'(scan_in_i);
        else
            current_state <= next_state;
    end

    always_comb begin : next_state_comb
        next_state = current_state;
        case (current_state)
            IDLE: if (req_i_branches[0]) next_state = RECEIVE;
            RECEIVE: if (!req_i_branches[0]) next_state = IDLE;
            default: next_state = IDLE;
        endcase
    end

    // shift arr
    always_ff @( posedge clk_i ) begin : shifter
        if (!rst_ni) begin
            for (int i = 0; i < shift_depth; i++) begin : rst_shift
                shift_arr[i] <= '0;
            end
        end else if (debug_mode_i) begin
            shift_arr <= {
                scan_shift_state[shift_depth*shift_width-2:0], scan_after_state
            };
        end else begin
            if (req_i_branches[1])
                shift_arr[0] <= serial_i;
            for (int i = 1; i < shift_depth; i++) begin : shift
                if (req_i_branches[1 + (i % 4)])
                    shift_arr[i] <= shift_arr[i-1];
            end
        end
    end

    // valid_o logic
    always_ff @( posedge clk_i ) begin : valid_reg
        if (!rst_ni) begin
            valid_o <= '0;
        end else if (debug_mode_i) begin
            valid_o <= scan_after_shift;
        end else if ((current_state == RECEIVE) & (next_state == IDLE)) begin
            valid_o <= '1;
        end else if ((current_state == IDLE) & (next_state == RECEIVE)) begin
            valid_o <= '0;
        end else if (ready_i) begin
            valid_o <= '0;
        end
    end

    // flatten shift array for output
    always_comb begin
        for (int i = 0; i < shift_depth; i++) begin
            data_o[i*shift_width +: shift_width] = shift_arr[i];
        end
    end


endmodule
