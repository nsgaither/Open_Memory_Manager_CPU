MAKEFILE_DIR := $(shell dirname $(realpath $(firstword $(MAKEFILE_LIST))))

RUN_TAG = $(shell ls librelane/runs/ | tail -n 1)
TOP = chip_top

PDK_ROOT ?= $(MAKEFILE_DIR)/gf180mcu
PDK ?= gf180mcuD
PDK_TAG ?= 1.8.0

AVAILABLE_SLOTS = 0p5x0p5
DEFAULT_SLOT = 0p5x0p5

# Slot can be any of AVAILABLE_SLOTS
SLOT ?= $(DEFAULT_SLOT)

ifeq ($(SLOT),default)        
    SLOT = $(DEFAULT_SLOT)
endif

ifeq ($(filter $(SLOT),$(AVAILABLE_SLOTS)),)
    $(error $(SLOT) does not exist in AVAILABLE_SLOTS: $(AVAILABLE_SLOTS))
endif

.DEFAULT_GOAL := help

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'
.PHONY: help

all: librelane ## Build the project (runs LibreLane)
.PHONY: all

clone-pdk: ## Clone the GF180MCU PDK repository
	rm -rf $(MAKEFILE_DIR)/gf180mcu
	git clone https://github.com/wafer-space/gf180mcu.git $(MAKEFILE_DIR)/gf180mcu --depth 1 --branch ${PDK_TAG}
.PHONY: clone-pdk

librelane: ## Run LibreLane flow (synthesis, PnR, verification)
	librelane librelane/slots/slot_${SLOT}.yaml librelane/config.yaml --save-views-to $(MAKEFILE_DIR)/final --pdk ${PDK} --pdk-root ${PDK_ROOT} --manual-pdk
.PHONY: librelane

librelane-nodrc: ## Run LibreLane flow without DRC checks
	librelane librelane/slots/slot_${SLOT}.yaml librelane/config.yaml --save-views-to $(MAKEFILE_DIR)/final --pdk ${PDK} --pdk-root ${PDK_ROOT} --manual-pdk --skip KLayout.Antenna --skip KLayout.DRC --skip Magic.DRC
.PHONY: librelane-nodrc

librelane-klayoutdrc: ## Run LibreLane flow without magic DRC checks
	librelane librelane/slots/slot_${SLOT}.yaml librelane/config.yaml --save-views-to $(MAKEFILE_DIR)/final --pdk ${PDK} --pdk-root ${PDK_ROOT} --manual-pdk --skip Magic.DRC
.PHONY: librelane-klayoutdrc

librelane-magicdrc: ## Run LibreLane flow without KLayout DRC checks
	librelane librelane/slots/slot_${SLOT}.yaml librelane/config.yaml --save-views-to $(MAKEFILE_DIR)/final --pdk ${PDK} --pdk-root ${PDK_ROOT} --manual-pdk --skip KLayout.DRC
.PHONY: librelane-magicdrc

librelane-openroad: ## Open the last run in OpenROAD
	librelane librelane/slots/slot_${SLOT}.yaml librelane/config.yaml --pdk ${PDK} --pdk-root ${PDK_ROOT} --manual-pdk --last-run --flow OpenInOpenROAD
.PHONY: librelane-openroad

librelane-klayout: ## Open the last run in KLayout
	librelane librelane/slots/slot_${SLOT}.yaml librelane/config.yaml --pdk ${PDK} --pdk-root ${PDK_ROOT} --manual-pdk --last-run --flow OpenInKLayout
.PHONY: librelane-klayout

librelane-padring: ## Only create the padring
	PDK_ROOT=${PDK_ROOT} PDK=${PDK} python3 scripts/padring.py librelane/slots/slot_${SLOT}.yaml librelane/config.yaml
.PHONY: librelane-padring

sim: ## Run RTL simulation with cocotb
	cd cocotb; PDK_ROOT=${PDK_ROOT} PDK=${PDK} SLOT=${SLOT} python3 chip_top_tb.py
.PHONY: sim

sim-gl: ## Run gate-level simulation with cocotb (after final views are populated)
	cd cocotb; GL=1 PDK_ROOT=${PDK_ROOT} PDK=${PDK} SLOT=${SLOT} python3 chip_top_tb.py
.PHONY: sim-gl

SDF_CORNER ?= max_tt_025C_5v00
SDF_FILE ?= $(MAKEFILE_DIR)/final/sdf/$(SDF_CORNER)/$(TOP)__$(SDF_CORNER).sdf
SDF_INTERCONNECT ?= 0

