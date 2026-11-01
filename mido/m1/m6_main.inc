static void dump(const char *name, unsigned long base, unsigned from, unsigned to)
{
	unsigned o;
	puts_(name);
	putc_('\n');
	for (o = from; o < to; o += 16) {
		hex(o, 3);
		puts_(":");
		for (unsigned k = 0; k < 16; k += 4) {
			putc_(' ');
			hex(*(volatile uint32_t *)(base + o + k), 8);
		}
		putc_('\n');
	}
}

static int try_cmd(const char *label)
{
	uint32_t resp[4] = {0, 0, 0, 0};
	uint32_t e = cmd(13, 1u << 16, 0x1a, 0, resp);
	puts_(label);
	puts_(" CMD13: ");
	hex(e, 8);
	puts_(" INT ");
	hex(r32(0x30), 4);
	putc_('\n');
	return e == 0;
}

__attribute__((visibility("hidden")))
void m1_main(uintptr_t dtb_address, unsigned long lvl)
{
	struct node_state f = {0};
	uint32_t st, e, resp[4] = {0, 0, 0, 0};
	unsigned n;

	if (dtb_address < 0x10000000 || dtb_address > 0x849f0000 || (dtb_address & 7))
		return;
	if (!framebuffer((const unsigned char *)dtb_address, &f))
		return;
	fb = (volatile unsigned char *)(uintptr_t)f.base;
	level = (unsigned int)lvl;
	clear();
	puts_("MIDO M6 SDHCI DIAG (READ MOSTLY, NOT IOS)\n");
	dump("core+0x00", CORE, 0x00, 0x40);
	dump("core+0x70", CORE, 0x70, 0x90);
	dump("core+0xd0", CORE, 0xd0, 0xf0);
	dump("core+0x100", CORE, 0x100, 0x130);
	dump("hc+0x100", SDHC, 0x100, 0x130);
	dump("hc+0xd0", SDHC, 0xd0, 0xf0);
	putc_('\n');

	if (try_cmd("A as-is"))
		goto done;
	st = c32(0xdc);
	puts_("PWRCTL status core+0xdc = "); hex(st, 8); puts_(" hc+0xdc = "); hex(*(volatile uint32_t *)(SDHC + 0xdc), 8); putc_('\n');
	if (st) {
		uint32_t ctl = 0;
		cw32(0xe0, st);
		if (st & 3)
			ctl |= 1;
		if (st & 0xc)
			ctl |= 4;
		cw32(0xe8, ctl);
		puts_("acked PWRCTL ctl="); hex(ctl, 4); putc_('\n');
		if (try_cmd("B after pwrctl ack"))
			goto done;
	}
	cw32(0x78, c32(0x78) | 1);
	puts_("HC_MODE now "); hex(c32(0x78), 8); putc_('\n');
	if (try_cmd("C after HC_MODE_EN"))
		goto done;
	/* D: slow clock, legacy timing, CMD0 + init */
	w16(0x2c, 0);
	w16(0x3e, 0);
	set_clock(250);
	delay_us(5000);
	e = cmd(0, 0, 0x00, 0, 0);
	puts_("D CMD0: "); hex(e, 8); putc_('\n');
	for (n = 0; n < 100; n++) {
		e = cmd(1, 0x40ff8080u, 0x02, 0, resp);
		if (e || (resp[0] & 0x80000000u))
			break;
		delay_us(5000);
	}
	puts_("D CMD1: "); hex(e, 8); putc_(' '); hex(resp[0], 8); putc_('\n');
done:
	puts_("PRES "); hex(r32(0x24), 8); puts_(" CLK "); hex(r16(0x2c), 4); puts_(" HCTL "); hex(r8(0x28), 2); puts_(" PWR "); hex(r8(0x29), 2); puts_(" HC2 "); hex(r16(0x3e), 4); putc_('\n');
	puts_("\nDONE. Hold power to restart.\n");
}
