/*
 * mido M1: 24bpp text console + hardware probes, RAM-only (loaded by lk2nd).
 *
 * Reuses the already hardware-validated entry (EL1/EL2, MMU+D-cache off,
 * x0 = DTB) and the strict simplefb parser of devices/mido/screen-test.
 * Every probe prints its label BEFORE touching hardware, so if a read
 * faults or hangs the photo shows where it stopped. Faults draw ESR/ELR/FAR.
 * Nothing here writes to the phone's storage or enables the MMU/GIC.
 */
#include <stdint.h>
#include <stddef.h>
#include "font.h"

#include "fdt_fb.inc"

#define FB_W		1080
#define FB_H		1920
#define FB_STRIDE	3240
#define SCALE		2
#define CH_W		(8 * SCALE)
#define CH_H		(16 * SCALE)
#define MARGIN		12
#define COLS		((FB_W - 2 * MARGIN) / CH_W)

#define rsr(r) ({ uint64_t _v; __asm__ volatile("mrs %0, " r : "=r"(_v)); _v; })

/* State lives in .data: the linker script forbids .bss. */
static volatile unsigned char *fb __attribute__((section(".data"))) = 0;
static unsigned int col __attribute__((section(".data"))) = 0;
static unsigned int row __attribute__((section(".data"))) = 0;
static unsigned int level __attribute__((section(".data"))) = 1;
static unsigned char fg[3] __attribute__((section(".data"))) = {255, 255, 255};
static unsigned char bg[3] __attribute__((section(".data"))) = {40, 24, 8};

static void put_px(unsigned int x, unsigned int y, const unsigned char *c)
{
	volatile unsigned char *p = fb + (size_t)y * FB_STRIDE + x * 3;
	p[0] = c[0];
	p[1] = c[1];
	p[2] = c[2];
}

static void clear(void)
{
	for (unsigned int y = 0; y < FB_H; y++)
		for (unsigned int x = 0; x < FB_W; x++)
			put_px(x, y, bg);
	col = row = 0;
}

static void putc_(char ch)
{
	if (ch == '\n') {
		col = 0;
		row++;
		return;
	}
	if (ch < 0x20 || ch > 0x7e)
		ch = '?';
	if (col >= COLS) {
		col = 0;
		row++;
	}
	unsigned int x0 = MARGIN + col * CH_W, y0 = MARGIN + row * CH_H;
	if (y0 + CH_H > FB_H)
		return;
	const unsigned char *g = font8x16[ch - 0x20];
	for (unsigned int gy = 0; gy < 16; gy++)
		for (unsigned int gx = 0; gx < 8; gx++) {
			const unsigned char *c = (g[gy] & (0x80 >> gx)) ? fg : bg;
			for (unsigned int sy = 0; sy < SCALE; sy++)
				for (unsigned int sx = 0; sx < SCALE; sx++)
					put_px(x0 + gx * SCALE + sx, y0 + gy * SCALE + sy, c);
		}
	col++;
	__asm__ volatile("dsb sy" ::: "memory");
}

static void puts_(const char *s)
{
	while (*s)
		putc_(*s++);
}

static void hex(uint64_t v, int digits)
{
	static const char h[] = "0123456789ABCDEF";
	for (int i = digits - 1; i >= 0; i--)
		putc_(h[(v >> (4 * i)) & 15]);
}

static void line(const char *label, uint64_t v, int digits)
{
	puts_(label);
	hex(v, digits);
	putc_('\n');
}

/* ---- tiny FDT walker: print /memory, /reserved-memory, /chosen, /cpus ---- */

static int starts(const char *s, const char *p)
{
	while (*p)
		if (*s++ != *p++)
			return 0;
	return 1;
}

static int same(const char *a, const char *b)
{
	while (*a && *a == *b)
		a++, b++;
	return *a == *b;
}

static void dump_fdt(const unsigned char *d)
{
	uint32_t p = read_be32(d + 8), strings = read_be32(d + 12);
	uint32_t end = p + read_be32(d + 36);
	const char *names[8];
	int depth = 0;
	char path[96];

	puts_("DTB bytes ");
	hex(read_be32(d + 4), 8);
	putc_('\n');
	while (p + 4 <= end) {
		uint32_t tok = read_be32(d + p);
		p += 4;
		if (tok == 1) {
			const char *n = (const char *)(d + p);
			uint32_t l = 0;
			while (n[l])
				l++;
			if (depth < 8)
				names[depth] = n;
			depth++;
			p = (p + l + 1 + 3) & ~3U;
		} else if (tok == 2) {
			depth--;
		} else if (tok == 3) {
			uint32_t len = read_be32(d + p), off = read_be32(d + p + 4);
			const unsigned char *v = d + p + 8;
			const char *pn = (const char *)(d + strings + off);
			int n = 0;
			/* build "/a/b" path of the current node */
			path[0] = 0;
			for (int i = 1; i < depth && i < 8 && n < 80; i++) {
				path[n++] = '/';
				for (const char *s = names[i]; *s && n < 90; s++)
					path[n++] = *s;
			}
			path[n] = 0;
			if (same(pn, "reg") && (starts(path, "/memory") || starts(path, "/reserved-memory/")) && len >= 16) {
				puts_(path);
				putc_(' ');
				for (uint32_t o = 0; o + 16 <= len; o += 16) {
					hex(read_be64(v + o), 9);
					putc_('+');
					hex(read_be64(v + o + 8), 8);
					putc_(' ');
				}
				putc_('\n');
			} else if (starts(path, "/chosen") && path[7] == 0) {
				puts_(" chosen.");
				puts_(pn);
				putc_('=');
				if (len == 4)
					hex(read_be32(v), 8);
				else if (len == 8)
					hex(read_be64(v), 16);
				else if (len > 1 && len < 40 && v[len - 1] == 0 && v[0] >= 0x20)
					puts_((const char *)v);
				else {
					puts_("len ");
					hex(len, 4);
				}
				putc_('\n');
			}
			p = (p + 8 + len + 3) & ~3U;
		} else if (tok == 9) {
			break;
		}
	}
}