sim-sdf: ## Run gate-level SDF timing simulation (SDF_CORNER=max_tt_025C_5v00)
	@echo "Running SDF gate-level timing simulation (corner: $(SDF_CORNER))..."
	@if [ ! -f "$(SDF_FILE)" ]; then \
		echo "Error: SDF file not found at $(SDF_FILE)"; \
		echo "Available corners:"; \
		ls "$(MAKEFILE_DIR)/final/sdf/"; \
		echo "Usage: make sim-sdf SDF_CORNER=max_ff_n40C_5v50"; \
		exit 1; \
	fi
	@mkdir -p cocotb/sim_build
	@cd cocotb; \
		GL=1 SDF=1 SDF_FILE=$(SDF_FILE) SDF_CORNER=$(SDF_CORNER) SDF_INTERCONNECT=$(SDF_INTERCONNECT) PDK_ROOT=${PDK_ROOT} PDK=${PDK} SLOT=${SLOT} \
		python3 chip_top_tb.py > sim_build/chip_top_sdf.log 2>&1; \
		status=$$?; \
		grep -E "SDF: annotating|TESTS=" sim_build/chip_top_sdf.log || true; \
		if [ $$status -ne 0 ]; then \
			echo "sim-sdf failed; last 80 log lines:"; \
			tail -n 80 sim_build/chip_top_sdf.log; \
		fi; \
		echo "Full sim-sdf log: cocotb/sim_build/chip_top_sdf.log"; \
		exit $$status
.PHONY: sim-sdf

sim-sdf-view: ## View SDF simulation waveforms in GTKWave
	gtkwave cocotb/sim_build/chip_top.fst
.PHONY: sim-sdf-view

sim-view: ## View simulation waveforms in GTKWave
	gtkwave cocotb/sim_build/chip_top.fst
.PHONY: sim-view

render-image: ## Render an image from the final layout
	mkdir -p img/
	PDK_ROOT=${PDK_ROOT} PDK=${PDK} python3 scripts/lay2img.py final/gds/${TOP}.gds img/${TOP}.png --width 2048 --oversampling 4
.PHONY: render-image

test-chip-top: ## Run chip_top cocotb testbench
	cd cocotb; PDK_ROOT=${PDK_ROOT} PDK=${PDK} SLOT=${SLOT} python3 chip_top_tb.py
.PHONY: test-chip-top

test-cocotb-clean: ## Clean cocotb build files
	rm -rf cocotb/sim_build* cocotb/__pycache__ cocotb/*.fst cocotb/*.vcd
.PHONY: test-cocotb-clean

# ─── Cocotb testbench targets (following OMM pattern) ────────────────────────

test-cache-controller: ## Run cache controller cocotb testbench
	cd cocotb; PDK_ROOT=${PDK_ROOT} PDK=${PDK} SLOT=${SLOT} python3 cache_controller_tb.py
.PHONY: test-cache-controller

test-cache-interface: ## Run cache interface cocotb testbench
	cd cocotb; PDK_ROOT=${PDK_ROOT} PDK=${PDK} SLOT=${SLOT} python3 cache_interface_tb.py
.PHONY: test-cache-interface

test-cache-mem: ## Run cache memory cocotb testbench
	cd cocotb; PDK_ROOT=${PDK_ROOT} PDK=${PDK} SLOT=${SLOT} python3 cache_mem_tb.py
.PHONY: test-cache-mem

test-cache-sram: ## Run cache SRAM golden-model cocotb testbench
	cd cocotb; PDK_ROOT=${PDK_ROOT} PDK=${PDK} SLOT=${SLOT} python3 cache_sram_test.py
.PHONY: test-cache-sram

test-mem128x32: ## Run mem128x32 cocotb testbench
	cd cocotb; PDK_ROOT=${PDK_ROOT} PDK=${PDK} SLOT=${SLOT} python3 mem128x32_tb.py
.PHONY: test-mem128x32

test-mem-ctrl-512: ## Run mem_ctrl_512x32 cocotb testbench
	cd cocotb; PDK_ROOT=${PDK_ROOT} PDK=${PDK} SLOT=${SLOT} python3 mem_ctrl_512x32_tb.py
.PHONY: test-mem-ctrl-512

test-two-port-cache-mem: ## Run two_port_cache_mem cocotb testbench
	cd cocotb; PDK_ROOT=${PDK_ROOT} PDK=${PDK} SLOT=${SLOT} python3 two_port_cache_mem_tb.py
.PHONY: test-two-port-cache-mem

test-mem-ctrl-128x4: ## Run mem_ctrl_128x4 cocotb testbench
	cd cocotb; PDK_ROOT=${PDK_ROOT} PDK=${PDK} SLOT=${SLOT} python3 test_mem_ctrl_128x4.py
.PHONY: test-mem-ctrl-128x4

test-all: ## Run all cocotb testbenches via test_all_cocotb.py
	cd cocotb; PDK_ROOT=${PDK_ROOT} PDK=${PDK} SLOT=${SLOT} python3 test_all_cocotb.py
.PHONY: test-all

clean-sim: ## Remove all sim_build dirs in cocotb
	rm -rf cocotb/sim_build*
.PHONY: clean-sim
