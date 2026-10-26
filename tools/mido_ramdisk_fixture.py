"""Reserve bounded synthetic RAM for the native memory-device diagnostic."""

import hashlib
import struct


PAGE_SIZE = 4096
MAX_DISK_BYTES = 1024 * 1024


def reserve_ramdisk(data, start, memory_start, memory_size, protected, command_line):
    if not isinstance(data, bytes) or not PAGE_SIZE <= len(data) <= MAX_DISK_BYTES:
        raise ValueError("synthetic RAM disk must contain 4 KiB to 1 MiB of explicit bytes")
    if len(data) % PAGE_SIZE or start % PAGE_SIZE:
        raise ValueError("synthetic RAM disk must be 4 KiB aligned")
    end = start + len(data)
    if memory_start < 0 or memory_size <= 0 or not memory_start <= start < end <= memory_start + memory_size:
        raise ValueError("synthetic RAM disk lies outside fixture RAM")
    if any(start < high and low < end for low, high in protected):
        raise ValueError("synthetic RAM disk overlaps protected fixture memory")
    root_options = [word for word in command_line.split()
                    if word.startswith("rd=") or word.startswith("rootdev=")]
    if root_options != ["rd=md0"]:
        raise ValueError("synthetic RAM disk requires exactly one explicit rd=md0 selector")
    return dict(physical_base=start, bytes=len(data), end=end,
                sha256=hashlib.sha256(data).hexdigest(),
                apple_property=struct.pack("<QQ", start, len(data)),
                filesystem_validated=False, boot_approved=False)


def selected_memory_root(status, name, root_device, flags, registrations, lookups, device_record=None):
    if status != 0 or name != "md0" or root_device < 0 or flags != 0:
        raise ValueError("original root discovery did not select a local md0 device")
    if len(registrations) != 1 or registrations[0].get("returned_device") != root_device:
        raise ValueError("root selection lacks matching native memdev registration and lookup")
    if lookups:
        if (len(lookups) != 1 or lookups[0].get("device_index") != 0
                or lookups[0].get("returned_device") != root_device):
            raise ValueError("native memdev lookup differs from selected root")
    elif (device_record is None or device_record.get("block_device") != root_device
            or device_record.get("flags") != 1 or device_record.get("sector_size") != 512
            or device_record.get("base_page") != registrations[0].get("base_page")
            or device_record.get("size_pages") != registrations[0].get("size_pages")):
        raise ValueError("inlined lookup requires the actual initialized native memdev record")
    return dict(root_name=name, root_device=root_device, original_return_status=status,
                root_selected=True, root_mounted=False, disk_io_validated=False,
                userspace_booted=False, device_boot_proven=False, boot_approved=False)
