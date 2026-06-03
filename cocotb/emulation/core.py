from typing import Callable, Optional, Awaitable
from .axi_request_types import axi_request

class Core:

    def __init__(self, cpu_id: int, axi_handler: Callable[[axi_request], Awaitable[axi_request]]):
        # cpe inentifier
        self.cpu_id: int = cpu_id
        # functions pointers to send and recive axi packets
        self.axi_send_and_recieve: Callable[[axi_request], Awaitable[axi_request]] = axi_handler

    # read functions
    async def read(self, addr: int) -> axi_request:
        read_request:axi_request = axi_request(
            mem_valid= True,
            mem_instr=False,
            mem_ready=False,
            mem_addr=addr,
            mem_wdata=0,
            mem_wstrb=0b0000,
            mem_rdata=0)

        return await self.axi_send_and_recieve(read_request)


    async def read_nothing(self) -> axi_request:
        read_request:axi_request = axi_request(
            mem_valid= False,
            mem_instr=False,
            mem_ready=False,
            mem_addr=0,
            mem_wdata=0,
            mem_wstrb=0b0000,
            mem_rdata=0)

        return await self.axi_send_and_recieve(read_request)
    
    # write functions
    async def write(self, addr_in: int, data_in: int, wstb_in: int) -> axi_request:

        write_request: axi_request = axi_request(
            mem_valid= True,
            mem_instr=False,
            mem_ready=False,
            mem_addr=addr_in,
            mem_wdata=data_in,
            mem_wstrb=wstb_in,
            mem_rdata=0
        ) 
       
        return await self.axi_send_and_recieve(write_request)


    
    async def write_nothing(self) -> axi_request:
        write_request: axi_request = axi_request(
            mem_valid=False,
            mem_instr=False,
            mem_ready=False,
            mem_addr=0,
            mem_wdata= 0,
            mem_wstrb= 0b1111,
            mem_rdata= 0
        ) 
      
        return await self.axi_send_and_recieve(write_request)
           
