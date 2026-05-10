`timescale 1ns/1ps

module cache_interface #(
    parameter int NUM_TPINS = 1,
    parameter int NUM_RPINS = 1
)
(
    input  logic                clk_i,
    input  logic                rst_ni,
    // UPSTREAM --------------------------------------
    // Cache Send Ports
    input  logic                cache_valid_i,
    input  logic [31:0]         cache_addr_i,
    input  logic [31:0]         cache_data_i,
    input  logic [8:0]          cache_cmd_i,
    output logic                cache_ready_o,

    // Bus Ack ports
    output logic                bus_valid_o,
    output logic [31:0]         bus_data_o,
    output logic [2:0]          bus_dircmd_o,
    input  logic                bus_ready_i,

    // Snoop Req ports
    output logic                snoop_valid_o,
    output logic [31:0]         snoop_data_o,
    output logic [2:0]          snoop_dircmd_o,
    input  logic                snoop_ready_i,

    // busy
    output logic                rbusy_o,

    // other
    output logic [7:0]          cpu_id_o,
    // -----------------------------------------------

    // DOWNSTREAM ------------------------------------
    // wrapped serializer IO
    input  logic                 req_i,
    input  logic [NUM_RPINS-1:0] serial_i,
    output logic                 req_o,
    output logic [NUM_TPINS-1:0] serial_o
    // -----------------------------------------------
);

    typedef enum logic [3:0] { 
        NULL            = 4'b0000,
        BusRD           = 4'b0001,
        BusRDX          = 4'b0010,
        BusUPGR         = 4'b0011,

        EvictClean      = 4'b0101,
        EvictDirty      = 4'b0110,


        SnoopBusRD      = 4'b1001,
        SnoopBusRDX     = 4'b1010,
        SnoopBusUPGR    = 4'b1011,

        
        WhoAmI          = 4'b1110,
        ResetDone       = 4'b1111
    } metadata;

    typedef enum logic [8:0] { 
        NULLcc1h            = 9'b0,
        BusRD_1h            = 9'b1,
        BusRDX_1h           = 9'b10,
        BusUPGR_1h          = 9'b100,
        EvictClean_1h       = 9'b1000,
        EvictDirty_1h       = 9'b10000,
        SnoopBusRD_Ack_1h   = 9'b100000,
        SnoopBusRDX_Ack_1h  = 9'b1000000,
        SnoopBusUPGR_Ack_1h = 9'b10000000,
        ResetDone_1h        = 9'b100000000
    } ccmd_1hot;

    typedef enum logic [6:0] { 
        NULLdc1h            = 7'b0,

        BusRD_Ack_1h        = 7'b1,
        BusRDX_Ack_1h       = 7'b10,
        BusUPGR_Ack_1h      = 7'b100,
        
        SnoopBusRD_1h       = 7'b1000,
        SnoopBusRDX_1h      = 7'b10000,
        SnoopBusUPGR_1h     = 7'b100000,
        
        WhoAmI_1h           = 7'b1000000
    } dcmd_1hot;

    typedef enum logic [1:0] {
        CMDONLY = 2'b00,
        SHORT   = 2'b01,
        MEDIUM  = 2'b10,
        LARGE   = 2'b11
    } msg_types;

    // TRANSMISSION
    logic [69:0] t_packet;
    always_comb begin : build_packet
        case (cache_cmd_i)
            BusRD_1h            : t_packet = {MEDIUM,  32'b0,        cache_addr_i, BusRD};
            BusRDX_1h           : t_packet = {MEDIUM,  32'b0,        cache_addr_i, BusRDX};
            BusUPGR_1h          : t_packet = {MEDIUM,  32'b0,        cache_addr_i, BusUPGR};
            EvictClean_1h       : t_packet = {MEDIUM,  32'b0,        cache_addr_i, EvictClean};
            EvictDirty_1h       : t_packet = {LARGE,   cache_data_i, cache_addr_i, EvictDirty};
            SnoopBusRD_Ack_1h   : t_packet = {MEDIUM,  32'b0,        cache_data_i, SnoopBusRD};
            SnoopBusRDX_Ack_1h  : t_packet = {MEDIUM,  32'b0,        cache_data_i, SnoopBusRDX};
            SnoopBusUPGR_Ack_1h : t_packet = {MEDIUM,  32'b0,        cache_data_i, SnoopBusUPGR};
            ResetDone_1h        : t_packet = {CMDONLY, 32'b0,        32'b0,        ResetDone};
            default             : t_packet = '0;
        endcase
    end

    tserializer #(
        .NUM_PINS    (NUM_TPINS),
        .MAX_MSG_LEN (68),
        .MSG_LEN_0   (4),
        .MSG_LEN_1   (12),
        .MSG_LEN_2   (36),
        .MSG_LEN_3   (68)
    ) u_tserializer (
        .clk_i    (clk_i),
        .rst_ni   (rst_ni),

        .req_o    (req_o),
        .serial_o (serial_o),

        .valid_i  (cache_valid_i),
        .data_in  (t_packet[67:0]),
        .msg_type (t_packet[69:68]),
        .ready_o  (cache_ready_o)
    );

    // RECEIVING
    wire [(int'($ceil(real'(36) / NUM_RPINS)) * NUM_RPINS)-1:0] rpacket_full;
    wire rvalid_o;
    assign rbusy_o = req_i;
    rserializer #(
        .NUM_PINS    (NUM_RPINS),
        .MAX_MSG_LEN (36)
    ) u_rserializer (
        .clk_i    (clk_i),
        .rst_ni   (rst_ni),
        
        .serial_i (serial_i),
        .req_i    (req_i),

        .valid_o  (rvalid_o),
        .data_o   (rpacket_full),
        .ready_i  (1'b1)
    );

    logic [3:0] rmetadata;
    assign rmetadata = rpacket_full[3:0];

    logic           bus_valid_d;
    logic           snoop_valid_d;
    
    dcmd_1hot   full_dircmd_1h;

    always_comb begin : decode_packet
        bus_valid_d = 1'b0;
        snoop_valid_d = 1'b0;

        case (rmetadata)
            BusRD           : begin
                full_dircmd_1h = BusRD_Ack_1h;
                bus_valid_d = rvalid_o;
            end
            BusRDX          : begin
                full_dircmd_1h = BusRDX_Ack_1h;
                bus_valid_d = rvalid_o;
            end
            BusUPGR         : begin
                full_dircmd_1h = BusUPGR_Ack_1h;
                bus_valid_d = rvalid_o;
            end
            SnoopBusRD      : begin
                full_dircmd_1h = SnoopBusRD_1h;
                snoop_valid_d = rvalid_o;
            end
            SnoopBusRDX     : begin
                full_dircmd_1h = SnoopBusRDX_1h;
                snoop_valid_d = rvalid_o;
            end
            SnoopBusUPGR    : begin
                full_dircmd_1h = SnoopBusUPGR_1h;
                snoop_valid_d = rvalid_o;
            end
            default         : begin
                full_dircmd_1h = NULLdc1h;
            end
        endcase
    end

    logic [31:0]    receive_data_d;
    assign receive_data_d = rpacket_full[35:4];

    // bus ack data interface
    wire bus_ack_rready_i;
    lossy_pipe_stage #(
        .WIDTH(35)
    ) bus_ack_pipe (
        .clk_i   (clk_i),
        .rst_ni  (rst_ni),

        // Upstream Interface
        .valid_i (bus_valid_d),
        .data_i  ({full_dircmd_1h[2:0], receive_data_d}),
        .ready_o (bus_ack_rready_i),    // tied to one because it's lossy 

        // Downstream Interface
        .valid_o (bus_valid_o),
        .data_o  ({bus_dircmd_o, bus_data_o}),
        .ready_i (bus_ready_i)
    );

    // snoop data interface
    wire snoop_rready_i;
    lossy_pipe_stage #(
        .WIDTH(35)
    ) snoop_pipe (
        .clk_i   (clk_i),
        .rst_ni  (rst_ni),

        // Upstream Interface
        .valid_i (snoop_valid_d),
        .data_i  ({full_dircmd_1h[5:3], receive_data_d}),
        .ready_o (snoop_rready_i),    // tied to one because it's lossy 

        // Downstream Interface
        .valid_o (snoop_valid_o),
        .data_o  ({snoop_dircmd_o, snoop_data_o}),
        .ready_i (snoop_ready_i)
    );

    // hold cpu_id
    logic [7:0] cpu_id_r;
    assign cpu_id_o = cpu_id_r;

    always_ff @( posedge clk_i or negedge rst_ni ) begin : cpuid_reg
        if (!rst_ni) begin
            cpu_id_r <= '0;
        end else if ((rmetadata == WhoAmI) & (rvalid_o == 1)) begin
            cpu_id_r <= rpacket_full[11:4];
        end
    end

endmodule
