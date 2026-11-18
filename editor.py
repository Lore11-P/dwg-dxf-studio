"""Modifica del disegno: selezione, proprietà, trasformazioni, undo.

Nessuna dipendenza da Tk: si può usare e provare da sola.
"""

from __future__ import annotations

import math
from typing import Callable

from ezdxf import bbox
from ezdxf.colors import aci2rgb
from ezdxf.math import Matrix44

# finestre di layout e parti interne di blocchi/quote: non si modificano da qui
SKIP = {"VIEWPORT", "SEQEND", "VERTEX", "ATTRIB"}
# disegnati ma non modificabili da ezdxf (proxy): si vedono, non si selezionano
NOT_EDITABLE = {"ACAD_TABLE", "MULTILEADER", "OLE2FRAME", "OLEFRAME"}
# shortcut: copre solo i proxy noti; ampliare se altri tipi disegnati falliscono

NAMES = {
    "LINE": "Linea",
    "LWPOLYLINE": "Polilinea",
    "POLYLINE": "Polilinea 3D",
    "CIRCLE": "Cerchio",
    "ARC": "Arco",
    "ELLIPSE": "Ellisse",
    "SPLINE": "Spline",
    "TEXT": "Testo",
    "MTEXT": "Testo",
    "INSERT": "Blocco",
    "DIMENSION": "Quota",
    "HATCH": "Tratteggio",
    "SOLID": "Solid",
    "POINT": "Punto",
    "LEADER": "Direttrice",
    "MLINE": "Multilinea",
    "IMAGE": "Immagine",
}

Undo = Callable[[], None]


def label(entity) -> str:
    return f"{NAMES.get(entity.dxftype(), entity.dxftype())}  #{entity.dxf.handle}"


def layer_of(entity):
    doc = entity.doc
    name = entity.dxf.get("layer", "0")
    return doc.layers.get(name) if doc is not None and name in doc.layers else None


def selectable(entity) -> bool:
    """True se l'entità si può selezionare: non è una finestra né sta su un layer spento/bloccato."""
    if entity.dxftype() in SKIP or entity.dxftype() in NOT_EDITABLE or entity.dxf.get("invisible", 0):
        return False
    layer = layer_of(entity)
    return layer is None or not (layer.is_off() or layer.is_frozen() or layer.is_locked())


def box_of(entity):
    ext = bbox.extents([entity])
    return ext if ext is not None and ext.has_data else None


def center_of(entity) -> tuple[float, float]:
    ext = box_of(entity)
    return (ext.center.x, ext.center.y) if ext is not None else (0.0, 0.0)


class PickIndex:
    """Riquadri delle entità, calcolati una volta sola e riusati per il click."""

    def __init__(self, layout) -> None:
        self.layout = layout
        self._boxes: dict[str, object] = {}

    def box(self, entity):
        key = entity.dxf.handle
        if key not in self._boxes:
            self._boxes[key] = box_of(entity)
        return self._boxes[key]

    def forget(self, entity) -> None:
        self._boxes.pop(entity.dxf.handle, None)

    def pick(self, x: float, y: float, tolerance: float):
        """Entità più piccola vicino al punto (entro `tolerance` unità del disegno), o None.

        Vince il riquadro più piccolo: un testo sopra una grande polilinea si seleziona
        dal testo, non dalla polilinea che lo contiene.
        """
        best = None
        for entity in self.layout:
            if not selectable(entity):
                continue
            ext = self.box(entity)
            if ext is None:
                continue
            # distanza punto → riquadro (0 se il punto è dentro)
            dx = max(ext.extmin.x - x, 0.0, x - ext.extmax.x)
            dy = max(ext.extmin.y - y, 0.0, y - ext.extmax.y)
            distance = math.hypot(dx, dy)
            if distance > tolerance:
                continue
            area = (ext.extmax.x - ext.extmin.x) * (ext.extmax.y - ext.extmin.y)
            if best is None or (area, distance) < best[:2]:
                best = (area, distance, entity)
        return None if best is None else best[2]


class UndoStack:
    def __init__(self) -> None:
        self._items: list[tuple[str, Undo, object | None, bool]] = []

    def push(self, text: str, undo: Undo, entity=None, structural: bool = False) -> None:
        # structural: l'undo rimette un'entità nel layout (cambia il numero di entità)
        self._items.append((text, undo, entity, structural))

    def next_is_structural(self) -> bool:
        return bool(self._items) and self._items[-1][3]

    def undo(self) -> tuple[str, object | None] | None:
        if not self._items:
            return None
        text, undo, entity, _structural = self._items.pop()
        undo()
        return text, entity

    def clear(self) -> None:
        self._items.clear()

    def __bool__(self) -> bool:
        return bool(self._items)


# --- trasformazioni -------------------------------------------------------
def about(pivot: tuple[float, float], matrix: Matrix44) -> Matrix44:
    """Matrice applicata attorno a `pivot` invece che all'origine."""
    px, py = pivot
    return Matrix44.translate(px, py, 0) * matrix * Matrix44.translate(-px, -py, 0)


def move(dx: float, dy: float) -> Matrix44:
    return Matrix44.translate(dx, dy, 0)


