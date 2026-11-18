"""DWG/DXF -> PDF e immagini: anteprima e conversione in locale."""

from __future__ import annotations

import io
import math
import os
import queue
import sys
import tempfile
import threading
from pathlib import Path

import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

import ezdxf
import editor
import pymupdf
from ezdxf import bbox
from ezdxf.addons import odafc
from ezdxf.addons.drawing import Frontend, RenderContext, config, layout
from ezdxf.addons.drawing.pymupdf import PyMuPdfBackend, get_coordinate_output_space
from ezdxf.math import Matrix44
from PIL import Image, ImageTk

MARGIN_MM = 5.0
ODA_URL = "https://www.opendesign.com/guestfiles/oda_file_converter"
FIT = "Adatta al disegno"
PAGES = {"A4": (210, 297), "A3": (297, 420), "A2": (420, 594), "A1": (594, 841), "A0": (841, 1189)}
MAX_PIXELS = 6000  # oltre, PNG/JPG diventano enormi e lento il render

# spessori DXF in 1/100 mm (-1 = da layer, -2 = da blocco, -3 = predefinito)
WEIGHTS = {
    -3: "Predefinito", -2: "Da blocco", -1: "Da layer", 0: "0.00 mm", 5: "0.05 mm", 9: "0.09 mm",
    13: "0.13 mm", 15: "0.15 mm", 18: "0.18 mm", 20: "0.20 mm", 25: "0.25 mm",
    30: "0.30 mm", 35: "0.35 mm", 40: "0.40 mm", 50: "0.50 mm", 53: "0.53 mm",
    60: "0.60 mm", 70: "0.70 mm", 80: "0.80 mm", 100: "1.00 mm", 120: "1.20 mm",
    140: "1.40 mm", 200: "2.00 mm",
}
# i sette colori ACI che si possono dare a un layer
ACI_COLORS = {
    1: (255, 0, 0), 2: (255, 255, 0), 3: (0, 255, 0), 4: (0, 255, 255),
    5: (0, 0, 255), 6: (255, 0, 255), 7: (255, 255, 255),
}


def oda_available() -> bool:
    """True se ODA File Converter è raggiungibile (anche in versioni con cartella versionata)."""
    if odafc.is_installed():
        return True
    oda_dir = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ODA"
    for exe in oda_dir.glob("ODAFileConverter*/ODAFileConverter.exe"):
        ezdxf.options.set("odafc-addon", "win_exec_path", str(exe))
        return True
    return False


def load_drawing(path) -> ezdxf.document.Drawing:
    """Apre un DXF, oppure un DWG tramite ODA File Converter."""
    if Path(path).suffix.lower() == ".dwg":
        if not oda_available():
            raise RuntimeError(
                "Per aprire i DWG serve ODA File Converter (gratuito).\n\n"
                f"Scaricalo da {ODA_URL}, installalo e riapri l'app.\n"
                "I file DXF funzionano subito, senza installare nulla."
            )
        doc = odafc.readfile(str(path))
    else:
        doc = ezdxf.readfile(str(path))
    # ezdxf salta in silenzio le entità su layer mancanti: li ricreiamo.
    for layer in {e.dxf.get("layer") for e in doc.entitydb.values() if e.dxf.hasattr("layer")}:
        if layer not in doc.layers:
            doc.layers.add(layer)
    return doc


def page_dims(page_name: str, width: float, height: float) -> tuple[float, float]:
    if page_name in PAGES:
        w_mm, h_mm = PAGES[page_name]
        return (h_mm, w_mm) if width > height else (w_mm, h_mm)
    # pagina grande quanto il disegno: le unità del DXF valgono come mm
    return max(width, 10.0), max(height, 10.0)


def render(doc, lay, *, mono: bool = False, page_name: str = "A3"):
    """Disegna il layout una volta: restituisce (backend, pagina).

    Il backend può essere usato per una sola esportazione: dopo il primo
    get_pdf_bytes/get_pixmap_bytes le registrazioni vengono trasformate.
    """
    cfg = config.Configuration(
        background_policy=config.BackgroundPolicy.WHITE,
        color_policy=config.ColorPolicy.BLACK if mono else config.ColorPolicy.COLOR,
    )
    out = PyMuPdfBackend()
    Frontend(RenderContext(doc), out, config=cfg).draw_layout(lay)
    ext = bbox.extents(lay)
    width, height = (ext.size.x, ext.size.y) if ext is not None else (0.0, 0.0)
    w_mm, h_mm = page_dims(page_name, width, height)
    page = layout.Page(w_mm, h_mm, layout.Units.mm, margins=layout.Margins.all(MARGIN_MM))
    return out, page


def placement(out, page):
    """Matrice entità → punti (1/72") della pagina, come la calcola il backend.

    Va letta prima di get_pixmap_bytes: l'esportazione trasforma le registrazioni.
    """
    settings = layout.Settings()
    render_box = out.player().bbox()
    if not render_box.has_data:  # nulla di disegnabile: la pagina resta bianca
        return Matrix44(), page
    output_layout = layout.Layout(render_box, flip_y=True)
    final = output_layout.get_final_page(page, settings)
    settings.output_coordinate_space = get_coordinate_output_space(final)
    matrix = output_layout.get_placement_matrix(final, settings=settings, top_origin=True)
    return matrix, final


def fit_dpi(page, dpi: int) -> int:
    longest_in = max(page.width_in_mm, page.height_in_mm) / 25.4
    return dpi if longest_in * dpi <= MAX_PIXELS else max(1, int(MAX_PIXELS / longest_in))


