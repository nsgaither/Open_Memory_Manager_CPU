`default_nettype none
`timescale 1ns/1ps

module outbound_arbiter (
    input  logic        clk_i,
    input  logic        rst_ni,

    // ---------- Master port 0 ----------
    input  logic        m0_valid_i,
    input  logic [31:0] m0_addr_i,
    input  logic [31:0] m0_data_i,
    input  logic [8:0]  m0_cmd_i,
    output logic        m0_ready_o,   // grant feedback to master 0

    // ---------- Master port 1 ----------
    input  logic        m1_valid_i,
    input  logic [31:0] m1_addr_i,
    input  logic [31:0] m1_data_i,
    input  logic [8:0]  m1_cmd_i,
    output logic        m1_ready_o,   // grant feedback to master 1

    // ---------- Cache slave port ----------
    output logic        cache_valid_o,
    output logic [31:0] cache_addr_o,
    output logic [31:0] cache_data_o,
    output logic [8:0]  cache_cmd_o,
    input  logic        cache_ready_i
);

    // -------------------------------------------------------------------------
    // Internal state
    // -------------------------------------------------------------------------

    // FSM
    typedef enum logic [1:0] {
        IDLE    = 2'b00,  // no active grant, waiting for a request
        GRANT_0 = 2'b01,  // master 0 owns the bus
        GRANT_1 = 2'b10   // master 1 owns the bus
    } arb_state_e;

    arb_state_e state_q, state_d;

    // Round-robin priority bit: 0 → prefer m0 when both request,
    //                            1 → prefer m1 when both request
    logic        rr_priority_q, rr_priority_d;

    // Transaction accepted by cache this cycle
    logic        txn_done;

    // -------------------------------------------------------------------------
    // Combinational next-state & output logic
    // -------------------------------------------------------------------------

    assign txn_done = cache_valid_o & cache_ready_i;

    always_comb begin
        // Defaults – hold state, no change to priority
        state_d      = state_q;
        rr_priority_d = rr_priority_q;

        // Cache outputs default to master 0 passthrough (overridden below)
        cache_valid_o = 1'b0;
        cache_addr_o  = 32'h0;
        cache_data_o  = 32'h0;
        cache_cmd_o   = 9'h0;

        m0_ready_o = 1'b0;
        m1_ready_o = 1'b0;

        case (state_q)

            // -----------------------------------------------------------------
            IDLE: begin
                // Arbitrate: grant to the requester that matches round-robin
                // priority, or to whichever single port is requesting.
                if (m0_valid_i && m1_valid_i) begin
                    // Both requesting – honour round-robin priority
                    if (rr_priority_q == 1'b0)
                        state_d = GRANT_0;
                    else
                        state_d = GRANT_1;
                end else if (m0_valid_i) begin
                    state_d = GRANT_0;
                end else if (m1_valid_i) begin
                    state_d = GRANT_1;
                end
                // else: stay IDLE
            end

            // -----------------------------------------------------------------
            GRANT_0: begin
                // Drive cache with master 0 signals
                cache_valid_o = m0_valid_i;
                cache_addr_o  = m0_addr_i;
                cache_data_o  = m0_data_i;
                cache_cmd_o   = m0_cmd_i;

                // Reflect cache back-pressure to master 0
                m0_ready_o = cache_ready_i;

                if (txn_done) begin
                    // Transaction complete – rotate priority and re-arbitrate
                    rr_priority_d = 1'b1;        // next turn favours m1
                    if (m1_valid_i)
                        state_d = GRANT_1;        // m1 is waiting, switch now
                    else if (m0_valid_i)
                        state_d = GRANT_0;        // m0 has more work, keep it
                    else
                        state_d = IDLE;
                end
            end

            // -----------------------------------------------------------------
            GRANT_1: begin
                // Drive cache with master 1 signals
                cache_valid_o = m1_valid_i;
                cache_addr_o  = m1_addr_i;
                cache_data_o  = m1_data_i;
                cache_cmd_o   = m1_cmd_i;

                // Reflect cache back-pressure to master 1
                m1_ready_o = cache_ready_i;

                if (txn_done) begin
                    rr_priority_d = 1'b0;        // next turn favours m0
                    if (m0_valid_i)
                        state_d = GRANT_0;
                    else if (m1_valid_i)
                        state_d = GRANT_1;
                    else
                        state_d = IDLE;
                end
            end

            // -----------------------------------------------------------------
            default: state_d = IDLE;

        endcase
    end

    // -------------------------------------------------------------------------
    // Sequential state registers
    // -------------------------------------------------------------------------

    always_ff @(posedge clk_i) begin
        if (!rst_ni) begin
            state_q       <= IDLE;
            rr_priority_q <= 1'b0;   // m0 has priority after reset
        end else begin
            state_q       <= state_d;
            rr_priority_q <= rr_priority_d;
        end
    end

endmodule
