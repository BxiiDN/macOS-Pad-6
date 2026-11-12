"""A reader for device tree *source* (.dts/.dtsi) as Android vendor trees ship it, for checking board constants
against files that cannot be compiled alone (they include headers and dtsi files of a vendor kernel).

It parses the files given, in order, into one tree: node definitions with labels, `&label { ... }` blocks merged
into the labelled node (or kept as a detached node when the label is defined in a file not given),
/delete-node/ and /delete-property/. Property values keep their parts: cells (integers; `&label` references and
unexpanded macros as strings; parenthesised expressions evaluated when they are integer arithmetic), strings and
byte strings. Preprocessor lines are skipped, so macros are not expanded: a check that needs a macro's value reads
it as a string. It does not resolve phandles or translate addresses (the vendor SM8250 `soc` node maps 1:1).

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import re
from pathlib import Path

TOKEN = re.compile(r'''
    (?P<ws>\s+)
  | (?P<comment>/\*.*?\*/|//[^\n]*)
  | (?P<pp>\#[ \t]*(?:include|define|undef|if|ifdef|ifndef|else|elif|endif)\b(?:[^\n]*\\\n)*[^\n]*)
  | (?P<string>"(?:\\.|[^"\\])*")
  | (?P<directive>/(?:dts-v1|plugin|bits|delete-node|delete-property|memreserve|include)/)
  | (?P<paren>\((?:[^()]|\([^()]*\))*\))
  | (?P<ref>&\{[^}]*\}|&[A-Za-z_][\w]*)
  | (?P<word>[A-Za-z0-9_,.+@#?\-][A-Za-z0-9_,.+@#?\-]*|/)
  | (?P<punct>[{}<>\[\];=:,])
''', re.S | re.X)


class DtsError(ValueError):
    pass


class SNode:
    def __init__(self, name, parent=None):
        self.name, self.parent = name, parent
        self.labels, self.props, self.children, self.macros = [], {}, {}, []

    @property
    def path(self):
        if self.parent is None:
            return "/" if self.name == "/" else f"&{self.name}"
        base = self.parent.path
        return (base.rstrip("/") + "/" if base != "/" else "/") + self.name

    def child(self, name):
        if name in self.children:
            return self.children[name]
        hits = [c for n, c in self.children.items() if n.split("@")[0] == name]
        if len(hits) == 1:
            return hits[0]
        raise LookupError(f"{self.path}: no child {name}" if not hits else f"{self.path}: {name} is ambiguous")

    def find(self, pred):
        """This node and its descendants, depth first, for which pred(node) is true."""
        out = [self] if pred(self) else []
        for c in self.children.values():
            out += c.find(pred)
        return out

    # Values
    def parts(self, prop):
        if prop not in self.props:
            raise LookupError(f"{self.path}: no property {prop}")
        return self.props[prop]

    def cells(self, prop):
        """Every cell of every <...> group, in order."""
        return [c for kind, v in self.parts(prop) if kind == "cells" for c in v]

    def groups(self, prop):
        """The <...> groups of a property, each a list of cells (for `a = <0 10>, <1 3>;`)."""
        return [v for kind, v in self.parts(prop) if kind == "cells"]

    def u32s(self, prop):
        out = self.cells(prop)
        if not all(isinstance(c, int) for c in out):
            raise DtsError(f"{self.path}: {prop} has non-integer cells {out}")
        return out

    def u32(self, prop):
        v = self.u32s(prop)
        if len(v) != 1:
            raise DtsError(f"{self.path}: {prop} is {v}, not one cell")
        return v[0]

    def strings(self, prop):
        return [v for kind, v in self.parts(prop) if kind == "str"]

    def string(self, prop):
        v = self.strings(prop)
        if len(v) != 1:
            raise DtsError(f"{self.path}: {prop} is {v}, not one string")
        return v[0]

    def bytes(self, prop):
        return b"".join(v for kind, v in self.parts(prop) if kind == "bytes")

    def flag(self, prop):
        return prop in self.props

    def enabled(self):
        st = self.strings("status")[0] if "status" in self.props and self.strings("status") else "okay"
        return st in ("okay", "ok")


def _cell(tok):
    if tok.startswith("&"):
        return tok
    if tok.startswith("("):
        expr = tok
        if re.fullmatch(r"[\s0-9a-fA-FxX()|&~<>+\-*/]*", expr) and not re.search(r"\b[a-wyzA-WYZ_]", expr.replace("0x", "")):
            try:
                return int(eval(expr, {"__builtins__": {}}))  # noqa: S307 - digits and operators only, checked above
            except (SyntaxError, ZeroDivisionError):
                pass
        return tok
    try:
        return int(re.sub(r"(?i)(ull|ul|u|l)$", "", tok), 0)
    except ValueError:
        return tok                                   # a macro the preprocessor would expand


def _unescape(s):
    return bytes(s[1:-1], "utf-8").decode("unicode_escape")


class Source:
    def __init__(self):
        self.root = SNode("/")
        self.labels = {}         # label -> node
        self.detached = {}       # label -> node for &label blocks whose definition was not among the files
        self.files = []

    @classmethod
    def load(cls, *paths):
        src = cls()
        for p in paths:
            src.parse(Path(p).read_text(errors="replace"), str(p))
        return src

    def label(self, name):
        if name in self.labels:
            return self.labels[name]
        if name in self.detached:
            return self.detached[name]
        raise LookupError(f"absent: no label {name}")

    # Parsing
    def parse(self, text, origin="<string>"):
        self.files.append(origin)
        toks = []
        pos = 0
        for m in TOKEN.finditer(text):
            if m.start() != pos:
                raise DtsError(f"{origin}: cannot read {text[pos:m.start()][:40]!r}")
            pos = m.end()
            kind = m.lastgroup
            if kind in ("ws", "comment", "pp"):
                continue
            toks.append((kind, m.group(kind), text.count("\n", 0, m.start()) + 1))
        if pos != len(text):
            raise DtsError(f"{origin}: cannot read {text[pos:][:40]!r}")
        self._toks, self._i, self._origin = toks, 0, origin
        while self._i < len(toks):
            self._top()

    def _peek(self, k=0):
        i = self._i + k
        return self._toks[i] if i < len(self._toks) else (None, None, None)

    def _next(self):
        t = self._peek()
        if t[0] is None:
            raise DtsError(f"{self._origin}: unexpected end of file")
        self._i += 1
        return t

    def _expect(self, value):
        kind, v, line = self._next()
        if v != value:
            raise DtsError(f"{self._origin}:{line}: expected {value!r}, found {v!r}")

    def _top(self):
        kind, v, line = self._peek()
        if kind == "directive" and v in ("/dts-v1/", "/plugin/"):
            self._next()
            self._expect(";")
        elif kind == "directive" and v == "/memreserve/":
            while self._next()[1] != ";":
                pass
        elif kind == "directive" and v in ("/delete-node/",):
            self._next()
            target = self._next()[1]
            self._expect(";")
            if target.startswith("&"):
                node = self.labels.pop(target[1:], None) or self.detached.pop(target[1:], None)
                if node is not None and node.parent is not None:
                    node.parent.children.pop(node.name, None)
        elif kind == "ref":
            self._next()
            label = v[1:]
            if label.startswith("{"):
                node = self._path_node(label[1:-1])
            elif label in self.labels:
                node = self.labels[label]
            else:
                node = self.detached.setdefault(label, SNode(label))
            self._expect("{")
            self._body(node)
            self._expect(";")
        elif v == "/" or kind == "word":
            labels = []
            while self._peek(1)[1] == ":":
                labels.append(self._next()[1])
                self._next()
            name = self._next()[1]
            node = self.root if name == "/" else self._child(self.root, name)
            self._label(node, labels)
            self._expect("{")
            self._body(node)
            self._expect(";")
        else:
            raise DtsError(f"{self._origin}:{line}: unexpected {v!r}")

    def _path_node(self, path):
        node = self.root
        for part in [p for p in path.split("/") if p]:
            node = self._child(node, part)
        return node

    def _child(self, parent, name):
        if name not in parent.children:
            parent.children[name] = SNode(name, parent)
        return parent.children[name]

    def _label(self, node, labels):
        for lb in labels:
            if lb in self.detached:                 # a &label block seen before its definition: merge it in
                self._merge(node, self.detached.pop(lb))
            self.labels[lb] = node
            if lb not in node.labels:
                node.labels.append(lb)

    def _merge(self, dst, src):
        dst.props.update(src.props)
        for name, c in src.children.items():
            if name in dst.children:
                self._merge(dst.children[name], c)
            else:
                c.parent = dst
                dst.children[name] = c

    def _body(self, node):
        while True:
            kind, v, line = self._peek()
            if v == "}":
                self._next()
                return
            if kind == "directive" and v == "/delete-property/":
                self._next()
                node.props.pop(self._next()[1], None)
                self._expect(";")
                continue
            if kind == "directive" and v == "/delete-node/":
                self._next()
                name = self._next()[1]
                node.children.pop(name, None)
                self._expect(";")
                continue
            if kind != "word":
                raise DtsError(f"{self._origin}:{line}: unexpected {v!r} in {node.path}")
            labels = []
            while self._peek(1)[1] == ":":
                labels.append(self._next()[1])
                self._next()
            name = self._next()[1]
            after = self._peek()[1]
            if after == "{":
                self._next()
                child = self._child(node, name)
                self._label(child, labels)
                self._body(child)
                self._expect(";")
            elif after == ";":
                self._next()
                node.props[name] = []
            elif after == "=":
                self._next()
                node.props[name] = self._value()
            elif self._peek()[0] == "paren" and not labels:   # an unexpanded macro statement: MACRO(a, b);
                node.macros.append(name + self._next()[1])
                self._expect(";")
            else:
                raise DtsError(f"{self._origin}:{line}: unexpected {after!r} after {name}")

    def _value(self):
        parts = []
        while True:
            kind, v, line = self._next()
            if kind == "directive" and v == "/bits/":
                self._next()                        # the width: cells are kept as integers either way
                kind, v, line = self._next()
            if v == "<":
                cells = []
                while True:
                    kind, v, line = self._next()
                    if v == ">":
                        break
                    if kind == "word" and self._peek()[0] == "paren":     # a function-like macro: MACRO(a, b)
                        cells.append(v + self._next()[1])
                    elif kind in ("word", "ref", "paren"):
                        cells.append(_cell(v))
                    elif v == ":":                  # a label inside cells: ignored
                        continue
                    else:
                        raise DtsError(f"{self._origin}:{line}: unexpected {v!r} in cells")
                parts.append(("cells", cells))
            elif kind == "string":
                parts.append(("str", _unescape(v)))
            elif v == "[":
                hexd = ""
                while True:
                    kind, v, line = self._next()
                    if v == "]":
                        break
                    hexd += v
                if len(hexd) % 2 or not re.fullmatch(r"[0-9a-fA-F]*", hexd):
                    raise DtsError(f"{self._origin}:{line}: bad byte string")
                parts.append(("bytes", bytes.fromhex(hexd)))
            elif kind == "ref":
                parts.append(("ref", v))
            else:
                raise DtsError(f"{self._origin}:{line}: unexpected {v!r} in a value")
            kind, v, line = self._next()
            if v == ";":
                return parts
            if v != ",":
                raise DtsError(f"{self._origin}:{line}: expected ',' or ';', found {v!r}")
