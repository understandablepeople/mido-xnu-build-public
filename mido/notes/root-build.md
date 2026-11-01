# iOS 16.7.16 (20H392) root image for iPhone10,2 (D21AP), built for mido

Built 2026-11-01 in WSL2 (Ubuntu 26.04, kernel 6.18.54.1-microsoft-standard-WSL2) as root. Nothing was committed and the
phone was not touched. The IPSW was only read in place (`/mnt/d/ios-ipsw/iPhone_5.5_P3_16.7.16_20H392_Restore.ipsw`);
three members were unzipped into `/mnt/d/ios-root-build/dmg` (deleted afterwards).

## Result (in `/mnt/d/ios-root-build/out/`)
| file | note |
|---|---|
| `ios16-root-20H392-iPhone10,2.img` | 17179869184 bytes (16 GiB), journaled case-sensitive HFS+, label `iOSRoot`, allocation block 4096, 8 MiB journal |
| `ios16-root-20H392-iPhone10,2.img.sha256` | `f89a95732e7fe8630057feec6926127900435d256c07b257496cc35d45e75a49` (re-verified after unmount) |
| `...files.txt.gz` | 321053 entries: type, mode, uid:gid, size, nlink, path, symlink target |
| `...contents.txt` | top-level listing and cryptex sizes |

Content: 12,513,796,096 bytes used (11.65 GiB) of 16 GiB, 4,666,073,088 free (4.35 GiB), about 184,000 non-directory entries.
OS root 7.56 GB (apparent) + SystemOS cryptex 3.2 GB (181583 + 1459 files) + AppOS cryptex 8 MB (884 files).
SystemVersion.plist: 16.7.16 / 20H392. fsck.hfsplus ends with "appears to be OK".

Size proposal: content is 11.65 GiB, so 14 GiB (2.3 GiB free) is the floor I would use; 16 GiB (what exists, same as sweet,
4.35 GiB free for /private/var growth) is the comfortable choice. Linux has no HFS+ resizer, so another size means a rebuild
(about 14 minutes). The phone `userdata` (~54 GB) will hold only the first 16 GiB as filesystem; the rest stays unused.

Copy to the phone later: keep the raw `.img`. D: is NTFS via DrvFs where the 16 GiB file is fully allocated, so for flashing
convert with `img2simg ios16-root-20H392-iPhone10,2.img X.simg` (installed: android-sdk-libsparse-utils; NOT run, to save about
12.5 GB on D:) and `fastboot -S 512M flash userdata X.simg` as sweet does. Verify the sha256 of the raw image first.

## BuildManifest.plist names (iPhone10,2 = d21ap; d211ap = iPhone10,5; all 4 identities identical)
| role | file in IPSW | size | zip method |
|---|---|---|---|
| OS (root FS) | `087-86694-044.dmg` | 4723392522 | stored, UDIF/APFS |
| Cryptex1,SystemOS | `087-86588-047.dmg` | 2743074816 | deflate, raw APFS |
| Cryptex1,AppOS | `087-86715-047.dmg` | 10485760 | deflate, raw APFS |
The same OS dmg serves D21AP and D211AP, so MediaToolbox ships D21/D211/Default dirs (all got StartRecorderServer=false).

## Tools and versions
- apfs-fuse: sgan81/apfs-fuse commit 66b86bd525e8cb90f9012543be89b1f092b75cf3 (+ lzfse e634ca5), built in
  `/mnt/d/ios-root-build/tools/apfs-fuse/build` with `cmake .. -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DCMAKE_CXX_FLAGS="-include cstdint"`
  (cmake 4 policy error; PList.h lacks `<cstdint>` for gcc 15; also `apt install libfuse3-dev fuse3`). Binary sha256
  2b290a81208b931ed1c775ba3b8f1848167b8756bcaade9409278a056fef23fb. It mounted all three dmgs and decompressed LZBITMAP files.
  The `ipsw` tool was NOT needed and was not downloaded.
