/*
 * FGE - Feature Gap Emulation. See fge.h.
 *
 * Encodings follow the Arm Architecture Reference Manual (DDI 0487) and are
 * checked against LLVM's assembler by tests/fge (encodings generated with
 * llvm-mc at test time, not typed in by hand).
 *
 * Copyright (c) 2026, macOS-Pad-6 contributors.
 * SPDX-License-Identifier: BSD-2-Clause-Patent
 */
#include "fge.h"

#define BITS(v, hi, lo) (((v) >> (lo)) & ((1u << ((hi) - (lo) + 1)) - 1u))

/* ---- register helpers -------------------------------------------------- */

static inline fge_u64
rx(const fge_ctx_t *c, unsigned n)          /* Xn, 31 = XZR */
{
	return n == 31 ? 0 : c->x[n];
}

static inline fge_u64
rxsp(const fge_ctx_t *c, unsigned n)        /* Xn|SP */
{
	return n == 31 ? c->sp : c->x[n];
}

static inline void
wx(fge_ctx_t *c, unsigned n, fge_u64 v)
{
	if (n != 31) {
		c->x[n] = v;
	}
}

static inline void
wxsp(fge_ctx_t *c, unsigned n, fge_u64 v)
{
	if (n == 31) {
		c->sp = v;
	} else {
		c->x[n] = v;
	}
}

static inline fge_s64
sext(fge_u64 v, unsigned bits)
{
	fge_u64 m = 1ull << (bits - 1);
	v &= (bits == 64) ? ~0ull : ((1ull << bits) - 1);
	return (fge_s64)((v ^ m) - m);
}

/* ---- classification ---------------------------------------------------- */

static int
is_pac_dp1(fge_u32 i)
{
	unsigned op, rn;

	if ((i & 0xFFFF0000u) != 0xDAC10000u) {   /* opcode in bits 15..10 */
		return 0;
	}
	op = BITS(i, 15, 10);
	rn = BITS(i, 9, 5);
	if (op <= 7) {
		return 1;                   /* PACIA..AUTDB: Xn|SP modifier */
	}
	if (op <= 17) {
		return rn == 31;            /* *Z forms and XPACI/XPACD need Rn = 11111 */
	}
	return 0;
}

static int
is_pacga(fge_u32 i)
{
	return (i & 0xFFE0FC00u) == 0x9AC03000u;
}

/* BRAA(Z)/BRAB(Z)/BLRAA(Z)/BLRAB(Z)/RETAA/RETAB. ERETAA/ERETAB are left alone. */
static int
is_pac_branch(fge_u32 i)
{
	unsigned opc, op3, rn, op4;

	if ((i >> 25) != 0x6Bu || BITS(i, 20, 16) != 31) {
		return 0;
	}
	opc = BITS(i, 24, 21);
	op3 = BITS(i, 15, 10);
	rn = BITS(i, 9, 5);
	op4 = BITS(i, 4, 0);
	if (op3 != 2 && op3 != 3) {
		return 0;
	}
	switch (opc) {
	case 0: /* BRAAZ, BRABZ */
	case 1: /* BLRAAZ, BLRABZ */
		return op4 == 31;
	case 2: /* RETAA, RETAB */
		return rn == 31 && op4 == 31;
	case 8: /* BRAA, BRAB */
	case 9: /* BLRAA, BLRAB */
		return 1;
	default:
		return 0;
	}
}

static int
is_pac_load(fge_u32 i)
{
	return (i & 0xFF200400u) == 0xF8200400u;
}

/* MSR/MRS with op0=3 op1=0 CRn=2 CRm=1..3: APIAKey..APGAKey (Lo/Hi). */
static int
is_pac_keyreg(fge_u32 i)
{
	unsigned crm, op2;

	if ((i & 0xFFDFF000u) != 0xD5182000u) {   /* L in bit 21 */
		return 0;
	}
	crm = BITS(i, 11, 8);
	op2 = BITS(i, 7, 5);
	if (crm == 1 || crm == 2) {
		return op2 <= 3;
	}
	if (crm == 3) {
		return op2 <= 1;
	}
	return 0;
}

