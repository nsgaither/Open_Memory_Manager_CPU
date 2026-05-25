`timescale 1ns/1ps

module boot_fsm #(
    parameter BOOT_SIZE = 32,
    parameter SRAM_BASE_ADDR = 32'h0000_0000
)(
    input logic clk_i,
    input logic reset_ni,
    output logic spi_start_o,
    output logic [7:0] spi_out_o,
    input logic [7:0] spi_in_i,
    input logic spi_done_i,
    input logic spi_busy_i,
    output logic flash_csb_o,
    output logic cores_en_o,
    output logic boot_done_o,

    output logic sram_wr_en_o,
    output logic [31:0] sram_addr_o,
    output logic [31:0] sram_data_o

);

    typedef enum logic [3:0] {
        IDLE,
        SEND_CMD,
        WAIT_CMD,
        SEND_ADDR,
        WAIT_ADDR,
        READ_BYTE,
        WAIT_BYTE,
        WRITE_SRAM,
        DONE
    } boot_state_t;

    boot_state_t curr_state, next_state;
    logic [31:0] word_buffer;  //collects 4 bytes
    logic [1:0]  byte_in_word;  // which byte in word (0-3)
    logic [31:0] byte_cntr;   // total bytes read
    logic [31:0] sram_addr;  // curr sram addr
    logic [1:0]  addr_byte_cnt;   // count 3 address bytes

    //state register
    always_ff @(posedge clk_i) begin
        if (!reset_ni) begin
            curr_state <= IDLE;
        end else begin
            curr_state <= next_state;
        end
    end

    // data path
    always_ff @(posedge clk_i) begin
        if(!reset_ni) begin
            word_buffer <= 32'h0;
            byte_in_word <= 2'd0;
            byte_cntr <= 32'h0;
            sram_addr <= SRAM_BASE_ADDR;
            addr_byte_cnt <= 2'd0;
        end else begin
            // idle to reset counters before a new boot starts
            if (curr_state == IDLE) begin
                byte_in_word <= 2'd0;
                addr_byte_cnt <= 2'd0;
                byte_cntr <= 32'h0;
            end

            if (curr_state == WAIT_ADDR && spi_done_i) begin
                addr_byte_cnt <= addr_byte_cnt + 1'b1;
            end
            
            // byte assembly
            if (curr_state == WAIT_BYTE && spi_done_i) begin
                case(byte_in_word)
                    2'd0: word_buffer[7:0] <= spi_in_i;
                    2'd1: word_buffer[15:8] <= spi_in_i;
                    2'd2: word_buffer[23:16] <= spi_in_i;
                    2'd3: word_buffer[31:24] <= spi_in_i;
                endcase
                byte_in_word <= byte_in_word + 1'b1;
                byte_cntr <= byte_cntr + 1'b1;
            end

            if (curr_state == WRITE_SRAM) begin
                byte_in_word <= 2'd0;
                sram_addr <= sram_addr + 4;
            end

        end
    end

    //fsm
    always_comb begin
        next_state = curr_state;
        spi_start_o = 1'b0;
        spi_out_o = 8'h00;
        flash_csb_o = 1'b1;
        sram_wr_en_o = 1'b0;
        sram_addr_o = sram_addr;
        sram_data_o = word_buffer;
        cores_en_o = 1'b0;
        boot_done_o = 1'b0;
        
        case(curr_state)
            IDLE: begin
                next_state = SEND_CMD;
            end

            SEND_CMD: begin
                flash_csb_o = 1'b0;
                spi_start_o = 1'b1;
                spi_out_o = 8'h03;  // read command
                next_state = WAIT_CMD;
            end


            WAIT_CMD: begin
                flash_csb_o = 1'b0;
                if (spi_done_i) begin
                    next_state = SEND_ADDR;
                end
            end

            SEND_ADDR: begin
                flash_csb_o = 1'b0;
                spi_start_o = 1'b1;
                spi_out_o = 8'h00;  // addr bytes are all 0x00
                next_state = WAIT_ADDR;
            end

            WAIT_ADDR: begin
                flash_csb_o = 1'b0;
                if (spi_done_i) begin
                    if (addr_byte_cnt == 2'd2)
                        // send all 3 addr bytes
                        next_state = READ_BYTE;
                    else
                        // send next addr byte
                        next_state = SEND_ADDR;
                end
            end

            READ_BYTE: begin
                flash_csb_o = 1'b0;
                spi_start_o = 1'b1;
                spi_out_o = 8'h00;
                next_state = WAIT_BYTE;
            end

            WAIT_BYTE: begin
                flash_csb_o = 1'b0;
                if (spi_done_i) begin
                    // if this was the 4th byte (index 3), move to write
                    if (byte_in_word == 2'd3) begin
                        next_state = WRITE_SRAM;
                    end else begin
                        next_state = READ_BYTE;
                    end
                end else begin
                    // need more bytes
                    next_state = WAIT_BYTE;
                end
            end

            WRITE_SRAM: begin
                flash_csb_o = 1'b0;
                sram_wr_en_o = 1'b1;
                sram_addr_o = sram_addr;
                sram_data_o = word_buffer;

                if (byte_cntr >= BOOT_SIZE) begin
                    next_state = DONE;
                end else begin
                    next_state = READ_BYTE;
                end
            end

            DONE: begin
                flash_csb_o = 1'b1;  // deselect flash
                cores_en_o = 1'b1;
                boot_done_o = 1'b1;
                next_state = DONE;   // stay here
            end
            
            default: next_state = IDLE;
        endcase
    end
endmodule