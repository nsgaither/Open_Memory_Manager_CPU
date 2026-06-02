import asyncio
import logging
from axi_request_types import axi_request
from memory_v2 import MemoryController

logging.basicConfig(level=logging.DEBUG, format='%(name)s [%(levelname)s] %(message)s')

async def test_memory_controller():
    mem = MemoryController(num_srams=8)  # max address = 255

    # --- test 1: write all bytes then read back ---
    write_req = axi_request(mem_valid=True, mem_instr=False, mem_ready=False,
                            mem_addr=0x10, mem_wdata=0xDEADBEEF, mem_wstrb=0b1111, mem_rdata=0)
    await mem.axi_handler(write_req)

    read_req = axi_request(mem_valid=True, mem_instr=False, mem_ready=False,
                           mem_addr=0x10, mem_wdata=0, mem_wstrb=0, mem_rdata=0)
    result = await mem.axi_handler(read_req)
    assert result.mem_ready == True
    assert result.mem_rdata == 0xDEADBEEF, f"expected 0xDEADBEEF got {result.mem_rdata:#010x}"
    print("PASS: test 1 - write all bytes, read back")

    # --- test 2: write only low byte ---
    write_req = axi_request(mem_valid=True, mem_instr=False, mem_ready=False,
                            mem_addr=0x20, mem_wdata=0xDEADBEEF, mem_wstrb=0b0001, mem_rdata=0)
    await mem.axi_handler(write_req)

    read_req = axi_request(mem_valid=True, mem_instr=False, mem_ready=False,
                           mem_addr=0x20, mem_wdata=0, mem_wstrb=0, mem_rdata=0)
    result = await mem.axi_handler(read_req)
    assert result.mem_rdata == 0x000000EF, f"expected 0x000000EF got {result.mem_rdata:#010x}"
    print("PASS: test 2 - write low byte only")

    # --- test 3: read from unwritten address returns 0 ---
    read_req = axi_request(mem_valid=True, mem_instr=False, mem_ready=False,
                           mem_addr=0x50, mem_wdata=0, mem_wstrb=0, mem_rdata=0)
    result = await mem.axi_handler(read_req)
    assert result.mem_rdata == 0, f"expected 0 got {result.mem_rdata:#010x}"
    print("PASS: test 3 - unwritten address returns 0")

    # --- test 4: out of range write is ignored ---
    write_req = axi_request(mem_valid=True, mem_instr=False, mem_ready=False,
                            mem_addr=0x100, mem_wdata=0x12345678, mem_wstrb=0b1111, mem_rdata=0)
    await mem.axi_handler(write_req)
    assert 0x100 not in mem.sram, "out of range write should not touch sram"
    print("PASS: test 4 - out of range write ignored")

    # --- test 5: mem_valid=False does nothing ---
    write_req = axi_request(mem_valid=False, mem_instr=False, mem_ready=False,
                            mem_addr=0x10, mem_wdata=0x0, mem_wstrb=0b1111, mem_rdata=0)
    result = await mem.axi_handler(write_req)
    assert result.mem_ready == False, "mem_valid=False should not set mem_ready"
    print("PASS: test 5 - mem_valid=False does nothing")

    print("\nAll tests passed!")

asyncio.run(test_memory_controller())
