`timescale 1ns/1ps

module lossy_pipe_stage #(
    parameter int WIDTH = 64
)(
    input  logic              clk_i,
    input  logic              rst_ni,

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

    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            valid_o_r <= 1'b0;
        end else begin
            if (valid_i) begin
                valid_o_r <= 1'b1;
            end else if (ready_i) begin
                valid_o_r <= 1'b0;
            end
        end
    end

    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            data_r <= '0;
        end else if (valid_i) begin
            data_r <= data_i;
        end
    end

endmodule