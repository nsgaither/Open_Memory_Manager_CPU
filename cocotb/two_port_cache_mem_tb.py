import os
import random
import logging
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, RisingEdge, FallingEdge
from cocotb_tools.runner import get_runner

sim = os.getenv("SIM", "icarus")

hdl_toplevel = "two_port_cache_mem"


# ============================================================
# Clock / Reset
# ============================================================

async def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, unit="ns").start())


async def reset(dut):
    dut.rst_ni.value = 0

    for p in [0, 1]:
        getattr(dut, f"p{p}_valid_i").value = 0
        getattr(dut, f"p{p}_ready_i").value = 0

    await Timer(100, unit="ns")
    await RisingEdge(dut.clk_i)

    dut.rst_ni.value = 1

    for _ in range(520):
        await RisingEdge(dut.clk_i)


# ============================================================
# Safe port access (WITH TIMEOUT FIX)
# ============================================================

async def cache_access(dut, port, addr, wdata=0, wstate=0, wtag=0, wstrb=0):

    vld = getattr(dut, f"p{port}_valid_i")
    rdy = getattr(dut, f"p{port}_ready_o")

    getattr(dut, f"p{port}_addr_i").value   = addr
    getattr(dut, f"p{port}_wdata_i").value  = wdata
    getattr(dut, f"p{port}_wstrb_i").value  = wstrb
    getattr(dut, f"p{port}_wstate_i").value = wstate
    getattr(dut, f"p{port}_wtag_i").value   = wtag

    vld.value = 1
    getattr(dut, f"p{port}_ready_i").value = 1

    # WAIT READY (timeout prevents infinite hang)
    for _ in range(2000):
        await RisingEdge(dut.clk_i)
        if rdy.value == 1:
            break
    else:
        raise RuntimeError(f"PORT{port} TIMEOUT WAITING READY")

    # WAIT VALID
    for _ in range(2000):
        await RisingEdge(dut.clk_i)

        if getattr(dut, f"p{port}_valid_o").value == 1:
            rdata  = int(getattr(dut, f"p{port}_rdata_o").value)
            rtag   = int(getattr(dut, f"p{port}_rtag_o").value)
            rstate = int(getattr(dut, f"p{port}_rstate_o").value)
            break
    else:
        raise RuntimeError(f"PORT{port} TIMEOUT WAITING VALID")

    vld.value = 0
    getattr(dut, f"p{port}_ready_i").value = 0

    await RisingEdge(dut.clk_i)

    return rdata, rtag, rstate


# ============================================================
# Tests
# ============================================================

@cocotb.test()
async def test_rr_basic(dut):

    await start_clock(dut)
    await reset(dut)

    # simple simultaneous contention
    task0 = cocotb.start_soon(cache_access(dut, 0, 0x10))
    task1 = cocotb.start_soon(cache_access(dut, 1, 0x20))

    r0 = await task0
    r1 = await task1

    assert r0 is not None
    assert r1 is not None


@cocotb.test()
async def test_rr_stress(dut):

    await start_clock(dut)
    await reset(dut)

    async def worker(p):

        for _ in range(50):

            addr = random.randint(0, 127)
            wdat = random.randint(0, 0xFFFFFFFF)

            await cache_access(dut, p, addr, wdat, 1, 1, 0xF)
            await cache_access(dut, p, addr)

    t0 = cocotb.start_soon(worker(0))
    t1 = cocotb.start_soon(worker(1))

    await t0
    await t1
# ============================================================================
# Runner
# ============================================================================

def test_two_port_cache_mem():

    proj_path = Path(__file__).resolve().parent
    pdk_root  = Path("../gf180mcu")

    sources = [

        pdk_root / "gf180mcuD/libs.ref/gf180mcu_fd_ip_sram/verilog/gf180mcu_fd_ip_sram__sram512x8m8wm1.v",
        pdk_root / "gf180mcuD/libs.ref/gf180mcu_fd_ip_sram/verilog/gf180mcu_fd_ip_sram__sram64x8m8wm1.v",

        proj_path / "../src/mem_ctrl/cache_dir_memory/mem128x32.sv",
        proj_path / "../src/mem_ctrl/cache_dir_memory/mem128x4.sv",
        proj_path / "../src/mem_ctrl/cache_dir_memory/cache_mem.sv",

        proj_path / "../src/mem_ctrl/cache_dir_memory/two_port_cache_mem.sv",
    ]

    build_args = []

    if sim == "verilator":
        build_args = [
            "--timing",
            "--trace",
            "--trace-fst",
            "--trace-structs"
        ]

    runner = get_runner(sim)

    runner.build(
        sources=sources,
        hdl_toplevel=hdl_toplevel,
        always=True,
        build_args=build_args,
        waves=True,
    )

    runner.test(
        hdl_toplevel=hdl_toplevel,
        test_module="two_port_cache_mem_tb",
        waves=True,
    )


if __name__ == "__main__":
    test_two_port_cache_mem()
