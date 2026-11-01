#!/bin/bash
# Build the SWEET iOS root: one case-sensitive HFS+ image holding an iOS OS
# root filesystem plus its cryptexes, for the userdata partition (rd=ufsroot0).
#
#   mkiosroot_d21ap.sh OS.dmg SYSTEMOS.dmg APPOS.dmg OUT.img [SIZE]   (SIZE default 16G)
#
# D21AP (iPhone 8 Plus, iPhone10,2) / mido variant of tools/mkiosroot.sh (kept
# byte-for-byte unmodified). Differences, all documented in mido/notes/root-build.md:
#   - runs as root in WSL2 (no sudo needed: SUDO is empty when EUID is 0)
#   - APFS_FUSE=/path/to/apfs-fuse overrides the binary lookup (built from
#     sgan81/apfs-fuse, not packaged); WORK_BASE=/dir puts the (large) temp
#     directory somewhere other than /tmp (default: $TMPDIR)
#   - TWEAKS=1 (default) also runs sweet-root-tweaks.py on the finished image
#     (fsck, mount, tweaks, umount, fsck), as README section 2 does by hand
#   - install -o/-g replaced by install + chown (uutils coreutils on Ubuntu 26.04)
#   - HFS+ volume uses an explicit 4096-byte allocation block (-b 4096)
# For the IPSW the dmg names come from BuildManifest.plist (iPhone10,2 / d21ap):
#   OS 087-86694-044.dmg  Cryptex1,SystemOS 087-86588-047.dmg  Cryptex1,AppOS 087-86715-047.dmg
#
# The IPSW images are raw APFS with LZBITMAP-compressed files: they are read
# through apfs-fuse (decompressing), so the HFS+ copy is uncompressed. On a
# device /private/preboot is its own volume holding the cryptexes, which
# /System/Cryptexes/{OS,App} link to; here they live inside the one volume.
# Owners, modes, symlinks and hard links are preserved (rsync -aH as root).
#
# The volume is journaled (XNU replays the journal after a panic; Linux only
# mounts it read-write with -o force and leaves the journal empty). SWEET
# additions: /System/Library/Caches/com.apple.dyld hard-links the SystemOS
# cryptex shared cache (ignition_level=1 looks there), and
# /private/var/keybags/systembag.kb is the plain-plist system keybag that
# keybagd reads with /defaults/no-effaceable-storage (tools/mkadt.py).
set -euo pipefail

