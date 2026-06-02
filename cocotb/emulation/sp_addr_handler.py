from axi_request import axi_request
from enum import Enum

class SP_ADDR(Enum):

    WHOAMI    = {0x8000_0000}
    MMIO_CSR  = {0x8000_0018}
    MMIO_DATA = {0x8000_0010, 
                 0x8000_0011, 
                 0x8000_0012, 
                 0x8000_0013, 
                 0x8000_0014, 
                 0x8000_0015, 
                 0x8000_0016, 
                 0x8000_0017}
    
class MMIO:

    def __init__(self):

        self.MMIO_data_r : list = [0] * 8
        self.MMIO_CSR_r  : list = [0] * 8

    def _int32_to_bool(self, val : int) -> bool:
        output = 0
        for _ in range(32):
            output |= val & 1
            val <<= 1
        return output

    def _set_CSR(self, data_i : int, wstrb_i : int):
        if (wstrb_i & 0x1):
            for i in range(8):
                self.MMIO_CSR_r[i] = data_i & 1
                data_i >>= 1

    def _set_data(self, addr : int, data_i : int, wstrb_i : int):
        id = addr & 0xF

        # only write if set to output and strb valid
        if (self.MMIO_CSR_r[id]) and (wstrb_i & 1):
            # only write LSB
            self.MMIO_data_r[id] = data_i & 1
    
    def _get_data(self, addr : int) -> int:
        id = addr & 0xF
        return self.MMIO_data_r[id]
    
    def _get_csr(self) -> list:
        return self.MMIO_CSR_r.copy()
    
    # called by IO device not CPU
    def set_pin(self, pin_num : int, val : int):
        assert 0 <= pin_num <= 7, "MMIO: set_pin - pin num outside of pin range"

        # only set if pin set to input
        if (self.MMIO_CSR_r[pin_num] == 0):
            self.MMIO_data_r =  val & 1

    def handle_req(self, axi_packet: axi_request):
        
        addr = axi_packet.mem_addr
        wdata = axi_packet.mem_wdata
        wstrb = axi_packet.mem_wstrb

        # requesting to CSR
        if addr in SP_ADDR.MMIO_CSR:
            # read req
            if wstrb == 0:
                axi_packet.mem_rdata = self._get_csr()
            
            # write req
            else:
                self._set_CSR(wdata, wstrb)

        # requesting to data
        elif addr in SP_ADDR.MMIO_DATA:
            # read req
            if wstrb == 0: 
                axi_packet.mem_rdata = self._get_data(addr)

            # write req
            else:
                self._set_data(addr, wdata, wstrb)

class sp_addr_handler:

    def __init__(self, WhoAmI : int):
        self.mem_packet  : axi_request = None

        self.MMIO = MMIO()

        self.cc_packet_o : axi_request = None
        self.WAI_r       : int = WhoAmI
        
    def _yield_WAI(self):
        self.mem_packet.mem_rdata = self.WAI_r
    
    def handle_req(self, axi_packet : axi_request):
        self.cc_packet_o = None
        addr = axi_packet.mem_addr

        if addr in SP_ADDR.WHOAMI:
            self._yield_WAI()

        elif addr in SP_ADDR.MMIO_CSR or addr in SP_ADDR.MMIO_DATA:
            self.MMIO.handle_req(axi_packet)

        # normal address passthrough
        else:
            self.cc_packet_o = axi_packet
