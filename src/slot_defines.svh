`ifdef SLOT_1X1

// Power/ground pads for core and I/O
`define NUM_DVDD_PADS 8
`define NUM_DVSS_PADS 10

// Signal pads
`define NUM_BIDIR_PADS 40

`endif

`ifdef SLOT_0P5X1

// Power/ground pads for core and I/O
`define NUM_DVDD_PADS 8
`define NUM_DVSS_PADS 8

// Signal pads
`define NUM_BIDIR_PADS 44

`endif

`ifdef SLOT_1X0P5

// Power/ground pads for core and I/O
`define NUM_DVDD_PADS 8
`define NUM_DVSS_PADS 8

// Signal pads
`define NUM_BIDIR_PADS 46

`endif

`ifdef SLOT_0P5X0P5

// Power/ground pads for core and I/O
`define NUM_DVDD_PADS 3
`define NUM_DVSS_PADS 3

// Signal pads
`define NUM_BIDIR_PADS 48

`endif
