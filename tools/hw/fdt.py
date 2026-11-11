"""Flattened device tree (DTB) reader with the lookups a board check needs.

    from tools.hw.fdt import Tree
    tree = Tree.load(path)            # a .dtb, ideally compiled with dtc -@ (labels in /__symbols__)
    node = tree.label("gpu")           # or tree.path("/soc@0/gpu@3d00000")
    tree.regs(node)                    # [(cpu physical address, size), ...] through every parent's ranges
    tree.interrupts(node)              # [{"controller": label, "cells": [...], ...decoded}]
    tree.phandle_list(node, "clocks", "#clock-cells")

Only the structure block and the strings block are read; reserve map entries are ignored. Nothing here
depends on dtc or libfdt.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import struct
from pathlib import Path

FDT_MAGIC = 0xd00dfeed
BEGIN_NODE, END_NODE, PROP, NOP, END = 1, 2, 3, 4, 9


class Node:
    __slots__ = ("name", "parent", "children", "props", "path")

    def __init__(self, name, parent):
        self.name, self.parent, self.children, self.props = name, parent, [], {}
        self.path = "/" if parent is None else (parent.path.rstrip("/") + "/" + name)

    def u32s(self, key):
        v = self.props.get(key)
        return list(struct.unpack(f">{len(v) // 4}I", v)) if v is not None else None

    def u32(self, key, default=None):
        v = self.u32s(key)
        return v[0] if v else default

    def strings(self, key):
        v = self.props.get(key)
        return [s.decode("utf-8", "replace") for s in v.rstrip(b"\0").split(b"\0")] if v else []

    def string(self, key, default=None):
        s = self.strings(key)
        return s[0] if s else default

    @property
    def enabled(self):
        return self.string("status", "okay") in ("okay", "ok")

    @property
    def unit_name(self):
        return self.name.split("@", 1)[0]

    def __repr__(self):
        return f"<Node {self.path}>"


class Tree:
    def __init__(self, root):
        self.root = root
        self.nodes = list(self._walk(root))
        self.by_path = {n.path: n for n in self.nodes}
        self.by_phandle = {}
        for n in self.nodes:
            for key in ("phandle", "linux,phandle"):
                if key in n.props:
                    self.by_phandle[n.u32(key)] = n
        sym = self.by_path.get("/__symbols__")
        self.labels = {k: v.rstrip(b"\0").decode() for k, v in sym.props.items()} if sym else {}
        self.label_of = {}
        for name, path in sorted(self.labels.items()):
            self.label_of.setdefault(path, name)

    @staticmethod
    def _walk(node):
        yield node
        for child in node.children:
            yield from Tree._walk(child)

    @classmethod
    def load(cls, path):
        return cls.parse(Path(path).read_bytes())

    @classmethod
    def parse(cls, blob):
        magic, total, off_struct, off_strings, _, version, _, _, size_strings, size_struct = struct.unpack_from(
            ">10I", blob)
        if magic != FDT_MAGIC:
            raise ValueError("not a flattened device tree")
        if version < 16 or total > len(blob):
            raise ValueError(f"unsupported or truncated FDT (version {version})")
        strings = blob[off_strings:off_strings + size_strings]
        at, end, stack, root = off_struct, off_struct + size_struct, [], None
        while at < end:
            token = struct.unpack_from(">I", blob, at)[0]
            at += 4
            if token == BEGIN_NODE:
                stop = blob.index(b"\0", at)
                name = blob[at:stop].decode("utf-8", "replace")
                at = (stop + 4) & ~3
                node = Node(name, stack[-1] if stack else None)
                if stack:
                    stack[-1].children.append(node)
                else:
                    root = node
                stack.append(node)
            elif token == END_NODE:
                stack.pop()
            elif token == PROP:
                length, name_off = struct.unpack_from(">II", blob, at)
                at += 8
                name = strings[name_off:strings.index(b"\0", name_off)].decode()
                stack[-1].props[name] = bytes(blob[at:at + length])
                at = (at + length + 3) & ~3
            elif token == NOP:
                continue
            elif token == END:
                break
            else:
                raise ValueError(f"bad FDT token {token:#x} at {at - 4:#x}")
        if root is None or stack:
            raise ValueError("unbalanced FDT structure block")
        return cls(root)

    # Lookups -------------------------------------------------------------------------------------------------

    def path(self, path):
        return self.by_path.get(path)

    def label(self, name):
        p = self.labels.get(name)
        return self.by_path.get(p) if p else None

    def name_of(self, node):
        return self.label_of.get(node.path, node.path)

    def phandle(self, value):
        return self.by_phandle.get(value)

    def compatible(self, *compatibles):
        want = set(compatibles)
        return [n for n in self.nodes if want & set(n.strings("compatible"))]

    def effectively_enabled(self, node):
        while node is not None:
            if not node.enabled:
                return False
            node = node.parent
        return True

    # Addresses ---------------------------------------------------------------------------------------------

    @staticmethod
    def _cells(node, key, default):
        return node.u32(key, default) if node is not None else default

    @staticmethod
    def _number(cells):
        value = 0
        for c in cells:
            value = value << 32 | c
        return value

    def _translate(self, bus, address):
        """Address on bus `bus` (the node whose children use it) to the CPU's physical address."""
        while bus is not None and bus.parent is not None:
            ranges = bus.props.get("ranges")
            if ranges is None:
                return None                                   # no mapping to the parent: not CPU-visible
            if ranges:
                child_ac = self._cells(bus, "#address-cells", 2)
                parent_ac = self._cells(bus.parent, "#address-cells", 2)
                size_c = self._cells(bus, "#size-cells", 1)
                cells = bus.u32s("ranges")
                step = child_ac + parent_ac + size_c
                for i in range(0, len(cells) - step + 1, step):
                    child = self._number(cells[i:i + child_ac])
                    parent = self._number(cells[i + child_ac:i + child_ac + parent_ac])
                    size = self._number(cells[i + child_ac + parent_ac:i + step])
                    if child <= address < child + size:
                        address = parent + address - child
                        break
                else:
                    return None
            bus = bus.parent
        return address

    def regs(self, node, translate=True):
        cells = node.u32s("reg")
        if not cells:
            return []
        bus = node.parent
        ac, sc = self._cells(bus, "#address-cells", 2), self._cells(bus, "#size-cells", 1)
        out = []
        for i in range(0, len(cells) - (ac + sc) + 1, ac + sc):
            address = self._number(cells[i:i + ac])
            size = self._number(cells[i + ac:i + ac + sc])
            out.append((self._translate(bus, address) if translate else address, size))
        return out

    def reg_named(self, node, name):
        names = node.strings("reg-names")
        regs = self.regs(node)
        return regs[names.index(name)] if name in names and names.index(name) < len(regs) else None

    # Phandle lists --------------------------------------------------------------------------------------

    def phandle_list(self, node, key, cells_key):
        """[(provider node, [argument cells])] of a property like clocks or power-domains."""
        cells = node.u32s(key) or []
        out, i = [], 0
        while i < len(cells):
            provider = self.phandle(cells[i])
            if provider is None:
                raise ValueError(f"{node.path}: {key} names unknown phandle {cells[i]:#x}")
            n = self._cells(provider, cells_key, 0)
            out.append((provider, cells[i + 1:i + 1 + n]))
            i += 1 + n
        return out

    def interrupt_parent(self, node):
        """As Linux's of_irq_find_parent: follow interrupt-parent, else the tree parent, until a node that has
        #interrupt-cells (a PMIC peripheral's parent is the SPMI arbiter, not the GIC an ancestor names)."""
        current = node
        while current is not None:
            if "interrupt-parent" in current.props:
                candidate = self.phandle(current.u32("interrupt-parent"))
            else:
                candidate = current.parent
            if candidate is None:
                return None
            if "#interrupt-cells" in candidate.props:
                return candidate
            current = candidate
        return None

    def interrupts(self, node):
        """Every interrupt of a node (interrupts or interrupts-extended), decoded for the GIC."""
        out = []
        if "interrupts-extended" in node.props:
            pairs = self.phandle_list(node, "interrupts-extended", "#interrupt-cells")
        else:
            parent = self.interrupt_parent(node)
            if parent is None or "interrupts" not in node.props:
                return []
            n = self._cells(parent, "#interrupt-cells", 1)
            cells = node.u32s("interrupts")
            pairs = [(parent, cells[i:i + n]) for i in range(0, len(cells) - n + 1, n)]
        names = node.strings("interrupt-names")
        for idx, (ctrl, args) in enumerate(pairs):
            row = {"controller": self.name_of(ctrl), "cells": args}
            if idx < len(names):
                row["name"] = names[idx]
            if "arm,gic-v3" in ctrl.strings("compatible") and len(args) >= 3:
                kind, number = args[0], args[1]
                row["gic"] = ("SPI", number, 32 + number) if kind == 0 else ("PPI", number, 16 + number)
            out.append(row)
        return out
