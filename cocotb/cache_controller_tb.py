import os
import random
import logging
from pathlib import Path

import cocotb
from cocotb.clock    import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer, ClockCycles, with_timeout
from cocotb_tools.runner import get_runner

# ─── Sim / logging setup ────────────────────────────────────────────────────
sim = os.getenv("SIM", "icarus")
log = logging.getLogger("cache_tb")
logging.basicConfig(level=logging.INFO)

TIMEOUT_CYCLES = 200   # cycles to wait for any single handshake

# ─── MSI coherence command encodings (must mirror cache_controller.sv) ───────
# Outbound (cache → directory)
CMD_BUS_RD         = 0b000000001
CMD_BUS_RDX        = 0b000000010
CMD_BUS_UPGR       = 0b000000100
CMD_EVICT_CLEAN    = 0b000001000
CMD_EVICT_DIRTY    = 0b000010000
# Snoop acks (cache → directory)
CMD_SNOOP_RD_ACK   = 0b000100000
CMD_SNOOP_RDX_ACK  = 0b001000000
CMD_SNOOP_UPGR_ACK = 0b010000000
# Inbound acks (directory → cache)  bus_dircmd_i
BUSRD_ACK   = 0b001
BUSRDX_ACK  = 0b010
BUSUPGR_ACK = 0b100
# Snoop commands  snoop_dircmd_i
SNOOP_RD   = 0b001
SNOOP_RDX  = 0b010
SNOOP_UPGR = 0b100
# Cache-line states
S_INVALID  = 0b00
S_SHARED   = 0b01
S_MODIFIED = 0b10


# ════════════════════════════════════════════════════════════════════════════
#  Low-level helpers
# ════════════════════════════════════════════════════════════════════════════

async def start_clock(dut, freq_mhz: int = 50):
    clock = Clock(dut.clk_i, 1_000 / freq_mhz, unit="ns")
    cocotb.start_soon(clock.start())


async def reset_dut(dut, duration_ns: int = 100):
    """Assert active-low reset and hold all inputs idle."""
    dut.rst_ni.value         = 0
    dut.mem_valid_i.value    = 0
    dut.mem_instr_i.value    = 0
    dut.mem_addr_i.value     = 0
    dut.mem_wdata_i.value    = 0
    dut.mem_wstrb_i.value    = 0
    dut.cache_ready_i.value  = 0
    dut.bus_valid_i.value    = 0
    dut.bus_data_i.value     = 0
    dut.bus_dircmd_i.value   = 0
    dut.snoop_valid_i.value  = 0
    dut.snoop_addr_i.value   = 0
    dut.snoop_dircmd_i.value = 0
    await Timer(duration_ns, unit="ns")
    await FallingEdge(dut.clk_i)
    dut.rst_ni.value = 1
    await FallingEdge(dut.clk_i)

    # The cache_mem initialises 128 lines × 4 cycles × 2 ports = 1024 cycles
    reset_time = 128 * 4 * 2
    for _ in range(reset_time):
        await FallingEdge(dut.clk_i)

    log.info("Reset released")


# ─── Processor request helper ────────────────────────────────────────────────

async def cpu_request(dut, addr: int, wdata: int = 0, wstrb: int = 0):
    """
    Drive a processor transaction onto the mem_* interface.
    wstrb == 0  → read
    wstrb != 0  → write
    Returns rdata (meaningful only for reads).
    """
    dut.mem_valid_i.value = 1
    dut.mem_addr_i.value  = addr
    dut.mem_wdata_i.value = wdata
    dut.mem_wstrb_i.value = wstrb
    dut.mem_instr_i.value = 0

    # Wait for mem_ready_o
    for _ in range(TIMEOUT_CYCLES):
        await RisingEdge(dut.clk_i)
        if dut.mem_ready_o.value == 1:
            rdata = int(dut.mem_rdata_o.value)
            dut.mem_valid_i.value = 0
            return rdata
    raise TimeoutError(f"cpu_request timed out: addr=0x{addr:08x}")


# ─── Directory response helpers ──────────────────────────────────────────────

