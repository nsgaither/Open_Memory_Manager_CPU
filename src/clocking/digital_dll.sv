`default_nettype none
`timescale 1ns/1ps

// Synthesizable bang-bang digital DLL.
//
// The delay line is intentionally built from preserved non-inverting delay
// cells. RTL simulation has zero-delay cells, so the controller will saturate
// at one boundary and assert locked_o once the tap stops moving. Post-layout
// timing gives these cells their physical delay.
module digital_dll #(
    parameter int NUM_TAPS = 16,
    parameter int LOCK_COUNT_MAX = 16,
    parameter int INITIAL_TAP = NUM_TAPS / 2,
    parameter int TAP_WIDTH = (NUM_TAPS <= 2) ? 1 : $clog2(NUM_TAPS)
)(
    input  wire                  clk_ref_i,
    input  wire                  rst_ni,
    input  wire                  enable_i,
    input  wire                  bypass_i,

    output wire                  clk_o,
    output logic                 locked_o,
    output logic [TAP_WIDTH-1:0] tap_o
);

    localparam int LOCK_WIDTH = (LOCK_COUNT_MAX <= 2) ? 1 : $clog2(LOCK_COUNT_MAX + 1);
    localparam logic [TAP_WIDTH-1:0] TAP_MAX = TAP_WIDTH'(NUM_TAPS - 1);
    localparam logic [TAP_WIDTH-1:0] INITIAL_TAP_VALUE = TAP_WIDTH'(INITIAL_TAP);
    localparam logic [LOCK_WIDTH-1:0] LOCK_COUNT_MAX_VALUE = LOCK_WIDTH'(LOCK_COUNT_MAX);

    wire [NUM_TAPS:0] delay_tap;
    wire              delayed_clk;
    wire [TAP_WIDTH:0] selected_tap;
    logic [LOCK_WIDTH-1:0] lock_count_q;

    assign delay_tap[0] = clk_ref_i;

    generate
        for (genvar i = 0; i < NUM_TAPS; i++) begin : gen_delay
            digital_dll_delay_cell u_delay_cell (
                .in_i  (delay_tap[i]),
                .out_o (delay_tap[i+1])
            );
        end
    endgenerate

    assign selected_tap = {1'b0, tap_o} + {{TAP_WIDTH{1'b0}}, 1'b1};
    assign delayed_clk = delay_tap[selected_tap];

    assign clk_o = (enable_i && !bypass_i) ? delayed_clk : clk_ref_i;

    always_ff @(posedge clk_ref_i or negedge rst_ni) begin : dll_control
        if (!rst_ni) begin
            tap_o        <= INITIAL_TAP_VALUE;
            lock_count_q <= '0;
            locked_o     <= 1'b0;
        end else if (!enable_i) begin
            tap_o        <= INITIAL_TAP_VALUE;
            lock_count_q <= '0;
            locked_o     <= 1'b0;
        end else if (bypass_i) begin
            tap_o        <= INITIAL_TAP_VALUE;
            lock_count_q <= LOCK_COUNT_MAX_VALUE;
            locked_o     <= 1'b1;
        end else begin
            locked_o <= 1'b0;

            if (delayed_clk && (tap_o != TAP_MAX)) begin
                tap_o        <= tap_o + 1'b1;
                lock_count_q <= '0;
            end else if (!delayed_clk && (tap_o != '0)) begin
                tap_o        <= tap_o - 1'b1;
                lock_count_q <= '0;
            end else begin
                if (lock_count_q != LOCK_COUNT_MAX_VALUE) begin
                    lock_count_q <= lock_count_q + 1'b1;
                end
                locked_o <= (lock_count_q >= (LOCK_COUNT_MAX_VALUE - 1'b1));
            end
        end
    end

endmodule

(* keep_hierarchy = "yes", dont_touch = "true" *)
module digital_dll_delay_cell (
    input  wire in_i,
    output wire out_o
);
    (* keep = "true", dont_touch = "true" *) wire inv_n;

    assign inv_n = ~in_i;
    assign out_o = ~inv_n;
endmodule

`default_nettype wire