static int
is_jscvt(fge_u32 i)
{
	return (i & 0xFFFFFC00u) == 0x1E7E0000u;
}

#define INSN_CFINV  0xD500401Fu
#define INSN_XAFLAG 0xD500403Fu
#define INSN_AXFLAG 0xD500405Fu
#define INSN_SB     0xD50330FFu

static int
is_rmif(fge_u32 i)
{
	return (i & 0xFFE07C10u) == 0xBA000400u;
}

static int
is_setf(fge_u32 i)
{
	return (i & 0xFFFFBC1Fu) == 0x3A00080Du;   /* bit 14: SETF16 */
}

static int
is_rcpc2(fge_u32 i)
{
	unsigned size, opc;

	if ((i & 0x3F200C00u) != 0x19000000u) {
		return 0;
	}
	size = BITS(i, 31, 30);
	opc = BITS(i, 23, 22);
	if (size == 2 && opc == 3) {
		return 0;
	}
	if (size == 3 && opc >= 2) {
		return 0;
	}
	return 1;
}

/* MSR DIT, #imm (op1=3, op2=2); MSR SSBS, #imm (op1=3, op2=1). */
static int
is_pstate_imm(fge_u32 i)
{
	return (i & 0xFFFFF0FFu) == 0xD503405Fu || (i & 0xFFFFF0FFu) == 0xD503403Fu;
}

/* MRS/MSR Xt, DIT (S3_3_C4_C2_5). */
static int
is_dit_reg(fge_u32 i)
{
	return (i & 0xFFDFFFE0u) == 0xD51B42A0u;
}

/* FEAT_SHA3 / FEAT_SHA512: crypto data processing, 0xCE000000 group. */
static int
is_sha3(fge_u32 i)
{
	if ((i & 0xFFC08000u) == 0xCE000000u) {        /* EOR3, BCAX */
		return 1;
	}
	if ((i & 0xFFE0FC00u) == 0xCE608C00u) {        /* RAX1 */
		return 1;
	}
	return (i & 0xFFE00000u) == 0xCE800000u;       /* XAR */
}

static int
is_sha512(fge_u32 i)
{
	if ((i & 0xFFE0F000u) == 0xCE608000u && BITS(i, 11, 10) != 3) {   /* SHA512H, H2, SU1 */
		return 1;
	}
	return (i & 0xFFFFFC00u) == 0xCEC08000u;       /* SHA512SU0 */
}

fge_class_t
fge_classify(fge_u32 i, int el)
{
	if (is_pac_dp1(i)) {
		return FGE_CLASS_PAC_DP1;
	}
	if (is_pacga(i)) {
		return FGE_CLASS_PACGA;
	}
	if (is_pac_branch(i)) {
		return FGE_CLASS_PAC_BRANCH;
	}
	if (is_pac_load(i)) {
		return FGE_CLASS_PAC_LOAD;
	}
	if (el == 1 && is_pac_keyreg(i)) {
		return FGE_CLASS_PAC_KEYREG;
	}
	if (is_jscvt(i)) {
		return FGE_CLASS_JSCVT;
	}
	/* Canonical encodings only: the should-be-zero CRm of CFINV/AXFLAG/XAFLAG
	 * is never set by an assembler. */
	if (i == INSN_CFINV || is_rmif(i) || is_setf(i)) {
		return FGE_CLASS_FLAGM;
	}
	if (i == INSN_AXFLAG || i == INSN_XAFLAG) {
		return FGE_CLASS_FLAGM2;
	}
	if (i == INSN_SB) {
		return FGE_CLASS_SB;
	}
	if (is_rcpc2(i)) {
		return FGE_CLASS_RCPC2;
	}
	if (is_pstate_imm(i) || is_dit_reg(i)) {
		return FGE_CLASS_PSTATE;
	}
	if (is_sha3(i)) {
		return FGE_CLASS_SHA3;
	}
	if (is_sha512(i)) {
		return FGE_CLASS_SHA512;
	}
	return FGE_CLASS_NONE;
}

