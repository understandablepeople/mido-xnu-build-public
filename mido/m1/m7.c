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


/* ---- eMMC full re-init from reset, SDHCI hc_mem @0x07824900 + core_mem @0x07824000 ---- */

#define SDHC		0x07824900UL
#define CORE		0x07824000UL

static uint32_t r32(unsigned o) { return *(volatile uint32_t *)(SDHC + o); }
static uint16_t r16(unsigned o) { return *(volatile uint16_t *)(SDHC + o); }
static uint8_t  r8(unsigned o)  { return *(volatile uint8_t *)(SDHC + o); }
static void w32(unsigned o, uint32_t v) { *(volatile uint32_t *)(SDHC + o) = v; }
static void w16(unsigned o, uint16_t v) { *(volatile uint16_t *)(SDHC + o) = v; }
static void w8(unsigned o, uint8_t v)   { *(volatile uint8_t *)(SDHC + o) = v; }
static uint32_t c32(unsigned o) { return *(volatile uint32_t *)(CORE + o); }
static void cw32(unsigned o, uint32_t v) { *(volatile uint32_t *)(CORE + o) = v; }

static void delay_us(unsigned us)
{
	uint64_t f = rsr("cntfrq_el0"), t0 = rsr("cntpct_el0");
	while ((rsr("cntpct_el0") - t0) < f / 1000000 * us)
		;
}

static void reg(const char *name, uint64_t v, int digits)
{
	puts_(name);
	hex(v, digits);
	puts_("  ");
}

static void cmd_reset(void)
{
	unsigned n;
	w8(0x2f, 0x06);				/* reset CMD + DAT lines */
	for (n = 0; n < 1000 && (r8(0x2f) & 6); n++)
		delay_us(10);
	w32(0x30, 0xffffffff);
}

/*
 * Returns 0 ok, else INT_STATUS (error bits) or 0x80000000 | state on poll timeout.
 * flags: bits1:0 response (0 none,1 136,2 48,3 48+busy), bit3 crc, bit4 index, bit5 data.
 */
static uint32_t cmd(unsigned idx, uint32_t arg, unsigned flags, unsigned mode, uint32_t resp[4])
{
	unsigned n;
	uint32_t st = 0;
	for (n = 0; n < 5000 && (r32(0x24) & 3); n++)
		delay_us(10);
	if (n == 5000) {
		cmd_reset();
		return 0x80000001;
	}
	w32(0x30, 0xffffffff);
	w32(0x08, arg);
	w32(0x0c, (uint32_t)mode | ((uint32_t)((idx << 8) | flags) << 16));
	for (n = 0; n < 200000; n++) {		/* up to ~1 s */
		st = r32(0x30);
		if ((st & 0x8000) || (st & 1))
			break;
		delay_us(5);
	}
	if (n == 200000 || (st & 0x8000)) {
		uint32_t r = (n == 200000) ? 0x80000002 : st;
		cmd_reset();
		return r;
	}
	if (resp) {
		resp[0] = r32(0x10); resp[1] = r32(0x14); resp[2] = r32(0x18); resp[3] = r32(0x1c);
	}
	w32(0x30, 1);
	if ((flags & 3) == 3) {
		for (n = 0; n < 400000 && !(r32(0x30) & 2); n++)
			delay_us(5);
		w32(0x30, 2);
	}
	return 0;
}

static void set_clock(unsigned n)		/* SDCLK = 200 MHz / (2*n), n = 0: base */
{
	unsigned i;
	uint16_t v;
	w16(0x2c, 0);
	v = (uint16_t)(((n & 0xff) << 8) | (((n >> 8) & 3) << 6) | 1);
	w16(0x2c, v);
	for (i = 0; i < 20000 && !(r16(0x2c) & 2); i++)
		delay_us(10);
	w16(0x2c, v | 4);
}

static uint32_t read_block(uint32_t arg, unsigned idx, unsigned char *buf)
{
	uint32_t r, st = 0, resp[4];
	unsigned n, i;

	w16(0x04, 0x0200);
	w16(0x06, 1);
	r = cmd(idx, arg, 0x3a, 0x0010, resp);	/* data present, read, PIO */
	if (r)
		return r;
	for (n = 0; n < 400000; n++) {
		st = r32(0x30);
		if (st & 0x20)
			break;
		if (st & 0x8000)
			return st;
		delay_us(5);
	}
	if (n == 400000)
		return 0x80000003;
	for (i = 0; i < 512; i += 4) {
		uint32_t v = r32(0x20);
		buf[i] = v; buf[i + 1] = v >> 8; buf[i + 2] = v >> 16; buf[i + 3] = v >> 24;
	}
	for (n = 0; n < 400000 && !(r32(0x30) & 2); n++)
		delay_us(5);
	w32(0x30, 0xffffffff);
	return 0;
}

static uint32_t le32(const unsigned char *p) { return p[0] | p[1] << 8 | p[2] << 16 | (uint32_t)p[3] << 24; }