- hfsprogs 540.1.linux3-6build1, rsync 3.4.1, libsparse (img2simg) 34.0.5.
- HFS+ kernel module: the WSL kernel has no `hfsplus` (CONFIG_HFSPLUS_FS not set, no .ko). I built it out of tree from
  microsoft/WSL2-Linux-Kernel tag linux-msft-wsl-6.18.54.1 (d504d40a) using the running kernel `/proc/config.gz` plus
  `CONFIG_HFSPLUS_FS=m`, `make modules_prepare`, `make M=fs/hfsplus KBUILD_MODPOST_WARN=1 modules`, `strip --strip-debug`.
  Needs libelf-dev libssl-dev dwarves (without pahole the first .ko failed: "this_module section size must match the kernel's
  built struct module size"). Loaded with `insmod -f`. Result `/mnt/d/ios-root-build/tools/hfsplus.ko`, sha256
  b7d51b370c2e888ac06061577e7a5f003cddfa12bc0e16a3709eda58efe1b099. Must be re-insmod'ed after each WSL restart.
  /dev/fuse and loop devices worked as they are.
- The image lives on DrvFs (D:) and is loop-mounted there. Works but is slow: the whole run took 13m45s, mostly rsync.

## Exact commands
```
# in WSL as root, cwd /mnt/c/Users/frant/Desktop/mido-ios
cd /mnt/d/ios-root-build/dmg
for f in 087-86694-044.dmg 087-86588-047.dmg 087-86715-047.dmg; do unzip -o -q /mnt/d/ios-ipsw/iPhone_5.5_P3_16.7.16_20H392_Restore.ipsw $f; done
insmod -f /mnt/d/ios-root-build/tools/hfsplus.ko
export APFS_FUSE=/mnt/d/ios-root-build/tools/apfs-fuse/build/apfs-fuse WORK_BASE=/mnt/d/ios-root-build/work
bash tools/mkiosroot_d21ap.sh /mnt/d/ios-root-build/dmg/087-86694-044.dmg /mnt/d/ios-root-build/dmg/087-86588-047.dmg \
     /mnt/d/ios-root-build/dmg/087-86715-047.dmg /mnt/d/ios-root-build/out/ios16-root-20H392-iPhone10,2.img 16G
```
The script does everything below, including `sweet-root-tweaks.py` (TWEAKS=1) and fsck (wrapper copy: `/mnt/d/ios-root-build/tools/run-build.sh`).
`patch-launchd-plist.py` was deliberately NOT run: `sweet-root-tweaks.py` already renames `_PanicOnCrash` to `_PanicOnCrasX`
(7 jobs) and removes the 2 CommCenter jobs; patch-launchd-plist.py only adds console logging for chosen job labels (sweet NOTES: the
v8 image with that for backboardd/SpringBoard was the one where backboardd never exec'd). Run it by hand on a mounted copy if wanted.

Applied, same as sweet: OS + cryptexes copied with `rsync -aH --numeric-ids` (cryptexes under /private/preboot/Cryptexes/{OS,App});
44 hard links `/System/Library/Caches/com.apple.dyld/*` to the OS cryptex shared cache (nlink 2 verified); 19 cryptex-only files hard-linked
to root paths (libobjc/ffi-trampolines, libstdc++ x3, VisualTestKit, DriverKit dyld cache x2, and App: SafariSupport.bundle files,
AuthenticationServicesAgent, com.apple.Safari.History, passwordbreachd, safarifetcherd, webbookmarksd, webinspectord, webpushd);
logd dirs (272:272, .migrated); `/private/var/keybags/systembag.kb` (dir 0700, file 0600, root); containers dirs; launchd.plist
tweaks; VirtualAudio plug-in moved to HAL.disabled; MediaToolbox StartRecorderServer=false; migration, springboard, purplebuddy and
managedconfiguration prefs. Tweaks warning: "no mobileactivationd system container in the image; skipped data ark" (the container
does not exist in the rootfs, so the activation data_ark was not seeded; check on the phone, not verified against sweet's own output).

## Differences versus sweet (`tools/mkiosroot_d21ap.sh`; original `tools/mkiosroot.sh` untouched)
1. `sudo` dropped when EUID=0. apfs-fuse located through `APFS_FUSE` (not packaged on Ubuntu 26.04).
2. `mktemp -d` under `WORK_BASE` (D:), not /tmp (WSL C: VHD has little space).
3. `mkfs.hfsplus -b 4096` made explicit (nothing in the script assumed 16K).
4. Ubuntu 26.04 uses uutils coreutils: `install -o 272 -g 272` fails ("invalid user: '272'", no passwd entry). Replaced by `install` then `chown`.
   The first full run died here after 13 minutes.
5. The final `fsck.hfsplus -f -n` of sweet exits 8 here ("Volume header needs minor repair (1, 0)") on every volume, even a fresh 64 MB mkfs
   (tested; also after fsck -y). The script now runs `fsck.hfsplus -f -y` and requires "appears to be OK" or "repaired successfully". The first
   run of the original logic failed at this point, after copying, so the image is real; one fsck pass reported "repaired successfully".
6. Added the tweaks step (fsck, remount, `sweet-root-tweaks.py`, unmount, fsck) inside the script, as README section 2 does by hand.
7. Nothing else was iPhone X specific: dmg names are arguments; `sweet-root-tweaks.py` has BUILD/VERSION 20H392/16.7.16 which are the same for the 8 Plus.
   D22AP names appear only in sweet's README (device tree extraction); `tools/extract_d21ap.py` already handles `DeviceTree.d21ap.im4p`.
8. Other notes: `truncate` on DrvFs produced a fully allocated 16 GiB file (D: free dropped by 16 GB, no sparse); `find` warns on 2 Thai WorkflowKit shortcut
   names (Linux hfsplus name decomposition), so those 2 files may be missing from the listing only.

## Conflicts with a 4K-page kernel (flagged, not fixed)
- dyld shared cache (44 files): every mapping address, size and file offset is 16 KiB aligned and every file size is a multiple of 16K; none are
  only 4K aligned. Slide info is version 2 with `page_size` 4096 (so rebase is per 4K page), which suggests the data is placeable on 4K,
  but the cache layout, shared region mapping and `__DATA_CONST`/`__DATA` protections are 16K-granular.
- All Mach-O executables checked (`/sbin/launchd`, `/usr/lib/dyld`, `/usr/libexec/xpcproxy`) have every segment vm/file aligned to 16K and
  plain arm64 (cputype 0x100000c, subtype 0). Userland will read hw.pagesize/vm_page_size/commpage values: with a 4K kernel these must be
  made consistent (expect dyld/libSystem to assume 16K on arm64).
- HFS+ allocation block 4096 is fine.
- Not verified: no QEMU or phone boot of this image was done.

## Disk usage after cleanup
`/mnt/d/ios-root-build`: out/ 17 GB (image and listings), tools/ 7 MB. Temp dmgs and work dirs deleted. D: free 39 GB.
WSL ext4 `/root/kbuild` (kernel checkout used for hfsplus.ko) can be deleted.
