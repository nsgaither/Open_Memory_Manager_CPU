// Compiled only when SDF_FILE is defined by make sim-sdf.
// Injects SDF back-annotation into the cocotb DUT instance at time 0.
`ifdef SDF_FILE
module sdf_annotate_shim;
  initial begin
    $display("SDF: annotating %0s", `SDF_FILE);
    $sdf_annotate(`SDF_FILE, chip_top);
  end
endmodule
`endif
