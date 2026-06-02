# External
from dataclasses import dataclass

# types
from typing import (Optional, Dict, Callable, Awaitable)
from .msi_v2 import (MSIState, CoherenceCmd)
from .axi_request_types import (axi_and_coherence_request, axi_request)
from .util import (axi_and_cohrenece_cmd_to_axi)

# helper functions
from .util import axi_and_cohrenece_cmd_to_axi

@dataclass
class DirectoryEntry:
    """
    Directory state for a single memory address.
    
    The directory maintains coherence by tracking:
    1. What state the line is in globally (INVALID, SHARED, or MODIFIED)
    2. Which caches have copies (sharers bitmask)
    
    """
    state: MSIState = MSIState.INVALID  # Global state
    sharers: int = 0                    # Bitmask of caches with copies

    def owner(self) -> Optional[int]:
        """
        Get the owner cache ID if this line is in MODIFIED state.
        
        In MODIFIED state, exactly one cache should have the line.
        This function extracts which cache owns it.
        
        Returns:
            Cache ID (0, 1, ...) if MODIFIED with single owner
            None if not MODIFIED, no sharers, or multiple sharers (error)
        
        """
        # Only MODIFIED state has an owner
        if self.state != MSIState.MODIFIED:
            return None
        
        # Must have at least one sharer
        if self.sharers == 0:
            return None
        
        # Must have exactly one sharer (power of 2 check)
        if self.sharers & (self.sharers - 1):
            return None  # Multiple bits set
        
        # Return which bit is set (cache ID)
        return self.sharers.bit_length() - 1


