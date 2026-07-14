`timescale 1ns/1ps

module mmio (
    input logic clk_i,
    input logic rst_ni,

    // DFT scan interface. debug_mode_i is the scan/functional mux select.
    input  logic debug_mode_i,
    input  logic scan_in_i,
    output logic scan_out_o,

    // interface from the addr decoder
    input logic [31:0] addr_i,
    input logic [31:0] wr_data_i, /* verilator lint_off UNUSEDSIGNAL */
    input logic [ 3:0] wstrb_i,   // picorv32 byte-lane strobes (byte select for writes)
    input logic wr_en_i, // write enable
    output logic [31:0] rd_data_o,     // read data back to cpu
    /* verilator lint_on UNUSEDSIGNAL */

    // physical connections to the serializer/pins
    output logic [7:0] gpio_pins_o, // data going out
    input logic [7:0] gpio_pins_i, // data coming in
    output logic [7:0] gpio_dir_o   // 1 = output, 0 = input
);

    // registers
    logic [7:0] data_reg; // holds pin vals
    logic [7:0] csr_reg;  // holds direction (out/in)

    logic [15:0] scan_state;
    assign scan_state = {csr_reg, data_reg};
    assign scan_out_o = scan_state[15];

    // addr constants
    //localparam ADDR_DATA = 32'h8000_0010;
    //localparam ADDR_CSR = 32'h8000_0018;

    // GPIO data pins are byte-addressed across 0x8000_0010..0x8000_0017 (pins
    // 0..7). picorv32's native bus is *word aligned*: a byte access to pin N
    // arrives with addr_i word-aligned (0x..10 for pins 0..3, 0x..14 for pins
    // 4..7) and the byte offset carried in wstrb_i on writes, or recovered by
    // the CPU's own byte extraction on reads. So the pin index is
    // {word-half, byte-lane} -- addr_i[2] picks the low/high nibble of pins and
    // the byte lane picks the pin within it; it is NEVER addr_i[2:0] (those low
    // bits are always zero on the native bus).
    logic is_gpio_data;
    logic is_csr;
    assign is_gpio_data = ((addr_i & 32'hFFFF_FFF8) == 32'h8000_0010);
    assign is_csr       = (addr_i == 32'h8000_0018);

    // pin index for byte lane `lane` (0..3) of the addressed GPIO word
    function automatic logic [2:0] pin_index(input logic [1:0] lane);
        pin_index = {addr_i[2], lane};
    endfunction

    // write
    integer wl;
    always_ff @(posedge clk_i) begin
        if(!rst_ni) begin
            data_reg <= 8'h00;
            csr_reg <= 8'h00; // default all to inputs
        end else if (debug_mode_i) begin
            {csr_reg, data_reg} <= {scan_state[14:0], scan_in_i};
        end else if(wr_en_i) begin
            //case where we write to csr (all 8 bits at once)
            if(is_csr) begin
                csr_reg <= wr_data_i[7:0];
            //case where we write to a specific data pin (one per written byte lane)
            end else if(is_gpio_data) begin
                for (wl = 0; wl < 4; wl = wl + 1) begin
                    // only drive the lanes the CPU actually wrote, and only if
                    // csr says that pin is an output
                    if(wstrb_i[wl] && csr_reg[pin_index(wl[1:0])]) begin
                        data_reg[pin_index(wl[1:0])] <= wr_data_i[8*wl]; //pin value = byte LSB
                    end
                end
            end
        end
    end

    // Two-flop synchronizer for the asynchronous GPIO input pins before they
    // are sampled into the CPU read datapath. These flops are deliberately
    // kept off the scan chain so scan-mux insertion cannot weaken the
    // metastability hardening; they reset to 0 to avoid X-propagation.
    logic [7:0] gpio_pins_meta, gpio_pins_sync;
    always_ff @(posedge clk_i) begin
        if (!rst_ni) begin
            gpio_pins_meta <= 8'h00;
            gpio_pins_sync <= 8'h00;
        end else begin
            gpio_pins_meta <= gpio_pins_i;
            gpio_pins_sync <= gpio_pins_meta;
        end
    end

    //read
    // The native bus carries no byte offset on reads: picorv32 fetches the whole
    // aligned word and extracts the addressed byte itself. So we pack each of the
    // four pins of the addressed word into its own byte lane; the CPU's byte
    // extraction then lands on the requested pin. Per pin: read-back the driven
    // value if it's an output, otherwise the synchronized input.
    integer rl;
    always_comb begin
        rd_data_o = 32'h0;
        if(is_csr) begin
            rd_data_o = {24'h0, csr_reg};
        end else if(is_gpio_data) begin
            for (rl = 0; rl < 4; rl = rl + 1) begin
                rd_data_o[8*rl] = csr_reg[pin_index(rl[1:0])] ?
                                      data_reg[pin_index(rl[1:0])] :
                                      gpio_pins_sync[pin_index(rl[1:0])];
            end
        end
    end

    assign gpio_pins_o = data_reg;
    assign gpio_dir_o = csr_reg;

endmodule