async def wait_for_cache_valid(dut):
    """
    Wait until the cache issues an outbound coherence command (cache_valid_o).
    Returns (addr, data, cmd).
    """
    for _ in range(TIMEOUT_CYCLES):
        await RisingEdge(dut.clk_i)
        if dut.cache_valid_o.value == 1:
            return (
                int(dut.cache_addr_o.value),
                int(dut.cache_data_o.value),
                int(dut.cache_cmd_o.value),
            )
    raise TimeoutError("Timed out waiting for cache_valid_o")


async def ack_cache_cmd(dut):
    """Single-cycle ready pulse to acknowledge an outbound cache command."""
    dut.cache_ready_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.cache_ready_i.value = 0


async def send_bus_response(dut, dircmd: int, data: int = 0):
    """
    Inject one bus_* inbound response from the directory.
    Waits until the cache asserts bus_ready_o to complete the handshake.
    """
    dut.bus_valid_i.value  = 1
    dut.bus_dircmd_i.value = dircmd
    dut.bus_data_i.value   = data

    for _ in range(TIMEOUT_CYCLES):
        await RisingEdge(dut.clk_i)
        if dut.bus_ready_o.value == 1:
            dut.bus_valid_i.value  = 0
            dut.bus_dircmd_i.value = 0
            dut.bus_data_i.value   = 0
            return
    raise TimeoutError("Timed out waiting for bus_ready_o")


# ─── Snoop helpers ───────────────────────────────────────────────────────────

async def send_snoop(dut, addr: int, dircmd: int):
    """
    Present one snoop request to the cache.
    Waits for snoop_ready_o (acceptance) then for the cache to issue its ack
    command on the outbound bus and accepts it.
    Returns (snoop_ack_cmd, snoop_ack_addr).
    """
    dut.snoop_valid_i.value  = 1
    dut.snoop_addr_i.value   = addr
    dut.snoop_dircmd_i.value = dircmd

    # Wait for snoop_ready_o (cache accepted the snoop)
    for _ in range(TIMEOUT_CYCLES):
        await RisingEdge(dut.clk_i)
        if dut.snoop_ready_o.value == 1:
            dut.snoop_valid_i.value  = 0
            dut.snoop_dircmd_i.value = 0
            break
    else:
        raise TimeoutError(f"Timed out waiting for snoop_ready_o: addr=0x{addr:08x}")

    # Wait for the cache to issue the snoop ack on the outbound bus
    ack_addr, _, ack_cmd = await wait_for_cache_valid(dut)
    await ack_cache_cmd(dut)
    return ack_cmd, ack_addr
y_i. When cache_ready_i is asserted, cache_valid_o should still be 1 if the master is still

# ─── Full transaction wrappers ───────────────────────────────────────────────

async def do_read_miss(dut, addr: int, fill_data: int):
    """
    Full read-miss flow:
      1. CPU issues read request → cache sends BusRD
      2. Testbench accepts BusRD and injects BUSRD_ACK with fill_data
      3. Returns the value the CPU received
    """
    # Start CPU request concurrently
    read_task = cocotb.start_soon(cpu_request(dut, addr, wstrb=0))

    # Wait for outbound BusRD
    c_addr, _, c_cmd = await wait_for_cache_valid(dut)
    assert c_cmd == CMD_BUS_RD,   f"Expected BusRD (0x{CMD_BUS_RD:03x}), got 0x{c_cmd:03x}"
    assert c_addr == addr,        f"BusRD addr mismatch: 0x{c_addr:08x} vs 0x{addr:08x}"
    await ack_cache_cmd(dut)

    # Inject bus response with data
    await send_bus_response(dut, BUSRD_ACK, fill_data)

    # Collect CPU result
    rdata = await read_task
    return rdata


async def do_write_miss(dut, addr: int, wdata: int, wstrb: int = 0xF,
                        existing_data: int = 0):
    """
    Full write-miss flow (line is Invalid):
      1. CPU issues write → cache sends BusRDX
      2. Testbench accepts BusRDX and injects BUSRDX_ACK
      3. Returns when the CPU completes (mem_ready_o)
    """
    write_task = cocotb.start_soon(cpu_request(dut, addr, wdata, wstrb))

    c_addr, _, c_cmd = await wait_for_cache_valid(dut)
    assert c_cmd == CMD_BUS_RDX,  f"Expected BusRDX (0x{CMD_BUS_RDX:03x}), got 0x{c_cmd:03x}"
    assert c_addr == addr,        f"BusRDX addr mismatch"
    await ack_cache_cmd(dut)

    await send_bus_response(dut, BUSRDX_ACK, existing_data)

    await write_task  # completes when mem_ready_o pulses


