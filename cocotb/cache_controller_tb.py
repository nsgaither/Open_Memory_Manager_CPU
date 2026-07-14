import os
import logging
from pathlib import Path
from typing import List

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer, with_timeout
from cocotb_tools.runner import get_runner

# ─────────────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────────────

sim = os.getenv("SIM", "icarus")
log = logging.getLogger("cache_tb")
logging.basicConfig(level=logging.INFO)

from emulation.cache import CacheController
from emulation.axi_request_types import axi_and_coherence_request, axi_request
from emulation.msi import CoherenceCmd, SnoopEvent, on_snoop_event

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

CMD_BUS_RD   = 0b000000001
CMD_BUS_RDX  = 0b000000010
CMD_BUS_UPGR = 0b000000100

BUSRD_ACK   = 0b001
BUSRDX_ACK  = 0b010
BUSUPGR_ACK = 0b100

# snoop_dircmd_i encoding (directory -> cache)
SNOOP_BUS_RD_1H   = 0b001
SNOOP_BUS_RDX_1H  = 0b010
SNOOP_BUS_UPGR_1H = 0b100

# cache_cmd_o encoding for snoop acks (cache -> directory, shares the bus
# with the CPU-side coherence cmds, see cache_controller.sv Snoop*_Ack_1h)
SNOOP_ACK_RD_1H   = 0b000100000
SNOOP_ACK_RDX_1H  = 0b001000000
SNOOP_ACK_UPGR_1H = 0b010000000

SNOOP_1H_TO_ACK = {
    SNOOP_BUS_RD_1H:   SNOOP_ACK_RD_1H,
    SNOOP_BUS_RDX_1H:  SNOOP_ACK_RDX_1H,
    SNOOP_BUS_UPGR_1H: SNOOP_ACK_UPGR_1H,
}

TIMEOUT_CYCLES = 1000

# ─────────────────────────────────────────────────────────────────────────────
# Golden model and helpers
# ─────────────────────────────────────────────────────────────────────────────

captured_dir_requests: List = []
async def dummy_directory_handler(req):
    # print(req)
    captured_dir_requests.append(req)

    return axi_request(
        mem_valid=True,
        mem_ready=True,
        mem_instr=False,
        mem_addr=req.mem_addr,
        mem_wdata=0,
        mem_wstrb=0,
        mem_rdata=req.mem_addr,
    )

def coherence_cmd_to_acks(cmd: CoherenceCmd) -> int:
    if cmd == CoherenceCmd.BUS_RD:
        return BUSRD_ACK
    elif cmd == CoherenceCmd.BUS_RDX:
        return BUSRDX_ACK
    elif cmd == CoherenceCmd.BUS_UPGR:
        return BUSUPGR_ACK
    return 0

cache = CacheController(
    core_id=0,
    directory_axi_handler=dummy_directory_handler,
)


# ─────────────────────────────────────────────────────────────────────────────
# Clock
# ─────────────────────────────────────────────────────────────────────────────

async def start_clock(dut, freq_mhz=1):
    clock = Clock(dut.clk_i, 1000 / freq_mhz, unit="ns")
    cocotb.start_soon(clock.start())


# ─────────────────────────────────────────────────────────────────────────────
# Reset
# ─────────────────────────────────────────────────────────────────────────────

async def reset_dut(dut):
    dut.rst_ni.value = 1

    dut.mem_valid_i.value = 0
    dut.mem_instr_i.value = 0
    dut.mem_addr_i.value = 0
    dut.mem_wdata_i.value = 0
    dut.mem_wstrb_i.value = 0

    dut.bus_valid_i.value = 0
    dut.bus_data_i.value = 0
    dut.bus_dircmd_i.value = 0

    dut.cache_ready_i.value = 0
    dut.snoop_valid_i.value = 0

    # reset pulse
    await RisingEdge(dut.clk_i)
    dut.rst_ni.value = 0
    await RisingEdge(dut.clk_i)
    dut.rst_ni.value = 1

    # its take very long to reset all the srams
    cycles_to_reset: int = 2 * 512
    for _ in range(cycles_to_reset):
        await RisingEdge(dut.clk_i)

    log.info("Reset complete")

    # keep the golden model in lockstep with the freshly-reset DUT: cocotb
    # runs every @cocotb.test() in this file against the same `cache`
    # instance, so without this, tests after the first would compare the
    # DUT against a golden cache that still remembers state from the last
    # test even though the DUT's SRAMs were just cleared.
    cache.flush_all()
    captured_dir_requests.clear()