[[ $# -ge 4 ]] || { sed -n '2,12p' "$0"; exit 2; }
os=$(realpath "$1") sysos=$(realpath "$2") appos=$(realpath "$3") out=$4 size=${5:-16G}
SUDO=""; [[ $EUID == 0 ]] || SUDO=sudo
TWEAKS=${TWEAKS:-1}
here=$(dirname "$(realpath "${BASH_SOURCE[0]}")")
[[ ! -e $out ]] || { echo "refusing to overwrite $out" >&2; exit 1; }

# Pre-flight tool check
missing_tools=()
[[ -n ${APFS_FUSE:-} ]] || APFS_FUSE=$(command -v apfs-fuse || true)
[[ -x ${APFS_FUSE:-/nonexistent} ]] || missing_tools+=(apfs-fuse)
for tool in mkfs.hfsplus rsync; do
	command -v "$tool" >/dev/null 2>&1 || missing_tools+=("$tool")
done

if [[ ${#missing_tools[@]} -gt 0 ]]; then
	echo "Error: missing required host utilities: ${missing_tools[*]}" >&2
	echo "  Install instructions:" >&2
	echo "    Arch Linux:    sudo pacman -S apfs-fuse hfsprogs rsync" >&2
	echo "    Ubuntu/Debian: sudo apt install apfs-fuse hfsprogs rsync" >&2
	echo "    Fedora:        sudo dnf install apfs-fuse hfsplus-tools rsync" >&2
	exit 1
fi

work=$(mktemp -d -p "${WORK_BASE:-${TMPDIR:-/tmp}}")
mounts=()
cleanup() {
	local busy=0
	for m in "${mounts[@]}"; do
		if mountpoint -q "$m"; then
			$SUDO umount "$m" 2>/dev/null || true
		fi
		mountpoint -q "$m" && busy=1
	done
	# Never recurse into a directory that is still mounted (the root is writable).
	if [[ $busy == 0 ]]; then
		rm -f "$work"/*.dmg
		rmdir "$work"/* "$work" 2>/dev/null || true
	else
		echo "still mounted under $work: left in place" >&2
	fi
}
trap cleanup EXIT

# D21AP/WSL change: sweet ends with `fsck.hfsplus -f -n`, which on this Linux
# fsck (540.1) reports "Volume header needs minor repair (1, 0)" even for a
# freshly mkfs'd journaled volume and exits 8. Verify with a -y pass instead and
# require the "appears to be OK" / "repaired successfully" verdict.
fsck_verify() {
	local r
	r=$(fsck.hfsplus -f -y "$1" 2>&1 | grep -v 'Illegal name') || true
	echo "$r" | tail -3
	echo "$r" | grep -Eq 'appears to be OK|repaired successfully' || { echo "fsck verification failed" >&2; exit 1; }
}

# apfs-fuse splits its options on ',' (e.g. in iPhone10,3 paths): use links.
# Keep the .dmg name: apfs-fuse only parses UDIF images (the OS one is UDIF,
# the cryptexes are raw APFS) when the file name ends in .dmg.
apfs_mount() {
	ln -s "$1" "$work/$2.dmg"
	mkdir "$work/$2"
	# As root: a user's FUSE mount is unreadable to the root rsync below.
	$SUDO "$APFS_FUSE" "$work/$2.dmg" "$work/$2"
	mounts+=("$work/$2")
}
apfs_mount "$os" os
apfs_mount "$sysos" sysos
apfs_mount "$appos" appos

truncate -s "$size" "$out"
mkfs.hfsplus -s -J -b 4096 -v iOSRoot "$out"
mkdir "$work/root"
$SUDO mount -t hfsplus -o loop,force "$out" "$work/root"
mounts=("$work/root" "${mounts[@]}")

copy() {
	echo "copying $1 -> ${2#"$work/root"}"
	$SUDO mkdir -p "$2"
	$SUDO rsync -aH --numeric-ids "$1/" "$2/"
}
copy "$work/os/root" "$work/root"
copy "$work/sysos/root" "$work/root/private/preboot/Cryptexes/OS"
copy "$work/appos/root" "$work/root/private/preboot/Cryptexes/App"

# Shared cache where dyld looks at ignition level 1: hard links, no extra space.
dsc=private/preboot/Cryptexes/OS/System/Library/Caches/com.apple.dyld
$SUDO mkdir -p "$work/root/System/Library/Caches/com.apple.dyld"
for f in "$work/root/$dsc"/*; do
	$SUDO ln "$f" "$work/root/System/Library/Caches/com.apple.dyld/${f##*/}"
done

# dyld does not search the cryptexes at ignition level 1: hard-link every
# cryptex file that has no counterpart in the OS root (libobjc-trampolines,
# libffi-trampolines, libstdc++, ...) to its root path.
for c in OS App; do
	(cd "$work/root/private/preboot/Cryptexes/$c" && $SUDO find . ! -type d ! -path './System/Library/Caches/com.apple.dyld/*') |
	while IFS= read -r f; do
		f=${f#./}
		if ! $SUDO test -e "$work/root/$f" && ! $SUDO test -L "$work/root/$f"; then
			$SUDO mkdir -p "$work/root/$(dirname "$f")"
			src="$work/root/private/preboot/Cryptexes/$c/$f"
			# Linux hfsplus cannot hard-link symlinks: copy those.
			if $SUDO test -L "$src"; then $SUDO cp -P "$src" "$work/root/$f"; else $SUDO ln "$src" "$work/root/$f"; fi
			echo "linked $c:/$f"
		fi
	done
done

# logd's log stores, normally made at restore: it checks owner _logd (272)
# and mode, plus a .migrated marker, else asks a helper and crashes
# ("BUG IN LIBTRACE: Failed to migrate directory").
# D21AP/WSL change: Ubuntu 26.04 ships uutils coreutils, whose `install -o 272`
# fails with "invalid user" for ids without a passwd entry: chown separately.
db="$work/root/private/var/db"
$SUDO install -d -m 0751 "$db/diagnostics"
$SUDO install -d -m 0755 "$db/uuidtext" "$db/diagnostics/timesync"
for d in diagnostics uuidtext diagnostics/timesync; do
	$SUDO install -m 0644 /dev/null "$db/$d/.migrated"
done
$SUDO chown 272:272 "$db/diagnostics" "$db/uuidtext" "$db/diagnostics/timesync" 	"$db/diagnostics/.migrated" "$db/uuidtext/.migrated" "$db/diagnostics/timesync/.migrated"

# System keybag for the built-in AppleKeyStore (no passcode).
$SUDO install -d -m 0700 "$work/root/private/var/keybags"
$SUDO chown 0:0 "$work/root/private/var/keybags"
printf '%s
' '<?xml version="1.0" encoding="UTF-8"?>' 	'<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">' 	'<plist version="1.0"><dict><key>KeyBagKeys</key><data>U1dFRVQ=</data></dict></plist>' |
	$SUDO install -m 0600 /dev/stdin "$work/root/private/var/keybags/systembag.kb"
$SUDO chown 0:0 "$work/root/private/var/keybags/systembag.kb"

df -h "$work/root"
$SUDO umount "$work/root"
# Linux hfsplus decomposes some non-ASCII names (localized Shortcuts examples)
# differently from Apple's tables; let fsck_hfs rewrite them, then verify.
fsck.hfsplus -f -y "$out" | grep -v 'Illegal name' || true
fsck_verify "$out"

if [[ $TWEAKS == 1 ]]; then
	# fsck first: the volume is never clean after a Linux read-write mount.
	fsck.hfsplus -f -y "$out" >/dev/null || true
	$SUDO mount -t hfsplus -o loop,force "$out" "$work/root"
	$SUDO python3 "$here/sweet-root-tweaks.py" "$work/root"
	$SUDO umount "$work/root"
	fsck.hfsplus -f -y "$out" | grep -v 'Illegal name' || true
	fsck_verify "$out"
fi
