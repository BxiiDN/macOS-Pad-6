/*
 * cpu_features_probe - read-only check of the CPU features macOS arm64e needs,
 * run on the Xiaomi Pad 6 under Android (no root, nothing written):
 *
 *   adb push build/device/cpu_features_probe /data/local/tmp/
 *   adb shell /data/local/tmp/cpu_features_probe
 *
 * It prints the kernel's AT_HWCAP/AT_HWCAP2 bits for each feature in
 * tools/isa/features.py, the MIDR of every CPU (from sysfs), and a verdict.
 * Freestanding: raw Linux syscalls, no libc, static position-independent ELF.
 *
 * Copyright (c) 2026, macOS-Pad-6 contributors.
 * SPDX-License-Identifier: BSD-2-Clause-Patent
 */
typedef unsigned long u64;
typedef long s64;

#define SYS_openat 56
#define SYS_close 57
#define SYS_read 63
#define SYS_write 64
#define SYS_exit_group 94
#define AT_FDCWD (-100)
#define AT_HWCAP 16
#define AT_HWCAP2 26

static s64
sys3(s64 n, s64 a, s64 b, s64 c)
{
	register s64 x8 __asm__("x8") = n;
	register s64 x0 __asm__("x0") = a;
	register s64 x1 __asm__("x1") = b;
	register s64 x2 __asm__("x2") = c;
	__asm__ volatile ("svc #0" : "+r"(x0) : "r"(x8), "r"(x1), "r"(x2) : "memory");
	return x0;
}

static s64
sys4(s64 n, s64 a, s64 b, s64 c, s64 d)
{
	register s64 x8 __asm__("x8") = n;
	register s64 x0 __asm__("x0") = a;
	register s64 x1 __asm__("x1") = b;
	register s64 x2 __asm__("x2") = c;
	register s64 x3 __asm__("x3") = d;
	__asm__ volatile ("svc #0" : "+r"(x0) : "r"(x8), "r"(x1), "r"(x2), "r"(x3) : "memory");
	return x0;
}

static unsigned
slen(const char *s)
{
	unsigned n = 0;
	while (s[n]) {
		n++;
	}
	return n;
}

static void
out(const char *s)
{
	sys3(SYS_write, 1, (s64)s, slen(s));
}

static void
out_hex(u64 v, int digits)
{
	char b[19];
	int k;
	b[0] = '0';
	b[1] = 'x';
	for (k = 0; k < digits; k++) {
		unsigned d = (unsigned)(v >> (4 * (digits - 1 - k))) & 0xF;
		b[2 + k] = (char)(d < 10 ? '0' + d : 'a' + d - 10);
	}
	b[2 + digits] = 0;
	out(b);
}

static s64
read_file(const char *path, char *buf, unsigned cap)
{
	s64 fd = sys4(SYS_openat, AT_FDCWD, (s64)path, 0, 0), n, got = 0;
	if (fd < 0) {
		return -1;
	}
	while (got < (s64)cap - 1 && (n = sys3(SYS_read, fd, (s64)(buf + got), cap - 1 - got)) > 0) {
		got += n;
	}
	sys3(SYS_close, fd, 0, 0);
	buf[got] = 0;
	return got;
}

/* Linux arm64 hwcap bits (arch/arm64/include/uapi/asm/hwcap.h). */
struct feat {
	char name[12];
	char hw2;                 /* 0: AT_HWCAP, 1: AT_HWCAP2 */
	char bit;
	char needed_by[24];
};

static const struct feat feats[] = {
	{ "paca",   0, 30, "arm64e (PAuth)" },
	{ "pacg",   0, 31, "arm64e (PACGA)" },
	{ "jscvt",  0, 13, "FJCVTZS" },
	{ "fcma",   0, 14, "FCMLA/FCADD" },
	{ "lrcpc",  0, 15, "LDAPR" },
	{ "ilrcpc", 0, 26, "LDAPUR (RCPC2)" },
	{ "flagm",  0, 27, "CFINV/RMIF/SETF" },
	{ "ssbs",   0, 28, "MSR SSBS" },
	{ "sb",     0, 29, "SB" },
	{ "dit",    0, 24, "MSR DIT" },
	{ "sha3",   0, 17, "EOR3/BCAX/XAR" },
	{ "sha512", 0, 21, "SHA512H" },
	{ "asimddp",0, 20, "UDOT/SDOT" },
	{ "flagm2", 1, 7,  "AXFLAG/XAFLAG" },
	{ "frint",  1, 8,  "FRINT32/64" },
	{ "bti",    1, 17, "BTI (hint)" },
};

int
probe_main(void)
{
	static char buf[4096];
	u64 hw[2] = { 0, 0 };
	s64 n, k;
	int cpu, paca = 0, pacg = 0;
	unsigned f;

	out("cpu_features_probe (macOS-Pad-6)\n");
	n = read_file("/proc/self/auxv", buf, sizeof(buf));
	if (n <= 0) {
		out("cannot read /proc/self/auxv\n");
		return 2;
	}
	for (k = 0; k + 16 <= n; k += 16) {
		u64 type = *(u64 *)(void *)(buf + k), val = *(u64 *)(void *)(buf + k + 8);
		if (type == AT_HWCAP) {
			hw[0] = val;
		} else if (type == AT_HWCAP2) {
			hw[1] = val;
		}
	}
	out("AT_HWCAP  ");
	out_hex(hw[0], 16);
	out("\nAT_HWCAP2 ");
	out_hex(hw[1], 16);
	out("\n\nfeature    present  used by\n");
	for (f = 0; f < sizeof(feats) / sizeof(feats[0]); f++) {
		int on = (int)((hw[(int)feats[f].hw2] >> feats[f].bit) & 1);
		unsigned pad = slen(feats[f].name);
		out(feats[f].name);
		while (pad++ < 11) {
			out(" ");
		}
		out(on ? "yes      " : "no       ");
		out(feats[f].needed_by);
		out("\n");
		if (f == 0) {
			paca = on;
		}
		if (f == 1) {
			pacg = on;
		}
	}

	out("\ncpu  midr_el1\n");
	for (cpu = 0; cpu < 16; cpu++) {
		char path[64] = "/sys/devices/system/cpu/cpu";
		unsigned p = slen(path);
		const char *tail = "/regs/identification/midr_el1";
		if (cpu >= 10) {
			path[p++] = '1';
		}
		path[p++] = (char)('0' + cpu % 10);
		while (*tail) {
			path[p++] = *tail++;
		}
		path[p] = 0;
		if (read_file(path, buf, 64) <= 0) {
			continue;
		}
		out(cpu >= 10 ? "" : " ");
		out_hex((u64)cpu, 1);
		out("  ");
		out(buf);                            /* sysfs value ends with a newline */
	}
	out("(0x41..d05: Cortex-A55, 0x41..d0d: Cortex-A77; Kryo 585 reports these)\n\n");

	if (paca && pacg) {
		out("verdict: PAuth present - arm64e can run natively (UniXNU arm64e profile).\n");
		return 0;
	}
	out("verdict: no PAuth - arm64e code (macOS userland, macOS kexts) traps here.\n"
	    "         It needs tools/isa/pacstrip on the kernel collection and kernel/fge\n"
	    "         in XNU (docs/feasibility.md).\n");
	return 1;
}

__asm__(
	".text\n"
	".globl _start\n"
	"_start:\n"
	"	mov x29, #0\n"
	"	bl probe_main\n"
	"	mov x8, #94\n"          /* exit_group */
	"	svc #0\n");