const char *
fge_class_name(fge_class_t cls)
{
	static const char *const names[FGE_CLASS_COUNT] = {
		"none", "pac-dp1", "pacga", "pac-branch", "pac-load", "pac-keyreg",
		"jscvt", "flagm", "flagm2", "sb", "rcpc2", "pstate", "sha3", "sha512",
	};
	return ((unsigned)cls < FGE_CLASS_COUNT) ? names[cls] : "?";
}

/* ---- FJCVTZS ----------------------------------------------------------- */

/*
 * Arm pseudocode FPToFixedJS(): round toward zero, result modulo 2^32,
 * Z = 1 only for an exact, in-range, non-negative-zero conversion.
 * Integer-only so that it is safe in kernel context.
 */
fge_u32
fge_fjcvtzs(fge_u64 bits, fge_u32 fpcr, int *z, fge_u32 *fpsr_bits)
{
	unsigned sign = (unsigned)(bits >> 63);
	unsigned exp = (unsigned)((bits >> 52) & 0x7FF);
	fge_u64 frac = bits & ((1ull << 52) - 1);
	fge_u64 m, int_abs, low32;
	int e, inexact = 0, overflow = 0;
	fge_u32 res;

	*z = 1;
	*fpsr_bits = 0;

	if (exp == 0x7FF) {                       /* Inf or NaN */
		*z = 0;
		*fpsr_bits |= FGE_FPSR_IOC;
		return 0;
	}
	if (exp == 0 && frac != 0 && (fpcr & FGE_FPCR_FZ)) {
		*z = 0;                               /* flushed denormal: value 0 */
		*fpsr_bits |= FGE_FPSR_IDC;
		return 0;
	}
	if (exp == 0 && frac == 0) {
		*z = sign ? 0 : 1;                    /* -0.0 clears Z */
		return 0;
	}

	m = exp ? ((1ull << 52) | frac) : frac;
	e = (exp ? (int)exp : 1) - 1075;          /* value = m * 2^e */

	if (e >= 0) {
		/* |value| >= 2^52: out of int32 range; keep the low 32 bits. */
		overflow = 1;
		low32 = (e >= 32) ? 0 : ((m << e) & 0xFFFFFFFFull);
	} else {
		unsigned sh = (unsigned)(-e);
		if (sh >= 64) {
			int_abs = 0;
			inexact = 1;
		} else {
			int_abs = m >> sh;
			inexact = (m & ((1ull << sh) - 1)) != 0;
		}
		if (sign ? (int_abs > 0x80000000ull) : (int_abs > 0x7FFFFFFFull)) {
			overflow = 1;
		}
		low32 = int_abs & 0xFFFFFFFFull;
	}

	res = (fge_u32)low32;
	if (sign) {
		res = (fge_u32)(0u - res);
	}

	if (overflow) {
		*z = 0;
		*fpsr_bits |= FGE_FPSR_IOC;
	} else if (inexact) {
		*z = 0;
		*fpsr_bits |= FGE_FPSR_IXC;
	}
	return res;
}

/* ---- emulation --------------------------------------------------------- */

static fge_u64
pacga_mix(fge_u64 a, fge_u64 b, fge_u64 key)
{
	/* Deterministic per boot; any function works because every PACGA value
	 * that is later compared was produced by this same function. */
	fge_u64 h = a ^ (key + 0x9E3779B97F4A7C15ull);
	h ^= b + 0xBF58476D1CE4E5B9ull + (h << 6) + (h >> 2);
	h ^= h >> 30;
	h *= 0xBF58476D1CE4E5B9ull;
	h ^= h >> 27;
	h *= 0x94D049BB133111EBull;
	h ^= h >> 31;
	return (h & 0xFFFFFFFFull) << 32;
}

