import os
import random
import logging
from pathlib import Path
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, RisingEdge, FallingEdge
from cocotb_tools.runner import get_runner

sim = os.getenv("SIM", "icarus")
hdl_toplevel = "cache_mem"


async def start_clock(dut, freq_mhz=50):
    clock = Clock(dut.clk_i, 1 / freq_mhz * 1000, unit="ns")
    cocotb.start_soon(clock.start())


async def reset(dut, duration_ns=100):
    dut.rst_ni.value   = 0
    dut.valid_i.value  = 0
    dut.addr_i.value   = 0
    dut.wdata_i.value  = 0
    dut.wstrb_i.value  = 0
    dut.wstate_i.value = 0
    dut.wtag_i.value   = 0
    dut.ready_i.value  = 0
    await Timer(duration_ns, unit="ns")
    await FallingEdge(dut.clk_i)
    dut.rst_ni.value = 1
    # mem_ctrl_128x32 RESET_DATA runs for 512 cycles
    for _ in range(520):
        await RisingEdge(dut.clk_i)


async def _handshake(dut):
    """Both sub-modules start simultaneously. Tag (2-cycle) waits for
    data (6-cycle) via mem_ready_i(ready_i && data_mem_valid), so
    asserting ready_i=1 upfront is safe."""
    dut.valid_i.value = 1
    dut.ready_i.value = 1

    while True:
        await FallingEdge(dut.clk_i)
        if dut.ready_o.value == 1:
            break

    while True:
        await FallingEdge(dut.clk_i)
        if dut.valid_o.value == 1:
            rdata  = int(dut.rdata_o.value)
            rtag   = int(dut.rtag_o.value)
            rstate = int(dut.rstate_o.value)
            break

    dut.valid_i.value = 0
    dut.ready_i.value = 0
    await RisingEdge(dut.clk_i)
    return rdata, rtag, rstate


async def cache_access(dut, addr, wdata=0, wstate=0, wtag=0, wstrb=0):
    """
    wstrb=0  → read  (RTL sets mem_read_en_i=1 on tag, data mem reads)
    wstrb!=0 → write (RTL sets mem_read_en_i=0 on tag, data mem byte-writes)
    """
    dut.addr_i.value   = addr
    dut.wdata_i.value  = wdata
    dut.wstate_i.value = wstate
    dut.wtag_i.value   = wtag
    dut.wstrb_i.value  = wstrb
    return await _handshake(dut)


# ---------------------------------------------------------------------------
# Golden model
# ---------------------------------------------------------------------------

class CacheMemGolden:
    def __init__(self):
        self._data = bytearray(128 * 4)
        self._tags = [0] * 128          # {wtag[1:0], wstate[1:0]}

    def write(self, addr, wdata, wstate, wtag, wstrb=0xF):
        word_addr = addr & 0x7F
        base      = word_addr * 4
        for b in range(4):
            if wstrb & (1 << b):
                self._data[base + b] = (wdata >> (b * 8)) & 0xFF
        self._tags[word_addr] = ((wtag & 0x3) << 2) | (wstate & 0x3)

    def read(self, addr):
        word_addr = addr & 0x7F
        base      = word_addr * 4
        rdata  = int.from_bytes(self._data[base:base + 4], "little")
        rtag   = (self._tags[word_addr] >> 2) & 0x3
        rstate =  self._tags[word_addr]        & 0x3
        return rdata, rtag, rstate


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@cocotb.test()
async def test_cache_mem_write_read(dut):
    """Random write/read pairs across the full address space."""
    logger = logging.getLogger("cache_mem_tb")
    golden = CacheMemGolden()

    await start_clock(dut)
    await reset(dut)

    for i in range(500):
        addr   = random.randint(0, 127)
        wdata  = random.randint(0, 0xFFFFFFFF)
        wstate = random.randint(0, 3)
        wtag   = random.randint(0, 3)
        wstrb  = random.randint(1, 0xF)

        await cache_access(dut, addr, wdata, wstate, wtag, wstrb)
        golden.write(addr, wdata, wstate, wtag, wstrb)

        dut_rdata, dut_rtag, dut_rstate = await cache_access(dut, addr)  # wstrb=0 → read
        g_rdata,   g_rtag,   g_rstate   = golden.read(addr)

        assert dut_rdata == g_rdata, (
            f"[{i}] rdata  @ {addr:#x}: DUT={dut_rdata:#010x} GOLDEN={g_rdata:#010x}"
        )
        assert dut_rtag == g_rtag, (
            f"[{i}] rtag   @ {addr:#x}: DUT={dut_rtag} GOLDEN={g_rtag}"
        )
        assert dut_rstate == g_rstate, (
            f"[{i}] rstate @ {addr:#x}: DUT={dut_rstate} GOLDEN={g_rstate}"
        )

    logger.info("test_cache_mem_write_read PASSED (500 transactions)")


