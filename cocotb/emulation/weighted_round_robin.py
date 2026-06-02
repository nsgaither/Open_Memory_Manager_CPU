# external modules
import asyncio

# types
from .axi_request_types import (axi_request, axi_and_coherence_request)
from typing import List, Callable, Optional, Awaitable

# functions
from .util import (axi_and_cohrenece_cmd_to_axi)


class WeightedRoundRobinArbiter:

    def __init__(self, num_requesters: int, weights: List[int], axi_handler: Callable[[axi_and_coherence_request], Awaitable[axi_request]]):
 
        # error checking
        if len(weights) != num_requesters:
            raise ValueError(f"Number of weights ({len(weights)}) must match " f"number of requesters ({num_requesters})")

        if any(w <= 0 for w in weights):
            raise ValueError("All weights must be positive integers")

        
        # num_requesters: Number of requesters in the system
        self.num_requesters = num_requesters
                
        # weights: List of weights for each requester, defines how many
        # times a requester gets prioroty
        self.weights = weights

        # current requester index
        self.current_index = 0

        # their reminading credits/tickets
        self.remaining_credits = self.weights[0]

        # area to send chossen axi call to
        self.axi_send_and_recieve: Callable[[axi_and_coherence_request], Awaitable[axi_request]] = axi_handler

        # find max possible iterations needed for round bin
        self.max_possible_iterations: int = sum(weights)

        # bit mapping to track that all cores requested
        self.cores_arrived: int = 0
        self.cores_axi_requsts: List[Optional[axi_and_coherence_request]] = [None] * self.num_requesters

        # Syncronazation stuff need for coroutines 
        self.lock_to_wait_for_all_cores = asyncio.Lock()
        self.all_arrived = asyncio.Event()
        self.arbitation_done = asyncio.Event()
        self.no_request: bool = False

        # request flags
        self.request_id: int = -1         


    async def axi_handler_arbiter(self, request_axi: axi_and_coherence_request) ->  axi_request:

        print("=== cache to arbiter ===")
        print(request_axi)

        # Wait all cores to sumbit something
        async with self.lock_to_wait_for_all_cores:          

            # mark core as arrived and store its data
            self.cores_arrived += 1
            self.cores_axi_requsts[request_axi.core_id] = request_axi

            # all cores arrived
            if self.cores_arrived == self.num_requesters:
                # self.cores_arrived = 0
                self.all_arrived.set()


        await self.all_arrived.wait() # this will stall till all cores here


        # use core 0 to run abitration, in the verilog this
        # will be done by a verilog module
        async with self.lock_to_wait_for_all_cores:
            if request_axi.core_id == 0:
                self.no_request = False
                # build requests arr from axi_arr
                requests_in: List[int] = [] 
                for axi_request in self.cores_axi_requsts:
                    # need this cause axi_arr doesnt force type
                    if axi_request is None:
                        raise ValueError("axi_requests None")

                    requests_in.append(axi_request.mem_valid)

                # send this into nick arbitrate function
                requests_out: List[int] = self.arbitrate(requests_in)

                # find core to let through
                try:
                    self.request_id = requests_out.index(1)
                except ValueError:
                    self.no_request = True

                self.arbitation_done.set()

        await self.arbitation_done.wait() 

        if self.no_request:
            to_return: axi_request = axi_and_cohrenece_cmd_to_axi(request_axi) 

        # let each core through one by one to check if it got its turn
        curr_core_axi_packet_temp: Optional[axi_and_coherence_request] = self.cores_axi_requsts[request_axi.core_id]

        ## i need to spin here not send back invalid packet !!
        if curr_core_axi_packet_temp is not None:
            curr_core_axi_packet: axi_and_coherence_request = curr_core_axi_packet_temp;
        else:
            raise TypeError("curr_core_axi_packet is None")


        # see if core was chosen by arbiter
        if request_axi.core_id == self.request_id:
            # print(f"let {request_axi.core_id} core through")
            to_return: axi_request = await self.axi_send_and_recieve(curr_core_axi_packet)
        else:
            # print(f"didnt let {request_axi.core_id} core through")
            to_return: axi_request = axi_and_cohrenece_cmd_to_axi(request_axi) 
            # print(to_return)


        # clean up
        async with self.lock_to_wait_for_all_cores:        
            self.cores_arrived -= 1
            if self.cores_arrived == 0:
                self.all_arrived.clear()
                self.arbitation_done.clear()


        print("=== arbiter to cache ===")
        print(to_return)

        
        # print(to_return)
        return to_return

        
    def arbitrate(self, requests: List[int]) -> List[int]:

        # error checker
        if len(requests) != self.num_requesters:
            raise ValueError(
                f"Number of requests ({len(requests)}) must match "
                f"number of requesters ({self.num_requesters})"
            )
        
        # If no requests, return all zeros
        if sum(requests) == 0:
            return [0] * self.num_requesters
        

        # Search for the next requester with an active request
        attempts = 0
        while attempts < self.max_possible_iterations:

            # If current requester has a request, grant it
            if requests[self.current_index] == 1:
                grant = [0] * self.num_requesters
                grant[self.current_index] = 1
                
                # Decrement credits
                self.remaining_credits -= 1
                
                # Move to next requester if credits exhausted
                if self.remaining_credits == 0:
                    self.current_index = (self.current_index + 1) % self.num_requesters
                    self.remaining_credits = self.weights[self.current_index]
                
                return grant

            # Current requester has no request, move to next
            else:
                self.current_index = (self.current_index + 1) % self.num_requesters
                self.remaining_credits = self.weights[self.current_index]
                attempts += 1
        
        # Fallback (should never reach here with valid inputs)
        print("error ")
        raise Exception("abritation hit timeout")