static fge_u32
flags_of(int n, int z, int c, int v)
{
	return (n ? FGE_N : 0) | (z ? FGE_Z : 0) | (c ? FGE_C : 0) | (v ? FGE_V : 0);
}

static fge_result_t
emu_flagm(fge_ctx_t *c, fge_u32 i)
{
	fge_u32 f = c->nzcv;
	int n = !!(f & FGE_N), z = !!(f & FGE_Z), cy = !!(f & FGE_C), v = !!(f & FGE_V);

	if (i == INSN_CFINV) {
		cy = !cy;
	} else if (i == INSN_XAFLAG) {
		int n2 = !cy && !z, z2 = z && cy, c2 = cy || z, v2 = !cy && z;
		n = n2; z = z2; cy = c2; v = v2;
	} else if (i == INSN_AXFLAG) {
		int z2 = z || v, c2 = cy && !v;
		n = 0; z = z2; cy = c2; v = 0;
	} else if (is_rmif(i)) {
		unsigned sh = BITS(i, 20, 15), mask = BITS(i, 3, 0);
		fge_u64 xn = rx(c, BITS(i, 9, 5));
		fge_u64 t = sh ? ((xn >> sh) | (xn << (64 - sh))) : xn;
		if (mask & 8) { n = (int)((t >> 3) & 1); }
		if (mask & 4) { z = (int)((t >> 2) & 1); }
		if (mask & 2) { cy = (int)((t >> 1) & 1); }
		if (mask & 1) { v = (int)(t & 1); }
	} else { /* SETF8 / SETF16 */
		unsigned w = (unsigned)rx(c, BITS(i, 9, 5));
		unsigned top = (i & (1u << 14)) ? 15 : 7;
		fge_u32 lowmask = (top == 15) ? 0xFFFFu : 0xFFu;
		n = (int)((w >> top) & 1);
		z = (w & lowmask) == 0;
		v = (int)(((w >> (top + 1)) ^ (w >> top)) & 1);
	}
	c->nzcv = (c->nzcv & ~(FGE_N | FGE_Z | FGE_C | FGE_V)) | flags_of(n, z, cy, v);
	return FGE_HANDLED;
}

static fge_result_t
emu_rcpc2(fge_ctx_t *c, fge_u32 i)
{
	unsigned size = BITS(i, 31, 30), opc = BITS(i, 23, 22);
	unsigned rn = BITS(i, 9, 5), rt = BITS(i, 4, 0);
	unsigned nbytes = 1u << size;
	fge_u64 addr = rxsp(c, rn) + (fge_u64)sext(BITS(i, 20, 12), 9);
	fge_u64 val = 0;

	if (opc == 0) {                         /* STLUR*: release store */
		fge_u64 src = rx(c, rt);
		if (c->write_mem == 0) {
			return FGE_NOT_HANDLED;
		}
		if (c->barrier) {
			c->barrier(c->cookie);
		}
		if (c->write_mem(c->cookie, addr, &src, nbytes) != 0) {   /* little-endian */
			return FGE_MEM_FAULT;
		}
		return FGE_HANDLED;
	}

	if (c->read_mem == 0) {
		return FGE_NOT_HANDLED;
	}
	if (c->read_mem(c->cookie, addr, &val, nbytes) != 0) {
		return FGE_MEM_FAULT;
	}
	if (c->barrier) {
		c->barrier(c->cookie);              /* acquire (RCpc) */
	}
	if (nbytes < 8) {
		val &= (1ull << (8 * nbytes)) - 1;
	}
	if (opc == 2) {                         /* sign-extend to 64 */
		val = (fge_u64)sext(val, 8 * nbytes);
	} else if (opc == 3) {                  /* sign-extend to 32, zero upper */
		val = (fge_u64)sext(val, 8 * nbytes) & 0xFFFFFFFFull;
	}
	wx(c, rt, val);
	return FGE_HANDLED;
}

static inline fge_u64
ror64(fge_u64 x, unsigned n)
{
	n &= 63;
	return n ? (x >> n) | (x << (64 - n)) : x;
}

