# Minimal RV32 template for Ibex stimulus replay (Difuzz-compatible markers)

  .section .text.init
  .align  6
  .weak stvec_handler
  .weak mtvec_handler
  .globl _start
_start:
  /* reset vector */
  addi x1,  zero, 0
  addi x2,  zero, 0
  addi x3,  zero, 0
  addi x4,  zero, 0
  addi x5,  zero, 0
  addi x6,  zero, 0
  addi x7,  zero, 0
  addi x8,  zero, 0
  addi x9,  zero, 0
  addi x10, zero, 0
  addi x11, zero, 0
  addi x12, zero, 0
  addi x13, zero, 0
  addi x14, zero, 0
  addi x15, zero, 0
  addi x16, zero, 0
  addi x17, zero, 0
  addi x18, zero, 0
  addi x19, zero, 0
  addi x20, zero, 0
  addi x21, zero, 0
  addi x22, zero, 0
  addi x23, zero, 0
  addi x24, zero, 0
  addi x25, zero, 0
  addi x26, zero, 0
  addi x27, zero, 0
  addi x28, zero, 0
  addi x29, zero, 0
  addi x30, zero, 0
  addi x31, zero, 0
  j reset_vector
 trap_stvec:
 trap_mtvec:
 _fuzz_trap:
   /* Fuzz trap */
   /**/
   jal ra, write_signature
write_tohost:
  li t0, 1
  la t1, tohost
  sw t0, 0(t1)
_test_end:
  j _test_end

write_signature:
  # Minimal, deterministic signature writer (RV32):
  # - Writes xregs as 64-bit little-endian (low32=data, high32=0).
  # - Writes a small CSR subset that is safe on Ibex.
  la t0, reg_x0_output
  sw x0,   0(t0); sw x0,   4(t0)
  sw x1,   8(t0); sw x0,  12(t0)
  sw x2,  16(t0); sw x0,  20(t0)
  sw x3,  24(t0); sw x0,  28(t0)
  sw x4,  32(t0); sw x0,  36(t0)
  sw x5,  40(t0); sw x0,  44(t0)
  sw x6,  48(t0); sw x0,  52(t0)
  sw x7,  56(t0); sw x0,  60(t0)
  sw x8,  64(t0); sw x0,  68(t0)
  sw x9,  72(t0); sw x0,  76(t0)
  sw x10, 80(t0); sw x0,  84(t0)
  sw x11, 88(t0); sw x0,  92(t0)
  sw x12, 96(t0); sw x0, 100(t0)
  sw x13,104(t0); sw x0, 108(t0)
  sw x14,112(t0); sw x0, 116(t0)
  sw x15,120(t0); sw x0, 124(t0)
  sw x16,128(t0); sw x0, 132(t0)
  sw x17,136(t0); sw x0, 140(t0)
  sw x18,144(t0); sw x0, 148(t0)
  sw x19,152(t0); sw x0, 156(t0)
  sw x20,160(t0); sw x0, 164(t0)
  sw x21,168(t0); sw x0, 172(t0)
  sw x22,176(t0); sw x0, 180(t0)
  sw x23,184(t0); sw x0, 188(t0)
  sw x24,192(t0); sw x0, 196(t0)
  sw x25,200(t0); sw x0, 204(t0)
  sw x26,208(t0); sw x0, 212(t0)
  sw x27,216(t0); sw x0, 220(t0)
  sw x28,224(t0); sw x0, 228(t0)
  sw x29,232(t0); sw x0, 236(t0)
  sw x30,240(t0); sw x0, 244(t0)
  sw x31,248(t0); sw x0, 252(t0)

  # CSR subset (safe on Ibex in M-mode):
  la t0, mhartid_output
  csrr t1, mhartid
  sw t1, 0(t0); sw x0, 4(t0)
  la t0, mstatus_output
  csrr t1, mstatus
  sw t1, 0(t0); sw x0, 4(t0)
  la t0, mie_output
  csrr t1, mie
  sw t1, 0(t0); sw x0, 4(t0)
  la t0, mscratch_output
  csrr t1, mscratch
  sw t1, 0(t0); sw x0, 4(t0)
  la t0, mepc_output
  csrr t1, mepc
  sw t1, 0(t0); sw x0, 4(t0)
  la t0, mcause_output
  csrr t1, mcause
  sw t1, 0(t0); sw x0, 4(t0)
  la t0, mtval_output
  csrr t1, mtval
  sw t1, 0(t0); sw x0, 4(t0)
  la t0, mip_output
  csrr t1, mip
  sw t1, 0(t0); sw x0, 4(t0)
  ret