async def do_write_upgrade(dut, addr: int, wdata: int, wstrb: int = 0xF):
    """
    Write-upgrade flow (line is Shared):
      1. CPU issues write → cache sends BusUPGR
      2. Testbench accepts BusUPGR and injects BUSUPGR_ACK
    """
    write_task = cocotb.start_soon(cpu_request(dut, addr, wdata, wstrb))

    c_addr, _, c_cmd = await wait_for_cache_valid(dut)
    assert c_cmd == CMD_BUS_UPGR, f"Expected BusUPGR (0x{CMD_BUS_UPGR:03x}), got 0x{c_cmd:03x}"
    assert c_addr == addr,        f"BusUPGR addr mismatch"
    await ack_cache_cmd(dut)

    await send_bus_response(dut, BUSUPGR_ACK, 0)
    await write_task


# ════════════════════════════════════════════════════════════════════════════
#  Test cases
# ════════════════════════════════════════════════════════════════════════════

@cocotb.test()
async def test_simple(dut):
    """
    Minimal smoke test:
      - Read-miss on address 0x00 → cache should issue BusRD, receive data,
        and return it to the processor.
    """
    await start_clock(dut)
    await reset_dut(dut)

    ADDR      = 0x00000000
    FILL_DATA = 0xDEADBEEF

    rdata = await do_read_miss(dut, ADDR, FILL_DATA)

    assert rdata == FILL_DATA, \
        f"test_simple FAIL: expected 0x{FILL_DATA:08x}, got 0x{rdata:08x}"
    log.info("test_simple PASS  rdata=0x%08x", rdata)


@cocotb.test()
async def test_read_miss_then_read_hit(dut):
    """
    After a read-miss brings the line into Shared state, a second read to the
    same address must complete without any outbound coherence command.
    """
    await start_clock(dut)
    await reset_dut(dut)

    ADDR      = 0x00000010
    FILL_DATA = 0xCAFEBABE

    # First access: cold miss
    rdata = await do_read_miss(dut, ADDR, FILL_DATA)
    assert rdata == FILL_DATA, f"First read wrong: 0x{rdata:08x}"

    # Second access: should be a cache hit (no BusRD on the outbound bus)
    hit_task = cocotb.start_soon(cpu_request(dut, ADDR, wstrb=0))

    # Give some cycles; if cache_valid_o fires it means an unexpected miss
    for _ in range(20):
        await RisingEdge(dut.clk_i)
        assert dut.cache_valid_o.value == 0, \
            "Unexpected outbound command on read hit"

    rdata2 = await hit_task
    assert rdata2 == FILL_DATA, \
        f"Read hit returned wrong data: 0x{rdata2:08x} expected 0x{FILL_DATA:08x}"
    log.info("test_read_miss_then_read_hit PASS")


@cocotb.test()
async def test_write_miss(dut):
    """
    Write to an Invalid line:
      cache should issue BusRDX, receive the ack, then complete the write.
    A subsequent read-hit must return the written data.
    """
    await start_clock(dut)
    await reset_dut(dut)

    ADDR   = 0x00000020
    WDATA  = 0x12345678
    WSTRB  = 0xF         # full-word write

    await do_write_miss(dut, ADDR, WDATA, WSTRB)

    # Read back without any coherence traffic (line now in Modified)
    read_task = cocotb.start_soon(cpu_request(dut, ADDR, wstrb=0))
    for _ in range(20):
        await RisingEdge(dut.clk_i)
        assert dut.cache_valid_o.value == 0, \
            "Unexpected outbound command on post-write read"
    rdata = await read_task

    assert rdata == WDATA, \
        f"test_write_miss read-back FAIL: got 0x{rdata:08x} expected 0x{WDATA:08x}"
    log.info("test_write_miss PASS")


