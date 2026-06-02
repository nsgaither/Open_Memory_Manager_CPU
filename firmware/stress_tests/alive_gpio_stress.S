/* SPDX-License-Identifier: Apache-2.0 */
/* Basic non-destructive bring-up stress for one or two OMM_CPU chips. */

    .option norvc
    .option norelax
    .section .text.start, "ax", @progbits
    .globl _start

    .equ WHOAMI_ADDR, 0x80000000
    .equ GPIO_BASE,   0x80000010
    .equ GPIO_DIR,    0x80000018

_start:
    li   s0, GPIO_BASE
    li   s1, GPIO_DIR
    li   s2, WHOAMI_ADDR

    li   t0, 0xff
    sw   t0, 0(s1)

    lw   s3, 0(s2)
    andi s3, s3, 0xff
    xori s4, s3, 0xa5
    ori  s4, s4, 1
    li   s5, 0x13579bdf
    li   s6, 0x01010101
    li   a7, 3

loop:
    add  s5, s5, s6
    xor  s4, s4, s5
    mul  t0, s4, s5
    divu t1, t0, a7
    xor  s4, s4, t1
    addi s4, s4, 0x31

    mv   t2, s4
    andi t3, t2, 1
    sw   t3, 0(s0)
    srli t2, t2, 1
    andi t3, t2, 1
    sw   t3, 1(s0)
    srli t2, t2, 1
    andi t3, t2, 1
    sw   t3, 2(s0)
    srli t2, t2, 1
    andi t3, t2, 1
    sw   t3, 3(s0)
    srli t2, t2, 1
    andi t3, t2, 1
    sw   t3, 4(s0)
    srli t2, t2, 1
    andi t3, t2, 1
    sw   t3, 5(s0)
    srli t2, t2, 1
    andi t3, t2, 1
    sw   t3, 6(s0)
    srli t2, t2, 1
    andi t3, t2, 1
    sw   t3, 7(s0)

    j    loop
