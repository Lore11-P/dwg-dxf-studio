"""Genera esempio.dxf (planimetria dimostrativa) per provare l'app."""
import ezdxf

doc = ezdxf.new("R2018", setup=True)
doc.units = ezdxf.units.MM
doc.layers.add("MURI", color=7)
doc.layers.add("ARREDI", color=8)
doc.layers.add("QUOTE", color=3)
doc.layers.add("TESTO", color=2)
msp = doc.modelspace()

W, H, T = 4200, 2970, 200

# muri perimetrali (spessore tramite larghezza costante)
msp.add_lwpolyline(
    [(0, 0), (W, 0), (W, H), (0, H)], close=True,
    dxfattribs={"layer": "MURI", "const_width": T},
)
# tramezzo
msp.add_line((2600, T / 2), (2600, 1700), dxfattribs={"layer": "MURI", "lineweight": 50})

# porta: anta + arco
msp.add_line((2600, 1700), (2600, 2500), dxfattribs={"layer": "MURI"})
msp.add_arc((2600, 1700), radius=800, start_angle=0, end_angle=90,
            dxfattribs={"layer": "MURI"})

# finestra sul muro alto
msp.add_line((1500, H - T / 2 - 60), (2300, H - T / 2 - 60), dxfattribs={"layer": "MURI"})
msp.add_line((1500, H - T / 2 + 60), (2300, H - T / 2 + 60), dxfattribs={"layer": "MURI"})

# arredi
msp.add_lwpolyline([(700, 700), (2100, 700), (2100, 1500), (700, 1500)], close=True,
                   dxfattribs={"layer": "ARREDI"})
for x in (1600, 1750, 1900):
    msp.add_circle((x, 1850), radius=180, dxfattribs={"layer": "ARREDI"})
msp.add_lwpolyline([(3250, 1800), (3950, 1800), (3950, 2500), (3250, 2500)], close=True,
                   dxfattribs={"layer": "ARREDI"})

# testi
msp.add_text("SOGGIORNO", height=180, dxfattribs={"layer": "TESTO"}).set_placement(
    (700, 2550), align=ezdxf.enums.TextEntityAlignment.LEFT)
msp.add_text("CUCINA", height=180, dxfattribs={"layer": "TESTO"}).set_placement(
    (2800, 2560), align=ezdxf.enums.TextEntityAlignment.LEFT)

# quote
dim = msp.add_linear_dim(base=(0, -600), p1=(0, 0), p2=(W, 0),
                         dxfattribs={"layer": "QUOTE"},
                         override={"dimtxt": 140, "dimasz": 120, "dimexo": 60, "dimlfac": 1})
dim.render()
dim = msp.add_linear_dim(base=(-600, 0), p1=(0, 0), p2=(0, H), angle=90,
                         dxfattribs={"layer": "QUOTE"},
                         override={"dimtxt": 140, "dimasz": 120, "dimexo": 60, "dimlfac": 1})
dim.render()

# cartiglio
msp.add_lwpolyline([(0, -1500), (W, -1500), (W, -900), (0, -900)], close=True,
                   dxfattribs={"layer": "MURI", "lineweight": 35})
msp.add_text("PIANTA - PIANO TERRA      scala 1:50", height=150,
             dxfattribs={"layer": "TESTO"}).set_placement(
    (300, -1300), align=ezdxf.enums.TextEntityAlignment.LEFT)
msp.add_text("esempio generato per DWG/DXF Studio", height=110,
             dxfattribs={"layer": "TESTO"}).set_placement(
    (300, -1050), align=ezdxf.enums.TextEntityAlignment.LEFT)

doc.saveas("esempio.dxf")
print("scritto esempio.dxf")
