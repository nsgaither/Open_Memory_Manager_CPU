`timescale 1ns/1ps

module lossy_pipe_stage #(
    parameter int WIDTH = 64
)(
    input  logic              clk_i,
    input  logic              rst_ni,

    // DFT scan interface. debug_mode_i is the scan/functional mux select.
    input  logic              debug_mode_i,
    input  logic              scan_in_i,
    output logic              scan_out_o,

    // Upstream Interface (Always Ready)
    input  logic              valid_i,
    input  logic [WIDTH-1:0]  data_i,
    output logic              ready_o,

    // Downstream Interface
    output logic              valid_o,
    output logic [WIDTH-1:0]  data_o,
    input  logic              ready_i
);

    logic             valid_o_r;
    logic [WIDTH-1:0] data_r;

    assign ready_o = 1'b1;

    // Output logic
    assign valid_o = valid_o_r;
    assign data_o  = data_r;
    assign scan_out_o = data_r[WIDTH-1];

    always_ff @(posedge clk_i) begin
        if (!rst_ni) begin
            valid_o_r <= 1'b0;
        end else if (debug_mode_i) begin
            valid_o_r <= scan_in_i;
        end else begin
            if (valid_i) begin
                valid_o_r <= 1'b1;
            end else if (ready_i) begin
                valid_o_r <= 1'b0;
            end
        end
    end

    always_ff @(posedge clk_i) begin
        if (!rst_ni) begin
            data_r <= '0;
        end else if (debug_mode_i) begin
            data_r <= (data_r << 1) | WIDTH'(valid_o_r);
        end else if (valid_i) begin
            data_r <= data_i;
        end
    end

endmodule