def blank_bytes(page, fmt: str, dpi: int) -> bytes:
    """Pagina bianca: layout che non disegnano nulla (finestre vuote, viste non piane)."""
    if fmt == "pdf":
        pdf = pymupdf.open()
        pdf.new_page(
            width=max(1.0, page.width_in_mm * 72 / 25.4),
            height=max(1.0, page.height_in_mm * 72 / 25.4),
        )
        return pdf.tobytes()
    w = max(1, int(page.width_in_mm / 25.4 * dpi))
    h = max(1, int(page.height_in_mm / 25.4 * dpi))
    buf = io.BytesIO()
    img = Image.new("RGB", (w, h), "white")
    if fmt == "jpg":
        img.save(buf, "JPEG", quality=92)
    else:
        img.save(buf, "PNG")
    return buf.getvalue()


def export(
    doc, lay, path, *, fmt: str, dpi: int = 300, mono: bool = False, page_name: str = "A3"
) -> Path:
    out, page = render(doc, lay, mono=mono, page_name=page_name)
    dpi = fit_dpi(page, dpi)
    path = Path(path)
    try:
        if fmt == "pdf":
            path.write_bytes(out.get_pdf_bytes(page))
        else:
            img = Image.open(io.BytesIO(out.get_pixmap_bytes(page, fmt="png", dpi=dpi)))
            if fmt == "jpg":
                img.convert("RGB").save(path, quality=92)
            else:
                img.save(path)
    except ValueError:  # backend: "empty bounding box" (layout senza entità disegnabili)
        path.write_bytes(blank_bytes(page, fmt, dpi))
    return path


def layout_names(doc) -> list[str]:
    return list(dict.fromkeys(["Model", *doc.layouts.names_in_taborder()]))


def get_layout(doc, name: str):
    if name == "Model":
        return doc.modelspace()
    return doc.layouts.get(name)