__attribute__((visibility("hidden")))
void m1_exception(uint64_t slot)
{
	bg[0] = 0; bg[1] = 0; bg[2] = 160;
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

static void step(const char *name, uint32_t e, const uint32_t *resp)
{
	puts_(name);
	puts_(": ");
	hex(e, 8);
	if (resp) {
		putc_(' ');
		hex(resp[0], 8);
	}
	putc_('\n');
}

__attribute__((visibility("hidden")))
void m1_main(uintptr_t dtb_address, unsigned long lvl)
{
	struct node_state f = {0};
	static unsigned char buf[512] __attribute__((section(".data")));
	uint32_t e, resp[4] = {0, 0, 0, 0};
	unsigned n;

	if (dtb_address < 0x10000000 || dtb_address > 0x849f0000 || (dtb_address & 7))
		return;
	if (!framebuffer((const unsigned char *)dtb_address, &f))
		return;
	fb = (volatile unsigned char *)(uintptr_t)f.base;
	level = (unsigned int)lvl;
	clear();
	puts_("MIDO M7 eMMC RE-INIT, DLL OFF (NOT IOS)\n\n");

	puts_("vendor (hc-relative) before: ");
	reg("DLLCFG ", r32(0x100), 8); reg("VSPEC ", r32(0x10c), 8); reg("DDRCFG ", r32(0x118), 8);
	putc_('\n');

	/* 1. HC mode on, controller reset, then leave HS400/DLL selection (vendor regs live at hc+0x100..) */
	cw32(0x78, c32(0x78) | 1);
	w8(0x2f, 1);
	for (n = 0; n < 10000 && (r8(0x2f) & 1); n++)
		delay_us(10);
	puts_("reset all done, n="); hex(n, 4); putc_('\n');
	w32(0x100, (r32(0x100) | (1u << 29)) & ~((1u << 16) | (1u << 17) | (1u << 18) | (1u << 19)));
	w32(0x10c, (r32(0x10c) & ~((3u << 8) | (1u << 18) | (7u << 19))) | (2u << 8));
	puts_("after: DLLCFG "); hex(r32(0x100), 8); puts_(" VSPEC "); hex(r32(0x10c), 8); putc_('\n');
	w32(0x34, 0xffffffff);
	w32(0x38, 0);
	w8(0x29, 0);
	delay_us(1000);
	w8(0x29, 0x0b);
	w8(0x2e, 0x0e);
	w8(0x28, 0);
	w16(0x3e, 0);
	set_clock(250);
	delay_us(5000);
	puts_("clk "); hex(r16(0x2c), 4); puts_(" pwr "); hex(r8(0x29), 2); puts_(" pres "); hex(r32(0x24), 8); putc_('\n');

	/* 2. eMMC identification */
	e = cmd(0, 0, 0x00, 0, 0);
	step("CMD0", e, 0);
	delay_us(2000);
	for (n = 0; n < 200; n++) {
		e = cmd(1, 0x40ff8080u, 0x02, 0, resp);
		if (e || (resp[0] & 0x80000000u))
			break;
		delay_us(5000);
	}
	step("CMD1", e, resp);
	e = cmd(2, 0, 0x09, 0, resp);
	step("CMD2", e, resp);
	e = cmd(3, 1u << 16, 0x1a, 0, resp);
	step("CMD3", e, resp);
	e = cmd(7, 1u << 16, 0x1b, 0, resp);
	step("CMD7", e, resp);
	e = cmd(13, 1u << 16, 0x1a, 0, resp);
	step("CMD13", e, resp);

	/* 3. EXT_CSD */
	e = read_block(0, 8, buf);
	step("CMD8 EXT_CSD", e, 0);
	if (!e) {
		puts_("SEC_COUNT "); hex(le32(buf + 212), 8);
		puts_(" REV "); hex(buf[192], 2);
		puts_(" BUSW "); hex(buf[183], 2);
		puts_(" HST "); hex(buf[185], 2);
		puts_(" PART "); hex(buf[179], 2);
		putc_('\n');
		/* 4. 8-bit bus, high-speed 50 MHz */
		e = cmd(6, (3u << 24) | (183u << 16) | (2u << 8), 0x1b, 0, resp);
		step("SWITCH 8bit", e, resp);
		w8(0x28, r8(0x28) | 0x20);
		e = cmd(6, (3u << 24) | (185u << 16) | (1u << 8), 0x1b, 0, resp);
		step("SWITCH HS", e, resp);
		w8(0x28, r8(0x28) | 0x04);
		set_clock(2);			/* 50 MHz */
		delay_us(2000);
		e = cmd(13, 1u << 16, 0x1a, 0, resp);
		step("CMD13 after", e, resp);
		/* 5. GPT */
		e = read_block(1, 17, buf);
		step("GPT LBA1", e, 0);
		if (!e) {
			unsigned count = le32(buf + 80), ok = buf[0] == 'E' && buf[1] == 'F' && buf[2] == 'I';
			unsigned i, shown = 0;
			puts_(ok ? "EFI PART OK" : "BAD SIGNATURE");
			puts_(" entries "); hex(count, 3); putc_('\n');
			for (i = 0; ok && i < count && shown < 40; i++) {
				const unsigned char *ent;
				uint32_t first, last, any = 0, k;
				if (i % 4 == 0 && read_block(2 + i / 4, 17, buf))
					break;
				ent = buf + (i % 4) * 128;
				first = le32(ent + 32);
				last = le32(ent + 40);
				for (k = 0; k < 16; k++)
					any |= ent[k];
				if (!any)
					continue;
				hex(i + 1, 2); putc_(' ');
				for (k = 0; k < 14; k++) {
					unsigned char c = ent[56 + k * 2];
					putc_(c >= 0x20 && c < 0x7f && ent[57 + k * 2] == 0 ? c : ' ');
				}
				putc_(' '); hex(first, 8); putc_(' '); hex(last - first + 1, 8); putc_('\n');
				shown++;
			}
		}
	}
	puts_("\nDONE. Hold power to restart.\n");
}
