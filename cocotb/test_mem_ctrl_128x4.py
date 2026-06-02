import os
import random
import logging
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, Edge, RisingEdge, FallingEdge, ClockCycles
from cocotb_tools.runner import get_runner

# golden model
from emulation.memory_v2 import MemoryController

sim = os.getenv("SIM", "icarus")
pdk_root = Path("../gf180mcu")
pdk = os.getenv("PDK", "gf180mcuD")
scl = os.getenv("SCL", "gf180mcu_fd_sc_mcu7t5v0")
gl = os.getenv("GL", False)
slot = os.getenv("SLOT", "1x1")

hdl_toplevel = "mem_ctrl_128x4"

async def start_clock(dut, freq_mhz=50):
    clock = Clock(dut.clk_i, 1 / freq_mhz * 1000, unit="ns")
    cocotb.start_soon(clock.start())


async def reset(dut, duration_ns=100):

    dut.rst_ni.value = 0
    dut.mem_valid_i.value = 0

    dut.mem_addr_i.value = 0
    dut.mem_wdata_i.value = 0
    dut.mem_ready_i.value = 0

    await Timer(duration_ns, unit="ns")
    await FallingEdge(dut.clk_i)
    dut.rst_ni.value = 1
    await FallingEdge(dut.clk_i)


async def axi_write(dut, addr, data):

    dut.mem_addr_i.value = addr
    dut.mem_wdata_i.value = data

    dut.mem_valid_i.value = 1
    dut.mem_read_en_i.value = 0
    dut.mem_ready_i.value = 1


    # Wait for dut to be ready 
    while True:
        await FallingEdge(dut.clk_i)
        if dut.mem_ready_o.value == 1:
            break
    
    # Wait for ready handshake
    while True:
        await FallingEdge(dut.clk_i)
        if dut.mem_valid_o.value == 1:
            break

    dut.mem_valid_i.value = 0
    dut.mem_ready_i.value = 0
    await RisingEdge(dut.clk_i)


async def axi_read(dut, addr):

    dut.mem_addr_i.value = addr

    dut.mem_valid_i.value = 1
    dut.mem_ready_i.value = 1
    dut.mem_read_en_i.value = 1

    # wait for dut to be ready
    while True:
        await FallingEdge(dut.clk_i)
        if dut.mem_ready_o.value == 1:
            break

    # tell data ready
    # dut.mem_valid_i.value = 1

    # Wait for ready handshake
    while True:
        await FallingEdge(dut.clk_i)
        if dut.mem_valid_o.value == 1:
            rdata = int(dut.mem_rdata_o.value)
            break

    dut.mem_valid_i.value = 0
    dut.mem_ready_i.value = 0

    await RisingEdge(dut.clk_i)

    return rdata

@cocotb.test()
async def test_mem_ctrl_against_golden(dut):

    logger = logging.getLogger("my_testbench")
    golden: MemoryController = MemoryController()

    await start_clock(dut)
    await reset(dut)

    NUM_TRANSACTIONS = 1000

    for _ in range(1, NUM_TRANSACTIONS + 1, 1):

        addr = random.randint(0, 127)
        data = random.randint(0, 15)

        wstrb = 15

        # write to DUT
        await axi_write(dut, addr, data)
        # Apply to golden model
        await golden.write(addr, data, wstrb)


        # read written data
        dut_rdata = await axi_read(dut, addr)
        golden_rdata = await golden.read(addr)

        # compare golden and dut
        assert dut_rdata == golden_rdata, \
            f"Read mismatch at addr {addr:#x}: DUT={dut_rdata:#x}, GOLDEN={golden_rdata:#x}"


    logger.info("Done!")


def mem_ctrl_runner():
    proj_path = Path(__file__).resolve().parent

    sources = [
        # SRAM macro
        Path(pdk_root) / pdk / "libs.ref/gf180mcu_fd_ip_sram/verilog/gf180mcu_fd_ip_sram__sram64x8m8wm1.v",
        # SRAM bank 
        proj_path / "../src/mem_ctrl/cache_dir_memory/mem128x4.sv",
    ]

    build_args = []
    if sim == "icarus":
        pass
    if sim == "verilator":
        build_args = ["--timing", "--trace", "--trace-fst", "--trace-structs"]
        
    runner = get_runner(sim)
    runner.build(
        sources=sources,
        hdl_toplevel="mem_ctrl_128x4",
        always=True,
        build_args=build_args,
        waves=True,
    )

    runner.test(
        hdl_toplevel="mem_ctrl_128x4",
        test_module="test_mem_ctrl_128x4",
        waves=True,
    )

if __name__ == "__main__":
    mem_ctrl_runner()
