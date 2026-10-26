# MIDO XNU experimental public build

Sanitized source snapshot for reproducible public GitHub Actions builds.
The original private repository, its history, phone backups, local artifacts,
device captures and uncommitted changes are not included.

Snapshot source: cf1afac (2026-10-26). This repository has independent history.
Upstream dependencies are downloaded by the build tools using pinned sources;
upstream licenses and notices remain applicable. No Apple SDK is distributed.

## Scope and safety

This is experimental kernel bring-up, not an installable iOS image.
The latest private milestone reaches IOFindBSDRoot in an offline synthetic
execution model; it does not demonstrate storage, userspace or hardware boot.
Do not flash diagnostic kernels or interpret a successful build as boot approval.

## Build

Use the manual workflow `mido-bootstrap-kernel.yml`. Its experimental providers
require explicit boolean inputs. The workflow has read-only repository permissions,
uses the standard macos-14 runner and keeps build artifacts for three days.
It does not access a phone or deploy anything. Pushes do not start builds.

Build scripts and platform contracts are under tools/ and devices/mido/xnu/.
Only the manual bootstrap workflow is published in this snapshot.