static fge_u64 sha_S0(fge_u64 x) { return ror64(x, 28) ^ ror64(x, 34) ^ ror64(x, 39); }
static fge_u64 sha_S1(fge_u64 x) { return ror64(x, 14) ^ ror64(x, 18) ^ ror64(x, 41); }
static fge_u64 sha_s0(fge_u64 x) { return ror64(x, 1) ^ ror64(x, 8) ^ (x >> 7); }
static fge_u64 sha_s1(fge_u64 x) { return ror64(x, 19) ^ ror64(x, 61) ^ (x >> 6); }
static fge_u64 sha_ch(fge_u64 x, fge_u64 y, fge_u64 z) { return (x & y) ^ (~x & z); }
static fge_u64 sha_maj(fge_u64 x, fge_u64 y, fge_u64 z) { return (x & y) ^ (x & z) ^ (y & z); }

/*
 * Arm pseudocode of EOR3, BCAX, RAX1, XAR and SHA512H/H2/SU0/SU1 (lane 0 is
 * the low 64 bits). The result is a full 128-bit write, as these have no
 * 64-bit (D) form.
 */
static fge_result_t
emu_sha(fge_ctx_t *c, fge_u32 i)
{
	fge_vreg_t *v = c->v, d, n, m, a, r;

	if (v == 0) {
		return FGE_NOT_HANDLED;
	}
	d = v[BITS(i, 4, 0)];
	n = v[BITS(i, 9, 5)];
	m = v[BITS(i, 20, 16)];
	if ((i & 0xFFC08000u) == 0xCE000000u) {                   /* EOR3 / BCAX */
		a = v[BITS(i, 14, 10)];
		if (BITS(i, 21, 21) == 0) {
			r.lo = n.lo ^ m.lo ^ a.lo;
			r.hi = n.hi ^ m.hi ^ a.hi;
		} else {
			r.lo = n.lo ^ (m.lo & ~a.lo);
			r.hi = n.hi ^ (m.hi & ~a.hi);
		}
	} else if ((i & 0xFFE00000u) == 0xCE800000u) {            /* XAR */
		unsigned imm = BITS(i, 15, 10);
		r.lo = ror64(n.lo ^ m.lo, imm);
		r.hi = ror64(n.hi ^ m.hi, imm);
	} else if ((i & 0xFFFFFC00u) == 0xCEC08000u) {            /* SHA512SU0 */
		r.lo = d.lo + sha_s0(d.hi);
		r.hi = d.hi + sha_s0(n.lo);
	} else {
		switch (BITS(i, 11, 10)) {
		case 0:                                               /* SHA512H */
			r.hi = d.hi + sha_S1(m.hi) + sha_ch(m.hi, n.lo, n.hi);
			r.lo = d.lo + sha_S1(r.hi + m.lo) + sha_ch(r.hi + m.lo, m.hi, n.lo);
			break;
		case 1:                                               /* SHA512H2 */
			r.hi = d.hi + sha_S0(m.lo) + sha_maj(n.lo, m.hi, m.lo);
			r.lo = d.lo + sha_S0(r.hi) + sha_maj(r.hi, m.lo, m.hi);
			break;
		case 2:                                               /* SHA512SU1 */
			r.lo = d.lo + sha_s1(n.lo) + m.lo;
			r.hi = d.hi + sha_s1(n.hi) + m.hi;
			break;
		default:                                              /* RAX1 */
			r.lo = n.lo ^ ((m.lo << 1) | (m.lo >> 63));
			r.hi = n.hi ^ ((m.hi << 1) | (m.hi >> 63));
			break;
		}
	}
	v[BITS(i, 4, 0)] = r;
	return FGE_HANDLED;
}

