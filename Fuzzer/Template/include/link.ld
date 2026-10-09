OUTPUT_ARCH( "riscv" )
ENTRY(_start)

MEMORY
{
  ram   : ORIGIN = __dut_ram_base, LENGTH = __dut_ram_size - 0x8000
  stack : ORIGIN = __dut_ram_base + __dut_ram_size - 0x8000, LENGTH = 0x00008000
}

_min_stack = 0x2000;
_stack_start = ORIGIN(stack) + LENGTH(stack) - 16;
tohost = __dut_tohost;
fromhost = _stack_start + 0x10;

SECTIONS
{
  .text.init ORIGIN(ram) + __dut_boot_offset : { *(.text.init) } > ram
  .text.trap ALIGN(0x100) : { *(.text.trap) } > ram
  . = ALIGN(0x1000);
  .text : { *(.text) } > ram
  . = ALIGN(0x1000);
  .data : { *(.data) } > ram
  .bss : { *(.bss) } > ram
  .data.random0 ALIGN(0x10000) : { *(.data.random0) } > ram
  .data.random1 ALIGN(0x10000) : { *(.data.random1) } > ram
  .data.random2 ALIGN(0x10000) : { *(.data.random2) } > ram
  .data.random3 ALIGN(0x10000) : { *(.data.random3) } > ram
  .data.random4 ALIGN(0x10000) : { *(.data.random4) } > ram
  .data.random5 ALIGN(0x10000) : { *(.data.random5) } > ram
  .stack (NOLOAD) : {
    . = ALIGN(4);
    . = . + _min_stack;
    . = ALIGN(4);
    stack = .;
    _stack = .;
  } > stack
  _end = .;
}
