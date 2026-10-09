# Verilator COCOTB Makefile

CWD=$(shell pwd)

SIM=verilator
CMD=verilator

PYTHONPATH := $(CWD)/src:$(CWD)/RTLSim/src:$(PYTHONPATH)

TOPLEVEL_LANG ?= verilog

TOPLEVEL ?= $(VFILE)
VERILOG_SOURCES = $(CWD)/../Benchmarks/Verilog/$(VFILE).v
ifeq ($(VFILE),Ibex)
VERILOG_SOURCES = $(IBEX_RTL) $(IBEX_WATCHDOG) $(IBEX_TB)
COMPILE_ARGS += -Wno-fatal -Wno-UNOPTFLAT -Wno-WIDTHEXPAND -I$(IBEX_MANIFEST) $(IBEX_DEFINES)
TOPLEVEL = ibex_tb_top
export FUZZER_TOPLEVEL ?= Ibex
else ifneq ($(DUT_RTL),)
VERILOG_SOURCES = $(DUT_RTL) $(DUT_WATCHDOG) $(DUT_TB)
COMPILE_ARGS += -I$(DUT_MANIFEST) $(DUT_DEFINES)
TOPLEVEL := $(VFILE)_tb_top
export FUZZER_TOPLEVEL ?= $(if $(filter ibex,$(VFILE)),Ibex,$(if $(filter cva6,$(VFILE)),cva6,picorv32_verif_top))
endif
COCOTB_HDL_TIMEUNIT=1us
COCOTB_HDL_TIMEPRECISION=1us

OUT ?= output

ifdef DEBUG
    PRINT=$(DEBUG)
    PRINTF_COND=0
else
    PRINT=0
endif

ifdef MULTICORE
    MULTI=-DMULTICORE
    PLUSARGS_OUT=+OUT=$(OUT)
else
    MULTI=
    PLUSARGS_OUT=
endif

ifeq ($(VFILE), RocketTile_VHarness)
    INCLUDE=-I $(CWD)/../Benchmarks/Verilog/RocketTile_mux.v
else
    INCLUDE=
endif

PRINTF_COND ?= 0
STOP_COND ?= 0

COMPILE_ARGS += $(MULTI) $(INCLUDE) -DPRINTF_COND=$(PRINTF_COND) -DSTOP_COND=$(STOP_COND) -Wno-PINMISSING
PLUSARGS=+DEBUG=$(PRINT) $(PLUSARGS_OUT)

MODULE=DifuzzRTL

CUSTOM_SIM_DEPS=$(CWD)/Makefile

include $(shell cocotb-config --makefiles)/Makefile.sim

.PHONY: sim
sim: $(COCOTB_RESULTS_FILE)
