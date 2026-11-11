/*
 * Host test of kernel/xnu/fge_xnu.c against the shim headers: register
 * marshalling, the atomic copy paths and the boot-arg switch, with copyin and
 * friends backed by a fake user address space. Built and run by check.sh.
 * Encodings were produced with llvm-mc (see the comment on each case).
 * SPDX-License-Identifier: BSD-2-Clause-Patent
 */
#include <stdio.h>
#include <string.h>
#include <arm64/fge_xnu.h>
#include <arm/misc_protos.h>
#include <kern/misc_protos.h>
#include <pexpert/pexpert.h>

#define USER_BASE 0x10000ull
static unsigned char user_mem[0x1000];
static int n_in32, n_in64, n_out32, n_out64, n_in, n_out;
static int bootarg_fge = 1;

static unsigned char *
umem(user_addr_t a, size_t n)
{
	return (a >= USER_BASE && a + n <= USER_BASE + sizeof(user_mem)) ? user_mem + (a - USER_BASE) : NULL;
}

int copyin(const user_addr_t a, void *k, size_t n) { n_in++; unsigned char *p = umem(a, n); if (!p) return 14; memcpy(k, p, n); return 0; }
int copyout(const void *k, user_addr_t a, size_t n) { n_out++; unsigned char *p = umem(a, n); if (!p) return 14; memcpy(p, k, n); return 0; }
int copyin_atomic32(const user_addr_t a, uint32_t *k) { n_in32++; unsigned char *p = umem(a, 4); if (!p || (a & 3)) return 14; memcpy(k, p, 4); return 0; }
int copyin_atomic64(const user_addr_t a, uint64_t *k) { n_in64++; unsigned char *p = umem(a, 8); if (!p || (a & 7)) return 14; memcpy(k, p, 8); return 0; }
int copyout_atomic32(uint32_t v, user_addr_t a) { n_out32++; unsigned char *p = umem(a, 4); if (!p || (a & 3)) return 14; memcpy(p, &v, 4); return 0; }
int copyout_atomic64(uint64_t v, user_addr_t a) { n_out64++; unsigned char *p = umem(a, 8); if (!p || (a & 7)) return 14; memcpy(p, &v, 8); return 0; }
int copyin_kern(const user_addr_t a, char *k, vm_size_t n) { memcpy(k, (const void *)(uintptr_t)a, n); return 0; }
int copyout_kern(const char *k, user_addr_t a, vm_size_t n) { memcpy((void *)(uintptr_t)a, k, n); return 0; }
uint64_t early_random(void) { return 0x1234; }
boolean_t PE_parse_boot_argn(const char *s, void *p, int n) { (void)s; (void)n; *(int *)p = bootarg_fge; return 1; }
void kprintf(const char *fmt, ...) { (void)fmt; }

static int failures, checks;
#define CHECK(c) do { checks++; if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); failures++; } } while (0)

static arm_context_t ctx;
static arm_saved_state64_t *ss = &ctx.ss.uss.ss_64;

static void
reset(uint32_t insn, uint32_t cpsr)
{
	memset(&ctx, 0, sizeof(ctx));
	memset(user_mem, 0, sizeof(user_mem));
	ctx.ss.ash.flavor = ARM_SAVED_STATE64;
	ctx.ns.nsh.flavor = ARM_NEON_SAVED_STATE64;
	ctx.ns.nsh.count = ARM_NEON_SAVED_STATE64_COUNT;
	ss->pc = USER_BASE;
	ss->cpsr = cpsr;
	memcpy(user_mem, &insn, 4);
	n_in32 = n_in64 = n_out32 = n_out64 = n_in = n_out = 0;
}

int
main(void)
{
	uint64_t v;

	/* blraa x8, x17 (0xd73f0911) at EL0: links x30, jumps, keeps NZCV and mode bits. */
	reset(0xD73F0911u, 0x60000000u);
	ss->x[8] = 0x40000;
	CHECK(fge_xnu_handle(&ctx));
	CHECK(ss->pc == 0x40000 && ss->lr == USER_BASE + 4 && ss->cpsr == 0x60000000u);

	/* ldapurh w1, [x2, #2] (0x59402041): one aligned 32-bit read, upper half extracted. */
	reset(0x59402041u, 0);
	ss->x[2] = USER_BASE + 0x100;
	v = 0xBEEF1234u;
	memcpy(user_mem + 0x100, &v, 4);
	CHECK(fge_xnu_handle(&ctx));
	CHECK(ss->x[1] == 0xBEEF && n_in32 == 1 && n_in == 1);   /* n_in: the instruction fetch */

	/* ldapur x3, [x4, #-3] (0xd95fd083): unaligned, falls back to copyin. */
	reset(0xD95FD083u, 0);
	ss->x[4] = USER_BASE + 0x204;          /* address 0x201: unaligned */
	v = 0x1122334455667788ull;
	memcpy(user_mem + 0x201, &v, 8);
	CHECK(fge_xnu_handle(&ctx));
	CHECK(ss->x[3] == 0x1122334455667788ull && n_in == 2 && n_in64 == 0);   /* fetch + data */

	/* stlur x5, [x6, #8] (0xd90080c5): aligned, copyout_atomic64. */
	reset(0xD90080C5u, 0);
	ss->x[5] = 0xCAFEF00DDEADBEEFull;
	ss->x[6] = USER_BASE + 0x300;
	CHECK(fge_xnu_handle(&ctx));
	memcpy(&v, user_mem + 0x308, 8);
	CHECK(v == 0xCAFEF00DDEADBEEFull && n_out64 == 1 && n_out == 0);

	/* ldraa x9, [x10, #16] (0xf8202549): aligned 64-bit, copyin_atomic64. */
	reset(0xF8202549u, 0);
	ss->x[10] = USER_BASE + 0x400;
	v = 77;
	memcpy(user_mem + 0x410, &v, 8);
	CHECK(fge_xnu_handle(&ctx));
	CHECK(ss->x[9] == 77 && n_in64 == 1 && ss->pc == USER_BASE + 4);

	/* A read outside user memory: not handled, state unchanged. */
	reset(0xF8202549u, 0);
	ss->x[10] = 0x9990000;
	CHECK(!fge_xnu_handle(&ctx));
	CHECK(ss->pc == USER_BASE && ss->x[9] == 0);

	/* fjcvtzs w0, d1 (0x1e7e0020) reads V1 from the NEON state and sets Z. */
	reset(0x1E7E0020u, 0x20000000u);
	v = 0x4045000000000000ull;               /* 42.0 */
	memcpy(&ctx.ns.ns_64.v.q[1], &v, 8);
	CHECK(fge_xnu_handle(&ctx));
	CHECK(ss->x[0] == 42 && ss->cpsr == 0x40000000u);

	/* An ordinary instruction (add, 0x8b000000) is left to the caller. */
	reset(0x8B000000u, 0);
	CHECK(!fge_xnu_handle(&ctx));

	/* Kernel mode: ldraa reads kernel memory with one aligned load. */
	{
		static uint64_t kword[4] = { 0, 0, 5, 0 };
		static uint32_t kinsn = 0xF8202549u;
		reset(0, 0x5);                       /* EL1h */
		ss->pc = (uint64_t)(uintptr_t)&kinsn;
		ss->x[10] = (uint64_t)(uintptr_t)&kword[0];
		CHECK(fge_xnu_handle(&ctx));
		CHECK(ss->x[9] == 5 && n_in64 == 0);
	}

	printf("glue host test: %d checks, %d failures\n", checks, failures);
	return failures != 0;
}
