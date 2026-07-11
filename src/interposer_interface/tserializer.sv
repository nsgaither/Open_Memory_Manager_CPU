`timescale 1ns/1ps

module tserializer #(
    parameter int NUM_PINS = 1,
    parameter int MAX_MSG_LEN = 68,
    parameter int MSG_LEN_0 = 4,
    parameter int MSG_LEN_1 = 12,
    parameter int MSG_LEN_2 = 36,
    parameter int MSG_LEN_3 = 68
)(
    input  logic                   clk_i,    
    input  logic                   rst_ni, 

    // DFT scan interface. debug_mode_i is the scan/functional mux select.
    input  logic                   debug_mode_i,
    input  logic                   scan_in_i,
    output logic                   scan_out_o,

    // data interface
    input  logic                   valid_i, 
    input  logic [int'($ceil(real'(MAX_MSG_LEN) / NUM_PINS) * NUM_PINS) - 1:0] data_in,
    input  logic [1:0]             msg_type,
    output logic                   ready_o,

    // serial interface
    output logic                   req_o,
    output logic [NUM_PINS-1:0]    serial_o 
);  

    // parameters
    localparam int shift_width = NUM_PINS;
    localparam int shift_depth = int'($ceil(real'(MAX_MSG_LEN) / NUM_PINS));

    localparam int depth_cnt_width = int'($clog2(shift_depth+1));
    localparam logic [depth_cnt_width-1:0] type0_depth = depth_cnt_width'(int'($ceil(real'(MSG_LEN_0) / NUM_PINS)));
    localparam logic [depth_cnt_width-1:0] type1_depth = depth_cnt_width'(int'($ceil(real'(MSG_LEN_1) / NUM_PINS)));
    localparam logic [depth_cnt_width-1:0] type2_depth = depth_cnt_width'(int'($ceil(real'(MSG_LEN_2) / NUM_PINS)));
    localparam logic [depth_cnt_width-1:0] type3_depth = depth_cnt_width'(int'($ceil(real'(MSG_LEN_3) / NUM_PINS)));

    logic cnt_done;

    // state machine
    typedef enum logic { 
        IDLE = 1'b0,
        SEND = 1'b1
    } state;

    state current_state, next_state;
    wire scan_after_state;

    assign scan_after_state = current_state;

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
            IDLE: if (valid_i) next_state = SEND;
            SEND: if (cnt_done) next_state = IDLE;
            default: next_state = IDLE;
        endcase
    end

    // message length
    logic [depth_cnt_width-1:0] curr_msg_len;
    wire scan_after_msg_len;
    assign scan_after_msg_len = curr_msg_len[depth_cnt_width-1];

    always_ff @( posedge clk_i ) begin : msg_length_reg
        if (!rst_ni) curr_msg_len <= '0;
        else if (debug_mode_i)
            curr_msg_len <= (curr_msg_len << 1) | depth_cnt_width'(scan_after_state);
        else if (current_state != SEND) begin
            case (msg_type)
                2'b00: curr_msg_len <= type0_depth;
                2'b01: curr_msg_len <= type1_depth;
                2'b10: curr_msg_len <= type2_depth;
                2'b11: curr_msg_len <= type3_depth;
                default: curr_msg_len <= '0;
            endcase
        end else curr_msg_len <= curr_msg_len;
    end

    // message counter
    logic [depth_cnt_width-1:0] count;
    wire scan_after_count;
    assign scan_after_count = count[depth_cnt_width-1];

    always_ff @( posedge clk_i ) begin : msg_cntr
        if (!rst_ni) begin
            count <= '0;
        end else if (debug_mode_i) begin
            count <= (count << 1) | depth_cnt_width'(scan_after_msg_len);
        end else if (current_state != SEND) begin
            count <= '0;
        end else begin
            count <= count + 1;
        end
    end    

    assign cnt_done = (count + 1 == curr_msg_len);

    // shift reg
    logic [shift_depth-1:0][shift_width-1:0] shift_arr;
    logic [shift_depth*shift_width-1:0] scan_shift_state;
    assign scan_shift_state = shift_arr;
    assign scan_out_o = shift_arr[shift_depth-1][shift_width-1];

    always_ff @( posedge clk_i ) begin : shifter
        if (!rst_ni) begin
            for (int i = 0; i < shift_depth; i++) begin : rst_shift
                shift_arr[i] <= '0;
            end
        end else if (debug_mode_i) begin
            shift_arr <= {
                scan_shift_state[shift_depth*shift_width-2:0], scan_after_count
            };
        end else if (current_state == SEND) begin
            for (int i = 1; i < shift_depth; i++) begin : shift
                shift_arr[i] <= shift_arr[i-1];
            end
        end else begin
            for (int i = 0; i < shift_depth; i++) begin : set_shift
                shift_arr[i] <= data_in[i*shift_width +: shift_width];
            end
        end
    end
    
    // output
    assign serial_o = shift_arr[curr_msg_len-1];
    assign req_o = (current_state == SEND);
    assign ready_o = (current_state != SEND);


endmodule
