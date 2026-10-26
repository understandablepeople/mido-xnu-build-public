"""Read-only evidence for the first native root-discovery resource wait."""


ROOT = "_IOFindBSDRoot"
WAIT = "__ZN9IOService31waitForMatchingServiceWithTokenEP12OSDictionaryyP24IOUserServerCheckInToken"


def root_resource_wait(events, wait_calls, bsd_thread):
    if not wait_calls or bsd_thread is None:
        raise ValueError("root resource checkpoint requires audited calls and BSD thread")
    roots = [event for event in events if event["function"] == ROOT
             and event["native_thread"] == bsd_thread]
    if not roots:
        return None
    event = events[-1]
    if (event["function"] != WAIT or event["native_thread"] != bsd_thread
            or event["caller_return_va"] != min(wait_calls) + 4):
        return None
    if event.get("timeout_nanoseconds") != 30_000_000_000:
        raise ValueError("native root resource wait timeout changed")
    return dict(root_entry=roots[-1], wait_entry=event,
                audited_call=min(wait_calls), root_selected=False,
                root_mounted=False, userspace_booted=False, device_boot_proven=False,
                scope="entry to original IOBSD resource wait, not root selection")