@cocotb.test()
async def test_write_upgrade(dut):
    """
    Read-miss (→ Shared) followed by write (→ must issue BusUPGR, not BusRDX).
    """
    await start_clock(dut)
    await reset_dut(dut)

    ADDR      = 0x00000030
    FILL_DATA = 0xAAAAAAAA
    WDATA     = 0x55555555

    # Bring line in as Shared
    await do_read_miss(dut, ADDR, FILL_DATA)

    # Write the same line → should upgrade, not re-fetch
    await do_write_upgrade(dut, ADDR, WDATA)

    log.info("test_write_upgrade PASS")


@cocotb.test()
async def test_snoop_rd_on_invalid_line(dut):
    """
    BusRD snoop targeting an Invalid (cold) line → cache should ack without
    flushing anything and NOT issue an EvictDirty.
    """
    await start_clock(dut)
    await reset_dut(dut)

    SNOOP_ADDR = 0x00000040
    ack_cmd, _ = await send_snoop(dut, SNOOP_ADDR, SNOOP_RD)

    assert ack_cmd == CMD_SNOOP_RD_ACK, \
        f"Expected SnoopBusRD_Ack (0x{CMD_SNOOP_RD_ACK:03x}), got 0x{ack_cmd:03x}"
    log.info("test_snoop_rd_on_invalid_line PASS")


@cocotb.test()
async def test_snoop_rdx_invalidates_shared(dut):
    """
    1. Bring a line into Shared via read-miss.
    2. Receive a BusRDX snoop → line should be invalidated (no flush needed).
    3. A subsequent read must re-issue BusRD (cold miss again).
    """
    await start_clock(dut)
    await reset_dut(dut)

    ADDR      = 0x00000050
    FILL_DATA = 0x11223344

    # Bring line into Shared
    await do_read_miss(dut, ADDR, FILL_DATA)

    # BusRDX snoop → invalidate
    ack_cmd, _ = await send_snoop(dut, ADDR, SNOOP_RDX)
    assert ack_cmd == CMD_SNOOP_RDX_ACK, \
        f"Expected SnoopBusRDX_Ack (0x{CMD_SNOOP_RDX_ACK:03x}), got 0x{ack_cmd:03x}"

    # Read must now be a miss again
    NEW_DATA = 0xDEADC0DE
    rdata = await do_read_miss(dut, ADDR, NEW_DATA)
    assert rdata == NEW_DATA, \
        f"Post-invalidate read returned stale data: 0x{rdata:08x}"
    log.info("test_snoop_rdx_invalidates_shared PASS")


@cocotb.test()
async def test_snoop_rd_flushes_modified(dut):
    """
    1. Bring a line into Modified via write-miss.
    2. Receive a BusRD snoop → cache must flush (EvictDirty) before acking.
    """
    await start_clock(dut)
    await reset_dut(dut)

    ADDR  = 0x00000060
    WDATA = 0xFACEFEED

    # Bring line into Modified
    await do_write_miss(dut, ADDR, WDATA)

    # Present BusRD snoop.  The snoop FSM will:
    #   fetch the line  →  detect flush needed  →  issue EvictDirty  →  ack
    # We need to accept the EvictDirty on the outbound bus first.
    snoop_task = cocotb.start_soon(send_snoop(dut, ADDR, SNOOP_RD))

    # The first outbound command must be EvictDirty
    c_addr, c_data, c_cmd = await wait_for_cache_valid(dut)
    assert c_cmd == CMD_EVICT_DIRTY, \
        f"Expected EvictDirty (0x{CMD_EVICT_DIRTY:03x}) before snoop ack, got 0x{c_cmd:03x}"
    assert c_data == WDATA, \
        f"EvictDirty carried wrong data: 0x{c_data:08x} expected 0x{WDATA:08x}"
    await ack_cache_cmd(dut)

    # Now the snoop FSM continues to issue its ack
    ack_cmd, _ = await snoop_task
    assert ack_cmd == CMD_SNOOP_RD_ACK, \
        f"Expected SnoopBusRD_Ack after flush, got 0x{ack_cmd:03x}"
    log.info("test_snoop_rd_flushes_modified PASS")


