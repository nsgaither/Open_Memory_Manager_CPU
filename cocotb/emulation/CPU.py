# external 
import copy
import asyncio
import logging

# hardware emulators
from .core import Core
from .memory_v2 import MemoryController
from .weighted_round_robin import WeightedRoundRobinArbiter
from .cache_v3 import CacheController
from .directory_v2 import DirectoryController

# types
from .axi_request_types import axi_request
from .testcase import test_case
from typing import List, Optional


logging.basicConfig(
    level=logging.DEBUG,  # show debug and above
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)


class CPU: 
    def __init__(self, size: int, test_cases: List[test_case]) -> None:

        # setup memory 
        self.memory: MemoryController = MemoryController()

        # setup directory
        self.directory: DirectoryController = DirectoryController(size, self.memory.axi_handler)

        # setup arbiter
        self.arbiter: WeightedRoundRobinArbiter = WeightedRoundRobinArbiter(size, [1] * size, self.directory.axi_handler_for_arbiter)
        
        # setup caches
        self.caches: List[CacheController] = [] 
        for i in range(size):
            cache_to_add: CacheController = CacheController(i, self.arbiter.axi_handler_arbiter)
            self.caches.append(cache_to_add)
            self.directory.register_cache(i, cache_to_add.axi_and_coherence_handler)

        # num cores
        self.num_cores: int = size
        # state of those cores
        self.finsihed_cores: int = 0

        # arr of those cores
        self.cores: List[Core] = []
        for i in range(size):
            self.cores.append(Core(i, self.caches[i].axi_handler_for_core))

        # build work load for each of those cores
        self.core_workloads: List[List[test_case]] = [[] for i in range(size)]
        for i in range(0, len(test_cases), size):
            for k in range(size):
                self.core_workloads[k].append(test_cases[i+k])


    async def core_worker_write(self, core_id: int, test_case_in: test_case, valid_testcase: bool) -> axi_request:  # try to write data
        # print(f"tryin to write {test_case_in.data} with core {core_id}")
        if valid_testcase:
            return await self.cores[core_id].write(test_case_in.data_addr, test_case_in.data, test_case_in.wstb)
        else:
            return await self.cores[core_id].write_nothing()

              

    async def core_worker_read(self, core_id: int, test_case_in: test_case, valid_testcase: bool) -> axi_request:  # try to write data
        if valid_testcase:
            return await self.cores[core_id].read(test_case_in.data_addr)
        else:
            return await self.cores[core_id].write_nothing()
              
    def print_caches(self)->None:
        print("=" * 70)
        print("Cache States")
        print("=" * 70)
        for i in range(self.num_cores):
            self.caches[i].dump_cache()


    def empty_caches(self)->None:
        print("=" * 70)
        print("invalidate all of cache")
        print("=" * 70)
        for i in range(self.num_cores):
            self.caches[i].flush_all()


    def dma(self, addr: int) -> int:
        return self.memory.direct_memory_acess(addr)

    async def start_sim(self):

        print("=" * 70)
        print("Starting CPU Simulation")
        print("=" * 70)

    
        core_workloads_copy: List[List[test_case]] = copy.deepcopy(self.core_workloads)
        while any(core_workloads_copy):

            tasks: List[asyncio.Task[axi_request]] = []        
            for core_id in range(self.num_cores):
                # check if test_case exists
                if len(core_workloads_copy[core_id]) > 0:
                    core_testcase: test_case = core_workloads_copy[core_id][-1]           
                    valid_testcase = True
                else:
                    valid_testcase: bool = False
                    core_testcase: test_case = test_case(-1, -1, 0)           
                    

                if core_testcase.wstb == 0:    
                    tasks.append(
                        asyncio.create_task(
                            self.core_worker_read(core_id, core_testcase, valid_testcase),
                            name=f"Core-{core_id}"
                        )
                    )
                else:
                    tasks.append(
                        asyncio.create_task(
                            self.core_worker_write(core_id, core_testcase, valid_testcase),
                            name=f"Core-{core_id}"
                        )
                    )

            # wait for all them and pop ones that are done
            cur_cycle_results: List[axi_request] = await asyncio.gather(*tasks)



            print("=== Current Cycle Copy ===")
            print(cur_cycle_results)

            for index, result in enumerate(cur_cycle_results):
                if result.mem_ready and result.mem_valid:
                    if result.mem_wstrb == 0:
                        print(f"READ: data at {result.mem_addr} is {result.mem_rdata}")
                    core_workloads_copy[index].pop() # <- im pop from empty list err here any idea                        

            print("=== Workload Copy ===")
            print(core_workloads_copy)

        # self.print_caches()



    
    async def start_sim_simple(self):

        print("=" * 70)
        print("Starting CPU Simulation")
        print("=" * 70)
        

        print("=" * 70)
        print("Writing Stuff")
        print("=" * 70)
        

        # to keep workloads intact for later use
        core_workloads_copy: List[List[test_case]] = copy.deepcopy(self.core_workloads)
        i: int = 1
        
        while any(core_workloads_copy):
            print(f"=== {i} Write Cycle ===")
            print(core_workloads_copy)
            i += 1


            tasks: List[asyncio.Task[axi_request]] = []        
            for core_id in range(self.num_cores):
                # check if test_case exists
                if len(core_workloads_copy[core_id]) > 0:
                    core_testcase: test_case = core_workloads_copy[core_id][-1]           
                    valid_testcase = True
                else:
                    valid_testcase: bool = False
                    core_testcase: test_case = test_case(-1, -1, -1)           
                    
             
            
                tasks.append(
                    asyncio.create_task(
                        self.core_worker_write(core_id, core_testcase, valid_testcase),
                        name=f"Core-{core_id}"
                    )
                
                )

            # wait for all them and pop ones that are done
            cur_cycle_results: List[axi_request] = await asyncio.gather(*tasks)


            for index, result in enumerate(cur_cycle_results):
                if result.mem_ready and result.mem_valid:
                    print(cur_cycle_results)
                    print(core_workloads_copy)
                    core_workloads_copy[index].pop()                         



        # self.print_caches()  
        # self.empty_caches()

        print("=" * 70)
        print("Reading Stuff Out")
        print("=" * 70)
        

        # to keep workloads intact for later use
        core_workloads_copy: List[List[test_case]] = copy.deepcopy(self.core_workloads)
        
        i = 0
        while any(core_workloads_copy):
            print(f"=== {i} Read Cycle ===")
            i += 1
            tasks: List[asyncio.Task[axi_request]] = []        
            for core_id in range(self.num_cores):
                # check if test_case exists
                valid_testcase: bool = False
                core_testcase: test_case = test_case(-1, -1, -1)           
                if len(core_workloads_copy[core_id]) > 0:
                    core_testcase: test_case = core_workloads_copy[core_id][-1]           
                    valid_testcase = True
             
            
                tasks.append(
                    asyncio.create_task(
                        self.core_worker_read(core_id, core_testcase, valid_testcase),
                        name=f"Core-{core_id}"
                    )
                
                )

            # wait for all them and pop ones that are done
            cur_cycle_results: List[axi_request] = await asyncio.gather(*tasks)
            for index, result in enumerate(cur_cycle_results):
                if result.mem_ready:
                    print(f" data at {result.mem_addr} is {result.mem_rdata}")
                    core_workloads_copy[index].pop()                        

            
        print("=" * 70)
        print("Reading Stuff Out again but from other core")
        print("=" * 70)
        

        # to keep workloads intact for later use
        core_workloads_copy: List[List[test_case]] = copy.deepcopy(self.core_workloads)
        
        while any(core_workloads_copy):
            tasks: List[asyncio.Task[axi_request]] = []        
            for core_id in range(self.num_cores):
                # check if test_case exists
                valid_testcase: bool = False
                core_testcase: test_case = test_case(-1, -1, -1)           
                if len(core_workloads_copy[core_id]) > 0:
                    core_testcase: test_case = core_workloads_copy[core_id][-1]           
                    valid_testcase = True
             
            
                tasks.append(
                    asyncio.create_task(
                        self.core_worker_read(core_id, core_testcase, valid_testcase),
                        name=f"Core-{core_id}"
                    )
                
                )

            # wait for all them and pop ones that are done
            cur_cycle_results: List[axi_request] = await asyncio.gather(*tasks)
            for index, result in enumerate(cur_cycle_results):
                if result.mem_ready:
                    print(f" data at {result.mem_addr} is {result.mem_rdata}")
                    core_workloads_copy[index].pop()                        

        print("=" * 70)
        print("We Did it")
        print("=" * 70)

        # self.print_caches()
        

