import os
from pathlib import Path
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, RisingEdge, FallingEdge, ClockCycles
from cocotb_tools.runner import get_runner


sim = os.getenv("SIM", "icarus")
pdk_root = os.getenv("PDK_ROOT", Path("~/.ciel").expanduser())
pdk = os.getenv("PDK", "gf180mcuD")
scl = os.getenv("SCL", "gf180mcu_fd_sc_mcu7t5v0")
gl = os.getenv("GL", False)
slot = os.getenv("SLOT", "1x1")

hdl_toplevel = "sp_addr_handler"

# Helper funcs
async def setup_reset(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, unit="ns").start())
    dut.rst_ni.value = 0
    # Initialize inputs to avoid 'X' propagation
    dut.mem_valid.value = 0
    dut.mem_addr.value = 0
    dut.mem_wdata.value = 0
    dut.mem_wstrb.value = 0
    dut.pass_mem_ready.value = 0
    dut.flush_ready_i.value = 0
    dut.gpio_pins_i.value = 0
    dut.cpu_id_i.value = 0xA5    # Set a test ID
    
    await Timer(20, unit="ns")
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)

async def cpu_write(dut, addr, data, strobe=None):
    """Simulates a PicoRV32 memory write cycle.

    The native bus is word-aligned (addr[1:0]==0); a byte store carries the
    target lane in wstrb and the byte value on that lane. When `strobe` is
    None this models a byte store to `addr`; pass an explicit strobe/data for
    a raw word write.
    """
    lane = addr & 0x3
    if strobe is None:
        strobe = 1 << lane
        data = (data & 0xFF) << (8 * lane)
    dut.mem_addr.value = addr & ~0x3
    dut.mem_wdata.value = data
    dut.mem_wstrb.value = strobe
    dut.mem_valid.value = 1
    await Timer(1, unit="ns")  # let the combinational ready/decode settle

    # Wait for ready
    while int(dut.mem_ready.value) == 0:
        await RisingEdge(dut.clk_i)
        await Timer(1, unit="ns")

    await RisingEdge(dut.clk_i)
    dut.mem_valid.value = 0
    dut.mem_wstrb.value = 0
    dut._log.info(f"CPU WRITE: Addr={hex(addr)}, Data={hex(data)}")

async def cpu_read(dut, addr):
    """Simulates a PicoRV32 memory read cycle.

    The bus returns the aligned word; the CPU extracts the byte at the
    addressed lane (matches mmio packing the four pins into four byte lanes).
    """
    lane = addr & 0x3
    dut.mem_addr.value = addr & ~0x3
    dut.mem_wstrb.value = 0
    dut.mem_valid.value = 1
    await Timer(1, unit="ns")  # let the combinational rdata/decode settle

    while int(dut.mem_ready.value) == 0:
        await RisingEdge(dut.clk_i)
        await Timer(1, unit="ns")

    val = (int(dut.mem_rdata.value) >> (8 * lane)) & 0xFF
    await RisingEdge(dut.clk_i)
    dut.mem_valid.value = 0
    dut._log.info(f"CPU READ:  Addr={hex(addr)}, Result={hex(val)}")
    return val

