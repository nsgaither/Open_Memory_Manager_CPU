# Scan-shift timing mode.
#
# This mode is intentionally separate from the functional P&R constraint set.
# Override the default 1000 ns period by exporting SCAN_CLOCK_PERIOD before
# invoking OpenSTA/OpenROAD.
set ::SCAN_TIMING_MODE 1
source [file join [file dirname [info script]] chip_top.sdc]