/* ---- probes ---- */

static uint64_t psci(uint64_t fn, uint64_t a1)
{
	register uint64_t x0 __asm__("x0") = fn;
	register uint64_t x1 __asm__("x1") = a1;
	register uint64_t x2 __asm__("x2") = 0;
	register uint64_t x3 __asm__("x3") = 0;
	__asm__ volatile("smc #0" : "+r"(x0), "+r"(x1), "+r"(x2), "+r"(x3)
			 :
			 : "x4", "x5", "x6", "x7", "x8", "x9", "x10", "x11", "x12", "x13",
			   "x14", "x15", "x16", "x17", "memory");
	return x0;
}

static uint32_t rd32(uintptr_t a)
{
	return *(volatile uint32_t *)a;
}

static void color_bars(void)
{
	/* Memory byte order test: which colour does each bar show? */
	static unsigned char c[3][3] __attribute__((section(".data"))) = {
		{255, 0, 0}, {0, 255, 0}, {0, 0, 255}};
	unsigned int y0 = MARGIN + (row + 1) * CH_H;
	for (unsigned int b = 0; b < 3; b++)
		for (unsigned int y = y0; y < y0 + 60; y++)
			for (unsigned int x = 60 + b * 330; x < 60 + b * 330 + 300; x++)
				put_px(x, y, c[b]);
	row += 4;
	puts_("bars: bytes B0=FF | B1=FF | B2=FF  (left..right)\n");
}

__attribute__((visibility("hidden")))
void m1_exception(uint64_t slot)
{
	unsigned char red[3] = {0, 0, 160};
	bg[0] = red[0];
	bg[1] = red[1];
	bg[2] = red[2];
	puts_("\n*** EXCEPTION slot ");
	hex(slot, 2);
	putc_('\n');
	line("ESR ", level == 1 ? rsr("esr_el1") : rsr("esr_el2"), 16);
	line("ELR ", level == 1 ? rsr("elr_el1") : rsr("elr_el2"), 16);
	line("FAR ", level == 1 ? rsr("far_el1") : rsr("far_el2"), 16);
	puts_("HALTED\n");
	for (;;)
		__asm__ volatile("wfe");
}

__attribute__((visibility("hidden")))
void m1_main(uintptr_t dtb_address, unsigned long lvl)
{
	struct node_state f = {0};

	if (dtb_address < 0x10000000 || dtb_address > 0x849f0000 || (dtb_address & 7))
		return;
	if (!framebuffer((const unsigned char *)dtb_address, &f))
		return;
	fb = (volatile unsigned char *)(uintptr_t)f.base;
	level = (unsigned int)lvl;
	clear();

	puts_("MIDO M1 PROBE (RAM ONLY, NOT IOS)\n\n");
	line("DTB     ", dtb_address, 9);
	line("EL      ", lvl, 1);
	line("SCTLR1  ", rsr("sctlr_el1"), 8);
	line("MIDR    ", rsr("midr_el1"), 8);
	line("MPIDR   ", rsr("mpidr_el1"), 8);
	line("CNTFRQ  ", rsr("cntfrq_el0"), 8);
	line("CTR     ", rsr("ctr_el0"), 8);
	line("PFR0    ", rsr("id_aa64pfr0_el1"), 16);
	line("ISAR0   ", rsr("id_aa64isar0_el1"), 16);
	line("MMFR0   ", rsr("id_aa64mmfr0_el1"), 16);
	line("MMFR1   ", rsr("id_aa64mmfr1_el1"), 16);
	if (lvl == 2)
		line("HCR     ", rsr("hcr_el2"), 16);
	putc_('\n');
	dump_fdt((const unsigned char *)dtb_address);
	putc_('\n');
	color_bars();
	putc_('\n');

	puts_("GICD CTLR/TYPER/IIDR ");
	{
		uint32_t a = rd32(0x0b000000), b = rd32(0x0b000004), c = rd32(0x0b000008);
		hex(a, 8);
		putc_(' ');
		hex(b, 8);
		putc_(' ');
		hex(c, 8);
		putc_('\n');
	}
	puts_("GICC CTLR/PMR/IIDR   ");
	{
		uint32_t a = rd32(0x0b002000), b = rd32(0x0b002004), c = rd32(0x0b0020fc);
		hex(a, 8);
		putc_(' ');
		hex(b, 8);
		putc_(' ');
		hex(c, 8);
		putc_('\n');
	}
	puts_("PSCI VERSION ");
	hex(psci(0x84000000UL, 0), 8);
	putc_('\n');
	puts_("PSCI CPU_ON feat ");
	hex(psci(0x8400000aUL, 0xc4000003UL), 8);
	putc_('\n');
	puts_("PSCI SYS_RESET feat ");
	hex(psci(0x8400000aUL, 0x84000009UL), 8);
	putc_('\n');
	puts_("\nDONE. Hold power to restart.\n");
}
