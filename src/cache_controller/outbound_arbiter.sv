`default_nettype none
`timescale 1ns/1ps

module outbound_arbiter (
    input  logic        clk_i,
    input  logic        rst_ni,

    // DFT scan interface. debug_mode_i is the scan/functional mux select.
    input  logic        debug_mode_i,
    input  logic        scan_in_i,
    output logic        scan_out_o,

    // ---------- Master port 0 ----------
    input  logic        m0_valid_i,
    input  logic [31:0] m0_addr_i,
    input  logic [31:0] m0_data_i,
    input  logic [3:0]  m0_cmd_i,
    output logic        m0_ready_o,

    // ---------- Master port 1 ----------
    input  logic        m1_valid_i,
    input  logic [31:0] m1_addr_i,
    input  logic [31:0] m1_data_i,
    input  logic [3:0]  m1_cmd_i,
    output logic        m1_ready_o,

    // ---------- Cache slave port ----------
    output logic        cache_valid_o,
    output logic [31:0] cache_addr_o,
    output logic [31:0] cache_data_o,
    output logic [3:0]  cache_cmd_o,
    input  logic        cache_ready_i
);

    typedef enum logic [1:0] {
        IDLE    = 2'b00,
        GRANT_0 = 2'b01,
        GRANT_1 = 2'b10
    } arb_state_e;

    arb_state_e state_q, state_d;

    // Round-robin tracker:
    // 0 => prefer master 0 next
    // 1 => prefer master 1 next
    logic rr_q, rr_d;

    // Registered cache request
    logic        cache_valid_q, cache_valid_d;
    logic [31:0] cache_addr_q,  cache_addr_d;
    logic [31:0] cache_data_q,  cache_data_d;
    logic [3:0]  cache_cmd_q,   cache_cmd_d;

    logic [71:0] scan_state;
    assign scan_state = {
        cache_cmd_q, cache_data_q, cache_addr_q,
        cache_valid_q, rr_q, state_q
    };
    assign scan_out_o = scan_state[71];

    // ------------------------------------------------------------
    // Outputs
    // ------------------------------------------------------------

    assign cache_valid_o = cache_valid_q;
    assign cache_addr_o  = cache_addr_q;
    assign cache_data_o  = cache_data_q;
    assign cache_cmd_o   = cache_cmd_q;

    // Ready only when transfer completes
    assign m0_ready_o =
        (state_q == GRANT_0) &&
        cache_valid_q &&
        cache_ready_i;

    assign m1_ready_o =
        (state_q == GRANT_1) &&
        cache_valid_q &&
        cache_ready_i;

    // ------------------------------------------------------------
    // Sequential logic
    // ------------------------------------------------------------

    always_ff @(posedge clk_i) begin
        if (!rst_ni) begin
            state_q       <= IDLE;
            rr_q          <= 1'b0;

            cache_valid_q <= 1'b0;
            cache_addr_q  <= '0;
            cache_data_q  <= '0;
            cache_cmd_q   <= '0;
        end
        else if (debug_mode_i) begin
            {
                cache_cmd_q, cache_data_q, cache_addr_q,
                cache_valid_q, rr_q, state_q
            } <= {scan_state[70:0], scan_in_i};
        end
        else begin
            state_q       <= state_d;
            rr_q          <= rr_d;

            cache_valid_q <= cache_valid_d;
            cache_addr_q  <= cache_addr_d;
            cache_data_q  <= cache_data_d;
            cache_cmd_q   <= cache_cmd_d;
        end
    end

    // ------------------------------------------------------------
    // Combinational next-state logic
    // ------------------------------------------------------------

    always_comb begin

        // Defaults
        state_d       = state_q;
        rr_d          = rr_q;

        cache_valid_d = cache_valid_q;
        cache_addr_d  = cache_addr_q;
        cache_data_d  = cache_data_q;
        cache_cmd_d   = cache_cmd_q;

        case (state_q)

            // ----------------------------------------------------
            // IDLE
            // ----------------------------------------------------

            IDLE: begin

                // Default to no valid in IDLE unless new request accepted
                cache_valid_d = 1'b0;

                // Both masters requesting
                if (m0_valid_i && m1_valid_i) begin

                    // Round-robin selection
                    if (rr_q == 1'b0) begin
                        // Grant master 0
                        state_d       = GRANT_0;

                        cache_valid_d = 1'b1;
                        cache_addr_d  = m0_addr_i;
                        cache_data_d  = m0_data_i;
                        cache_cmd_d   = m0_cmd_i;

                        // Next time prefer master 1
                        rr_d = 1'b1;
                    end
                    else begin
                        // Grant master 1
                        state_d       = GRANT_1;

                        cache_valid_d = 1'b1;
                        cache_addr_d  = m1_addr_i;
                        cache_data_d  = m1_data_i;
                        cache_cmd_d   = m1_cmd_i;

                        // Next time prefer master 0
                        rr_d = 1'b0;
                    end
                end

                // Only master 0 requesting
                else if (m0_valid_i) begin
                    state_d       = GRANT_0;

                    cache_valid_d = 1'b1;
                    cache_addr_d  = m0_addr_i;
                    cache_data_d  = m0_data_i;
                    cache_cmd_d   = m0_cmd_i;

                    // Next contention prefers master 1
                    rr_d = 1'b1;
                end

                // Only master 1 requesting
                else if (m1_valid_i) begin
                    state_d       = GRANT_1;

                    cache_valid_d = 1'b1;
                    cache_addr_d  = m1_addr_i;
                    cache_data_d  = m1_data_i;
                    cache_cmd_d   = m1_cmd_i;

                    // Next contention prefers master 0
                    rr_d = 1'b0;
                end
            end

            // ----------------------------------------------------
            // GRANT_0
            // ----------------------------------------------------

            GRANT_0: begin

                // Hold request stable until handshake completes
                if (cache_valid_q && cache_ready_i) begin
                    state_d       = IDLE;
                    cache_valid_d = 1'b0;
                end
            end

            // ----------------------------------------------------
            // GRANT_1
            // ----------------------------------------------------

            GRANT_1: begin

                // Hold request stable until handshake completes
                if (cache_valid_q && cache_ready_i) begin
                    state_d       = IDLE;
                    cache_valid_d = 1'b0;
                end
            end

            // ----------------------------------------------------
            // Default recovery
            // ----------------------------------------------------

            default: begin
                state_d       = IDLE;
                cache_valid_d = 1'b0;
            end
        endcase
    end

endmodule

`default_nettype wire
