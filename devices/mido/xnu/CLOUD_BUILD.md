# Cloud build preparation, 2026-10-25

The user authorized a private GitHub repository and cloud build preparation.
The authenticated REST API identifies the owner as understandablepeople;
the older local authentication label sweetbat is not the owner to use.

Created repository: understandablepeople/mido-xnu-bringup.
Initially verified private=true, size=0 and Actions enabled=false.
The user subsequently authorized the first commit/push and provided a billing
screenshot showing GitHub Free, 0 / 2000 included Actions minutes used and
zero billable Actions usage. One manual standard-runner preflight is approved.
No paid overages, recurring runs or full kernel builds are authorized.
Never upload backups, firmware dumps, tokens or personal device data.

## Local preflight files

.github/workflows/macos-preflight.yml is the approved first preflight.
The user completed a fresh login with workflow scope and approved its
publication in a second commit and a single manual dispatch.
It has only workflow_dispatch, a required quota acknowledgement, read-only
contents permission and a five-minute job timeout. No push, pull-request or
scheduled triggers are configured. Checkout is pinned to an immutable
actions/checkout v4 commit and does not persist credentials.

The job uses the standard macos-15 label rather than a larger runner or
macos-latest. The current official actions/runner-images table marks macOS 14
deprecated, and macos-14 is no longer the historical Intel/Xcode 15 recipe.
Consequently this is a toolchain discovery job, NOT a full XNU build recipe.
It reports Xcode/clang/SDK/iig availability, checks the pinned Apple boot_args
layout and runs host Python tests. A green job does not prove that modern
Xcode/iig can build the selected historical XNU release.

tools/check_xnu_boot_args.py downloads only the boot.h header from the pinned
Apple source commit, checks its SHA-256 and compiles layout assertions for
arm64-apple-macos13.0. Unused dependency headers are empty stubs and KERNEL is
not defined. This proves the exposed structure layout, not the complete
kernel header graph or boot pointer semantics. The same assertions passed
locally using NDK Clang: size 736, alignment 8, all 13 field offsets.

## Billing gate

The token cannot read the personal billing endpoints: API replies were 404
with a missing user-scope notice. No billing-related scope was added.
The user's screenshot supplies the plan and included-usage evidence for the
single bounded preflight. Hard spending limits remain unverified. Do not
change billing settings or enable paid overages. A job timeout or workflow
acknowledgement is NOT a financial spending cap. Recheck the allowance before
additional cloud jobs, and review the first run's usage with the user.

The account owner should check GitHub Settings / Billing and licensing:

1. Review remaining included Actions usage.
2. In Budgets and alerts, verify the Actions budget scope and hard-stop
   setting, not just email alerts. Do not enable paid overages for this
   experiment without agreeing a monetary cap first.
3. If no payment method is attached, confirm that; GitHub documents that
   usage is blocked when the included allowance runs out. There is no need
   to add a card solely for this preflight.

Official references reviewed:

- docs.github.com/en/billing/concepts/product-billing/github-actions
- docs.github.com/en/billing/how-tos/set-up-budgets
- github.com/actions/runner-images/blob/main/README.md

## Deployment gate

The initial source commit 9112282 excludes .github/workflows because the
original token did not have workflow scope. Refresh failed after the account
rename: it expected sweetbat but received understandablepeople. A fresh
login resolved that identity mismatch:

    gh auth login --hostname github.com --git-protocol https --web --scopes workflow

REST API verification now confirms understandablepeople and scopes gist,
read:org, repo and workflow. The old inactive keyring entry is untouched.
Use an explicit source allowlist: .github, tools, tests, devices/mido and
README.md/.gitignore. Review every file before upload. Never stage or upload
the whole desktop directory, artifacts, upstream or phone-backup. Do not
assume .gitignore alone is an adequate privacy check.

After billing is safe and reviewed source is deployed, enable Actions and
dispatch a single preflight. Inspect its toolchain report before attempting
the dedicated MIDO kernel configuration and platform changes. A preflight
does not justify running a sweet image on the phone.
