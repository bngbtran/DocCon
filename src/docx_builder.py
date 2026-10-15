"""Page layouts (see layout.py) → .docx, one Word section per PDF page."""
import copy
import io
from typing import List, Optional

from docx import Document
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Pt
from lxml import etree

from .fonts import COMMON_FONTS, font_hint
from .layout import layout_region, _atom

_JC = {"left": "left", "center": "center", "right": "right", "justify": "both"}


def _tw(pt: float) -> str:
    return str(int(round(pt * 20)))


def _emu(pt: float) -> int:
    return int(round(pt * 12700))


def _el(tag: str, **attrs) -> OxmlElement:
    e = OxmlElement(tag)
    for k, v in attrs.items():
        e.set(qn("w:" + k), str(v))
    return e


class DocxBuilder:
    def __init__(self):
        self.doc = Document()
        body = self.doc.element.body
        for child in list(body):
            if child.tag != qn("w:sectPr"):
                body.remove(child)
        self._fonts = {}
        self._z = 251658240
        self._pic_id = 1000
        self._setup_document()

    # ── document-level settings ──────────────────────────────────────────

    def _setup_document(self):
        settings = self.doc.settings.element
        compat = settings.find(qn("w:compat"))
        if compat is None:
            compat = _el("w:compat")
            settings.append(compat)
        for cs in compat.findall(qn("w:compatSetting")):
            if cs.get(qn("w:name")) == "compatibilityMode":
                cs.set(qn("w:val"), "15")

        normal = self.doc.styles["Normal"]
        pf = normal.paragraph_format
        pf.space_before = Pt(0)
        pf.space_after = Pt(0)
        pf.line_spacing = 1.0
        pf.widow_control = False

    def _set_default_font(self, font: str, size: float):
        normal = self.doc.styles["Normal"]
        normal.font.name = font
        normal.font.size = Pt(size)
        rpr = normal.element.get_or_add_rPr()
        rfonts = rpr.find(qn("w:rFonts"))
        for a in ("ascii", "hAnsi", "cs", "eastAsia"):
            rfonts.set(qn("w:" + a), font)

    # ── pages ────────────────────────────────────────────────────────────

    def add_page(self, lay: dict, first: bool):
        body = self.doc.element.body
        sectPr = body.get_or_add_sectPr()
        if not first:
            self._close_section(sectPr)
        else:
            font, size = _dominant_font(lay)
            if font:
                self._set_default_font(font, size)
        self._configure_section(sectPr, lay)

        start = len(body) - 1  # index of sectPr: new content goes before it
        cursor = lay["margins"]["top"]
        self._render_items(self.doc, lay["items"], cursor, top_level=True)

        new = [c for c in list(body)[start:] if c.tag != qn("w:sectPr")]
        if not new or (lay["floats"] and new[0].tag != qn("w:p")):
            p = self._spacer_element(1.0)
            if new:
                new[0].addprevious(p)
            else:
                sectPr.addprevious(p)
            new.insert(0, p)
        if new[-1].tag != qn("w:p"):
            sectPr.addprevious(self._spacer_element(1.0))

        anchor_p = new[0]
        for im in lay["floats"]:
            self._add_float(anchor_p, im)

    def _close_section(self, sectPr):
        """Store this page's settings in its last paragraph; the body sectPr moves on."""
        last = sectPr.getprevious()
        if last is None or last.tag != qn("w:p"):
            last = self._spacer_element(1.0)
            sectPr.addprevious(last)
        pPr = last.find(qn("w:pPr"))
        if pPr is None:
            pPr = _el("w:pPr")
            last.insert(0, pPr)
        pPr.append(copy.deepcopy(sectPr))

    @staticmethod
    def _configure_section(sectPr, lay: dict):
        for tag in ("w:pgSz", "w:pgMar", "w:docGrid", "w:type"):
            for e in sectPr.findall(qn(tag)):
                sectPr.remove(e)
        w, h = lay["width"], lay["height"]
        m = lay["margins"]
        pgSz = _el("w:pgSz", w=_tw(w), h=_tw(h))
        if w > h:
            pgSz.set(qn("w:orient"), "landscape")
        pgMar = _el("w:pgMar", top=_tw(m["top"]), right=_tw(m["right"]), bottom=_tw(m["bottom"]),
                    left=_tw(m["left"]), header="0", footer="0", gutter="0")
        sectPr.insert(0, pgMar)
        sectPr.insert(0, pgSz)
        sectPr.insert(0, _el("w:type", val="nextPage"))

    def save(self, output_path: str):
        self._write_font_table()
        self.doc.save(output_path)

    # ── items ────────────────────────────────────────────────────────────

    def _render_items(self, container, items: List[dict], cursor: float, top_level=False) -> float:
        prev_kind = None
        for it in items:
            kind = it["type"]
            gap = it["top"] - cursor
            if kind == "para":
                self._para(container, it, max(0.0, gap))
            elif kind in ("table", "columns"):
                if gap > 0.7 or prev_kind in ("table", "columns"):
                    self._spacer(container, max(gap, 1.0))
                if kind == "table":
                    self._table(container, it)
                else:
                    self._columns(container, it)
            elif kind == "image":
                self._inline_image(container, it, max(0.0, gap))
            elif kind == "hline":
                self._hline(container, it, max(0.0, gap))
            cursor = max(cursor, it["top"]) + (it["bottom"] - it["top"])
            prev_kind = kind
        return cursor

    def _new_p(self, container):
        return container.add_paragraph()._p

    def _spacer_element(self, height: float):
        p = _el("w:p")
        pPr = _el("w:pPr")
        pPr.append(_el("w:spacing", before="0", after="0", line=_tw(max(height, 0.7)), lineRule="exact"))
        rPr = _el("w:rPr")
        rPr.append(_el("w:sz", val="2"))
        pPr.append(rPr)
        p.append(pPr)
        return p

    def _spacer(self, container, height: float):
        p = self._new_p(container)
        p.getparent().replace(p, self._spacer_element(height))

    def _ppr(self, p, before=0.0, line=None, rule="exact", align=None, left=0.0, right=0.0,
             first=0.0, tabs=None):
        pPr = p.get_or_add_pPr()
        for child in list(pPr):
            pPr.remove(child)
        pPr.append(_el("w:widowControl", val="0"))
        if tabs:
            t = _el("w:tabs")
            for s in tabs:
                tab = _el("w:tab", val=s["align"], pos=_tw(max(0.0, s["pos"])))
                if s.get("leader"):
                    tab.set(qn("w:leader"), s["leader"])
                t.append(tab)
            pPr.append(t)
        sp = _el("w:spacing", before=_tw(before), after="0")
        if line is not None:
            sp.set(qn("w:line"), _tw(line) if rule != "auto" else str(int(line)))
            sp.set(qn("w:lineRule"), rule)
        pPr.append(sp)
        ind = _el("w:ind", left=_tw(left), right=_tw(right))
        if first >= 0:
            ind.set(qn("w:firstLine"), _tw(first))
        else:
            ind.set(qn("w:hanging"), _tw(-first))
        pPr.append(ind)
        if align:
            pPr.append(_el("w:jc", val=_JC.get(align, "left")))
        return pPr

    def _para(self, container, it: dict, before: float):
        p = self._new_p(container)
        self._ppr(p, before=before, line=it["pitch"], align=it["align"], left=it["left"],
                  right=it["right"], first=it["first"], tabs=it["tabs"])
        last_text = ""
        for li, line in enumerate(it["lines"]):
            runs = line["runs"]
            if li > 0:
                if it["breaks"][li - 1]:
                    br = OxmlElement("w:r")
                    br.append(OxmlElement("w:br"))
                    p.append(br)
                    last_text = ""
                else:
                    first_txt = next((r["text"] for r in runs if not r.get("tab")), "")
                    if last_text and not last_text[-1].isspace() and last_text[-1] != "-" \
                            and first_txt and not first_txt[0].isspace():
                        runs = [dict(runs[0], text=" " + runs[0]["text"])] + runs[1:] \
                            if not runs[0].get("tab") else runs
            for r in runs:
                if r.get("tab"):
                    tr = OxmlElement("w:r")
                    tr.append(OxmlElement("w:tab"))
                    p.append(tr)
                    last_text = "\t"
                elif r["text"]:
                    p.append(self._run(r, line["size"]))
                    last_text = r["text"]

    def _run(self, r: dict, line_size: float):
        el = OxmlElement("w:r")
        rPr = OxmlElement("w:rPr")
        font = r.get("font") or "Times New Roman"
        self._note_font(font, r)
        rPr.append(_el("w:rFonts", ascii=font, hAnsi=font, cs=font, eastAsia=font))
        if r.get("bold"):
            rPr.append(_el("w:b"))
            rPr.append(_el("w:bCs"))
        if r.get("italic"):
            rPr.append(_el("w:i"))
            rPr.append(_el("w:iCs"))
        if r.get("strike"):
            rPr.append(_el("w:strike"))
        color = r.get("color") or 0
        if color:
            rPr.append(_el("w:color", val=f"{color & 0xFFFFFF:06X}"))
        size = line_size if r.get("super") else r["size"]
        half = str(max(2, int(round(size * 2))))
        rPr.append(_el("w:sz", val=half))
        rPr.append(_el("w:szCs", val=half))
        if r.get("underline"):
            rPr.append(_el("w:u", val="single"))
        if r.get("super"):
            rPr.append(_el("w:vertAlign", val="superscript"))
        el.append(rPr)
        t = OxmlElement("w:t")
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        t.text = r["text"]
        el.append(t)
        return el

    def _note_font(self, font: str, r: dict):
        if font not in self._fonts and (font not in COMMON_FONTS or font in ("Aptos", "Aptos Display",
                                                                          "Cascadia Code", "Cascadia Mono")):
            self._fonts[font] = font_hint(font, r.get("mono", False), r.get("serif", False))

    def _hline(self, container, it: dict, before: float):
        p = self._new_p(container)
        pPr = self._ppr(p, before=before, line=max(1.0, it["bottom"] - it["top"]),
                        left=it["left"], right=it["right"])
        bdr = _el("w:pBdr")
        sz = max(2, min(96, int(round(it["w"] * 8))))
        bdr.append(_el("w:bottom", val="single", sz=str(sz), space="0", color=it["color"]))
        pPr.insert(1, bdr)
        rPr = _el("w:rPr")
        rPr.append(_el("w:sz", val="2"))
        pPr.append(rPr)

    def _inline_image(self, container, it: dict, before: float):
        im = it["img"]
        b = im["bbox"]
        par = container.add_paragraph()
        self._ppr(par._p, before=before, line=240, rule="auto", left=it["left"])
        run = par.add_run()
        try:
            run.add_picture(io.BytesIO(im["png"]), width=Pt(b[2] - b[0]), height=Pt(b[3] - b[1]))
        except Exception:
            return
        rPr = run._r.get_or_add_rPr()
        rPr.append(_el("w:sz", val="2"))

    def _add_float(self, p, im: dict):
        b = im["bbox"]
        w, h = max(1.0, b[2] - b[0]), max(1.0, b[3] - b[1])
        try:
            inline = self.doc.part.new_pic_inline(io.BytesIO(im["png"]), _emu(w), _emu(h))
        except Exception:
            return
        self._z += 1
        self._pic_id += 1
        behind = "1" if im.get("behind", True) else "0"
        anchor = parse_xml(
            f'<wp:anchor {nsdecls("wp")} distT="0" distB="0" distL="0" distR="0" simplePos="0" '
            f'relativeHeight="{self._z}" behindDoc="{behind}" locked="0" layoutInCell="0" allowOverlap="1">'
            f'<wp:simplePos x="0" y="0"/>'
            f'<wp:positionH relativeFrom="page"><wp:posOffset>{_emu(b[0])}</wp:posOffset></wp:positionH>'
            f'<wp:positionV relativeFrom="page"><wp:posOffset>{_emu(b[1])}</wp:posOffset></wp:positionV>'
            f'<wp:extent cx="{_emu(w)}" cy="{_emu(h)}"/><wp:effectExtent l="0" t="0" r="0" b="0"/>'
            f'<wp:wrapNone/></wp:anchor>'
        )
        for tag in ("wp:docPr", "wp:cNvGraphicFramePr", "a:graphic"):
            child = inline.find(qn(tag))
            if child is not None:
                if tag == "wp:docPr":
                    child.set("id", str(self._pic_id))
                anchor.append(child)
        run = OxmlElement("w:r")
        drawing = OxmlElement("w:drawing")
        drawing.append(anchor)
        run.append(drawing)
        pPr = p.find(qn("w:pPr"))
        if pPr is not None:
            pPr.addnext(run)
        else:
            p.insert(0, run)

    # ── tables ───────────────────────────────────────────────────────────

    def _make_table(self, container, n_rows: int, widths: List[float], indent: float,
                    borders: Optional[float]):
        table = container.add_table(rows=n_rows, cols=len(widths))
        tbl = table._tbl
        tblPr = tbl.tblPr
        for tag in ("w:tblStyle", "w:tblW", "w:tblInd", "w:tblLayout", "w:tblBorders",
                    "w:tblCellMar", "w:tblLook"):
            for e in tblPr.findall(qn(tag)):
                tblPr.remove(e)
        tblPr.append(_el("w:tblW", w=_tw(sum(widths)), type="dxa"))
        tblPr.append(_el("w:tblInd", w=_tw(indent), type="dxa"))
        bd = _el("w:tblBorders")
        for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
            if borders:
                bd.append(_el("w:" + side, val="single", sz=str(max(2, min(96, int(round(borders * 8))))),
                              space="0", color="000000"))
            else:
                bd.append(_el("w:" + side, val="nil"))
        tblPr.append(bd)
        tblPr.append(_el("w:tblLayout", type="fixed"))
        mar = _el("w:tblCellMar")
        for side in ("top", "left", "bottom", "right"):
            mar.append(_el("w:" + side, w="0", type="dxa"))
        tblPr.append(mar)

        grid = tbl.tblGrid
        for gc in list(grid):
            grid.remove(gc)
        for wd in widths:
            grid.append(_el("w:gridCol", w=_tw(wd)))
        for row in table.rows:
            for ci, cell in enumerate(row.cells):
                tcPr = cell._tc.get_or_add_tcPr()
                for e in tcPr.findall(qn("w:tcW")):
                    tcPr.remove(e)
                tcPr.insert(0, _el("w:tcW", w=_tw(widths[ci]), type="dxa"))
        return table

    @staticmethod
    def _clear_cell(cell):
        for p in list(cell._tc.findall(qn("w:p"))):
            cell._tc.remove(p)

    def _finish_cell(self, cell):
        last = cell._tc[-1] if len(cell._tc) else None
        if last is None or last.tag != qn("w:p"):
            cell._tc.append(self._spacer_element(0.7))

    @staticmethod
    def _row_height(row, height: float):
        trPr = row._tr.get_or_add_trPr()
        trPr.append(_el("w:trHeight", val=_tw(height), hRule="atLeast"))
        trPr.append(_el("w:cantSplit"))

    def _columns(self, container, it: dict):
        bounds = it["bounds"]
        widths = [max(1.0, bounds[k + 1] - bounds[k]) for k in range(len(bounds) - 1)]
        table = self._make_table(container, 1, widths, 0.0, None)
        self._row_height(table.rows[0], it["bottom"] - it["top"])
        for ci, col_items in enumerate(it["cols"]):
            cell = table.cell(0, ci)
            self._clear_cell(cell)
            self._render_items(cell, col_items, it["top"])
            self._finish_cell(cell)

    def _table(self, container, it: dict):
        t = it["table"]
        xs, ys = t["xs"], t["ys"]
        widths = [max(1.0, xs[k + 1] - xs[k]) for k in range(len(xs) - 1)]
        table = self._make_table(container, len(ys) - 1, widths, xs[0] - it["x0"],
                                 max(0.25, t.get("border_pt", 0.5)))
        for ri in range(len(ys) - 1):
            self._row_height(table.rows[ri], ys[ri + 1] - ys[ri])

        for c in t["cells"]:
            r1 = min(len(ys) - 2, c["r"] + c["rs"] - 1)
            c1 = min(len(xs) - 2, c["c"] + c["cs"] - 1)
            cell = table.cell(c["r"], c["c"])
            if r1 > c["r"] or c1 > c["c"]:
                try:
                    cell = cell.merge(table.cell(r1, c1))
                except Exception:
                    pass
            self._clear_cell(cell)
            if c.get("fill"):
                tcPr = cell._tc.get_or_add_tcPr()
                tcPr.append(_el("w:shd", val="clear", color="auto", fill=c["fill"]))
            x0, x1 = xs[c["c"]], xs[c1 + 1]
            atoms = [_atom("line", ln["bbox"], ln) for ln in c["lines"]]
            items = layout_region(atoms, x0, x1) if atoms else []
            self._render_items(cell, items, ys[c["r"]])
            self._finish_cell(cell)

    # ── font table ───────────────────────────────────────────────────────

    def _write_font_table(self):
        if not self._fonts:
            return
        part = next((p for p in self.doc.part.package.iter_parts()
                     if str(p.partname) == "/word/fontTable.xml"), None)
        if part is None:
            return
        root = etree.fromstring(part.blob)
        w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        for name, (alt, family, pitch) in self._fonts.items():
            f = etree.SubElement(root, f"{{{w}}}font")
            f.set(f"{{{w}}}name", name)
            for tag, val in (("altName", alt), ("family", family), ("pitch", pitch)):
                e = etree.SubElement(f, f"{{{w}}}{tag}")
                e.set(f"{{{w}}}val", val)
        part._blob = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _dominant_font(lay: dict):
    weight = {}

    def visit(items):
        for it in items:
            if it["type"] == "para":
                for l in it["lines"]:
                    for r in l["runs"]:
                        if not r.get("tab"):
                            k = (r["font"], r["size"])
                            weight[k] = weight.get(k, 0) + len(r["text"])
            elif it["type"] == "columns":
                for c in it["cols"]:
                    visit(c)
    visit(lay["items"])
    if not weight:
        return None, 12
    return max(weight, key=weight.get)
