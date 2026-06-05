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

async def cpu_write(dut, addr, data, strobe=0xF):
    """Simulates a PicoRV32 memory write cycle"""
    dut.mem_addr.value = addr
    dut.mem_wdata.value = data
    dut.mem_wstrb.value = strobe
    dut.mem_valid.value = 1
    
    # Wait for ready
    while not dut.mem_ready.value:
        await RisingEdge(dut.clk_i)
    
    await RisingEdge(dut.clk_i)
    dut.mem_valid.value = 0
    dut.mem_wstrb.value = 0
    dut._log.info(f"CPU WRITE: Addr={hex(addr)}, Data={hex(data)}")

async def cpu_read(dut, addr):
    """Simulates a PicoRV32 memory read cycle"""
    dut.mem_addr.value = addr
    dut.mem_wstrb.value = 0
    dut.mem_valid.value = 1

    while not dut.mem_ready.value:
        print(f"\n\n\n\ncpu_read\n\n\n\n")
        await RisingEdge(dut.clk_i)
    
    val = int(dut.mem_rdata.value)
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
    await cpu_write(dut, 0x8000_0020, 0x12345678) # Write to flush addr
    await RisingEdge(dut.clk_i)
    # Note: Using the typo 'flush_vaild_o' if you haven't fixed it in RTL yet
    assert dut.flush_valid_o.value == 1, "Flush valid did not assert"
    
    # Pulse flush_ready to clear it
    dut.flush_ready_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.flush_ready_i.value = 0
    await RisingEdge(dut.clk_i)
    assert dut.flush_valid_o.value == 0, "Flush valid did not clear after ready"

    # 3. Config GPIO Direction (CSR at 0x8000_0018)
    test_dir = 0x81
    await cpu_write(dut, 0x8000_0018, test_dir)
    await RisingEdge(dut.clk_i)
    assert int(dut.gpio_dir_o.value) == test_dir, "CSR Update failed"

    # write and read output pin
    await cpu_write(dut, 0x8000_0010, 0x1)
    await RisingEdge(dut.clk_i)
    await cpu_read(dut, 0x8000_0010)
    assert int(dut.mem_rdata.value) == 1, "GPIO output pin was not successfully set"

    # write and read input pin
    await cpu_write(dut, 0x8000_0011, 0x1)
    await RisingEdge(dut.clk_i)
    await cpu_read(dut, 0x8000_0011)
    assert int(dut.mem_rdata.value) == 0, "GPIO input pin should not be set by CPU"
    dut.gpio_pins_i.value = 0x2
    await RisingEdge(dut.clk_i)
    await cpu_read(dut, 0x8000_0011)
    assert int(dut.mem_rdata.value) == 1, "GPIO input pin not successfully read"


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
            proj_path / "../src/mmio/mmio.sv",
            proj_path / "../src/mmio/sp_addr_handler.sv"
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
    