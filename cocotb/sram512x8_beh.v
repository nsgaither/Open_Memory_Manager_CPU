// Simple behavioral SRAM model for simulation
// 512x8 SRAM, synchronous read/write

module gf180mcu_fd_ip_sram__sram512x8m8wm1 (
    input  wire        CLK,
    input  wire        CEN,
    input  wire        GWEN,
    input  wire [7:0] WEN,
    input  wire [8:0] A,
    input  wire [7:0] D,
    output reg  [7:0] Q
);

    reg [7:0] mem [0:511];

    initial begin
        $display("-------- MESSAGE: Behavioral SRAM model initialized ---------");
    end

    always @(posedge CLK) begin
        if (!CEN) begin
            if (!GWEN) begin
                // Write
                if (!WEN[0]) mem[A] <= D;
            end else begin
                // Read
                Q <= mem[A];
            end
        end
    end

endmodule