async def wait_for_signal(dut, sig):
    for _ in range(TIMEOUT_CYCLES):
        await RisingEdge(dut.clk_i)
        if sig.value == 1:
            return
    raise TimeoutError(f"{sig._name} never asserted")


# ─────────────────────────────────────────────────────────────────────────────
# Test transaction
# ─────────────────────────────────────────────────────────────────────────────

async def one_read(dut, addr: int):

    if addr > 512:
        raise Exception("addr out of range")

    # ── CPU request ─────────────────────────────────────────────
    await FallingEdge(dut.clk_i)
    dut.mem_valid_i.value = 1
    dut.mem_instr_i.value = 0
    dut.mem_addr_i.value = addr
    dut.mem_wdata_i.value = 0
    dut.mem_wstrb_i.value = 0
    dut.cache_ready_i.value = 1

    # golden model
    golden_resp = await cache.axi_handler_for_core(
        axi_request(
            mem_valid=True,
            mem_ready=False,
            mem_instr=False,
            mem_addr=addr,
            mem_wdata=0,
            mem_wstrb=0,
            mem_rdata=0,
        )
    )


    # ── Wait for DUT request to directory ───────────────────────
    # if need a response give it a respone
    assert captured_dir_requests, "No directory request captured"
    dir_req: axi_and_coherence_request = captured_dir_requests[0]


    if dir_req.coherence_cmd == CoherenceCmd.BUS_RD or dir_req.coherence_cmd == CoherenceCmd.BUS_RDX or dir_req.coherence_cmd == CoherenceCmd.BUS_UPGR:

        await wait_for_signal(dut, dut.cache_valid_o)
        dut.cache_ready_i.value = 0
        dut_cmd = int(dut.cache_cmd_o.value)

        assert int(dir_req.coherence_cmd) == dut_cmd, (
            f"Expected {dir_req.coherence_cmd}, got {dut_cmd} at addr {addr}"
        )

        # ── Respond from directory ───────────────────────────────────
        dut.bus_valid_i.value = 1
        dut.bus_data_i.value = addr
        dut.bus_dircmd_i.value = coherence_cmd_to_acks(dir_req.coherence_cmd)

        # wait for DUT to accept response
        await wait_for_signal(dut, dut.bus_ready_o)
        dut.bus_valid_i.value = 0


    if dir_req.coherence_cmd == CoherenceCmd.EVICT_DIRTY or dir_req.coherence_cmd == CoherenceCmd.EVICT_CLEAN:

        # Let the evict go through
        await wait_for_signal(dut, dut.cache_valid_o)
        dut.cache_ready_i.value = 0
        dut_cmd = int(dut.cache_cmd_o.value)
        assert int(dir_req.coherence_cmd) == dut_cmd, (
            f"Expected {dir_req.coherence_cmd}, got {dut_cmd} at addr {addr}"
        )


        # Run the bus cmd
        await FallingEdge(dut.clk_i)
        await FallingEdge(dut.clk_i)
        dut.cache_ready_i.value = 1
        await wait_for_signal(dut, dut.cache_valid_o)
        dut.cache_ready_i.value = 1

        dir_req: axi_and_coherence_request = captured_dir_requests[1]
        dut_cmd = int(dut.cache_cmd_o.value)
        assert int(dir_req.coherence_cmd) == dut_cmd, (
            f"Expected {dir_req.coherence_cmd}, got {dut_cmd} at addr {addr}"
        )

        # ── Respond from directory ───────────────────────────────────
        dut.bus_valid_i.value = 1
        dut.bus_data_i.value = addr
        dut.bus_dircmd_i.value = coherence_cmd_to_acks(dir_req.coherence_cmd)

        # wait for DUT to accept response
        await wait_for_signal(dut, dut.bus_ready_o)
        dut.bus_valid_i.value = 0
        captured_dir_requests.pop()

    if dir_req.coherence_cmd == CoherenceCmd.NULL:
        pass

    # ── Wait for completion ─────────────────────────────────────
    await wait_for_signal(dut, dut.mem_ready_o)
    assert int(dut.mem_rdata_o.value) == golden_resp.mem_rdata
    dut.mem_valid_i.value = 0
    captured_dir_requests.clear()
    dut._log.info(f"Read complete: data=%#010x", dut.mem_rdata_o.value)


