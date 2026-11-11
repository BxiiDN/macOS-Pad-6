/*
 * XNU glue for FGE. See fge_xnu.h and docs/architecture.md.
 *
 * Requirements this file checks or relies on:
 *  - The kernel collection was rewritten by tools/isa/pacstrip and verified by
 *    tools/isa/audit (no non-hint PAC instruction left in kernel or kexts).
 *    Otherwise every kernel function return traps, including this file's.
 *  - The saved state is not signed with PACGA. With HAS_APPLE_PAC (needed for
 *    arm64e processes and kexts) that means the null-PAC mode of
 *    profiles/macos-26.5 (HAS_NULL_PAC: the thread-state hash is constant), so
 *    registers can be written straight into the saved state.
 *  - Emulated accesses keep single-copy atomicity for naturally aligned 4- and
 *    8-byte accesses (copyin_atomic*, copyout_atomic*, or one load/store in
 *    the kernel); aligned 1- and 2-byte loads read the aligned 32-bit word that
 *    holds them. Aligned 2-byte stores from user space are copied bytewise.
 *
 * Copyright (c) 2026, macOS-Pad-6 contributors.
 * SPDX-License-Identifier: BSD-2-Clause-Patent
 */
#include <arm64/fge.h>
#include <arm64/fge_xnu.h>

#include <arm/misc_protos.h>
#include <arm64/proc_reg.h>
#include <kern/misc_protos.h>
#include <machine/atomic.h>
#include <mach/arm/thread_status.h>
#include <pexpert/pexpert.h>

#if HAS_APPLE_PAC && !HAS_NULL_PAC
#error "FGE writes the saved state directly; a PACGA-signed thread state needs MANIPULATE_SIGNED_THREAD_STATE here"
#endif

uint64_t fge_xnu_counts[16];

static int      fge_mode = -1;          /* -1 unread, 0 off, 1 on, 2 on + log */
static uint64_t fge_key;

static void
fge_xnu_init(void)
{
	int mode = 1;

	if (!PE_parse_boot_argn("fge", &mode, sizeof(mode))) {
		mode = 1;
	}
	fge_key = early_random();
	fge_mode = mode;                    /* benign race: every reader computes the same */
}

static int
fge_read_user(void *cookie __unused, fge_u64 addr, void *dst, unsigned size)
{
	uint32_t w;
	int err;

	if (size == 8 && (addr & 7) == 0) {
		return copyin_atomic64((user_addr_t)addr, (uint64_t *)dst);
	}
	if (size <= 4 && (addr & (size - 1)) == 0) {
		/* One aligned 32-bit read holds the whole aligned 1, 2 or 4 bytes. */
		err = copyin_atomic32((user_addr_t)(addr & ~3ull), &w);
		if (err == 0) {
			w >>= 8 * (unsigned)(addr & 3);
			__builtin_memcpy(dst, &w, size);
		}
		return err;
	}
	return copyin((user_addr_t)addr, (char *)dst, size);
}

static int
fge_write_user(void *cookie __unused, fge_u64 addr, const void *src, unsigned size)
{
	if (size == 8 && (addr & 7) == 0) {
		uint64_t v;
		__builtin_memcpy(&v, src, 8);
		return copyout_atomic64(v, (user_addr_t)addr);
	}
	if (size == 4 && (addr & 3) == 0) {
		uint32_t v;
		__builtin_memcpy(&v, src, 4);
		return copyout_atomic32(v, (user_addr_t)addr);
	}
	return copyout((const char *)src, (user_addr_t)addr, size);
}

static int
fge_read_kern(void *cookie __unused, fge_u64 addr, void *dst, unsigned size)
{
	/* An aligned access is one load, as the original instruction was; a
	 * bad kernel address faults here exactly as it would have there. */
	switch ((addr & (size - 1)) == 0 ? size : 0) {
	case 1: *(uint8_t *)dst = *(volatile uint8_t *)addr; return 0;
	case 2: { uint16_t v = *(volatile uint16_t *)addr; __builtin_memcpy(dst, &v, 2); return 0; }
	case 4: { uint32_t v = *(volatile uint32_t *)addr; __builtin_memcpy(dst, &v, 4); return 0; }
	case 8: { uint64_t v = *(volatile uint64_t *)addr; __builtin_memcpy(dst, &v, 8); return 0; }
	default: return copyin_kern((user_addr_t)addr, (char *)dst, size);
	}
}

