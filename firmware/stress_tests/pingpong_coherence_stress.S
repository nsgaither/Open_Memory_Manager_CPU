/* SPDX-License-Identifier: Apache-2.0 */
/* Two-chip OMM interposer stress. Same image runs on both OMM_CPU chips. */

    .option norvc
    .option norelax
    .section .text.start, "ax", @progbits
    .globl _start

    .equ WHOAMI_ADDR, 0x80000000
    .equ GPIO_BASE,   0x80000010
    .equ GPIO_DIR,    0x80000018

    /*
     * Normal addresses go through the cache/interposer path. The pairs below
     * share low index bits but use different tag bits in the current RTL.
     */
    .equ SHARED_A0,   0x00000100
    .equ SHARED_A1,   0x00000180
    .equ SHARED_B0,   0x00000104
    .equ SHARED_B1,   0x00000184

_start:
    li   s0, GPIO_BASE
    li   s1, GPIO_DIR
    li   s2, WHOAMI_ADDR

    li   t0, 0xff
    sw   t0, 0(s1)

    lw   s3, 0(s2)
    andi s3, s3, 0xff
    andi s4, s3, 1

    li   s5, SHARED_A0
    li   s6, SHARED_A1
    li   a0, SHARED_B0
    li   a1, SHARED_B1

    li   a2, 0x12345678
    beqz s4, role_ready
    li   a2, 0x87654321

role_ready:
    add  a2, a2, s3
    li   a3, 0x9e3779b9
    li   a4, 7

loop:
    lw   t0, 0(s5)
    lw   t1, 0(a0)
    xor  t0, t0, a2
    add  t0, t0, t1
    mul  t2, t0, a3
    divu t3, t2, a4
    xor  t2, t2, t3

    beqz s4, cpu0_store

cpu1_store:
    sw   t2, 0(s5)
    sw   t0, 0(a1)
    j    status

cpu0_store:
    sw   t2, 0(s6)
    sw   t0, 0(a0)

status:
    xor  a2, a2, t2
    add  a2, a2, a3
    andi t4, a2, 1
    sw   t4, 0(s0)
    srli t4, a2, 1
    andi t4, t4, 1
    sw   t4, 1(s0)
    sw   s4, 2(s0)
    j    loop
