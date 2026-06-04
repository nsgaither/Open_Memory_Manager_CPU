`default_nettype none
`timescale 1ns/1ps

module scan_chain #(
    parameter int WIDTH = 128
)(
    input  wire             clk_i,
    input  wire             rst_ni,
    input  wire             scan_mode_i,
    input  wire             scan_enable_i,
    input  wire             scan_in_i,
    input  wire [WIDTH-1:0] capture_i,
    output wire             scan_out_o,
    output wire [WIDTH-1:0] scan_data_o
);

    logic [WIDTH-1:0] scan_q;

    always_ff @(posedge clk_i) begin : scan_shift_capture
        if (!rst_ni) begin
            scan_q <= '0;
        end else if (scan_mode_i) begin
            if (scan_enable_i) begin
                scan_q <= {scan_q[WIDTH-2:0], scan_in_i};
            end else begin
                scan_q <= capture_i;
            end
        end
    end

    assign scan_out_o  = scan_q[WIDTH-1];
    assign scan_data_o = scan_q;

endmodule

`default_nettype wire