async def one_write(dut, addr, data, wstrb):

    if addr > 512:
        raise Exception("addr out of range")


    # ── CPU request ─────────────────────────────────────────────
    await FallingEdge(dut.clk_i)
    dut.mem_valid_i.value = 1
    dut.mem_instr_i.value = 0
    dut.mem_addr_i.value  = addr
    dut.mem_wdata_i.value = data
    dut.mem_wstrb_i.value = wstrb
    dut.cache_ready_i.value = 1

    # ── Golden model ─────────────────────────────────────────────
    golden_resp = await cache.axi_handler_for_core(
        axi_request(
            mem_valid=True,
            mem_ready=False,
            mem_instr=False,
            mem_addr=addr,
            mem_wdata=data,
            mem_wstrb=wstrb,
            mem_rdata=0,
        )
    )

    # ── Wait for DUT request to directory ───────────────────────
    # A write can require 0, 1, or 2 directory transactions:
    #   0: write hit while MODIFIED (no coherence action)
    #   1: write hit while SHARED (BUS_UPGR), or write miss on an
    #      already-invalid line (BUS_RDX)
    #   2: write miss on a *stale* tag (EVICT_CLEAN/EVICT_DIRTY, then
    #      BUS_RDX), same as one_read's tag-mismatch handling.
    assert captured_dir_requests, "No directory request captured for write"
    dir_req: axi_and_coherence_request = captured_dir_requests[0]

    if dir_req.coherence_cmd == CoherenceCmd.BUS_RD or dir_req.coherence_cmd == CoherenceCmd.BUS_RDX or dir_req.coherence_cmd == CoherenceCmd.BUS_UPGR:

        await wait_for_signal(dut, dut.cache_valid_o)
        dut.cache_ready_i.value = 0
        dut_cmd = int(dut.cache_cmd_o.value)

        assert int(dir_req.coherence_cmd) == dut_cmd, (
            f"Expected {dir_req.coherence_cmd}, got {dut_cmd} at addr {addr}"
        )

        # ── Respond from directory ───────────────────────────────────
        dut.bus_valid_i.value = 1
        dut.bus_data_i.value = addr
        dut.bus_dircmd_i.value = coherence_cmd_to_acks(dir_req.coherence_cmd)

        # wait for DUT to accept response
        await wait_for_signal(dut, dut.bus_ready_o)
        dut.bus_valid_i.value = 0


    if dir_req.coherence_cmd == CoherenceCmd.EVICT_DIRTY or dir_req.coherence_cmd == CoherenceCmd.EVICT_CLEAN:

        # Let the evict go through
        await wait_for_signal(dut, dut.cache_valid_o)
        dut.cache_ready_i.value = 0
        dut_cmd = int(dut.cache_cmd_o.value)
        assert int(dir_req.coherence_cmd) == dut_cmd, (
            f"Expected {dir_req.coherence_cmd}, got {dut_cmd} at addr {addr}"
        )


        # Run the bus cmd
        await FallingEdge(dut.clk_i)
        await FallingEdge(dut.clk_i)
        dut.cache_ready_i.value = 1
        await wait_for_signal(dut, dut.cache_valid_o)
        dut.cache_ready_i.value = 1

        assert len(captured_dir_requests) > 1, "No follow-up directory request captured after eviction"
        dir_req = captured_dir_requests[1]
        dut_cmd = int(dut.cache_cmd_o.value)
        assert int(dir_req.coherence_cmd) == dut_cmd, (
            f"Expected {dir_req.coherence_cmd}, got {dut_cmd} at addr {addr}"
        )

        # ── Respond from directory ───────────────────────────────────
        dut.bus_valid_i.value = 1
        dut.bus_data_i.value = addr
        dut.bus_dircmd_i.value = coherence_cmd_to_acks(dir_req.coherence_cmd)

        # wait for DUT to accept response
        await wait_for_signal(dut, dut.bus_ready_o)
        dut.bus_valid_i.value = 0
        captured_dir_requests.pop()

    if dir_req.coherence_cmd == CoherenceCmd.NULL:
        pass

    # ── Wait for completion ─────────────────────────────────────
    await wait_for_signal(dut, dut.mem_ready_o)
    dut.mem_valid_i.value = 0
    captured_dir_requests.clear()

    log.info("Write transaction complete — addr=%#05x data=%#010x strb=%#x", addr, data, wstrb)