fge_result_t
fge_emulate(fge_ctx_t *c, fge_u32 i, fge_class_t *out_cls)
{
	fge_class_t cls = fge_classify(i, c->el);
	fge_u64 next = c->pc + 4;
	fge_result_t r = FGE_HANDLED;

	if (out_cls) {
		*out_cls = cls;
	}

	switch (cls) {
	case FGE_CLASS_NONE:
		return FGE_NOT_HANDLED;

	case FGE_CLASS_PAC_DP1:
		/* null PAC: PAC* and AUT* leave Xd unchanged; XPAC* strips nothing
		 * because nothing was ever signed. */
		break;

	case FGE_CLASS_PACGA:
		wx(c, BITS(i, 4, 0),
		    pacga_mix(rx(c, BITS(i, 9, 5)), rxsp(c, BITS(i, 20, 16)), c->pacga_key));
		break;

	case FGE_CLASS_PAC_BRANCH: {
		unsigned opc = BITS(i, 24, 21), rn = BITS(i, 9, 5);
		fge_u64 target = (opc == 2) ? c->x[30] : rx(c, rn);
		if (opc == 1 || opc == 9) {
			c->x[30] = next;                 /* BLRAA*: link after reading Xn */
		}
		next = target;
		break;
	}

	case FGE_CLASS_PAC_LOAD: {
		unsigned rn = BITS(i, 9, 5), rt = BITS(i, 4, 0);
		fge_s64 off = sext((BITS(i, 22, 22) << 9) | BITS(i, 20, 12), 10) * 8;
		fge_u64 addr = rxsp(c, rn) + (fge_u64)off;
		fge_u64 val;
		if (c->read_mem == 0) {
			return FGE_NOT_HANDLED;
		}
		if (c->read_mem(c->cookie, addr, &val, 8) != 0) {
			return FGE_MEM_FAULT;
		}
		if (BITS(i, 11, 11)) {
			wxsp(c, rn, addr);               /* pre-index writeback */
		}
		wx(c, rt, val);
		break;
	}

	case FGE_CLASS_PAC_KEYREG:
		/* No key registers on ARMv8.2: writes are dropped, reads return 0. */
		if (BITS(i, 21, 21)) {
			wx(c, BITS(i, 4, 0), 0);
		}
		break;

	case FGE_CLASS_JSCVT: {
		int z;
		fge_u32 fl, res;
		if (c->v == 0) {
			return FGE_NOT_HANDLED;
		}
		res = fge_fjcvtzs(c->v[BITS(i, 9, 5)].lo, c->fpcr, &z, &fl);
		wx(c, BITS(i, 4, 0), (fge_u64)res);  /* W write zero-extends */
		c->nzcv = (c->nzcv & ~(FGE_N | FGE_Z | FGE_C | FGE_V)) | (z ? FGE_Z : 0);
		if (c->fpsr) {
			*c->fpsr |= fl;
		}
		break;
	}

	case FGE_CLASS_FLAGM:
	case FGE_CLASS_FLAGM2:
		r = emu_flagm(c, i);
		break;

	case FGE_CLASS_SB:
		/* The exception entry and return are context synchronizing and
		 * stop speculation past this point; nothing more to do. */
		break;

	case FGE_CLASS_RCPC2:
		r = emu_rcpc2(c, i);
		break;

	case FGE_CLASS_SHA3:
	case FGE_CLASS_SHA512:
		r = emu_sha(c, i);
		break;

	case FGE_CLASS_PSTATE:
		/* DIT and SSBS are hints for timing and speculation; the cores
		 * without them behave as with the feature off. MRS DIT reads 0. */
		if (is_dit_reg(i) && BITS(i, 21, 21)) {
			wx(c, BITS(i, 4, 0), 0);
		}
		break;

	default:
		return FGE_NOT_HANDLED;
	}

	if (r == FGE_HANDLED) {
		c->pc = next;
	}
	return r;
}

void
fge_stats_record(fge_stats_t *s, fge_result_t res, fge_class_t cls)
{
	if (res == FGE_HANDLED && (unsigned)cls < FGE_CLASS_COUNT) {
		s->count[cls]++;
	} else if (res == FGE_MEM_FAULT) {
		s->faults++;
	} else {
		s->not_handled++;
	}
}