reset_vector:
  csrwi mstatus, 0
  li t0, (3 << 11)
  csrs mstatus, t0
  la t0, trap_mtvec
  csrw mtvec, t0
_fuzz_prefix:
  /* Fuzz prefix */
  /**/
_end_prefix:
  la t0, main
  csrw mepc, t0
  mret

  .align 6
main:
_fuzz_main:
  /* Fuzz main */
  /**/
_end_main:
  ecall
  unimp

  .section .tohost,"aw",@progbits
  .align 4
  .globl tohost
  .globl fromhost
tohost:      .word 0
fromhost:    .word 0

  .section .data
  .align 8
  .globl begin_signature
begin_signature:
xreg_output_data:
  .globl reg_x0_output
reg_x0_output:  .dword 0
  .globl reg_x1_output
reg_x1_output:  .dword 0
  .globl reg_x2_output
reg_x2_output:  .dword 0
  .globl reg_x3_output
reg_x3_output:  .dword 0
  .globl reg_x4_output
reg_x4_output:  .dword 0
  .globl reg_x5_output
reg_x5_output:  .dword 0
  .globl reg_x6_output
reg_x6_output:  .dword 0
  .globl reg_x7_output
reg_x7_output:  .dword 0
  .globl reg_x8_output
reg_x8_output:  .dword 0
  .globl reg_x9_output
reg_x9_output:  .dword 0
  .globl reg_x10_output
reg_x10_output: .dword 0
  .globl reg_x11_output
reg_x11_output: .dword 0
  .globl reg_x12_output
reg_x12_output: .dword 0
  .globl reg_x13_output
reg_x13_output: .dword 0
  .globl reg_x14_output
reg_x14_output: .dword 0
  .globl reg_x15_output
reg_x15_output: .dword 0
  .globl reg_x16_output
reg_x16_output: .dword 0
  .globl reg_x17_output
reg_x17_output: .dword 0
  .globl reg_x18_output
reg_x18_output: .dword 0
  .globl reg_x19_output
reg_x19_output: .dword 0
  .globl reg_x20_output
reg_x20_output: .dword 0
  .globl reg_x21_output
reg_x21_output: .dword 0
  .globl reg_x22_output
reg_x22_output: .dword 0
  .globl reg_x23_output
reg_x23_output: .dword 0
  .globl reg_x24_output
reg_x24_output: .dword 0
  .globl reg_x25_output
reg_x25_output: .dword 0
  .globl reg_x26_output
reg_x26_output: .dword 0
  .globl reg_x27_output
reg_x27_output: .dword 0
  .globl reg_x28_output
reg_x28_output: .dword 0
  .globl reg_x29_output
reg_x29_output: .dword 0
  .globl reg_x30_output
reg_x30_output: .dword 0
  .globl reg_x31_output
reg_x31_output: .dword 0

  .align 8
freg_output_data:
  .globl reg_f0_output
reg_f0_output:  .dword 0
  .globl reg_f1_output
reg_f1_output:  .dword 0
  .globl reg_f2_output
reg_f2_output:  .dword 0
  .globl reg_f3_output
reg_f3_output:  .dword 0
  .globl reg_f4_output
reg_f4_output:  .dword 0
  .globl reg_f5_output
reg_f5_output:  .dword 0
  .globl reg_f6_output
reg_f6_output:  .dword 0
  .globl reg_f7_output
reg_f7_output:  .dword 0
  .globl reg_f8_output
reg_f8_output:  .dword 0
  .globl reg_f9_output
reg_f9_output:  .dword 0
  .globl reg_f10_output
reg_f10_output: .dword 0
  .globl reg_f11_output
reg_f11_output: .dword 0
  .globl reg_f12_output
reg_f12_output: .dword 0
  .globl reg_f13_output
reg_f13_output: .dword 0
  .globl reg_f14_output
