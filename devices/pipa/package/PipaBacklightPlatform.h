// SPDX-License-Identifier: BSD-2-Clause-Patent
// What PipaBacklight.c needs from its environment: map and unmap a physical register window, read and write a 32-bit
// register in it, wait, read a boot argument, order device accesses, log. In the kernel (KERNEL defined) these are XNU's own calls; on the host the test
// (PipaBacklightTests.c) defines them over simulated register files. New in macOS-Pad-6.
#ifndef PIPA_BACKLIGHT_PLATFORM_H
#define PIPA_BACKLIGHT_PLATFORM_H
#include <stdint.h>
#include <stddef.h>

#ifdef KERNEL
#include <pexpert/pexpert.h>
extern unsigned long ml_io_map_unmappable(unsigned long phys_addr, unsigned long size, unsigned int flags);
extern void ml_io_unmap(unsigned long vaddr, unsigned long size);
extern void IODelay(unsigned microseconds);
extern int printf(const char *, ...);
// VM_WIMG_IO (7): device memory. Unmappable mappings, as UniXNU-sheng's BootReset.c explains: ml_io_map's cannot be freed.
static inline volatile uint32_t *pipa_map(uint64_t phys, uint64_t size) {
    return (volatile uint32_t *)ml_io_map_unmappable((unsigned long)phys, (unsigned long)size, 7);
}
static inline void pipa_unmap(volatile uint32_t *va, uint64_t size) {
    if (va) ml_io_unmap((unsigned long)va, (unsigned long)size);
}
static inline void pipa_delay_us(unsigned us) { IODelay(us); }
static inline int pipa_boot_arg(const char *name, uint32_t *value) { return PE_parse_boot_argn(name, value, sizeof(*value)) ? 1 : 0; }
static inline void pipa_barrier(void) { __asm__ volatile("dsb sy" ::: "memory"); }
static inline uint32_t pipa_rd(volatile uint32_t *base, uint32_t off) { return base[off / 4]; }
static inline void pipa_wr(volatile uint32_t *base, uint32_t off, uint32_t v) { base[off / 4] = v; pipa_barrier(); }
#define pipa_log printf
#else
volatile uint32_t *pipa_map(uint64_t phys, uint64_t size);
void pipa_unmap(volatile uint32_t *va, uint64_t size);
void pipa_delay_us(unsigned us);
int pipa_boot_arg(const char *name, uint32_t *value);
void pipa_barrier(void);
uint32_t pipa_rd(volatile uint32_t *base, uint32_t off);
void pipa_wr(volatile uint32_t *base, uint32_t off, uint32_t v);
int pipa_log(const char *fmt, ...);
#endif

#endif
