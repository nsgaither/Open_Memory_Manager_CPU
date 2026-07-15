# SRAM macros -- 4x cache layout.
#
# Three 3.3V ocd macros, all orientation N and all 301.30um wide (the ocd
# 1024x8 and 512x8 share the same width), placed as a west-edge column:
#   data.sram0 / data.sram1  = ocd 1024x8  (data, 512 words x 32b)
#   tag.sram0                = ocd 512x8   (tag+state, 512 x 6b)
# Because they share width and orientation, one NS grid with a single stripe
# geometry powers all three.

define_pdn_grid \
    -macro \
    -instances "i_chip_core.u_cache_controller.cache_mem.u_cache_mem.data.sram0 \
                i_chip_core.u_cache_controller.cache_mem.u_cache_mem.data.sram1 \
                i_chip_core.u_cache_controller.cache_mem.u_cache_mem.tag.sram0" \
    -name sram_macros_NS \
    -starts_with POWER \
    -halo "$::env(PDN_HORIZONTAL_HALO) $::env(PDN_VERTICAL_HALO)"

add_pdn_connect \
    -grid sram_macros_NS \
    -layers "$::env(PDN_VERTICAL_LAYER) $::env(PDN_HORIZONTAL_LAYER)"

add_pdn_connect \
    -grid sram_macros_NS \
    -layers "$::env(PDN_VERTICAL_LAYER) Metal3"

# Add stripes on W/E edges of SRAM (one strap near each vertical edge of the
# 301.30um-wide macros).
add_pdn_stripe \
    -grid sram_macros_NS \
    -layer Metal4 \
    -width 1.36 \
    -offset 0.68 \
    -spacing 0.28 \
    -pitch 298.30 \
    -starts_with GROUND \
    -number_of_straps 2

# Since the above stripes block the top level PDN at Metal4, add some more stripes
# to improve the PDN's integrity and ensure a better connection for the macro.
add_pdn_stripe \
    -grid sram_macros_NS \
    -layer Metal4 \
    -width 4.00 \
    -offset 50.80 \
    -spacing 0.28 \
    -pitch 48.86 \
    -starts_with GROUND \
    -number_of_straps 5
