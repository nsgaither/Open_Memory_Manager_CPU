`timescale 1ns/1ps

module sp_addr_handler (
    input         clk_i,
    input         rst_ni,

    //interface from cpu (native picorv32)
    input         mem_valid,
    output        mem_ready,

    input  [31:0] mem_addr,
    input  [31:0] mem_wdata,
    input  [ 3:0] mem_wstrb,
    output [31:0] mem_rdata,

    //downstream passthrough interface
    output        pass_mem_valid,
    input         pass_mem_ready,

    output [31:0] pass_mem_addr,
    output [31:0] pass_mem_wdata,
    output [ 3:0] pass_mem_wstrb,
    input  [31:0] pass_mem_rdata,

    // flush special instruction
    input         flush_ready_i,
    output [31:0] flush_addr_o,
    output        flush_valid_o,

    //gpio pin connections
    output [ 7:0] gpio_pins_o,
    input  [ 7:0] gpio_pins_i,
    output [ 7:0] gpio_dir_o,

    //cpu_id
    input  [ 7:0] cpu_id_i
);

    //addr decoding
    //check if addr starts with 0x8000
    logic is_mmio;
    logic is_flush;
    logic is_whoami;
    logic is_special_addr;
    always_comb begin
        is_mmio = ((mem_addr & 32'hFFFF_FFF0) == 32'h8000_0010);
        is_flush = (mem_addr == 32'h8000_0020);
        is_whoami = (mem_addr == 32'h8000_0000);
        is_special_addr = is_mmio | is_flush | is_whoami;
    end

    //rdata logic
    logic [31:0] mmio_rd_data;
    logic [31:0] mem_rdata_l;
    assign mem_rdata = mem_rdata_l;
    always_comb begin
        if (is_whoami) begin
            mem_rdata_l = {24'b0, cpu_id_i}; // return chips unique ID
        end else if (is_flush) begin
            mem_rdata_l = '0;
        end else if (is_mmio) begin
            mem_rdata_l = mmio_rd_data; //return data from the mmio regs
        end else begin
            mem_rdata_l = pass_mem_rdata;
        end
    end

    logic mmio_wr_en;
    assign mmio_wr_en = |mem_wstrb & is_mmio & mem_valid;

    mmio mmio_inst (
        .clk_i(clk_i),
        .rst_ni(rst_ni),
        .addr_i(mem_addr),
        .wr_data_i(mem_wdata),
        .wr_en_i(mmio_wr_en), //only write if its a special addr
        .rd_data_o(mmio_rd_data),
        .gpio_pins_o(gpio_pins_o),
        .gpio_pins_i(gpio_pins_i),
        .gpio_dir_o(gpio_dir_o)
    );

    // flush logic
    logic [31:0] flush_addr_r;
    logic        flush_valid_r;
    always_ff @( posedge clk_i or negedge rst_ni ) begin : flush_reg
        if (!rst_ni) begin
            flush_addr_r <= '0;
            flush_valid_r <= '0;
        end else if (is_flush & mem_valid) begin
            flush_addr_r <= mem_addr;
            flush_valid_r <= '1;
        end else if (flush_ready_i) begin
                flush_valid_r <= '0;
        end else begin
            flush_valid_r <= flush_valid_r;
            flush_addr_r <= flush_addr_r;
        end
    end
    assign flush_valid_o = flush_valid_r;
    assign flush_addr_o = flush_addr_r;

    // passthrough but only validate if not sp addr
    assign pass_mem_addr = mem_addr;
    assign pass_mem_wdata = mem_wdata;
    assign pass_mem_wstrb = mem_wstrb;
    assign pass_mem_valid = ~is_special_addr & mem_valid;
    
    logic mem_ready_l;
    assign mem_ready = mem_ready_l;
    always_comb begin : mem_ready_comb
        if (~is_special_addr) begin
            mem_ready_l = pass_mem_ready;
        end else if (is_mmio) begin
            mem_ready_l = '1; //mmio is always ready
        end else if (is_flush) begin
            mem_ready_l = flush_ready_i;
        end else if (is_whoami) begin
            mem_ready_l = '1; //whoami is always ready
        end else begin
            mem_ready_l = '0;
        end
    end

endmodule
