"""Validate observed native diagnostic mount returns, never manufacture them."""


def mounted_diagnostic_root(selection, events, mount, bsd_thread):
    if not selection or not selection.get("root_selected") or selection.get("root_name") != "md0":
        raise ValueError("native mount lacks selected md0")
    if not bsd_thread or mount.get("native_thread") != bsd_thread or mount.get("returned_status") != 0:
        raise ValueError("original VFS mount did not return success on the BSD thread")
    providers = [event for event in events if event.get("function") == "_mockfs_mountroot"]
    if (len(providers) != 1 or providers[0].get("native_thread") != bsd_thread
            or providers[0].get("returned_status") != 0
            or not providers[0].get("mount_pointer") or not providers[0].get("device_vnode")
            or events.index(mount) >= events.index(providers[0])):
        raise ValueError("missing original successful mockfs mount callback")
    registration = selection.get("native_registration", {})
    if registration.get("native_thread") != bsd_thread:
        raise ValueError("root registration and mounting occurred on different threads")
    return dict(filesystem="mockfs", diagnostic_only=True, root_vfs_mounted=True,
                original_vfs_return_status=0, original_provider_return_status=0,
                backing_device=selection["root_device"], native_mount_pointer=providers[0]["mount_pointer"],
                disk_io_validated=False, executable_validated=False, userspace_booted=False,
                device_boot_proven=False, production_filesystem=False, boot_approved=False)


def init_exec_entry(mount, events, entry, calls):
    if not mount or not mount.get("root_vfs_mounted"):
        raise ValueError("init loader reached without observed root mount")
    if (not calls or entry.get("caller_return_va") not in {address + 4 for address in calls}
            or not entry.get("process_pointer") or not entry.get("native_thread")):
        raise ValueError("init loader lacks audited native caller and process")
    tasks = [event for event in events if event.get("function") == "_bsdinit_task"
             and event.get("native_thread") == entry.get("native_thread")]
    if len(tasks) != 1 or events.index(tasks[0]) >= events.index(entry):
        raise ValueError("init loader lacks original BSD init task entry")
    return dict(original_init_loader_entered=True, native_thread=entry["native_thread"],
                process_pointer=entry["process_pointer"], executable_loaded=False,
                userspace_booted=False, device_boot_proven=False, boot_approved=False)


def image_loader_entry(init, events, entry, calls, header, expected_header, disk_unchanged):
    if not init or not init.get("original_init_loader_entered"):
        raise ValueError("image loader lacks observed init loader")
    if (not calls or entry.get("caller_return_va") not in {address + 4 for address in calls}
            or entry.get("native_thread") != init["native_thread"]):
        raise ValueError("image loader lacks audited activator call on the init thread")
    if (len(header) != 32 or header != expected_header or not disk_unchanged
            or header[:12] != bytes.fromhex("cffaedfe0c00000100000000")):
        raise ValueError("original file read differs from the ARM64 root payload header")
    reads = [event for event in events if event.get("function") == "_mdevstrategy"
             and event.get("native_thread") == entry["native_thread"]
             and event.get("buffer_pointer") and event.get("original_return_observed")
             and events.index(event) < events.index(entry)]
    if not reads:
        raise ValueError("image header lacks original completed memdev strategy call")
    return dict(original_image_loader_entered=True, root_payload_header_read=True,
                memdev_strategy_returns=len(reads), disk_contents_unchanged=True,
                executable_loaded=False, userspace_booted=False, device_boot_proven=False, boot_approved=False)


def user_entry_evidence(init_return, eret, thread, pc, pstate, mapping, code, expected_code):
    if not init_return or not init_return.get("original_init_loader_return_observed"):
        raise ValueError("EL0 entry lacks original successful init exec")
    if (not eret or not thread or eret.get("native_thread") != thread or
            eret.get("elr") != pc or eret.get("spsr", 15) & 15 or pstate & 15 or
            not eret.get("original_kernel_eret")):
        raise ValueError("EL0 entry lacks matching original kernel exception return")
    if (mapping.get("status") != "mapped" or not mapping.get("access_flag") or
            not mapping.get("access_permissions", 0) & 1 or
            mapping["levels"][-1]["descriptor"] & (1 << 54) or
            len(code) != 28 or code != expected_code):
        raise ValueError("EL0 instruction mapping differs from native executable payload")
    return dict(pc=pc, native_thread=thread, pstate=pstate, original_el0_entry_observed=True,
                native_payload_mapping_verified=True, first_instruction_executed=False,
                syscall_completed=False, device_boot_proven=False, boot_approved=False)


def user_syscall_evidence(entry, call, eret, thread, pstate, result, saved_result, marker):
    if not entry or not entry.get("original_el0_entry_observed") or not thread or pstate & 15:
        raise ValueError("syscall return lacks original EL0 entry")
    if (not call or call.get("native_thread") != thread or
            thread != entry.get("native_thread") or not call.get("process_pointer") or
            not call.get("original_return_observed") or call.get("returned_status") != 0 or
            not isinstance(call.get("returned_pid"), int) or call["returned_pid"] <= 0):
        raise ValueError("getpid did not return successfully on the observed native thread")
    if (not eret or not eret.get("original_kernel_eret") or
            eret.get("native_thread") != thread or eret.get("elr") != 0x100004008 or
            eret.get("spsr", 15) & 15):
        raise ValueError("syscall lacks original native exception return")
    if result != call["returned_pid"] or saved_result != result or marker != 0x444f4d49:
        raise ValueError("EL0 result and executed diagnostic marker differ from native getpid")
    return dict(native_getpid_completed=True, returned_pid=result, native_thread=thread,
                diagnostic_user_instructions_executed=True, result_injected=False,
                userspace_booted=False, device_boot_proven=False, boot_approved=False)