def has_content(doc, name: str) -> bool:
    """True se la tavola stampa qualcosa: entità proprie o una finestra che mostra il modello.

    I layout di carta appena creati contengono solo la finestra "attiva" (status 1), che è
    il foglio stesso e non produce nulla: quelli vengono esclusi dall'elenco.
    """
    layout_obj = get_layout(doc, name)
    return any(e.dxftype() != "VIEWPORT" or e.dxf.status > 1 for e in layout_obj)


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.doc = None
        self.src: Path | None = None
        self.preview: Image.Image | None = None
        self._photo = None
        self._resize_job = None
        self._job = 0
        self._pending = 0
        self._edits = 0
        self.view: editor.View | None = None
        self.selected = None
        self.index: editor.PickIndex | None = None
        self.undo = editor.UndoStack()
        self._modified = False
        self._img_origin = (0, 0)
        self._img_size = (1, 1)
        self._drag = None
        self._writing = 0  # scritture su file in corso (salvataggi ed esportazioni)

        root.title("DWG / DXF → PDF e immagini")
        root.geometry("1280x840")
        root.minsize(900, 600)

        bar = ttk.Frame(root, padding=(8, 8, 8, 4))
        bar.pack(fill="x")

        self.btn_open = ttk.Button(bar, text="Apri DWG/DXF…", command=self.open_file)
        self.btn_open.pack(side="left")

        self.buttons: list[ttk.Button] = []
        for label, fmt in (("PDF", "pdf"), ("PNG", "png"), ("JPG", "jpg")):
            b = ttk.Button(
                bar, text=f"Esporta {label}", command=lambda f=fmt: self.save_as(f), state="disabled"
            )
            b.pack(side="left", padx=(6, 0))
            self.buttons.append(b)

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=10)

        ttk.Label(bar, text="Tavola:").pack(side="left")
        self.var_layout = tk.StringVar()
        self.cmb_layout = ttk.Combobox(bar, textvariable=self.var_layout, width=22, state="disabled")
        self.cmb_layout.pack(side="left", padx=(4, 10))
        self.cmb_layout.bind("<<ComboboxSelected>>", lambda _e: self._layout_changed())

        ttk.Label(bar, text="Formato:").pack(side="left")
        self.var_page = tk.StringVar(value="A3")
        cmb_page = ttk.Combobox(
            bar,
            textvariable=self.var_page,
            values=[FIT, "A4", "A3", "A2", "A1", "A0"],
            width=17,
            state="readonly",
        )
        cmb_page.pack(side="left", padx=(4, 10))
        cmb_page.bind("<<ComboboxSelected>>", lambda _e: self.show_preview())

        ttk.Label(bar, text="Risoluzione:").pack(side="left")
        self.var_dpi = tk.StringVar(value="300 dpi")
        ttk.Combobox(
            bar,
            textvariable=self.var_dpi,
            values=[f"{d} dpi" for d in (150, 300, 600)],
            width=8,
            state="readonly",
        ).pack(side="left", padx=(4, 10))

        self.var_mono = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            bar, text="Monocromatico", variable=self.var_mono, command=self.show_preview
        ).pack(side="left")

        body = ttk.Frame(root)
        body.pack(fill="both", expand=True, padx=8, pady=4)
        self.canvas = tk.Canvas(body, bg="#e9e9e9", highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

        self._build_panel(body)

        self.status = tk.StringVar(value="Apri un file DWG o DXF per iniziare.")
        ttk.Label(root, textvariable=self.status, padding=(8, 4)).pack(fill="x")

        root.bind("<Control-o>", lambda _e: self.open_file())
        root.bind("<Control-z>", lambda _e: self._typing() or self.undo_last())
        root.bind("<Delete>", lambda _e: self._typing() or self.delete_selected())
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._queue: queue.Queue = queue.Queue()
        self.root.after(50, self._poll_queue)

        if len(sys.argv) > 1 and Path(sys.argv[1]).suffix.lower() in (".dwg", ".dxf"):
            self.load(Path(sys.argv[1]))

    # --- pannello di modifica --------------------------------------------
    def _build_panel(self, parent) -> None:
        side = ttk.Frame(parent, width=290)
        side.pack(side="right", fill="y", padx=(8, 0))
        side.pack_propagate(False)

        self.var_sel = tk.StringVar(value="Nessuna selezione")
        ttk.Label(side, textvariable=self.var_sel, wraplength=280).pack(anchor="w", pady=(0, 4))
        riga = ttk.Frame(side)
        riga.pack(fill="x", pady=(0, 6))
        self.btn_delete = ttk.Button(riga, text="Elimina", command=self.delete_selected, state="disabled")
        self.btn_delete.pack(side="left")
        ttk.Button(riga, text="Deseleziona", command=lambda: self._select(None)).pack(side="left", padx=4)

        prop = ttk.LabelFrame(side, text="Proprietà", padding=6)
        prop.pack(fill="x", pady=(0, 6))

        ttk.Label(prop, text="Layer").grid(padx=(0, 6), row=0, column=0, sticky="w")
        self.var_layer = tk.StringVar()
        self.cmb_layer = ttk.Combobox(prop, textvariable=self.var_layer, state="disabled", width=20)
        self.cmb_layer.grid(row=0, column=1, columnspan=2, sticky="we", pady=2)
        self.cmb_layer.bind("<<ComboboxSelected>>", lambda _e: self.change_layer())

        ttk.Label(prop, text="Colore").grid(padx=(0, 6), row=1, column=0, sticky="w")
        self.btn_color = tk.Button(prop, width=3, relief="groove", command=self.choose_color, state="disabled")
        self.btn_color.grid(row=1, column=1, sticky="w", pady=2)
        self.btn_bylayer = ttk.Button(
            prop, text="Da layer", command=self.color_from_layer, state="disabled"
        )
        self.btn_bylayer.grid(row=1, column=2, sticky="e", pady=2)

        ttk.Label(prop, text="Spessore").grid(padx=(0, 6), row=2, column=0, sticky="w")
        self.var_weight = tk.StringVar()
        self.cmb_weight = ttk.Combobox(
            prop,
            textvariable=self.var_weight,
            values=list(WEIGHTS.values()),
            state="disabled",
            width=20,
        )
        self.cmb_weight.grid(row=2, column=1, columnspan=2, sticky="we", pady=2)
        self.cmb_weight.bind("<<ComboboxSelected>>", lambda _e: self.change_weight())

        ttk.Label(prop, text="Testo").grid(padx=(0, 6), row=3, column=0, sticky="w")
        self.var_text = tk.StringVar()
        self.txt_text = ttk.Entry(prop, textvariable=self.var_text, state="disabled")
        self.txt_text.grid(row=3, column=1, sticky="we", pady=2)
        self.txt_text.bind("<Return>", lambda _e: self.change_text())
        self.btn_text = ttk.Button(prop, text="Applica", width=8, command=self.change_text, state="disabled")
        self.btn_text.grid(row=3, column=2, sticky="e", pady=2, padx=(4, 0))
        prop.columnconfigure(1, weight=1)

        gen = ttk.LabelFrame(side, text="Trasforma", padding=6)
        gen.pack(fill="x", pady=(0, 6))

        self.var_dx, self.var_dy = tk.StringVar(value="0"), tk.StringVar(value="0")
        ttk.Label(gen, text="ΔX").grid(row=0, column=0, sticky="w")
        ttk.Entry(gen, textvariable=self.var_dx, width=8).grid(row=0, column=1, sticky="we", pady=2)
        ttk.Label(gen, text="ΔY").grid(row=0, column=2, sticky="w", padx=(6, 0))
        ttk.Entry(gen, textvariable=self.var_dy, width=8).grid(row=0, column=3, sticky="we", pady=2)
        ttk.Button(gen, text="Sposta", width=7, command=self.move_selected).grid(
            row=0, column=4, padx=(6, 0)
        )

        self.var_angle = tk.StringVar(value="90")
        ttk.Label(gen, text="Angolo").grid(row=1, column=0, sticky="w")
        ttk.Entry(gen, textvariable=self.var_angle, width=8).grid(
            row=1, column=1, sticky="we", pady=2
        )
        ttk.Button(gen, text="Ruota", width=7, command=self.rotate_selected).grid(
            row=1, column=2, columnspan=3, sticky="e", padx=(6, 0)
        )

        self.var_factor = tk.StringVar(value="2")
        ttk.Label(gen, text="Fattore").grid(row=2, column=0, sticky="w")
        ttk.Entry(gen, textvariable=self.var_factor, width=8).grid(
            row=2, column=1, sticky="we", pady=2
        )
        ttk.Button(gen, text="Scala", width=7, command=self.scale_selected).grid(
            row=2, column=2, columnspan=3, sticky="e", padx=(6, 0)
        )

        ttk.Label(gen, text="Snap").grid(row=3, column=0, sticky="w")
        self.var_snap = tk.StringVar(value="Nessuno")
        ttk.Combobox(
            gen,
            textvariable=self.var_snap,
            values=["Nessuno", "0.1", "1", "10", "100", "1000"],
            width=8,
            state="readonly",
        ).grid(row=3, column=1, sticky="we", pady=2)
        gen.columnconfigure(3, weight=1)

        lay = ttk.LabelFrame(side, text="Layer", padding=6)
        lay.pack(fill="both", expand=True, pady=(0, 6))
        self.lst_layers = tk.Listbox(lay, height=6, exportselection=False)
        self.lst_layers.pack(fill="both", expand=True)
        riga = ttk.Frame(lay)
        riga.pack(fill="x", pady=(4, 0))
        ttk.Button(riga, text="On / Off", command=self.toggle_layer).pack(side="left")
        ttk.Button(riga, text="Colore…", command=self.change_layer_color).pack(side="left", padx=4)

        ttk.Button(side, text="Annulla (Ctrl+Z)", command=self.undo_last).pack(fill="x", pady=(0, 4))
        riga = ttk.Frame(side)
        riga.pack(fill="x")
        ttk.Button(riga, text="Salva DXF…", command=lambda: self.save_drawing("dxf")).pack(
            side="left", expand=True, fill="x"
        )
        ttk.Button(riga, text="Salva DWG…", command=lambda: self.save_drawing("dwg")).pack(
            side="left", expand=True, fill="x", padx=(4, 0)
        )

    # --- caricamento -----------------------------------------------------
    def open_file(self) -> None:
        if self._modified and not messagebox.askyesno(
            "Modifiche non salvate", "Aprire un altro disegno e perdere le modifiche?"
        ):
            return
        path = filedialog.askopenfilename(
            title="Apri disegno",
            filetypes=[("Disegni CAD", "*.dwg *.dxf"), ("DWG", "*.dwg"), ("DXF", "*.dxf")],
        )
        if path:
            self.load(Path(path))

    def load(self, path: Path) -> None:
        self.status.set(f"Apertura di {path.name}…")
        self.root.update_idletasks()
        try:
            doc = load_drawing(path)
        except Exception as exc:
            messagebox.showerror("Impossibile aprire il file", str(exc))
            self.status.set("Apertura non riuscita.")
            return

        self.doc, self.src = doc, path
        # elenco solo le tavole stampabili: i layout di carta vuoti non hanno nulla da esportare
        names = [n for n in layout_names(doc) if has_content(doc, n)] or ["Model"]
        self.cmb_layout.configure(values=names, state="readonly")
        self.var_layout.set(names[0])
        for b in self.buttons:
            b.state(["!disabled"])
        self.undo.clear()
        self._modified = False
        self._update_title()
        self._clear_preview()
        self.index = editor.PickIndex(self._current_layout())
        self._fill_layers()
        self.show_preview()

    def _clear_preview(self) -> None:
        """Niente anteprima finché non arriva quella nuova: il click non modifica il disegno sbagliato."""
        self.preview, self.view = None, None
        self._select(None)
        self.canvas.delete("all")

    # --- anteprima -------------------------------------------------------
    def _current_layout(self):
        return get_layout(self.doc, self.var_layout.get() or "Model")

    def _layout_changed(self) -> None:
        if not self.doc:
            return
        self.undo.clear()  # l'undo vale solo per il layout in cui è nato
        self._clear_preview()
        self.index = editor.PickIndex(self._current_layout())
        self.show_preview()

    def _on_resize(self, _event=None) -> None:
        if self._resize_job:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(250, self._refit)

    def _refit(self) -> None:
        self._resize_job = None
        if self.preview:
            self._draw_image()

    def show_preview(self) -> None:
        if not self.doc:
            return
        # la tavola può richiedere decine di secondi: si disegna fuori dal thread UI
        doc, name = self.doc, self.var_layout.get() or "Model"
        mono, page_name = self.var_mono.get(), self.var_page.get()
        w = max(self.canvas.winfo_width(), 900) - 20
        h = max(self.canvas.winfo_height(), 560) - 20

        def work():
            out, page = render(doc, get_layout(doc, name), mono=mono, page_name=page_name)
            # la matrice serve per il click: va letta prima dell'esportazione
            matrix, _final = placement(out, page)
            dpi = min(w * 25.4 / page.width_in_mm, h * 25.4 / page.height_in_mm)
            dpi = fit_dpi(page, max(1, min(400, int(dpi))))
            try:
                png = out.get_pixmap_bytes(page, fmt="png", dpi=dpi)
            except ValueError:  # tavola senza entità disegnabili
                png = blank_bytes(page, "png", dpi)
            return Image.open(io.BytesIO(png)), page, matrix, dpi

        self.status.set("Rendering…")
        self._run(work, self._preview_done, coalesce=True)

    def _preview_done(self, result, error) -> None:
        if error is not None:
            self.preview = None
            self.view = None
            self.canvas.delete("all")
            self.status.set("Anteprima non disponibile.")
            messagebox.showerror("Errore di rendering", str(error))
            return
        self.preview, page, matrix, dpi = result
        self.view = editor.View(matrix, dpi)
        self._draw_image()
        self._update_status(page)

    def _run(self, work, done, *, coalesce: bool = False) -> None:
        """Esegue `work` in background e passa (risultato, errore) a `done` nel thread UI.

        Con `coalesce` solo l'ultima richiesta consegna il risultato (anteprime);
        salvataggi ed esportazioni vengono consegnati sempre.
        """
        token = None
        if coalesce:
            self._job += 1
            token = self._job
        self._pending += 1
        self._set_busy(True)

        def runner():
            try:
                result, error = work(), None
            except Exception as exc:  # noqa: BLE001 - mostrato all'utente
                result, error = None, exc
            self._queue.put((token, done, result, error))

        threading.Thread(target=runner, daemon=True).start()

    def _poll_queue(self) -> None:
        # il risultato arriva dal thread di lavoro: qui siamo nel thread UI
        try:
            while True:
                self._finish(*self._queue.get_nowait())
        except queue.Empty:
            pass
        self.root.after(50, self._poll_queue)

    def _finish(self, token, done, result, error) -> None:
        self._pending -= 1
        self._set_busy(self._pending > 0)
        if token is not None and token != self._job:  # anteprima superata da una più recente
            return
        done(result, error)

    def _set_busy(self, busy: bool) -> None:
        self.root.config(cursor="watch" if busy else "")
        state = ["disabled"] if busy else ["!disabled"]
        for b in self.buttons:
            b.state(state)

    def _draw_image(self) -> None:
        img = self.preview.copy()
        img.thumbnail((max(self.canvas.winfo_width(), 100) - 16,
                       max(self.canvas.winfo_height(), 100) - 16))
        self._photo = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        cx, cy = self.canvas.winfo_width() // 2, self.canvas.winfo_height() // 2
        self.canvas.create_image(cx, cy, image=self._photo, anchor="center")
        self._img_size = img.size
        self._img_origin = (cx - img.width // 2, cy - img.height // 2)
        self._draw_selection()

    # --- selezione e modifica --------------------------------------------
    def _to_canvas(self, x: float, y: float) -> tuple[float, float]:
        """Punto del disegno → pixel della finestra."""
        ix, iy = self.view.to_image(x, y)
        x0, y0 = self._img_origin
        kx = self._img_size[0] / self.preview.width
        ky = self._img_size[1] / self.preview.height
        return x0 + ix * kx, y0 + iy * ky

    def _to_model(self, cx: float, cy: float) -> tuple[float, float]:
        """Pixel della finestra → punto del disegno."""
        x0, y0 = self._img_origin
        kx = self.preview.width / self._img_size[0]
        ky = self.preview.height / self._img_size[1]
        return self.view.to_model((cx - x0) * kx, (cy - y0) * ky)

    def _ready(self) -> bool:
        return bool(self.doc and self.preview and self.view and self.index)

    def _draw_selection(self) -> None:
        self.canvas.delete("sel")
        if not (self.selected is not None and self._ready()):
            return
        ext = self.index.box(self.selected)
        if ext is None:
            return
        x0, y0 = self._to_canvas(ext.extmin.x, ext.extmin.y)
        x1, y1 = self._to_canvas(ext.extmax.x, ext.extmax.y)
        self.canvas.create_rectangle(
            min(x0, x1) - 2, min(y0, y1) - 2, max(x0, x1) + 2, max(y0, y1) + 2,
            outline="#d9480f", width=2, dash=(5, 3), tags="sel",
        )

    def _pick(self, cx: float, cy: float):
        x, y = self._to_model(cx, cy)
        ex, ey = self._to_model(cx + 5, cy + 5)
        return self.index.pick(x, y, math.hypot(ex - x, ey - y))

    def _on_press(self, event) -> None:
        if not self._ready():
            return
        self._drag = None
        picked = self._pick(event.x, event.y)
        self._select(picked)
        if picked is not None:
            self._drag = (event.x, event.y, self._to_model(event.x, event.y))
            self.canvas.configure(cursor="fleur")

    def _on_motion(self, event) -> None:
        if not self._drag:
            return
        self.canvas.delete("drag")
        x0, y0, _ = self._drag
        self.canvas.create_line(
            x0, y0, event.x, event.y, fill="#1971c2", dash=(4, 3), arrow="last", tags="drag"
        )

    def _on_release(self, event) -> None:
        self.canvas.configure(cursor="")
        drag, self._drag = self._drag, None
        self.canvas.delete("drag")
        if not drag:
            return
        x0, y0, start = drag
        if abs(event.x - x0) < 3 and abs(event.y - y0) < 3:
            return  # è stato un click: nessuno spostamento
        dx, dy = self._to_model(event.x, event.y)
        dx, dy = self._snap(dx - start[0]), self._snap(dy - start[1])
        if dx or dy:
            self._apply(editor.move(dx, dy), f"spostamento {dx:g}, {dy:g}")

    def _snap(self, value: float) -> float:
        step = 0.0 if self.var_snap.get() == "Nessuno" else float(self.var_snap.get())
        return round(value / step) * step if step else value

    def _select(self, entity) -> None:
        self.selected = entity
        self._fill_properties()
        self._draw_selection()

    def _fill_properties(self) -> None:
        on = self.selected is not None
        self.var_sel.set(editor.label(self.selected) if on else "Nessuna selezione")
        state = "normal" if on else "disabled"
        self.btn_delete.state(["!disabled" if on else "disabled"])
        self.cmb_layer.configure(state="readonly" if on else "disabled")
        self.btn_color.configure(state=state)
        self.btn_bylayer.state(["!disabled" if on else "disabled"])
        self.cmb_weight.configure(state="readonly" if on else "disabled")
        self.txt_text.configure(state=state)
        self.btn_text.state(["!disabled" if on else "disabled"])

        if not on:
            self.btn_color.configure(bg=self.root.cget("bg"))
            self.var_text.set("")
            return
        self.var_layer.set(self.selected.dxf.get("layer", "0"))
        r, g, b = editor.effective_color(self.selected)
        self.btn_color.configure(bg=f"#{r:02x}{g:02x}{b:02x}")
        weight = self.selected.dxf.get("lineweight", -1)
        self.var_weight.set(WEIGHTS.get(weight, f"{weight / 100:g} mm"))
        text = editor.text_of(self.selected)
        self.var_text.set("" if text is None else text)
        self.txt_text.configure(state="normal" if text is not None else "disabled")
        # evidenzia il layer dell'entità nell'elenco, così On/Off e Colore agiscono su quello
        names = editor.layer_names(self.doc)
        layer = self.selected.dxf.get("layer", "0")
        if layer in names and self.lst_layers.size() == len(names):
            self.lst_layers.selection_clear(0, "end")
            self.lst_layers.selection_set(names.index(layer))
            self.lst_layers.see(names.index(layer))

    def _update_title(self) -> None:
        name = self.src.name if self.src else ""
        mark = " *" if self._modified else ""
        self.root.title(f"DWG / DXF → PDF e immagini{mark}" + (f" — {name}" if name else ""))

    def _apply(self, matrix, what: str) -> None:
        if self.selected is None:
            return
        pivot = editor.center_of(self.selected)
        undo = editor.transform(self.selected, editor.about(pivot, matrix))
        self._after_edit(what, undo)

    def _after_edit(self, what: str, undo, entity=None, structural: bool = False) -> None:
        self.undo.push(
            what, undo, entity if entity is not None else self.selected, structural
        )
        self._edits += 1
        self._modified = True
        if self.selected is not None:
            self.index.forget(self.selected)
        self._update_title()
        self._fill_properties()
        if self.selected is not None and not editor.selectable(self.selected):
            self._select(None)  # spostata su un layer spento/bloccato: niente selezione nascosta
        self._draw_selection()
        self.status.set(f"Modifica: {what}")
        self.show_preview()

    def _number(self, var) -> float | None:
        try:
            value = float(var.get().replace(",", "."))
        except ValueError:
            value = math.nan
        if not math.isfinite(value):
            messagebox.showwarning("Valore non valido", f"«{var.get()}» non è un numero.")
            return None
        return value

    def move_selected(self) -> None:
        dx, dy = self._number(self.var_dx), self._number(self.var_dy)
        if dx is None or dy is None or not (dx or dy):
            return
        self._apply(editor.move(dx, dy), f"spostamento {dx:g}, {dy:g}")

    def rotate_selected(self) -> None:
        angle = self._number(self.var_angle)
        if not angle:
            return
        self._apply(editor.rotate(angle), f"rotazione {angle:g}°")

    def scale_selected(self) -> None:
        factor = self._number(self.var_factor)
        if factor is None:
            return
        if factor <= 0:
            messagebox.showwarning(
                "Valore non valido", "Il fattore di scala deve essere maggiore di zero."
            )
            return
        if factor == 1:  # nessuna modifica: niente undo né nuovo render
            return
        self._apply(editor.scale(factor), f"scala {factor:g}×")

    def change_layer(self) -> None:
        if self.selected is None or self.var_layer.get() == self.selected.dxf.get("layer"):
            return
        name = self.var_layer.get()
        self._after_edit(f"layer «{name}»", editor.set_layer(self.selected, name))

    def choose_color(self) -> None:
        if self.selected is None:
            return
        r, g, b = editor.effective_color(self.selected)
        picked = colorchooser.askcolor(color=(r, g, b), title="Colore entità")
        if picked and picked[0]:
            rgb = tuple(int(v) for v in picked[0])
            self._after_edit(f"colore {rgb}", editor.set_color(self.selected, rgb))

    def color_from_layer(self) -> None:
        if self.selected is not None:
            self._after_edit("colore da layer", editor.use_layer_color(self.selected))

    def change_weight(self) -> None:
        if self.selected is None:
            return
        weight = next((k for k, v in WEIGHTS.items() if v == self.var_weight.get()), None)
        if weight is None or weight == self.selected.dxf.get("lineweight", -1):
            return
        self._after_edit(f"spessore {self.var_weight.get()}", editor.set_lineweight(self.selected, weight))

    def change_text(self) -> None:
        if self.selected is None or editor.text_of(self.selected) is None:
            return
        text = self.var_text.get()
        if text == editor.text_of(self.selected):
            return
        self._after_edit("testo", editor.set_text(self.selected, text))

    def delete_selected(self) -> None:
        if self.selected is None:
            return
        if self._writing or self._pending:  # il render legge il layout: niente modifiche strutturali
            self.status.set(
                "Salvataggio in corso: riprova tra poco."
                if self._writing
                else "Rendering in corso: riprova tra poco."
            )
            return
        entity = self.selected
        undo = editor.delete(self._current_layout(), entity)
        self._select(None)
        self._after_edit(f"eliminato {editor.label(entity)}", undo, entity, structural=True)

    def undo_last(self) -> None:
        if not self.doc or not self.undo:
            return
        if self._writing:  # file in scrittura
            self.status.set("Salvataggio in corso: riprova tra poco.")
            return
        if self._pending and self.undo.next_is_structural():
            # solo l'undo della cancellazione cambia il numero di entità lette dal render
            self.status.set("Rendering in corso: riprova tra poco.")
            return
        done = self.undo.undo()
        if done is None:
            return
        text, entity = done
        self._modified = True
        self._edits += 1
        if self.index is not None:
            for item in (self.selected, entity):
                if item is not None:
                    self.index.forget(item)
        self._select(self.selected)
        self._fill_layers()
        self._update_title()
        self.status.set(f"Annullato: {text}")
        self._draw_selection()
        self.show_preview()

    # --- layer -----------------------------------------------------------
    def _fill_layers(self) -> None:
        current = self._selected_layer()
        self.lst_layers.delete(0, "end")
        if not self.doc:
            return
        names = editor.layer_names(self.doc)
        for name in names:
            layer = self.doc.layers.get(name)
            self.lst_layers.insert("end", f"{'[ ]' if layer.is_off() else '[x]'} {name}")
        self.cmb_layer.configure(values=names)
        if current in names:  # la riga selezionata resta selezionata dopo il refresh
            self.lst_layers.selection_set(names.index(current))
            self.lst_layers.see(names.index(current))

    def _selected_layer(self) -> str | None:
        pick = self.lst_layers.curselection()
        names = editor.layer_names(self.doc) if self.doc else []
        return names[pick[0]] if pick and pick[0] < len(names) else None

    def toggle_layer(self) -> None:
        name = self._selected_layer()
        if name is None:
            return
        layer = self.doc.layers.get(name)
        self._layer_edit(
            f"layer «{name}» {'spento' if not layer.is_off() else 'acceso'}",
            editor.set_layer_visible(self.doc, name, layer.is_off()),
            name,
        )

    def change_layer_color(self) -> None:
        name = self._selected_layer()
        if name is None:
            return
        layer = self.doc.layers.get(name)
        # se il layer ha un vero colore, il selettore parte da quello (l'ACI è solo un ripiego)
        r, g, b = layer.rgb or editor.layer_rgb(layer.color)
        picked = colorchooser.askcolor(color=(r, g, b), title=f"Colore layer «{name}»")
        if not picked or not picked[0]:
            return
        rgb = picked[0]
        # il nero nel selettore corrisponde al bianco/nero di AutoCAD (ACI 7)
        aci = 7 if sum(rgb) < 128 else min(
            ACI_COLORS, key=lambda k: sum((a - b) ** 2 for a, b in zip(ACI_COLORS[k], rgb))
        )
        self._layer_edit(f"colore layer «{name}»", editor.set_layer_color(self.doc, name, aci), name)

    def _layer_edit(self, what: str, undo, name: str | None = None) -> None:
        self.undo.push(what, undo)
        self._edits += 1
        self._modified = True
        self._update_title()
        self._fill_properties()
        if self.selected is not None and not editor.selectable(self.selected):
            self._select(None)
        self._fill_layers()
        if name is not None:  # la riga su cui hai agito resta selezionata
            names = editor.layer_names(self.doc)
            if name in names:
                self.lst_layers.selection_clear(0, "end")
                self.lst_layers.selection_set(names.index(name))
                self.lst_layers.see(names.index(name))
        self._draw_selection()
        self.status.set(f"Modifica: {what}")
        self.show_preview()

    # --- salvataggio del disegno -----------------------------------------
    def save_drawing(self, fmt: str) -> None:
        if not self.doc:
            return
        if fmt == "dwg" and not oda_available():
            messagebox.showerror(
                "DWG non disponibile",
                "Per salvare in DWG serve ODA File Converter.\n"
                f"Scaricalo da {ODA_URL} oppure salva in DXF.",
            )
            return
        stem = self.src.stem if self.src else "disegno"
        path = filedialog.asksaveasfilename(
            title=f"Salva in {fmt.upper()}",
            defaultextension=f".{fmt}",
            initialfile=f"{stem} - modificato.{fmt}",
            filetypes=[(fmt.upper(), f"*.{fmt}")],
        )
        if not path:
            return
        doc = self.doc
        edits = self._edits

        def work():
            if fmt == "dwg":
                odafc.export_dwg(doc, path, replace=True)
            else:
                doc.saveas(path)

        self.status.set("Salvataggio…")
        self._writing += 1
        self._run(work, lambda _r, err: self._drawing_saved(path, err, edits, doc))

    def _drawing_saved(self, path, error, edits, doc) -> None:
        self._writing -= 1
        if error is not None:
            messagebox.showerror("Salvataggio non riuscito", str(error))
            self.status.set("Salvataggio non riuscito.")
            return
        # solo se è ancora il disegno corrente e non ci sono modifiche successive
        if doc is self.doc and edits == self._edits:
            self._modified = False
            self._update_title()
        self.status.set(f"Salvato: {path}")
        messagebox.showinfo("Disegno salvato", f"File creato:\n{path}")

    def on_close(self) -> None:
        if self._writing:
            messagebox.showinfo(
                "Salvataggio in corso…",
                "Attendi la fine del salvataggio o dell'esportazione prima di chiudere.",
            )
            return
        if self._modified and not messagebox.askyesno(
            "Modifiche non salvate", "Il disegno ha modifiche non salvate. Chiudere lo stesso?"
        ):
            return
        self.root.destroy()

    def _typing(self) -> bool:
        return isinstance(self.root.focus_get(), (tk.Entry, ttk.Entry, tk.Text))

    def _update_status(self, page) -> None:
        n = len(self._current_layout())
        self.status.set(
            f"{self.src.name}  •  tavola «{self.var_layout.get()}»  •  {n} entità  •  "
            f"pagina {page.width_in_mm:.0f} × {page.height_in_mm:.0f} mm"
        )

    # --- esportazione ----------------------------------------------------
    def save_as(self, fmt: str) -> None:
        if not self.doc:
            return
        stem = self.src.stem if self.src else "disegno"
        label = self.var_layout.get()
        base = stem if label == "Model" else f"{stem} - {label}"
        if fmt == "pdf":
            types = [("PDF", "*.pdf")]
        elif fmt == "png":
            types = [("Immagine PNG", "*.png")]
        else:
            types = [("Immagine JPG", "*.jpg")]
        path = filedialog.asksaveasfilename(
            title=f"Esporta in {fmt.upper()}",
            defaultextension=f".{fmt}",
            initialfile=f"{base}.{fmt}",
            filetypes=types,
        )
        if not path:
            return

        doc, lay, dpi = self.doc, self._current_layout(), int(self.var_dpi.get().split()[0])
        mono, page_name = self.var_mono.get(), self.var_page.get()

        def work():
            export(doc, lay, path, fmt=fmt, dpi=dpi, mono=mono, page_name=page_name)

        self.status.set("Esportazione…")
        self._writing += 1
        self._run(work, lambda _r, err: self._export_done(path, err))

    def _export_done(self, path, error) -> None:
        self._writing -= 1
        if error is not None:
            messagebox.showerror("Esportazione non riuscita", str(error))
            self.status.set("Esportazione non riuscita.")
            return
        self.status.set(f"Salvato: {path}")
        messagebox.showinfo("Esportazione completata", f"File creato:\n{path}")


def selftest() -> int:
    """Genera un DXF di prova e verifica l'intera catena di esportazione."""
    tmp = Path(tempfile.mkdtemp(prefix="dwgviewer_"))
    doc = ezdxf.new(setup=True)
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (120, 0), (120, 80), (0, 80)], close=True)
    msp.add_line((10, 10), (110, 10))
    msp.add_circle((60, 40), 25)
    msp.add_text("PROVA DWG / DXF", height=7).set_placement(
        (18, 66), align=ezdxf.enums.TextEntityAlignment.LEFT
    )
    msp.add_linear_dim(
        base=(0, -14), p1=(0, 0), p2=(120, 0), override={"dimtxt": 5}
    ).render()

    dxf = tmp / "prova.dxf"
    doc.saveas(dxf)

    loaded = load_drawing(dxf)
    lay = loaded.modelspace()
    assert bbox.extents(lay) is not None, "estensioni non calcolate"

    # stessa conversione usata per il click: andata e ritorno devono coincidere
    out, page = render(loaded, lay, page_name="A3")
    view = editor.View(placement(out, page)[0], 96)
    back = view.to_model(*view.to_image(12.5, 34.5))
    assert all(abs(a - b) < 1e-6 for a, b in zip(back, (12.5, 34.5))), "View non invertibile"

    pdf = export(loaded, lay, tmp / "prova.pdf", fmt="pdf")
    assert pdf.read_bytes()[:4] == b"%PDF", "PDF non valido"

    png = export(loaded, lay, tmp / "prova.png", fmt="png", dpi=200)
    assert Image.open(png).size[0] > 200, "PNG troppo piccolo"

    jpg = export(loaded, lay, tmp / "prova.jpg", fmt="jpg", dpi=200)
    assert Image.open(jpg).format == "JPEG", "JPG non valido"

    mono = export(loaded, lay, tmp / "mono.png", fmt="png", dpi=150, mono=True)
    assert mono.stat().st_size > 1000, "esportazione monocromatica vuota"

    # disegno enorme (unità = mm) in formato Adatta: il render non deve esplodere
    big = ezdxf.new()
    big.modelspace().add_lwpolyline(
        [(0, 0), (8000, 0), (8000, 6000), (0, 6000)], close=True
    )
    huge = export(big, big.modelspace(), tmp / "grande.png", fmt="png", dpi=600, page_name=FIT)
    assert max(Image.open(huge).size) <= MAX_PIXELS, "immagine troppo grande"

    # A3 con disegno orizzontale: pagina in orizzontale
    rect = pymupdf.open(pdf)[0].rect
    assert rect.width > rect.height, "formato A3 non orientato"

    # --- modifica del disegno -------------------------------------------
    index = editor.PickIndex(lay)
    line = lay.query("LINE")[0]
    x0, y0 = line.dxf.start.x, line.dxf.start.y
    picked = index.pick(x0, y0, 0.5)
    assert picked is not None, "click su un punto della linea non la seleziona"
    assert index.pick(x0 - 1000, y0, 0.5) is None, "click lontano seleziona qualcosa"

    pivot = editor.center_of(line)
    undo_move = editor.transform(line, editor.about(pivot, editor.move(10, 0)))
    assert abs(line.dxf.start.x - x0 - 10) < 1e-6, "spostamento non applicato"
    undo_move()
    assert abs(line.dxf.start.x - x0) < 1e-6, "undo dello spostamento non ripristina"

    circle = lay.query("CIRCLE")[0]
    radius = circle.dxf.radius
    undo_scale = editor.transform(circle, editor.about(editor.center_of(circle), editor.scale(2)))
    assert abs(circle.dxf.radius - 2 * radius) < 1e-6, "scala non applicata"
    undo_scale()
    assert abs(circle.dxf.radius - radius) < 1e-6, "undo della scala non ripristina"

    text = lay.query("TEXT")[0]
    original = text.dxf.text
    undo_text = editor.set_text(text, "MODIFICATO")
    assert text.dxf.text == "MODIFICATO", "testo non cambiato"
    undo_text()
    assert text.dxf.text == original, "undo del testo non ripristina"

    undo_color = editor.set_color(line, (255, 0, 0))
    assert editor.effective_color(line) == (255, 0, 0), "colore non impostato"
    undo_color()

    count = len(lay)
    undo_delete = editor.delete(lay, line)
    assert len(lay) == count - 1, "eliminazione non applicata"
    undo_delete()
    assert len(lay) == count, "undo dell'eliminazione non rimette l'entità"

    editor.set_text(lay.query("TEXT")[0], "SALVATO")
    out_dxf = tmp / "modificato.dxf"
    loaded.saveas(out_dxf)
    saved = load_drawing(out_dxf)
    assert saved.modelspace().query("TEXT")[0].dxf.text == "SALVATO", "DXF salvato non riletto"

    # DWG: scrive un DWG con ODA e lo riapre (solo se ODA è installato)
    if oda_available():
        dwg = tmp / "prova.dwg"
        odafc.export_dwg(loaded, str(dwg))
        assert dwg.stat().st_size > 1000, "DWG non creato"
        dwg_doc = load_drawing(dwg)
        assert has_content(dwg_doc, "Model"), "DWG riletto vuoto"
        export(dwg_doc, dwg_doc.modelspace(), tmp / "prova_dwg.png", fmt="png", dpi=120)
        print("DWG: conversione e rilettura OK")

    print(f"selftest OK — file di prova in {tmp}")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    root = tk.Tk()
    App(root)
    root.mainloop()