reg_f14_output: .dword 0
  .globl reg_f15_output
reg_f15_output: .dword 0
  .globl reg_f16_output
reg_f16_output: .dword 0
  .globl reg_f17_output
reg_f17_output: .dword 0
  .globl reg_f18_output
reg_f18_output: .dword 0
  .globl reg_f19_output
reg_f19_output: .dword 0
  .globl reg_f20_output
reg_f20_output: .dword 0
  .globl reg_f21_output
reg_f21_output: .dword 0
  .globl reg_f22_output
reg_f22_output: .dword 0
  .globl reg_f23_output
reg_f23_output: .dword 0
  .globl reg_f24_output
reg_f24_output: .dword 0
  .globl reg_f25_output
reg_f25_output: .dword 0
  .globl reg_f26_output
reg_f26_output: .dword 0
  .globl reg_f27_output
reg_f27_output: .dword 0
  .globl reg_f28_output
reg_f28_output: .dword 0
  .globl reg_f29_output
reg_f29_output: .dword 0
  .globl reg_f30_output
reg_f30_output: .dword 0
  .globl reg_f31_output
reg_f31_output: .dword 0

  .align 8
csr_output_data:
  .globl fflags_output
fflags_output:   .dword 0
  .globl frm_output
frm_output:      .dword 0
  .globl fcsr_output
fcsr_output:     .dword 0
  .globl sstatus_output
sstatus_output:  .dword 0
  .globl sie_output
sie_output:      .dword 0
  .globl sscratch_output
sscratch_output: .dword 0
  .globl sepc_output
sepc_output:     .dword 0
  .globl scause_output
scause_output:   .dword 0
  .globl stval_output
stval_output:    .dword 0
  .globl sip_output
sip_output:      .dword 0
  .globl satp_output
satp_output:     .dword 0
  .globl mhartid_output
mhartid_output:  .dword 0
  .globl mstatus_output
mstatus_output:  .dword 0
  .globl medeleg_output
medeleg_output:  .dword 0
  .globl mie_output
mie_output:      .dword 0
  .globl mscratch_output
mscratch_output: .dword 0
  .globl mepc_output
mepc_output:     .dword 0
  .globl mcause_output
mcause_output:   .dword 0
  .globl mtval_output
mtval_output:    .dword 0
  .globl mip_output
mip_output:      .dword 0
  .globl pmpcfg0_output
pmpcfg0_output:  .dword 0
  .globl pmpaddr0_output
pmpaddr0_output: .dword 0
  .globl pmpaddr1_output
pmpaddr1_output: .dword 0
  .globl pmpaddr2_output
pmpaddr2_output: .dword 0
  .globl pmpaddr3_output
pmpaddr3_output: .dword 0
  .globl pmpaddr4_output
pmpaddr4_output: .dword 0
  .globl pmpaddr5_output
pmpaddr5_output: .dword 0
  .globl pmpaddr6_output
pmpaddr6_output: .dword 0
  .globl pmpaddr7_output
pmpaddr7_output: .dword 0

  .align 4
  .globl end_signature
end_signature:

  # Random data blocks (filled by preprocessor)
  .section .data.random0
  .align 8
  .globl _random_data0
  .globl _end_data0
_random_data0:
_end_data0:

  .section .data.random1
  .align 8
  .globl _random_data1
  .globl _end_data1
_random_data1:
_end_data1:

  .section .data.random2
  .align 8
  .globl _random_data2
  .globl _end_data2
_random_data2:
_end_data2:

  .section .data.random3
  .align 8
  .globl _random_data3
  .globl _end_data3
_random_data3:
_end_data3:

  .section .data.random4
  .align 8
  .globl _random_data4
  .globl _end_data4
_random_data4:
_end_data4:

  .section .data.random5
  .align 8
  .globl _random_data5
  .globl _end_data5
_random_data5:
_end_data5:

  .section .bss
  .align 4
  .globl _stack
  .globl _stack_top
_stack:
  .space 4096
_stack_top:

  # Page table stubs (some generated programs reference pt0-pt3)
  .align 12
  .globl pt0
  .globl pt1
  .globl pt2
  .globl pt3
pt0:
  .space 4096
pt1:
  .space 4096
pt2:
  .space 4096
pt3:
  .space 4096