@cocotb.test()
async def test_byte_write_strobe(dut):
    """
    Write a single byte (wstrb = 0x1) into an existing Modified line and
    verify that only that byte changes in the read-back.
    """
    await start_clock(dut)
    await reset_dut(dut)

    ADDR       = 0x00000070
    FILL_DATA  = 0x11223344   # initial line content

    # Full write-miss to bring line in Modified with known content
    await do_write_miss(dut, ADDR, FILL_DATA)

    # Byte-write: overwrite byte 0 only (bits [7:0]) with 0xFF
    BYTE_VAL = 0xFF
    write_task = cocotb.start_soon(cpu_request(dut, ADDR, BYTE_VAL, wstrb=0x1))

    # This is a write-hit on a Modified line → no outbound command expected
    for _ in range(20):
        await RisingEdge(dut.clk_i)
        assert dut.cache_valid_o.value == 0, \
            "Unexpected outbound command on Modified write-hit"
    await write_task
y_i. When cache_ready_i is asserted, cache_valid_o should still be 1 if the master is still
    # Read back: bytes [31:8] unchanged, byte [7:0] = 0xFF
    expected = (FILL_DATA & 0xFFFFFF00) | 0xFF
    rdata = await with_timeout(
        cocotb.start_soon(cpu_request(dut, ADDR, wstrb=0)),
        timeout_time=TIMEOUT_CYCLES * 20, timeout_unit="ns"
    )
    assert rdata == expected, \
        f"Byte-write mismatch: got 0x{rdata:08x}, expected 0x{expected:08x}"
    log.info("test_byte_write_strobe PASS")


@cocotb.test()
async def test_multiple_addresses_independent(dut):
    """
    Verify that two addresses that map to different cache indices are
    completely independent – read-miss, fill, and hit on each.
    """
    await start_clock(dut)
    await reset_dut(dut)

    # index bits are addr[6:0]; choose two distinct indices
    ADDR_A, DATA_A = 0x00000000, 0xAAAA0000
    ADDR_B, DATA_B = 0x00000008, 0x0000BBBB

    await do_read_miss(dut, ADDR_A, DATA_A)
    await do_read_miss(dut, ADDR_B, DATA_B)

    # Both should now be hits
    for addr, expected in [(ADDR_A, DATA_A), (ADDR_B, DATA_B)]:
        hit_task = cocotb.start_soon(cpu_request(dut, addr, wstrb=0))
        for _ in range(20):
            await RisingEdge(dut.clk_i)
            assert dut.cache_valid_o.value == 0, "Unexpected miss on repeat read"
        rdata = await hit_task
        assert rdata == expected, \
            f"Read at 0x{addr:08x}: got 0x{rdata:08x} expected 0x{expected:08x}"

    log.info("test_multiple_addresses_independent PASS")


# ════════════════════════════════════════════════════════════════════════════
#  Runner
# ════════════════════════════════════════════════════════════════════════════

def cache_controller_test():
    proj_path = Path(__file__).resolve().parent
    pdk_root  = Path("../gf180mcu")

    sources = [
        proj_path / "../src/msi_protocol/apply_wstrb.sv",
        proj_path / "../src/msi_protocol/on_processor_event_state_machine.sv",
        proj_path / "../src/msi_protocol/on_snoop_event_state_machine.sv",
        proj_path / "../src/msi_protocol/cache_controller.sv",
        proj_path / "../src/msi_protocol/outbound_arbiter.sv",
        proj_path / "../src/mem_ctrl/cache_dir_memory/mem128x4.sv",
        proj_path / "../src/mem_ctrl/cache_dir_memory/mem128x32.sv",
        proj_path / "../src/mem_ctrl/cache_dir_memory/cache_mem.sv",
        proj_path / "../src/mem_ctrl/cache_dir_memory/two_port_cache_mem.sv",
        pdk_root / "gf180mcuD/libs.ref/gf180mcu_fd_ip_sram/verilog/gf180mcu_fd_ip_sram__sram512x8m8wm1.v",
        pdk_root / "gf180mcuD/libs.ref/gf180mcu_fd_ip_sram/verilog/gf180mcu_fd_ip_sram__sram64x8m8wm1.v",
    ]

    build_args = []
    if sim == "verilator":
        build_args = ["--timing", "--trace", "--trace-fst", "--trace-structs"]

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
