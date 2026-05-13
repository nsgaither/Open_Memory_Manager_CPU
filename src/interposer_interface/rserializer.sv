`timescale 1ns/1ps

module rserializer #(
    parameter int NUM_PINS = 1,
    parameter int MAX_MSG_LEN = 68
)(

    input  logic                  clk_i,
    input  logic                  rst_ni,

    input  logic [NUM_PINS-1 : 0] serial_i,
    input  logic                  req_i,

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

    always_ff @( posedge clk_i or negedge rst_ni ) begin : state_reg
        if (!rst_ni)
            current_state <= IDLE;
        else
            current_state <= next_state;
    end

    always_comb begin : next_state_comb
        next_state = current_state;
        case (current_state)
            IDLE: if (req_i) next_state = RECEIVE;
            RECEIVE: if (!req_i) next_state = IDLE;
            default: next_state = IDLE;
        endcase
    end

    // shift arr
    logic [shift_depth-1:0][shift_width-1:0] shift_arr;
    always_ff @( posedge clk_i or negedge rst_ni ) begin : shifter
        if (!rst_ni) begin
            for (int i = 0; i < shift_depth; i++) begin : rst_shift
                shift_arr[i] <= '0;
            end
        end else if (req_i) begin
            shift_arr[0] <= serial_i;
            for (int i = 1; i < shift_depth; i++) begin : shift
                shift_arr[i] <= shift_arr[i-1];
            end
        end else begin
            shift_arr <= shift_arr;
        end
    end

    // valid_o logic
    always_ff @( posedge clk_i or negedge rst_ni ) begin : valid_reg
        if (!rst_ni) begin
            valid_o <= '0;
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