@cocotb.test()
async def test_cache_mem_wstrb(dut):
    """Partial byte-enable must not disturb untouched bytes."""
    logger = logging.getLogger("cache_mem_tb")
    golden = CacheMemGolden()

    await start_clock(dut)
    await reset(dut)

    addr = 0x05

    await cache_access(dut, addr, 0xFFFFFFFF, 0, 0, wstrb=0xF)
    golden.write(addr, 0xFFFFFFFF, 0, 0, wstrb=0xF)

    await cache_access(dut, addr, 0x000000AB, 0, 0, wstrb=0x1)
    golden.write(addr, 0x000000AB, 0, 0, wstrb=0x1)

    dut_rdata, _, _ = await cache_access(dut, addr)
    g_rdata,   _, _ = golden.read(addr)

    assert dut_rdata == g_rdata, f"DUT={dut_rdata:#010x} GOLDEN={g_rdata:#010x}"
    assert g_rdata == 0xFFFFFFAB, f"golden sanity: {g_rdata:#010x}"

    logger.info("test_cache_mem_wstrb PASSED")


@cocotb.test()
async def test_cache_mem_read_no_tag_corrupt(dut):
    """Reads must not overwrite tag/state (regression for missing read_en)."""
    logger = logging.getLogger("cache_mem_tb")
    golden = CacheMemGolden()

    await start_clock(dut)
    await reset(dut)

    addr = 0x20

    await cache_access(dut, addr, 0xDEADBEEF, wstate=2, wtag=3, wstrb=0xF)
    golden.write(addr, 0xDEADBEEF, wstate=2, wtag=3)

    for i in range(5):
        dut_rdata, dut_rtag, dut_rstate = await cache_access(dut, addr)
        g_rdata,   g_rtag,   g_rstate   = golden.read(addr)

        assert dut_rdata  == g_rdata,  f"read {i}: rdata  {dut_rdata:#010x} != {g_rdata:#010x}"
        assert dut_rtag   == g_rtag,   f"read {i}: rtag   {dut_rtag} != {g_rtag}"
        assert dut_rstate == g_rstate, f"read {i}: rstate {dut_rstate} != {g_rstate}"

    logger.info("test_cache_mem_read_no_tag_corrupt PASSED")


@cocotb.test()
async def test_cache_mem_overwrite(dut):
    """Last write wins across repeated overwrites."""
    logger = logging.getLogger("cache_mem_tb")
    golden = CacheMemGolden()

    await start_clock(dut)
    await reset(dut)

    addr = 0x10
    for _ in range(20):
        wdata  = random.randint(0, 0xFFFFFFFF)
        wstate = random.randint(0, 3)
        wtag   = random.randint(0, 3)
        await cache_access(dut, addr, wdata, wstate, wtag, wstrb=0xF)
        golden.write(addr, wdata, wstate, wtag)

    dut_rdata, dut_rtag, dut_rstate = await cache_access(dut, addr)
    g_rdata,   g_rtag,   g_rstate   = golden.read(addr)

    assert dut_rdata  == g_rdata,  f"rdata:  DUT={dut_rdata:#010x} GOLDEN={g_rdata:#010x}"
    assert dut_rtag   == g_rtag,   f"rtag:   {dut_rtag} != {g_rtag}"
    assert dut_rstate == g_rstate, f"rstate: {dut_rstate} != {g_rstate}"

    logger.info("test_cache_mem_overwrite PASSED")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def test_cache_mem():
    proj_path = Path(__file__).resolve().parent
    pdk_root  = Path("../gf180mcu")

    sources = [
        pdk_root / "gf180mcuD/libs.ref/gf180mcu_fd_ip_sram/verilog/gf180mcu_fd_ip_sram__sram512x8m8wm1.v",
        pdk_root / "gf180mcuD/libs.ref/gf180mcu_fd_ip_sram/verilog/gf180mcu_fd_ip_sram__sram64x8m8wm1.v",
        proj_path / "../src/mem_ctrl/cache_dir_memory/mem128x32.sv",
        proj_path / "../src/mem_ctrl/cache_dir_memory/mem128x4.sv",
        proj_path / "../src/mem_ctrl/cache_dir_memory/cache_mem.sv",
    ]

    build_args = []
    if sim == "verilator":
        build_args = ["--timing", "--trace", "--trace-fst", "--trace-structs"]

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
        test_module="test_cache_mem",
        waves=True,
    )


if __name__ == "__main__":
    test_cache_mem()
