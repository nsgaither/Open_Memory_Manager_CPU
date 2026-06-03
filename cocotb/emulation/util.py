from .axi_request_types import (axi_request, axi_and_coherence_request)

def apply_wstrb(old_value: int, new_value: int, wstrb: int) -> int:
    """
    Apply byte-level write strobe to merge new data with old data.
    
    This function implements byte-granular writes, allowing partial word updates.
    Each bit in wstrb controls whether the corresponding byte is updated.
    
    Args:
        old_value: Existing 32-bit value in cache
        new_value: New 32-bit value from CPU write
        wstrb: Write strobe mask (4 bits for 4 bytes)
               Bit 0 = byte 0 (bits [7:0])
               Bit 1 = byte 1 (bits [15:8])
               Bit 2 = byte 2 (bits [23:16])
               Bit 3 = byte 3 (bits [31:24])
    
    Returns:
        Merged 32-bit value with selected bytes updated    
    """
    result = old_value
    for i in range(4):  # 4 bytes in a 32-bit word
        if (wstrb >> i) & 1:  # Check if bit i is set
            # Update byte i
            byte_mask = 0xFF << (8 * i)  # Mask for byte i
            result = (result & ~byte_mask) | (new_value & byte_mask)
    return result

def axi_and_cohrenece_cmd_to_axi(to_cast: axi_and_coherence_request) -> axi_request:

    to_return: axi_request = axi_request(to_cast.mem_valid,
                                         to_cast.mem_instr,
                                         to_cast.mem_ready,
                                         to_cast.mem_addr,
                                         to_cast.mem_wdata_or_msi_payload,
                                         to_cast.mem_wstrb,
                                         to_cast.mem_rdata
                                     )

    return to_return
        
