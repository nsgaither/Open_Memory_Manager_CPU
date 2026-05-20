# External
import math

# Types
from typing import Final

# Configrable
## memory sizes in btyes
MAIN_MEM_SIZE_IN_WORDS: Final = 4096
## cache configs
CACHE_LINE_SIZE_IN_WORDS: Final = 1
CACHE_MEM_SIZE_IN_WORDS: Final = 1024


# Calcs based on config
## cache line widths
OFFSET_WIDTH: int = int(math.log2(CACHE_LINE_SIZE_IN_WORDS))
NUM_CACHE_LINES: int = int(CACHE_MEM_SIZE_IN_WORDS/CACHE_LINE_SIZE_IN_WORDS)
INDEX_WIDTH: int = int(math.log2(NUM_CACHE_LINES))
TAG_WIDTH: int = 32 - (INDEX_WIDTH + OFFSET_WIDTH)
