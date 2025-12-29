# Verilator COCOTB Makefile

CWD=$(shell pwd)

SIM=verilator
CMD=verilator

export PYTHONPATH := $(CWD)/src:$(CWD)/RTLSim/src:$(PYTHONPATH)

# Prefer the project's venv Python when present so cocotb is discoverable even
# if the shell hasn't activated the venv.
VENV_PYTHON := $(CWD)/../.venv/bin/python
ifeq ($(wildcard $(VENV_PYTHON)),)
PYTHON ?= python3
else
PYTHON ?= $(VENV_PYTHON)
endif

# Locate cocotb makefiles without requiring `cocotb-config` on PATH.
COCOTB_MAKEFILES_DIR := $(shell $(PYTHON) -c "import pathlib, cocotb; print(pathlib.Path(cocotb.__file__).resolve().parent / 'share' / 'makefiles')")

TOPLEVEL_LAGN ?= verilog

TOPLEVEL ?= $(VFILE)

# Allow either .v or .sv benchmarks. You can pass VFILE=foo (auto-detect)
# or VFILE=foo.sv / VFILE=foo.v explicitly.
VFILE_BASENAME := $(basename $(VFILE))
VFILE_EXT := $(suffix $(VFILE))

# Extra args accumulated during source selection (e.g. -sv)
COMPILE_ARGS_EXTRA :=

ifeq ($(VFILE_EXT),)
    ifneq ($(wildcard $(CWD)/../Benchmarks/Verilog/$(VFILE_BASENAME).sv),)
        VERILOG_SOURCES = $(CWD)/../Benchmarks/Verilog/$(VFILE_BASENAME).sv
        COMPILE_ARGS_EXTRA += -sv
    else
        VERILOG_SOURCES = $(CWD)/../Benchmarks/Verilog/$(VFILE_BASENAME).v
    endif
else
    VERILOG_SOURCES = $(CWD)/../Benchmarks/Verilog/$(VFILE)
    ifeq ($(VFILE_EXT),.sv)
        COMPILE_ARGS_EXTRA += -sv
    endif
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

# Verilator: keep warnings but do not treat them as fatal by default.
VERILATOR_NONFATAL_WARNINGS ?= 1
ifeq ($(VERILATOR_NONFATAL_WARNINGS),1)
    COMPILE_ARGS_WARN := -Wno-fatal
else
    COMPILE_ARGS_WARN :=
endif

COMPILE_ARGS=$(MULTI) $(INCLUDE) -DPRINTF_COND=$(PRINTF_COND) -DSTOP_COND=$(STOP_COND) -Wno-PINMISSING $(COMPILE_ARGS_WARN) $(COMPILE_ARGS_EXTRA)
PLUSARGS=+DEBUG=$(PRINT) $(PLUSARGS_OUT)

MODULE=DifuzzRTL

CUSTOM_SIM_DEPS=$(CWD)/Makefile

include $(COCOTB_MAKEFILES_DIR)/Makefile.sim

sim: $(MODULE).py
