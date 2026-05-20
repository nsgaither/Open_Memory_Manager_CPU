# external libs
import logging

# types
from .axi_request_types import axi_request
from .config import MAIN_MEM_SIZE_IN_WORDS

BYTE_MASKS = [0x000000FF, 0x0000FF00, 0x00FF0000, 0xFF000000]

class MemoryController:

    def __init__(self) -> None:
        self.sram: dict[int, int] = {}
        self.log = logging.getLogger(__name__)
        self.max_address: int = MAIN_MEM_SIZE_IN_WORDS        

    # read address, if not in address spcae return 0        
    async def read(self, address: int) -> int:

        if address > self.max_address:
            self.log.error("read err: address out of range, cant read")
            return 0

        found_val: int = self.sram.get(address, 0)
        self.log.debug(f"read addr={address:#010x} got={found_val:#010x}")
        return found_val

    # async def write_n(self, address: int, data: int, write_strobe: int) -> None:

    #     self.log.debug(f"write addr={address} with {data}")
    #     # address not in physical address spcae
    #     if address > self.max_address:
    #         self.log.error(f"write err: address out of range, wrote nothing max address is {self.max_address}")
    #         return

    #     # assemble word to write based on bit mask
    #     data_to_write: int = 0
    #     for index, bit_mask in enumerate(BYTE_MASKS):
    #         byte: int = data & bit_mask
    #         if (write_strobe >> index) & 1: # shift and isolate last bit
    #             data_to_write |= byte        

    #     self.sram[address] = data_to_write
    #     return

    async def write(self, address: int, data: int, write_strobe: int) -> None:
        if address > self.max_address:
            self.log.error(f"write err: address out of range")
            return
    
        existing: int = self.sram.get(address, 0)  # read existing value
        data_to_write: int = existing               # start from existing
    
        for index, bit_mask in enumerate(BYTE_MASKS):
            if (write_strobe >> index) & 1:
                data_to_write = (data_to_write & ~bit_mask) | (data & bit_mask)
    
        self.sram[address] = data_to_write
    
    async def axi_handler(self, request: axi_request) -> axi_request:

        print("=== Directory to Memory ===")
        print(request)

        self.log.debug(f"memory axi handler started")        
        # we get a valid mem request and handshake
        if request.mem_valid:
        
            # read
            if request.mem_wstrb == 0:
                request.mem_rdata = await self.read(request.mem_addr)

            # write 
            else:
                await self.write(request.mem_addr, request.mem_wdata, request.mem_wstrb)

            # mark request as done
            request.mem_ready = True        
             
        self.log.debug(f"memory axi handler ended")        
        print("=== Memory to Directory ===")
        print(request)
        return request 

    def direct_memory_acess(self, addr: int) -> int:
        found_val: int = self.sram.get(addr, 0)
        print("=== DMA ACESS ===")
        print(f"found val {found_val} at addr {addr}")
        return found_val
        
