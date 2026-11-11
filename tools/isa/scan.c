/*
 * Fast classifier for tools/isa: the same rules as features.py, in C, so a
 * multi-gigabyte dyld shared cache can be scanned in seconds. Loaded through
 * ctypes by tools/isa/fast.py. tests/isa/test_scan.py checks parity with the
 * Python classifier on random words.
 *
 * Copyright (c) 2026, macOS-Pad-6 contributors.
 * SPDX-License-Identifier: BSD-2-Clause-Patent
 */
#include <stddef.h>
#include <stdint.h>

#include "rules.h"

static int
valid(int r, uint32_t w)
{
	unsigned op, rn, opc, op4, crm, op2, size, q;

	switch (r) {
	case R_PAC_DP1:
		op = (w >> 10) & 0x3F;
		rn = (w >> 5) & 0x1F;
		return op <= 7 || (op <= 17 && rn == 31);
	case R_PAC_BRANCH:
		opc = (w >> 21) & 0xF;
		rn = (w >> 5) & 0x1F;
		op4 = w & 0x1F;
		if (opc <= 1) {
			return op4 == 31;
		}
		if (opc == 2) {
			return rn == 31 && op4 == 31;
		}
		return opc == 8 || opc == 9;
	case R_PAC_KEYREG:
		crm = (w >> 8) & 0xF;
		op2 = (w >> 5) & 7;
		return ((crm == 1 || crm == 2) && op2 <= 3) || (crm == 3 && op2 <= 1);
	case R_RCPC2:
		size = w >> 30;
		opc = (w >> 22) & 3;
		return !((size == 2 && opc == 3) || (size == 3 && opc >= 2));
	case R_FCADD:
	case R_FCMLA:
		size = (w >> 22) & 3;
		q = (w >> 30) & 1;
		return size != 0 && !(size == 3 && q == 0);
	case R_FRINT_VECTOR:
		return !(((w >> 22) & 1) && !((w >> 30) & 1));
	case R_FCMLA_ELEM:
		size = (w >> 22) & 3;
		q = (w >> 30) & 1;
		if (size == 2) {
			return q == 1 && ((w >> 21) & 1) == 0;
		}
		if (size == 1) {
			return !(((w >> 11) & 1) && q == 0);
		}
		return 0;
	default:
		return 1;
	}
}

/* Rule index, or -1 for a word the SM8250 cores execute. */
int
isa_classify(uint32_t w)
{
	int r;

	for (r = 0; r < ISA_NRULES; r++) {
		if ((w & isa_rules[r].mask) == isa_rules[r].value && valid(r, w)) {
			return r;
		}
	}
	return -1;
}

int
isa_nrules(void)
{
	return ISA_NRULES;
}

const char *
isa_rule_name(int r)
{
	return (r >= 0 && r < ISA_NRULES) ? isa_rules[r].name : "";
}

/*
 * Count rule hits in n little-endian words. Word indices of hits whose rule
 * bit is set in record_mask are written to hits (at most hits_cap), and the
 * total number of such hits is returned through *hits_total.
 */
void
isa_scan(const uint32_t *words, size_t n, uint64_t *counts, uint64_t record_mask,
    uint64_t *hits, size_t hits_cap, size_t *hits_total, uint64_t base_index)
{
	size_t i, nh = *hits_total;

	for (i = 0; i < n; i++) {
		uint32_t w = words[i];
		int r;
		if (!isa_top[w >> 24]) {          /* no rule can match this top byte */
			continue;
		}
		r = isa_classify(w);
		if (r < 0) {
			continue;
		}
		counts[r]++;
		if (record_mask & (1ull << r)) {
			if (nh < hits_cap) {
				hits[nh] = base_index + i;
			}
			nh++;
		}
	}
	*hits_total = nh;
}