static int
fge_write_kern(void *cookie __unused, fge_u64 addr, const void *src, unsigned size)
{
	switch ((addr & (size - 1)) == 0 ? size : 0) {
	case 1: *(volatile uint8_t *)addr = *(const uint8_t *)src; return 0;
	case 2: { uint16_t v; __builtin_memcpy(&v, src, 2); *(volatile uint16_t *)addr = v; return 0; }
	case 4: { uint32_t v; __builtin_memcpy(&v, src, 4); *(volatile uint32_t *)addr = v; return 0; }
	case 8: { uint64_t v; __builtin_memcpy(&v, src, 8); *(volatile uint64_t *)addr = v; return 0; }
	default: return copyout_kern((const char *)src, (user_addr_t)addr, size);
	}
}

static void
fge_barrier(void *cookie __unused)
{
	__builtin_arm_dmb(DMB_ISH);
}

bool
fge_xnu_handle(arm_context_t *context)
{
	arm_saved_state_t *state = &context->ss;
	arm_saved_state64_t *ss;
	fge_ctx_t ctx;
	fge_class_t cls = FGE_CLASS_NONE;
	fge_result_t res;
	uint32_t insn = 0;
	bool kernel;
	unsigned r;

	if (__improbable(fge_mode < 0)) {
		fge_xnu_init();
	}
	if (fge_mode == 0 || !is_saved_state64(state)) {
		return false;
	}
	ss = saved_state64(state);
	kernel = PSR64_IS_KERNEL(ss->cpsr);
	if (!kernel && !PSR64_IS_USER64(ss->cpsr)) {
		return false;
	}

	if (kernel) {
		insn = *(volatile uint32_t *)ss->pc;
	} else if (copyin((user_addr_t)ss->pc, (char *)&insn, sizeof(insn)) != 0) {
		return false;
	}

	for (r = 0; r < 29; r++) {
		ctx.x[r] = ss->x[r];
	}
	ctx.x[29] = ss->fp;
	ctx.x[30] = ss->lr;
	ctx.sp = ss->sp;
	ctx.pc = ss->pc;
	ctx.nzcv = ss->cpsr;
	ctx.el = kernel ? 1 : 0;
	if (context->ns.nsh.flavor == ARM_NEON_SAVED_STATE64 &&
	    context->ns.nsh.count == ARM_NEON_SAVED_STATE64_COUNT) {
		ctx.v = (fge_vreg_t *)(void *)&context->ns.ns_64.v.q[0];
		ctx.fpsr = &context->ns.ns_64.fpsr;
		ctx.fpcr = context->ns.ns_64.fpcr;
	} else {
		ctx.v = NULL;
		ctx.fpsr = NULL;
		ctx.fpcr = 0;
	}
	ctx.read_mem = kernel ? fge_read_kern : fge_read_user;
	ctx.write_mem = kernel ? fge_write_kern : fge_write_user;
	ctx.barrier = fge_barrier;
	ctx.cookie = NULL;
	ctx.pacga_key = fge_key;

	res = fge_emulate(&ctx, insn, &cls);
	if (res != FGE_HANDLED) {
		/* FGE_MEM_FAULT: the original instruction would have faulted; the
		 * caller's undefined-instruction path reports it. A precise data
		 * abort is a later refinement (docs/roadmap.md). */
		return false;
	}

	for (r = 0; r < 29; r++) {
		ss->x[r] = ctx.x[r];
	}
	ss->fp = ctx.x[29];
	ss->lr = ctx.x[30];
	ss->sp = ctx.sp;
	ss->pc = ctx.pc;
	ss->cpsr = (ss->cpsr & 0x0FFFFFFFu) | (ctx.nzcv & 0xF0000000u);

	if ((unsigned)cls < 16) {
		uint64_t n = os_atomic_inc(&fge_xnu_counts[cls], relaxed);
		if (fge_mode == 2 && (n & 0xFFFFF) == 0) {
			kprintf("fge: %s %llu (pc 0x%llx)\n", fge_class_name(cls),
			    (unsigned long long)n, (unsigned long long)ss->pc);
		}
	}
	return true;
}
