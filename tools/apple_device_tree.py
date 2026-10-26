"""Bounded codec for the pinned XNU flattened tree layout, not Linux FDT."""

import struct


MAX_BYTES = 1024 * 1024
MAX_NODES = 1024
MAX_DEPTH = 32
MAX_PROPERTIES = 256
MAX_VALUE = 65536


def text(value, maximum, label):
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"invalid {label}")
    raw = value.encode("ascii")
    if any(character < 33 or character > 126 for character in raw) or b"/" in raw:
        raise ValueError(f"invalid {label}")
    return raw


def encode_tree(tree):
    output = bytearray()
    node_count = 0

    def emit(node, depth):
        nonlocal node_count
        node_count += 1
        if depth > MAX_DEPTH or node_count > MAX_NODES:
            raise ValueError("tree depth/node limit exceeded")
        if not isinstance(node, dict) or set(node) != {"name", "properties", "children"}:
            raise ValueError("node needs name, properties and children")
        name = text(node["name"], 63, "node name")
        properties, children = node["properties"], node["children"]
        if not isinstance(properties, dict) or "name" in properties or len(properties) >= MAX_PROPERTIES:
            raise ValueError("invalid properties or explicit name override")
        if not isinstance(children, list) or len(children) > MAX_NODES:
            raise ValueError("invalid child list")
        output.extend(struct.pack("<II", len(properties) + 1, len(children)))
        for key, value in [("name", name + b"\0")] + list(properties.items()):
            encoded_key = text(key, 31, "property name")
            if not isinstance(value, bytes) or len(value) > MAX_VALUE:
                raise ValueError("property values must be bounded bytes")
            output.extend(struct.pack("<32sI", encoded_key, len(value)))
            output.extend(value)
            output.extend(bytes((-len(value)) % 4))
            if len(output) > MAX_BYTES:
                raise ValueError("serialized tree limit exceeded")
        names = set()
        for child in children:
            if not isinstance(child, dict) or not isinstance(child.get("name"), str) or child["name"] in names:
                raise ValueError("invalid or duplicate child name")
            names.add(child["name"])
            emit(child, depth + 1)

    emit(tree, 0)
    return bytes(output)


def decode_tree(data):
    if not isinstance(data, bytes) or len(data) > MAX_BYTES:
        raise ValueError("invalid or oversized serialized tree")
    position = 0
    node_count = 0

    def take(size):
        nonlocal position
        if size > len(data) - position:
            raise ValueError("truncated flattened tree")
        value = data[position:position + size]
        position += size
        return value

    def read(depth):
        nonlocal node_count
        node_count += 1
        if depth > MAX_DEPTH or node_count > MAX_NODES:
            raise ValueError("tree depth/node limit exceeded")
        property_count, child_count = struct.unpack("<II", take(8))
        if not 1 <= property_count <= MAX_PROPERTIES or child_count > MAX_NODES:
            raise ValueError("invalid flattened tree counts")
        properties = {}
        for property_index in range(property_count):
            raw_name, size = struct.unpack("<32sI", take(36))
            if b"\0" not in raw_name or size > MAX_VALUE:
                raise ValueError("invalid property header")
            name_bytes, padding = raw_name.split(b"\0", 1)
            name = name_bytes.decode("ascii")
            text(name, 31, "property name")
            if any(padding) or name in properties:
                raise ValueError("noncanonical or duplicate property name")
            properties[name] = take(size)
            if any(take((-size) % 4)):
                raise ValueError("nonzero value padding")
        name_value = properties.pop("name", b"")
        if not name_value.endswith(b"\0") or b"\0" in name_value[:-1]:
            raise ValueError("invalid node name property")
        name = name_value[:-1].decode("ascii")
        text(name, 63, "node name")
        children = [read(depth + 1) for child_index in range(child_count)]
        if len({child["name"] for child in children}) != len(children):
            raise ValueError("duplicate child name")
        return dict(name=name, properties=properties, children=children)

    result = read(0)
    if position != len(data):
        raise ValueError("trailing flattened tree data")
    return result
