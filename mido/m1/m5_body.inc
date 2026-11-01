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
	puts_("MIDO M5 eMMC FULL RE-INIT (NOT IOS)\n\n");

	puts_("vendor core before: ");
	reg("HCMODE ", c32(0x78), 8); reg("DLLCFG ", c32(0x100), 8); reg("VSPEC ", c32(0x10c), 8);
	reg("DLLST ", c32(0x108), 8);
	putc_('\n');

	/* 1. controller reset, then default (legacy) clock selection */
	w8(0x2f, 1);
	for (n = 0; n < 10000 && (r8(0x2f) & 1); n++)
		delay_us(10);
	puts_("reset all done, n="); hex(n, 4); putc_('\n');
	cw32(0x100, c32(0x100) | 2);		/* DLL power down (PDN) */
	cw32(0x10c, (c32(0x10c) & ~((3u << 8) | (1u << 18) | (7u << 19))) | (2u << 8));
	w32(0x34, 0xffffffff);			/* all status enabled, no signals: polled */
	w32(0x38, 0);
	w8(0x29, 0);
	delay_us(1000);
	w8(0x29, 0x0b);				/* 1.8 V, bus power on (eMMC VCCQ) */
	w8(0x2e, 0x0e);				/* timeout counter */
	w8(0x28, 0);				/* 1-bit, normal speed */
	w16(0x3e, 0);
	set_clock(250);				/* 400 kHz */
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