async def one_snoop(dut, addr: int, dircmd_1h: int):
    """
    Drive one directory -> cache snoop transaction and check the cache's
    response against the MSI snoop table (emulation.msi.on_snoop_event),
    which is used here as the oracle for whether a flush write-back is
    expected, what data it should carry, and what the line's next state
    should be. Keeps the golden model's line state in sync afterward so
    later one_read/one_write calls on this address predict correctly.
    """

    if addr > 512:
        raise Exception("addr out of range")

    line = cache._line(addr)
    event = SnoopEvent(dircmd_1h)
    tr = on_snoop_event(line.state, event)
    expected_flush_data = line.data if tr.flush else None

    dut.cache_ready_i.value = 1  # always accept outbound evict/ack traffic

    # ── Directory -> cache snoop request ─────────────────────────
    await FallingEdge(dut.clk_i)
    dut.snoop_addr_i.value = addr
    dut.snoop_dircmd_i.value = dircmd_1h
    dut.snoop_valid_i.value = 1

    await wait_for_signal(dut, dut.snoop_ready_o)
    dut.snoop_valid_i.value = 0

    # ── Flush write-back (only if evicting dirty data) ───────────
    if expected_flush_data is not None:
        await wait_for_signal(dut, dut.cache_valid_o)
        dut_cmd = int(dut.cache_cmd_o.value)
        assert dut_cmd == int(CoherenceCmd.EVICT_DIRTY), (
            f"Expected flush write-back at addr {addr}, got cmd {dut_cmd}"
        )
        assert int(dut.cache_data_o.value) == expected_flush_data, (
            f"Flushed data mismatch at addr {addr}: expected {expected_flush_data:#010x}, "
            f"got {int(dut.cache_data_o.value):#010x}"
        )
        await FallingEdge(dut.clk_i)

    # ── Snoop ack back to directory ───────────────────────────────
    await wait_for_signal(dut, dut.cache_valid_o)
    dut_cmd = int(dut.cache_cmd_o.value)
    expected_ack = SNOOP_1H_TO_ACK[dircmd_1h]
    assert dut_cmd == expected_ack, (
        f"Expected snoop ack {expected_ack:#09b}, got {dut_cmd:#09b} at addr {addr}"
    )

    # keep the golden model's state in sync with the real transition
    line.state = tr.next_state

    dut._log.info(
        f"Snoop complete: addr={addr:#05x} event={event.name} "
        f"next_state={tr.next_state.name} flush={tr.flush}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Read/write all addrs
# ─────────────────────────────────────────────────────────────────────────────
async def test_read(dut):
    for i in range(512):
      await one_read(dut, i)


async def test_write(dut):
    for i in range(512):
      await one_write(dut, i, i, 0xF)


# ─────────────────────────────────────────────────────────────────────────────
# Coherence (MSI snoop) scenarios
# ─────────────────────────────────────────────────────────────────────────────
async def test_coherence(dut):

    # ── SHARED + BUS_RD snoop: stays SHARED, no flush ────────────
    await one_read(dut, 5)
    await one_snoop(dut, 5, SNOOP_BUS_RD_1H)
    await one_read(dut, 5)  # still a hit: a read-only snoop can't evict us

    # ── SHARED + BUS_RDX snoop: invalidated, no flush ────────────
    await one_read(dut, 6)
    await one_snoop(dut, 6, SNOOP_BUS_RDX_1H)
    await one_read(dut, 6)  # must miss again and refetch

    # ── SHARED + BUS_UPGR snoop: invalidated, no flush ───────────
    await one_read(dut, 9)
    await one_snoop(dut, 9, SNOOP_BUS_UPGR_1H)
    await one_read(dut, 9)  # must miss again and refetch

    # ── MODIFIED + BUS_RD snoop: flush + downgrade to SHARED ─────
    await one_write(dut, 7, 0xDEADBEEF, 0xF)
    await one_snoop(dut, 7, SNOOP_BUS_RD_1H)
    await one_read(dut, 7)  # hit: must still see the dirty data we wrote

    # ── MODIFIED + BUS_RDX snoop: flush + invalidate ─────────────
    await one_write(dut, 8, 0xCAFEBABE, 0xF)
    await one_snoop(dut, 8, SNOOP_BUS_RDX_1H)
    await one_read(dut, 8)  # must miss again (line was invalidated)


# ─────────────────────────────────────────────────────────────────────────────
# Test entry
# ─────────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def test_simple(dut):
    await start_clock(dut)
    await reset_dut(dut)
    await test_read(dut)
    await one_write(dut, 0, 1, 15)


@cocotb.test()
async def test_write_all(dut):
    await start_clock(dut)
    await reset_dut(dut)
    await test_write(dut)


@cocotb.test()
async def test_coherence_snoop(dut):
    await start_clock(dut)
    await reset_dut(dut)
    await test_coherence(dut)


# ════════════════════════════════════════════════════════════════════════════
#  Runner
# ════════════════════════════════════════════════════════════════════════════

def cache_controller_test():
    proj_path = Path(__file__).resolve().parent
    pdk_root  = Path("../gf180mcu")

    sources =[
        proj_path / "../src/cache_controller/apply_wstrb.sv",
        proj_path / "../src/cache_controller/on_processor_event_state_machine.sv",
        proj_path / "../src/cache_controller/on_snoop_event_state_machine.sv",
        proj_path / "../src/cache_controller/cache_controller.sv",
        proj_path / "../src/cache_controller/outbound_arbiter.sv",
        proj_path / "../src/mem_ctrl/mem128x4.sv",
        proj_path / "../src/mem_ctrl/mem128x32.sv",
        proj_path / "../src/mem_ctrl/cache_mem.sv",
        proj_path / "../src/mem_ctrl/two_port_cache_mem.sv",
        pdk_root / "gf180mcuD/libs.ref/gf180mcu_fd_ip_sram/verilog/gf180mcu_fd_ip_sram__sram512x8m8wm1.v",
        pdk_root / "gf180mcuD/libs.ref/gf180mcu_fd_ip_sram/verilog/gf180mcu_fd_ip_sram__sram64x8m8wm1.v",
    ]

    build_args = []

    if sim == "verilator":
        build_args = [
            "--timing",
            "--trace",
            "--trace-fst",
            "--trace-structs",
        ]
    else:
        build_args = [
            "-Wall",
            "-Winfloop"
        ]
    runner = get_runner(sim)

    runner.build(
        sources=sources,
        hdl_toplevel="cache_controller",
        always=True,
        build_args=build_args,
        waves=True,
    )

    runner.test(
        hdl_toplevel="cache_controller",
        test_module="cache_controller_tb",
        waves=True,
    )


if __name__ == "__main__":
    cache_controller_test()