class DirectoryController:
    """
    Central directory controller for MSI cache coherence.
    
    The directory is the "home node" for all memory addresses. It:
    1. Maintains directory entries tracking cache states
    2. Stores memory data
    3. Coordinates coherence by sending snoops to caches
    4. Responds to coherence requests from caches
    
    Attributes:
        num_cores: Number of caches in the system
        entries: Directory state (address → DirectoryEntry)
        memory: Main memory storage (address → data)
        cache_ports: Cache AXI handlers (cache_id → axi_handler function)
    """

    def __init__(self, num_cores: int, mem_axi_handler: Callable[[axi_request], Awaitable[axi_request]]):

        """
        Initialize directory controller.
        
        Args:
            num_cores: Number of caches/cores in the system (default 2)        
            axi_handler: axi handler of memory
        """

        self.num_cores = num_cores
        
        # Directory state: lazy allocation (created on first access)
        self.entries: Dict[int, DirectoryEntry] = {}
        
        # Main memory storage
        # self.memory: Dict[int, int] = {}
        self.memory_axi_handler: Callable[[axi_request], Awaitable[axi_request]] = mem_axi_handler
        
        # Cache communication ports
        # Maps cache_id → cache's axi_handler function
        self.cache_ports: Dict[int, Callable[[axi_and_coherence_request], Awaitable[axi_and_coherence_request]]] = {}

    def register_cache(self, core_id: int, cache_axi_handler: Callable[[axi_and_coherence_request], Awaitable[axi_and_coherence_request]]) -> None:
        """
        Register a cache controller's AXI handler for snoop communication.
                
        Args:
            core_id: Cache identifier (0, 1, ...)
            cache_axi_handler: Cache's axi_handler function        
        """

        self.cache_ports[core_id] = cache_axi_handler


    def _entry(self, addr: int) -> DirectoryEntry:
        """
        Get directory entry for an address, creating if necessary.
        
        Args:
            addr: Memory address
        
        Returns:
            DirectoryEntry for this address
        """

        if addr not in self.entries:
            self.entries[addr] = DirectoryEntry()
        return self.entries[addr]
    


    async def _send_snoop(self, target_core: int, addr: int, snoop_cmd: CoherenceCmd, requester: int) -> axi_and_coherence_request:
        """
        send a snoop message to a specific cache.
        
        args:
            target_core: which cache to snoop (cache id)
            addr: memory address being snooped
            snoop_cmd: type of snoop (snoop_bus_rd, snoop_bus_rdx, snoop_bus_upgr)
            requester: which cache initiated the original request
        
        returns:
            flushed data from target cache as an axi + cohrence cmd
                    
        raises:
            runtimeerror: if target cache doesn't acknowledge snoop
        """

        # get target cache's axi handler
        port = self.cache_ports[target_core]

        # build snoop request
        req = axi_and_coherence_request(
            mem_valid = True,
            mem_ready = False,
            mem_instr = False,  # this is coherence traffic
            mem_addr = addr,
            mem_wdata_or_msi_payload = 0,
            mem_wstrb = 0x0,
            mem_rdata = 0,
            coherence_cmd = snoop_cmd,
            core_id = requester
        )
             
        # send snoop to cache (synchronous call)
        resp: axi_and_coherence_request = await port(req)
        
        # verify cache acknowledged
        if not resp.mem_ready:
            raise RuntimeError(f"snoop not acknowledged by core {target_core}")
        
        # return any flushed data
        return resp


    async def _bus_rd(self, request: axi_and_coherence_request) -> axi_request:
        """
        Handle BUS_RD request (read miss from a cache).
        
        Args:
            requester: Cache ID issuing the request
            addr: Memory address to read
        
        Returns:
            Data value (from memory or owner cache)        
        """

        axi_to_mem: axi_request = axi_and_cohrenece_cmd_to_axi(request) 

        entry = self._entry(request.mem_addr)

        # Case 1: INVALID - no cache has it
        if entry.state == MSIState.INVALID:
            # Fetch from memory (or default to 0 if never written)
            entry.state = MSIState.SHARED
            entry.sharers = 1 << request.core_id  # Set requester bit
            # return self.memory.get(addr, 0)
            return await self.memory_axi_handler(axi_to_mem)

        # Case 2: SHARED - one or more caches have clean copies
        if entry.state == MSIState.SHARED:
            # Add requester to sharers
            entry.sharers |= 1 << request.core_id
            # Data is clean in memory
            return await self.memory_axi_handler(axi_to_mem)

        # Case 3: MODIFIED - one cache has dirty copy
        # Get owner cache ID
        owner = entry.owner()
        
        # If there's a valid owner and it's not the axi_and_coherence_request.core_id
        if owner is not None and owner != request.core_id:

            # Snoop owner to get dirty data
            # flushed = (await self._send_snoop(owner, request.mem_addr, CoherenceCmd.SNOOP_BUS_RD, request.core_id)).mem_rdata
            flushed = (await self._send_snoop(owner, request.mem_addr, CoherenceCmd.SNOOP_BUS_RD, request.core_id)).mem_wdata_or_msi_payload
            
            # Update memory with flushed data
            write_request: axi_request = axi_request(
                mem_valid= True,
                mem_instr= False,
                mem_ready= False,
                mem_addr= request.mem_addr,
                mem_wdata= flushed,
                mem_wstrb= 0x0f,
                mem_rdata=0
            ) 
       
            memory_resp: axi_request = await self.memory_axi_handler(write_request)

            if memory_resp.mem_ready is not True:
                print("errrororororor")


            # Keep owner in sharers (it downgrades to SHARED)
            entry.sharers |= 1 << owner

        # Transition to SHARED state
        entry.state = MSIState.SHARED
        
        # Add requester to sharers
        entry.sharers |= 1 << request.core_id
        
        # Return data (now clean in memory)
        read_request: axi_request = axi_request(
            mem_valid= True,
            mem_instr= False,
            mem_ready= False,
            mem_addr= request.mem_addr,
            mem_wdata= 0,
            mem_wstrb= 0x00,
            mem_rdata= 0
        ) 

        memory_resp: axi_request = await self.memory_axi_handler(read_request)

        if memory_resp.mem_ready is not True:
            print("error xd")

        return memory_resp


    async def _bus_rdx(self, request: axi_and_coherence_request) -> axi_request:
        """
        Handle BUS_RDX request (write miss from a cache).
        
        A cache issues BUS_RDX when:
        - Cache line is INVALID (write miss)
        - Cache needs data AND exclusive access
        
        Directory Action:
        - Provides data
        - Invalidates all other copies
        - Grants exclusive access to requester
        - Updates state to MODIFIED
        
        Args:
            requester: Cache ID issuing the request
            addr: Memory address to write
        
        Returns:
            Data value (from memory or owner cache)

        """
        entry = self._entry(request.mem_addr)
        print(f"entry state is {entry.state} owner is {entry.owner} shares are {entry.sharers}")

        # read data from address
        read_request: axi_request = axi_request(
            mem_valid= True,
            mem_instr= False,
            mem_ready= False,
            mem_addr= request.mem_addr,
            mem_wdata= 0,
            mem_wstrb= 0x00,
            mem_rdata= 0
        ) 

        # write_request: axi_request = axi_and_cohrenece_cmd_to_axi(request)
        # Case 1: INVALID - no cache has it
        if entry.state == MSIState.INVALID:
            # Grant exclusive access
            data: axi_request = await self.memory_axi_handler(read_request) # Bug here maybe, why am i reading shouldnt i write
            entry.state = MSIState.MODIFIED
            entry.sharers = 1 << request.core_id
            return data 

        # Case 2: SHARED - invalidate all other sharers
        if entry.state == MSIState.SHARED:
            # Snoop all sharers except requester
            for c in range(self.num_cores):
                if c != request.core_id and ((entry.sharers >> c) & 1):
                    # Send invalidation
                    _ = await self._send_snoop(c, request.mem_addr, CoherenceCmd.SNOOP_BUS_RDX, request.core_id)
            data: axi_request = await self.memory_axi_handler(read_request) # bug here maybe, why am i reading should i wirte
            
            # Grant exclusive access
            entry.state = MSIState.MODIFIED
            entry.sharers = 1 << request.core_id
            return data

        # Case 3: MODIFIED - transfer ownership
        owner = entry.owner()
        if owner is not None and owner != request.core_id:
            print("is snoop called")
            # Get dirty data from owner
            flushed = await self._send_snoop(owner, request.mem_addr, CoherenceCmd.SNOOP_BUS_RDX, request.core_id)
            
            # Update memory
            write_request: axi_request = axi_request(
                mem_valid= True,
                mem_instr= False,
                mem_ready= False,
                mem_addr= request.mem_addr,
                mem_wdata= flushed.mem_wdata_or_msi_payload,
                mem_wstrb= 0x0f,
                mem_rdata= 0
            ) 

            await self.memory_axi_handler(write_request)

            # Grant exclusive access to requester
            entry.state = MSIState.MODIFIED
            entry.sharers = 1 << request.core_id
            return axi_request(
                mem_valid=True,
                mem_instr=False,
                mem_ready=True,
                mem_addr=request.mem_addr,
                mem_wdata=0,
                mem_wstrb=0,
                mem_rdata=flushed.mem_wdata_or_msi_payload  # dirty data in mem_rdata
            )
        
        # lsp mad so i put this here
        print("this shouldnt have got hit")
        return axi_request(False, False, False, 0, 0, 0, 0)

    async def _bus_upgr(self, request: axi_and_coherence_request) -> axi_request:

        """
        Handle BUS_UPGR request (upgrade from SHARED to MODIFIED).
        
        A cache issues BUS_UPGR when:
        - Cache line is SHARED (already has data)
        - CPU writes to the line
        - Cache needs exclusive access but ALREADY has the data
        
        Difference from BUS_RDX:
        - BUS_RDX: Need data + exclusive (cache miss on write)
        - BUS_UPGR: Already have data, just need exclusive (cache hit on write)
        
        Directory Action:
        - Invalidates all other sharers (not requester)
        - No data transfer needed (requester already has it)
        - Updates state to MODIFIED
        
        Args:
            requester: Cache ID issuing the request
            addr: Memory address being upgraded
        
        Returns:
            Data value from memory (for consistency, though requester has it)        
        """

        entry = self._entry(request.mem_addr)

        # Normal case: state is SHARED
        if entry.state == MSIState.SHARED:
            # Invalidate all other sharers
            for c in range(self.num_cores):
                if c != request.core_id and ((entry.sharers >> c) & 1):
                    _ = await self._send_snoop(c, request.mem_addr, CoherenceCmd.SNOOP_BUS_UPGR, request.core_id)
            
            # Grant exclusive access
            entry.state = MSIState.MODIFIED
            entry.sharers = 1 << request.core_id


            return axi_request(
                mem_valid= True,
                mem_instr= False,
                mem_ready= True,
                mem_addr= request.mem_addr,
                mem_wdata= 0,
                mem_wstrb= 0x00,
                mem_rdata= 0
            ) 

            # return await self.memory_axi_handler(read_request)
            
        # Fallback: if not SHARED, treat as BUS_RDX
        # This handles edge cases (e.g., race conditions, protocol violations)
        return await self._bus_rdx(request)

    def _evict_clean(self, request: axi_and_coherence_request) -> axi_request:
        """
        Handle clean eviction (evicting a SHARED line).
        
        A cache issues EVICT_CLEAN when:
        - Evicting a line in SHARED state
        - No writeback needed (data is clean)
        
        Directory Action:
        - Remove cache from sharers list
        - If no more sharers, transition to INVALID
        - If MODIFIED and multiple sharers (error), downgrade to SHARED
        
        Args:
            requester: Cache ID evicting the line
            addr: Memory address being evicted
                
        """
        entry = self._entry(request.mem_addr)
        
        # Remove requester from sharers
        entry.sharers &= ~(1 << request.core_id)
        
        # If no sharers left, transition to INVALID
        if entry.sharers == 0:
            entry.state = MSIState.INVALID
        # Error recovery: MODIFIED but no valid single owner
        elif entry.state == MSIState.MODIFIED and entry.owner() is None:
            entry.state = MSIState.SHARED

        return axi_request(
            mem_valid=True,
            mem_instr=False,
            mem_ready=True,  
            mem_addr=request.mem_addr,
            mem_wdata=0,
            mem_wstrb=0,
            mem_rdata=0 # No data needed for clean eviction
        )

        

    async def _evict_dirty(self, request: axi_and_coherence_request) -> axi_request:
        """
        Handle dirty eviction (evicting a MODIFIED line).
        
        A cache issues EVICT_DIRTY when:
        - Evicting a line in MODIFIED state
        - Line has dirty data that must be written back
        
        Directory Action:
        - Write back data to memory
        - Remove cache from sharers
        - Update directory state appropriately
        
        Args:
            requester: Cache ID evicting the line
            addr: Memory address being evicted
            data: Dirty data to write back        
        """

        # Write back dirty data to memory
        write_request: axi_request = axi_request(
            mem_valid= True,
            mem_instr= False,
            mem_ready= False,
            mem_addr= request.mem_addr,
            mem_wdata= request.mem_wdata_or_msi_payload,
            mem_wstrb= 0x0f,
            mem_rdata=0
        ) 
        to_return: axi_request = await self.memory_axi_handler(write_request)
        
        # Clean up directory entry
        self._evict_clean(request)

        return to_return

    async def _handle_coherence(self, request: axi_and_coherence_request) -> axi_request:
        """
        Dispatch coherence commands to appropriate handlers.
        
        This is the main dispatcher for all coherence protocol commands
        received from caches. It unpacks the command and routes to the
        appropriate handler.
        
        Args:
            addr: Memory address
            packed_cmd: Packed coherence command from cache
        
        Returns:
            Response data (relevant for BUS_RD, BUS_RDX, BUS_UPGR)

        Raises:
            ValueError: If command is not recognized
        """
        # Unpack command
        cmd = request.coherence_cmd 
        # cmd, requester, payload = unpack_cmd(packed_cmd)

        # Route to appropriate handler
        if cmd == CoherenceCmd.BUS_RD:
            return await self._bus_rd(request)
        
        if cmd == CoherenceCmd.BUS_RDX:
            return await self._bus_rdx(request)
        
        if cmd == CoherenceCmd.BUS_UPGR:
            return await self._bus_upgr(request)
        
        if cmd == CoherenceCmd.EVICT_CLEAN:
            return self._evict_clean(request)
        
        if cmd == CoherenceCmd.EVICT_DIRTY:
            return await self._evict_dirty(request)

        # Unknown command
        raise ValueError(f"unknown coherence cmd {cmd}")


    async def axi_handler_for_arbiter(self, request: axi_and_coherence_request) -> axi_request:
        """
        Main AXI request handler for directory controller.
        
        Routes requests based on mem_instr flag:
        - mem_instr=True: Coherence traffic (BUS_RD, evictions, etc.)
        - mem_instr=False: Normal memory read/write
        
        Args:
            request: AXI request from cache or CPU
        
        Returns:
            AXI response with data and mem_ready=True
        
       """
        # Ignore invalid requests         
        print("=== Arbiter to Directory ===")
        print(request)

        if not request.mem_valid:
            request.mem_ready = False
            return axi_and_cohrenece_cmd_to_axi(request)

        x = await self._handle_coherence(request)
        print("=== Directory to Arbiter ===")
        print(x)
        return x

        # # Route based on traffic type
        # if request.mem_instr:
        #     # Coherence command from cache
            
            
        # # Direct memory access (non-coherent)
        # if request.mem_wstrb == 0:
        #     # Memory read
        #     request.mem_rdata = self.memory.get(request.mem_addr, 0)
        # else:
        #     # Memory write (with byte-level granularity)
        #     old_value = self.memory.get(request.mem_addr, 0)
        #     self.memory[request.mem_addr] = apply_wstrb(
        #         old_value,
        #         request.mem_wdata,
        #         request.mem_wstrb
        #     )
        #     request.mem_rdata = self.memory[request.mem_addr]

        # request.mem_ready = True
        # return request
    