@cocotb.test()
async def thorough_mmio_test(dut):
    await setup_reset(dut)
    await RisingEdge(dut.clk_i)
    dut._log.info("--- Starting Updated MMIO Testbench ---")

    # 1. Test WHOAMI (now uses cpu_id_i port)
    # Expected: {24'b0, 0xA5} = 0x000000A5
    expected_id = 0xA5
    val = await cpu_read(dut, 0x8000_0000)
    assert val == expected_id, f"WHOAMI failed: expected {hex(expected_id)}, got {hex(val)}"

    # 2. Test Flush Logic (New Feature)
    dut._log.info("Testing Flush Mechanism...")
    dut.mem_addr.value = 0x8000_0020
    dut.mem_wdata.value = 0x12345678
    dut.mem_wstrb.value = 0xF
    dut.mem_valid.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, unit="ns")
    assert dut.flush_valid_o.value == 1, "Flush valid did not assert"
    # flush_addr_o must carry the target address the CPU wrote as data
    # (0x1234_5678), not the fixed 0x8000_0020 trigger address itself --
    # otherwise every flush would always hit the same one cache line. The
    # handler word-indexes it (byte addr >> 2, same translation as pass_mem_addr
    # for the word-indexed cache), so expect 0x1234_5678 >> 2 == 0x48D_159E.
    assert dut.flush_addr_o.value == (0x12345678 >> 2), (
        f"Flush addr should be the written target word index "
        f"(0x{0x12345678 >> 2:x}), got {hex(int(dut.flush_addr_o.value))}"
    )

    # Pulse flush_ready to clear it
    dut.mem_valid.value = 0
    dut.mem_wstrb.value = 0
    dut.flush_ready_i.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, unit="ns")
    dut.flush_ready_i.value = 0
    await RisingEdge(dut.clk_i)
    assert dut.flush_valid_o.value == 0, "Flush valid did not clear after ready"

    # 3. GPIO full-coverage test. Every one of the 8 pins must be individually
    # addressable by the core: pin P lives at byte address 0x8000_0010 + P
    # (addr[2] picks the 4-pin group, the wstrb byte lane picks the pin within
    # it). Regression guard for the old bug where only pins 0 and 4 -- the
    # lane-0 pins of each word -- were reachable.

    # 3a. All 8 pins as OUTPUTS: write a distinct per-pin value, read each back,
    # and confirm the aggregate is driven onto gpio_pins_o.
    await cpu_write(dut, 0x8000_0018, 0xFF)   # CSR: all outputs
    await RisingEdge(dut.clk_i)
    assert int(dut.gpio_dir_o.value) == 0xFF, "CSR (dir) update failed"

    out_pattern = [1, 0, 1, 1, 0, 0, 1, 0]
    for p in range(8):
        await cpu_write(dut, 0x8000_0010 + p, out_pattern[p])
    for p in range(8):
        val = await cpu_read(dut, 0x8000_0010 + p)
        assert val == out_pattern[p], (
            f"output pin {p} readback: expected {out_pattern[p]}, got {val}"
        )
    expected_out = sum(out_pattern[p] << p for p in range(8))
    assert int(dut.gpio_pins_o.value) == expected_out, (
        f"gpio_pins_o: expected {expected_out:#04x}, "
        f"got {hex(int(dut.gpio_pins_o.value))}"
    )

    # 3b. All 8 pins as INPUTS: CPU writes must not stick, and every pin must
    # read back its (synchronized) external value.
    await cpu_write(dut, 0x8000_0018, 0x00)   # CSR: all inputs
    await RisingEdge(dut.clk_i)
    for p in range(8):                        # writes to inputs are ignored
        await cpu_write(dut, 0x8000_0010 + p, 1)
    in_pattern = 0b0101_1010
    dut.gpio_pins_i.value = in_pattern
    await ClockCycles(dut.clk_i, 3)           # two-flop synchronizer settle
    for p in range(8):
        val = await cpu_read(dut, 0x8000_0010 + p)
        exp = (in_pattern >> p) & 1
        assert val == exp, f"input pin {p} read: expected {exp}, got {val}"


    # 4. Test Passthrough Logic
    # For non-special addresses, mem_ready depends on pass_mem_ready
    dut.pass_mem_ready.value = 0
    dut.mem_addr.value = 0x0000_1000 # Normal memory addr
    dut.mem_valid.value = 1
    await Timer(20, unit="ns")
    assert dut.pass_mem_valid.value == 1, "Error: mem_valid not passing through with valid address"
    assert dut.mem_ready.value == 0, "Error: mem_ready high when downstream is busy"
    
    await RisingEdge(dut.clk_i)
    dut.pass_mem_ready.value = 1
    dut.pass_mem_rdata.value = 0xDEADBEEF
    await RisingEdge(dut.clk_i)
    assert dut.mem_ready.value == 1, "Error: mem_ready did not follow pass_mem_ready"
    assert dut.mem_rdata.value == 0xDEADBEEF, "Error: mem_rdata did not follow pass_mem_rdata"
    dut.mem_valid.value = 0

    dut._log.info("--- ALL TESTS PASSED ---")

    
def sp_handler_tb_runner():
    proj_path = Path(__file__).resolve().parent

    sources = []
    if gl:
        pdk_lib = os.path.join(
            pdk_root, 
            pdk, 
            "libs.ref", 
            scl, 
            "verilog"
        )
        sources += [proj_path / f"../src/netlists/{hdl_toplevel}.nl.v"]
        sources += [os.path.join(pdk_lib, f) for f in [f"{scl}.v", f"primitives.v"]]
    else:
        sources = [
            proj_path / "../src/sp_addr_handling/mmio.sv",
            proj_path / "../src/sp_addr_handling/sp_addr_handler.sv"
        ]

    build_args = []
    if sim == "icarus":
        pass
    if sim == "verilator":
        build_args = ["--timing", "--trace", "--trace-fst", "--trace-structs"]

    runner = get_runner(sim)
    runner.build(
        sources=sources,
        hdl_toplevel="sp_addr_handler",
        always=True,
        build_args=build_args,
        waves=True
    )

    runner.test(hdl_toplevel="sp_addr_handler", test_module="sp_handler_tb", waves=True)

if __name__ == "__main__":
    sp_handler_tb_runner()
