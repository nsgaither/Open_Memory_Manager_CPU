# External
import math

# Types
from typing import Final

# Configrable
## memory sizes in btyes
## 4x cache: 512 lines (index 9b) + 4b tag => 13-bit / 8192-word address space
MAIN_MEM_SIZE_IN_WORDS: Final = 8192
## cache configs
CACHE_LINE_SIZE_IN_WORDS: Final = 1
CACHE_MEM_SIZE_IN_WORDS: Final = 512


# Calcs based on config
## cache line widths
OFFSET_WIDTH: int = int(math.log2(CACHE_LINE_SIZE_IN_WORDS))
NUM_CACHE_LINES: int = int(CACHE_MEM_SIZE_IN_WORDS/CACHE_LINE_SIZE_IN_WORDS)
INDEX_WIDTH: int = int(math.log2(NUM_CACHE_LINES))
TAG_WIDTH: int = int(math.log2(MAIN_MEM_SIZE_IN_WORDS)) - (INDEX_WIDTH + OFFSET_WIDTH)
