import os
import random
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
from emulation.msi import CoherenceCmd, SnoopEvent, MSIState, on_snoop_event
from emulation.config import MAIN_MEM_SIZE_IN_WORDS, INDEX_WIDTH

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

    dut.flush_valid_i.value = 0
    dut.flush_addr_i.value = 0

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

    if addr >= MAIN_MEM_SIZE_IN_WORDS:
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
        # Regression guard for the (tag << INDEX_WIDTH) | index eviction
        # address bug: dir_req.mem_addr is the golden model's reconstructed
        # evicted-line address (built in cache._handle_tag_mismatch), which
        # must match evict_addr in the RTL exactly.
        assert int(dut.cache_addr_o.value) == dir_req.mem_addr, (
            f"Evicted address mismatch at addr {addr}: expected "
            f"{dir_req.mem_addr:#05x}, got {int(dut.cache_addr_o.value):#05x}"
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

    if addr >= MAIN_MEM_SIZE_IN_WORDS:
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
        # Regression guard for the (tag << INDEX_WIDTH) | index eviction
        # address bug: dir_req.mem_addr is the golden model's reconstructed
        # evicted-line address (built in cache._handle_tag_mismatch), which
        # must match evict_addr in the RTL exactly.
        assert int(dut.cache_addr_o.value) == dir_req.mem_addr, (
            f"Evicted address mismatch at addr {addr}: expected "
            f"{dir_req.mem_addr:#05x}, got {int(dut.cache_addr_o.value):#05x}"
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

    if addr >= MAIN_MEM_SIZE_IN_WORDS:
        raise Exception("addr out of range")

    line = cache._line(addr)
    event = SnoopEvent(dircmd_1h)

    # Ghost snoop: this index is currently aliased to a different tag, so
    # there's nothing here to invalidate/flush for the requested address.
    # Mirrors the RTL's tag check in SNP_FETCH_LINE_RESP (and
    # emulation.cache._handle_snoop) -- without it we'd wrongly apply the
    # MSI transition to whatever unrelated line happens to share the index.
    is_ghost = line.tag != cache._tag(addr)
    if is_ghost:
        expected_next_state = line.state
        expected_flush = False
    else:
        tr = on_snoop_event(line.state, event)
        expected_next_state = tr.next_state
        expected_flush = tr.flush
    expected_flush_data = line.data if expected_flush else None

    dut.cache_ready_i.value = 1  # always accept outbound ack traffic

    # ── Directory -> cache snoop request ─────────────────────────
    await FallingEdge(dut.clk_i)
    dut.snoop_addr_i.value = addr
    dut.snoop_dircmd_i.value = dircmd_1h
    dut.snoop_valid_i.value = 1

    await wait_for_signal(dut, dut.snoop_ready_o)
    dut.snoop_valid_i.value = 0

    # ── Snoop ack back to directory (flush data, if any, rides on the
    # ack itself -- there's no separate evict transaction; matches the
    # SnoopXXX_Ack wire encoding and directory._send_snoop, which reads
    # the flushed data straight out of the snoop response) ───────────
    await wait_for_signal(dut, dut.cache_valid_o)
    dut_cmd = int(dut.cache_cmd_o.value)
    expected_ack = SNOOP_1H_TO_ACK[dircmd_1h]
    assert dut_cmd == expected_ack, (
        f"Expected snoop ack {expected_ack:#09b}, got {dut_cmd:#09b} at addr {addr}"
    )
    expected_ack_data = expected_flush_data if expected_flush_data is not None else 0
    assert int(dut.cache_data_o.value) == expected_ack_data, (
        f"Snoop ack data mismatch at addr {addr}: expected {expected_ack_data:#010x}, "
        f"got {int(dut.cache_data_o.value):#010x}"
    )

    # keep the golden model's state in sync with the real transition
    line.state = expected_next_state

    dut._log.info(
        f"Snoop complete: addr={addr:#05x} event={event.name} "
        f"next_state={expected_next_state.name} flush={expected_flush} ghost={is_ghost}"
    )


async def one_flush(dut, addr: int):
    """
    Drive one CPU-initiated flush and check the cache's response:
    - If this cache doesn't actually hold the line (tag mismatch or
      already INVALID), it's a no-op: no outbound bus transaction, just
      an ack.
    - Otherwise it must evict (EVICT_CLEAN if SHARED, EVICT_DIRTY with
      the line's data if MODIFIED) using the same reconstructed
      (tag << INDEX_WIDTH) | index address as a tag-miss eviction, then
      invalidate the line.
    """

    if addr >= MAIN_MEM_SIZE_IN_WORDS:
        raise Exception("addr out of range")

    line = cache._line(addr)
    is_present = (line.tag == cache._tag(addr)) and (line.state != MSIState.INVALID)

    if is_present:
        expected_evict_cmd = (
            CoherenceCmd.EVICT_DIRTY if line.state == MSIState.MODIFIED
            else CoherenceCmd.EVICT_CLEAN
        )
        expected_evict_data = line.data
        expected_evict_addr = (line.tag << INDEX_WIDTH) | line.index

    dut.cache_ready_i.value = 1

    await FallingEdge(dut.clk_i)
    dut.flush_addr_i.value = addr
    dut.flush_valid_i.value = 1

    if is_present:
        await wait_for_signal(dut, dut.cache_valid_o)
        dut_cmd = int(dut.cache_cmd_o.value)
        assert dut_cmd == int(expected_evict_cmd), (
            f"Expected flush evict {expected_evict_cmd}, got {dut_cmd} at addr {addr}"
        )
        assert int(dut.cache_addr_o.value) == expected_evict_addr, (
            f"Flush evict address mismatch at addr {addr}: expected "
            f"{expected_evict_addr:#05x}, got {int(dut.cache_addr_o.value):#05x}"
        )
        assert int(dut.cache_data_o.value) == expected_evict_data, (
            f"Flush evict data mismatch at addr {addr}: expected "
            f"{expected_evict_data:#010x}, got {int(dut.cache_data_o.value):#010x}"
        )
        # evicts have no directory ack in this system -- nothing further
        # to drive before the flush completes.

    await wait_for_signal(dut, dut.flush_ready_o)
    dut.flush_valid_i.value = 0

    # keep the golden model's state in sync with the real transition --
    # a ghost flush (tag mismatch) is a no-op and must NOT touch the
    # line, since _line() returns the same aliased object for any
    # address sharing this index.
    if is_present:
        line.state = MSIState.INVALID

    dut._log.info(f"Flush complete: addr={addr:#05x} evicted={is_present}")


# ─────────────────────────────────────────────────────────────────────────────
# Concurrent CPU/snoop driving
#
# one_read/one_write/one_snoop above strictly serialize CPU and snoop
# traffic: cache_ready_i and bus_valid_i are toggled by whichever helper
# is running, so two of them can never be in flight at once. But in the
# RTL, the CPU FSM and snoop FSM are independent state machines that
# share the two-port cache_mem (arbitrated by two_port_cache_mem.sv) and
# the outbound cache->directory bus (arbitrated by outbound_arbiter.sv)
# -- real hardware allows a CPU request and a directory snoop to be
# in flight at the same time, and that arbitration path has never been
# exercised by this testbench. The helpers below let a CPU transaction
# and a snoop run as genuinely concurrent coroutines.
# ─────────────────────────────────────────────────────────────────────────────

async def outbound_bus_director(dut):
    """
    Background task that owns the shared outbound bus (cache_valid_o/
    cache_cmd_o/cache_addr_o/cache_data_o/cache_ready_i) and the
    directory->CPU response bus (bus_valid_i/bus_data_i/bus_dircmd_i).
    Both the CPU FSM and the snoop FSM route through the same outbound
    arbiter (see outbound_arbiter.sv m0/m1), so a concurrently-running
    CPU transaction and snoop transaction must not each try to drive
    cache_ready_i/bus_valid_i themselves -- this task drains that shared
    bus for both of them.

    Response contract mirrors dummy_directory_handler: BUS_RD/BUS_RDX/
    BUS_UPGR (CPU-only commands -- the snoop FSM never issues these) are
    ack'd with mem_rdata = addr. Evictions and snoop acks need no reply,
    just draining via cache_ready_i.
    """
    dut.cache_ready_i.value = 1
    ack_for_cmd = {
        CMD_BUS_RD: BUSRD_ACK,
        CMD_BUS_RDX: BUSRDX_ACK,
        CMD_BUS_UPGR: BUSUPGR_ACK,
    }

    while True:
        await RisingEdge(dut.clk_i)

        if dut.cache_valid_o.value != 1:
            continue

        cmd = int(dut.cache_cmd_o.value)
        if cmd not in ack_for_cmd:
            # Evictions (CPU tag-miss or snoop flush) and snoop acks:
            # no reply needed, cache_ready_i=1 above already drained it.
            continue

        addr = int(dut.cache_addr_o.value)
        await FallingEdge(dut.clk_i)
        dut.bus_valid_i.value = 1
        dut.bus_data_i.value = addr
        dut.bus_dircmd_i.value = ack_for_cmd[cmd]
        await wait_for_signal(dut, dut.bus_ready_o)
        dut.bus_valid_i.value = 0


async def cpu_op_concurrent(dut, addr: int, wdata: int = 0, wstrb: int = 0):
    """
    Drive one CPU read (wstrb=0) or write, assuming an
    outbound_bus_director task is already running. Safe to run
    concurrently with snoop_op_concurrent() on a different address.
    """
    if addr >= MAIN_MEM_SIZE_IN_WORDS:
        raise Exception("addr out of range")

    await FallingEdge(dut.clk_i)
    dut.mem_valid_i.value = 1
    dut.mem_instr_i.value = 0
    dut.mem_addr_i.value = addr
    dut.mem_wdata_i.value = wdata
    dut.mem_wstrb_i.value = wstrb

    golden_resp = await cache.axi_handler_for_core(
        axi_request(
            mem_valid=True,
            mem_ready=False,
            mem_instr=False,
            mem_addr=addr,
            mem_wdata=wdata,
            mem_wstrb=wstrb,
            mem_rdata=0,
        )
    )

    await wait_for_signal(dut, dut.mem_ready_o)
    if wstrb == 0:
        assert int(dut.mem_rdata_o.value) == golden_resp.mem_rdata, (
            f"Concurrent CPU read mismatch at addr {addr}: expected "
            f"{golden_resp.mem_rdata:#010x}, got {int(dut.mem_rdata_o.value):#010x}"
        )
    dut.mem_valid_i.value = 0
    captured_dir_requests.clear()


async def snoop_op_concurrent(dut, addr: int, dircmd_1h: int):
    """
    Drive one directory->cache snoop, assuming an outbound_bus_director
    task is already running. Safe to run concurrently with
    cpu_op_concurrent() on a different address. Same ghost-snoop (tag
    mismatch) handling as one_snoop().
    """
    if addr >= MAIN_MEM_SIZE_IN_WORDS:
        raise Exception("addr out of range")

    line = cache._line(addr)
    is_ghost = line.tag != cache._tag(addr)
    if is_ghost:
        expected_next_state = line.state
    else:
        tr = on_snoop_event(line.state, SnoopEvent(dircmd_1h))
        expected_next_state = tr.next_state

    await FallingEdge(dut.clk_i)
    dut.snoop_addr_i.value = addr
    dut.snoop_dircmd_i.value = dircmd_1h
    dut.snoop_valid_i.value = 1

    await wait_for_signal(dut, dut.snoop_ready_o)
    dut.snoop_valid_i.value = 0

    # Wait for this snoop's ack to actually drain through the shared
    # outbound bus before declaring it done and updating the golden
    # model -- the director consumes it, but a concurrent CPU eviction
    # could be granted the bus first, so poll rather than assume.
    expected_ack = SNOOP_1H_TO_ACK[dircmd_1h]
    for _ in range(TIMEOUT_CYCLES):
        await RisingEdge(dut.clk_i)
        if dut.cache_valid_o.value == 1 and int(dut.cache_cmd_o.value) == expected_ack:
            break
    else:
        raise TimeoutError(f"snoop ack for addr {addr} never observed on outbound bus")

    line.state = expected_next_state


# ─────────────────────────────────────────────────────────────────────────────
# Read/write all addrs
# ─────────────────────────────────────────────────────────────────────────────
async def test_read(dut):
    for i in range(MAIN_MEM_SIZE_IN_WORDS):
      await one_read(dut, i)


async def test_write(dut):
    for i in range(MAIN_MEM_SIZE_IN_WORDS):
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
# Ghost snoop (tag mismatch) edge cases
# ─────────────────────────────────────────────────────────────────────────────
async def test_ghost_snoop(dut):

    # ── Snoop a line that has never been touched ──────────────────
    # Straight after reset the line is INVALID with a default tag, so
    # this should just ack with no flush regardless of which path the
    # RTL takes to get there.
    await one_snoop(dut, 100, SNOOP_BUS_RDX_1H)
    await one_read(dut, 100)  # must still miss cleanly and fetch fresh data

    # ── Real aliasing: snoop a *different* tag at an occupied index ──
    # Index 20 holds tag 0 (addr 20) as a dirty MODIFIED line. Addr 148
    # maps to the same index (148 % 128 == 20) but tag 1 -- this cache
    # doesn't actually have that line, so the snoop must be a no-op
    # ghost ack: no flush, and critically, must NOT disturb the real
    # line's state/data at that index.
    await one_write(dut, 20, 0xAAAA0000, 0xF)
    await one_snoop(dut, 148, SNOOP_BUS_RDX_1H)

    # The real line at index 20 must still be MODIFIED with our dirty
    # data -- a hit, unaffected by the aliased snoop.
    await one_read(dut, 20)

    # And addr 148 itself, now genuinely fetched for the first time,
    # must miss and pull its own fresh data (not 20's stale data).
    await one_read(dut, 148)

    # ── Ghost snoop against a SHARED (not just MODIFIED) alias ──────
    await one_read(dut, 21)          # index 21, tag 0, now SHARED
    await one_snoop(dut, 149, SNOOP_BUS_RD_1H)   # index 21, tag 1: ghost
    await one_read(dut, 21)          # still SHARED: must remain a hit


# ─────────────────────────────────────────────────────────────────────────────
# CPU-initiated flush (0x8000_0020 MMIO trigger, sp_addr_handler.sv)
# ─────────────────────────────────────────────────────────────────────────────
async def test_flush(dut):

    # ── Flush a MODIFIED (dirty) line: must evict-dirty, then invalidate ──
    await one_write(dut, 40, 0xDEADBEEF, 0xF)
    await one_flush(dut, 40)
    await one_read(dut, 40)  # must miss again: fresh fetch, not a hit

    # ── Flush a SHARED (clean) line: must evict-clean, then invalidate ──
    await one_read(dut, 41)
    await one_flush(dut, 41)
    await one_read(dut, 41)  # must miss again

    # ── Flush a line that was never touched: no-op, no bus traffic ──
    await one_flush(dut, 42)
    await one_read(dut, 42)  # first touch: still a normal miss

    # ── Flush an address that aliases an occupied index by tag ──
    # Index 20 holds tag 0 (addr 20) as dirty MODIFIED. Addr 148 maps to
    # the same index (148 % 128 == 20) but tag 1 -- this cache doesn't
    # actually hold that line, so the flush must be a no-op ghost: no
    # eviction, and critically, must not disturb the real line at index 20.
    await one_write(dut, 20, 0xAAAA0000, 0xF)
    await one_flush(dut, 148)
    await one_read(dut, 20)   # still MODIFIED with our dirty data: a hit
    await one_read(dut, 148)  # its own first touch: a normal miss


# ─────────────────────────────────────────────────────────────────────────────
# Real CPU/snoop contention (genuinely concurrent coroutines)
# ─────────────────────────────────────────────────────────────────────────────
async def test_snoop_processor_contention(dut):

    # Prime index 7 to MODIFIED (dirty) sequentially, before the shared
    # bus is handed over to the director.
    await one_write(dut, 7, 0xDEADBEEF, 0xF)

    director = cocotb.start_soon(outbound_bus_director(dut))

    # CPU read-miss on a fresh, different-index line racing a snoop
    # that flushes+downgrades index 7 -- both need the outbound bus and
    # the two-port cache_mem at the same time.
    cpu_task = cocotb.start_soon(cpu_op_concurrent(dut, 50))
    snoop_task = cocotb.start_soon(snoop_op_concurrent(dut, 7, SNOOP_BUS_RD_1H))
    await cpu_task
    await snoop_task
    director.cancel()

    await one_read(dut, 50)  # now a hit with its fetched data
    await one_read(dut, 7)   # downgraded to SHARED, still the dirty data

    # Roles swapped: CPU write-miss racing a snoop that invalidates a
    # different, currently-SHARED line.
    await one_read(dut, 30)  # bring index 30 to SHARED

    director = cocotb.start_soon(outbound_bus_director(dut))
    cpu_task = cocotb.start_soon(cpu_op_concurrent(dut, 60, 0x12345678, 0xF))
    snoop_task = cocotb.start_soon(snoop_op_concurrent(dut, 30, SNOOP_BUS_RDX_1H))
    await cpu_task
    await snoop_task
    director.cancel()

    await one_read(dut, 60)  # write landed despite the concurrent snoop
    await one_read(dut, 30)  # invalidated: must miss and refetch


async def test_snoop_processor_stress(dut):
    """
    Randomized concurrent CPU + snoop stress: many rounds, each pairing
    a random CPU read/write with a random snoop command on a different
    index (indices split into disjoint halves so a round's pair can
    never alias each other), checking for hangs/deadlock/data
    corruption in the shared two-port cache_mem / outbound arbiters
    under repeated contention.
    """
    director = cocotb.start_soon(outbound_bus_director(dut))
    snoop_cmds = [SNOOP_BUS_RD_1H, SNOOP_BUS_RDX_1H, SNOOP_BUS_UPGR_1H]

    for _ in range(40):
        cpu_index = random.randint(0, 63)
        snoop_index = random.randint(64, 127)
        cpu_addr = cpu_index + 128 * random.randint(0, 15)
        snoop_addr = snoop_index + 128 * random.randint(0, 15)

        is_write = random.random() < 0.5
        wdata = random.randint(0, 0xFFFFFFFF)
        wstrb = 0xF if is_write else 0

        cpu_task = cocotb.start_soon(cpu_op_concurrent(dut, cpu_addr, wdata, wstrb))
        snoop_task = cocotb.start_soon(
            snoop_op_concurrent(dut, snoop_addr, random.choice(snoop_cmds))
        )
        await cpu_task
        await snoop_task

    director.cancel()


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


@cocotb.test()
async def test_coherence_ghost_snoop(dut):
    await start_clock(dut)
    await reset_dut(dut)
    await test_ghost_snoop(dut)


@cocotb.test()
async def test_flush_line(dut):
    await start_clock(dut)
    await reset_dut(dut)
    await test_flush(dut)


@cocotb.test()
async def test_coherence_contention(dut):
    await start_clock(dut)
    await reset_dut(dut)
    await test_snoop_processor_contention(dut)


@cocotb.test()
async def test_coherence_contention_stress(dut):
    await start_clock(dut)
    await reset_dut(dut)
    await test_snoop_processor_stress(dut)


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
        proj_path / "../src/mem_ctrl/mem128x6.sv",
        proj_path / "../src/mem_ctrl/mem128x32.sv",
        proj_path / "../src/mem_ctrl/cache_mem.sv",
        proj_path / "../src/mem_ctrl/two_port_cache_mem.sv",
        pdk_root / "gf180mcuD/libs.ref/gf180mcu_fd_ip_sram/verilog/gf180mcu_fd_ip_sram__sram512x8m8wm1.v",
        pdk_root / "gf180mcuD/libs.ref/gf180mcu_fd_ip_sram/verilog/gf180mcu_fd_ip_sram__sram128x8m8wm1.v",
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