def rotate(degrees: float) -> Matrix44:
    return Matrix44.z_rotate(math.radians(degrees))


def scale(factor: float) -> Matrix44:
    return Matrix44.scale(factor)


def transform(entity, matrix: Matrix44) -> Undo:
    entity.transform(matrix)
    inverse = matrix.copy()
    inverse.inverse()
    return lambda: entity.transform(inverse)


# --- proprietà ------------------------------------------------------------
def text_of(entity) -> str | None:
    kind = entity.dxftype()
    if kind == "MTEXT":
        return entity.text
    if kind == "TEXT":
        return entity.dxf.text
    return None


def set_text(entity, text: str) -> Undo:
    old = text_of(entity)
    if old is None:
        return lambda: None
    if entity.dxftype() == "MTEXT":
        entity.text = text
    else:
        entity.dxf.text = text
    return lambda: set_text(entity, old)


def effective_color(entity) -> tuple[int, int, int]:
    """Colore mostrato: RGB vero, ACI esplicito o colore del layer."""
    rgb = entity.rgb
    if rgb is not None:
        return rgb.r, rgb.g, rgb.b
    aci = entity.dxf.get("color", 256)
    if aci in (0, 256):  # da blocco / da layer: si usa il colore del layer
        layer = layer_of(entity)
        if layer is not None and layer.rgb is not None:
            return layer.rgb[0], layer.rgb[1], layer.rgb[2]
        aci = layer.color if layer is not None else 7
    if aci == 7 or not 0 < aci <= 256:  # 7 e ACI non validi (0, >256): bianco su foglio bianco = nero
        return 0, 0, 0
    return aci2rgb(aci)


def set_color(entity, rgb: tuple[int, int, int]) -> Undo:
    old_true, old_aci = entity.dxf.get("true_color"), entity.dxf.get("color")
    entity.rgb = rgb

    def undo() -> None:
        if old_true is None:
            entity.dxf.discard("true_color")
        else:
            entity.dxf.true_color = old_true
        if old_aci is None:
            entity.dxf.discard("color")
        else:
            entity.dxf.color = old_aci

    return undo


def use_layer_color(entity) -> Undo:
    old_true, old_aci = entity.dxf.get("true_color"), entity.dxf.get("color")
    entity.dxf.discard("true_color")
    entity.dxf.color = 256

    def undo() -> None:
        if old_true is not None:
            entity.dxf.true_color = old_true
        if old_aci is not None:
            entity.dxf.color = old_aci

    return undo


def set_layer(entity, name: str) -> Undo:
    old = entity.dxf.get("layer", "0")
    entity.dxf.layer = name
    return lambda: setattr(entity.dxf, "layer", old)


def set_lineweight(entity, weight: int) -> Undo:
    old = entity.dxf.get("lineweight", -1)
    entity.dxf.lineweight = weight
    return lambda: setattr(entity.dxf, "lineweight", old)


def delete(layout, entity) -> Undo:
    """Toglie l'entità dal layout lasciandola viva: l'undo la rimette dov'era."""
    space = layout.entity_space
    at = space.entities.index(entity)
    layout.unlink_entity(entity)

    def undo() -> None:
        layout.add_entity(entity)
        space.remove(entity)
        space.insert(at, entity)

    return undo


# --- layer ----------------------------------------------------------------
def layer_names(doc) -> list[str]:
    """Nomi dei layer per i menu, senza i layer interni di AutoCAD/Xref (`*...`)."""
    names = [layer.dxf.name for layer in doc.layers if not layer.dxf.name.startswith("*")]
    return sorted(names or [layer.dxf.name for layer in doc.layers])


def set_layer_visible(doc, name: str, visible: bool) -> Undo:
    layer = doc.layers.get(name)
    was_off = layer.is_off()

    def apply(show: bool) -> None:
        layer.on() if show else layer.off()

    apply(visible)
    return lambda: apply(not was_off)


def set_layer_color(doc, name: str, aci: int) -> Undo:
    layer = doc.layers.get(name)
    old, old_true = layer.color, layer.dxf.get("true_color")
    # il vero colore vince sull'ACI: va tolto, altrimenti il cambio non si vede
    layer.dxf.discard("true_color")
    layer.color = aci

    def undo() -> None:
        layer.color = old
        if old_true is not None:
            layer.dxf.true_color = old_true

    return undo


def layer_rgb(color: int) -> tuple[int, int, int]:
    return (0, 0, 0) if color == 7 or not 0 < color <= 256 else aci2rgb(color)


# --- anteprima ------------------------------------------------------------
class View:
    """Converte punti del disegno in pixel dell'immagine renderizzata e viceversa."""

    def __init__(self, matrix: Matrix44, dpi: int) -> None:
        self.matrix = matrix
        self.dpi = dpi
        self._inverse = matrix.copy()
        self._inverse.inverse()

    def to_image(self, x: float, y: float) -> tuple[float, float]:
        p = self.matrix.transform((x, y, 0))
        k = self.dpi / 72  # il backend lavora in punti (1/72 di pollice)
        return p.x * k, p.y * k

    def to_model(self, px: float, py: float) -> tuple[float, float]:
        p = self._inverse.transform((px * 72 / self.dpi, py * 72 / self.dpi, 0))
        return p.x, p.y
