`timescale 1ns/1ps

module spi_engine (
    input logic clk_i,
    input logic reset_ni,
    input logic start_i,
    input logic [7:0] data_in_i,
    output logic [7:0] data_out_o,
    output logic done_o,
    output logic busy_o,

    //spi pins
    output logic spi_sck_o,
    output logic spi_mosi_o,
    input logic spi_miso_i
    //output logic spi_csb_o
);
    typedef enum logic [1:0] {IDLE, SHIFT_LOW, SHIFT_HIGH} spi_state_t;

    spi_state_t curr_state, next_state;

    logic [7:0] shift_out, shift_in;
    logic [2:0] bit_cnt;
    logic [3:0] sck_div;

    always_ff @(posedge clk_i) begin
        if(!reset_ni) begin
            curr_state <= IDLE;
            bit_cnt <= 3'd0;
            shift_out <= 8'h00;
            shift_in <= 8'h00;
            data_out_o <= 8'h00;
            spi_mosi_o <= 1'b0;
            sck_div <= 4'd0;
        end else begin
            case(curr_state)
                IDLE: begin
                    sck_div <= 4'd0;
                    if(start_i) begin
                        shift_out <= data_in_i;
                        bit_cnt <= 3'd0;
                        spi_mosi_o <= data_in_i[7];
                        curr_state <= SHIFT_LOW;
                    end
                end

                SHIFT_LOW: begin
                    if (sck_div == 4'd7) begin
                        sck_div <= 4'd0;
                        curr_state <= SHIFT_HIGH;
                        // sample miso on the rising edge
                        shift_in <= {shift_in[6:0], spi_miso_i};
                    end else begin
                        sck_div <= sck_div + 1'b1;
                    end
                end

                SHIFT_HIGH: begin
                    if (sck_div == 4'd7) begin
                        sck_div <= 4'd0;
                        if (bit_cnt == 3'd7) begin
                            //data_out_o <= shift_in;
                            curr_state <= IDLE;
                        end else begin
                            bit_cnt <= bit_cnt + 1'b1;
                            // shift out next mosi bit on falling edge
                            spi_mosi_o <= shift_out[6];
                            shift_out <= {shift_out[6:0], 1'b0};
                            curr_state <= SHIFT_LOW;
                        end
                    end else begin
                        sck_div <= sck_div + 1'b1;
                        if (bit_cnt == 3'd7 && sck_div == 4'd6) begin
                            data_out_o <= shift_in;
                        end
                    end
                end
            endcase
        end 
    end

    // combinational out
    assign spi_sck_o = (curr_state == SHIFT_HIGH);
    assign done_o = (curr_state == SHIFT_HIGH && sck_div == 4'd7 && bit_cnt == 3'd7);
    assign busy_o = (curr_state != IDLE);

endmodule