"""Tema dark (terminal de trading) - culori + stylesheet pentru Qt/pyqtgraph."""

# Culori de baza (stil DeepCharts - negru pur, contrast mare)
BG = "#000000"          # fundal general (negru pur)
PANEL = "#0b0b0d"       # panouri / bare de control
PANEL2 = "#141418"
BORDER = "#1e1e24"
GRID = "#15171e"
TEXT = "#e6e6ea"
TEXT_DIM = "#7d818c"
# Umbrire sesiune: benzi verticale discrete peste OVERNIGHT (Globex), ca RTH-ul (NY) sa iasa in evidenta
SESSION_SHADE = (108, 120, 146, 13)

# Trading (paleta DeepCharts: verde / MOV, nu verde/rosu)
UP = "#2ee08a"          # lumanare verde / buy (mai viu, mai curat)
DOWN = "#b06bf7"        # lumanare MOV / sell
UP_EDGE = "#5cf0aa"     # contur lumanare urcare (definire crisp)
DOWN_EDGE = "#c99bff"   # contur lumanare coborare
BUY = "#2ee08a"
SELL = "#b06bf7"
# Profil VP "simplu" (o singura culoare, stil ATAS): slate rece calm, cu zona
# Value Area mai luminoasa si bara POC accentuata -> curat, nu "fierastrau" de culori.
VP_BASE = (96, 110, 138)   # slate-albastru discret (nivelurile din afara VA)
VP_VA = (140, 170, 214)    # steel-blue mai luminos (nivelurile din Value Area)
POC = "#ff2d7e"         # magenta (linia POC, ca la DeepCharts)
VWAP = "#ff9d2e"        # portocaliu (curba VWAP)
VA_LINE = "#ff9d2e"     # marginile Value Area (portocaliu)
# Cutie Value Area: gri-albastrui NEUTRU si discret (nu portocaliu) ca sa nu se bata
# cu VWAP-ul si sa nu "inunde" fundalul; zona ramane marcata de liniile VAH/VAL punctate.
VA_BAND = (124, 136, 162, 20)  # slate rece, foarte transparent (stil ATAS)
ACCENT = "#ff9d2e"
AVWAP = "#2bd4c0"       # teal - Anchored VWAP (distinct de VWAP-ul portocaliu; benzi std-dev)
CMP = "#5b9bd5"         # albastru - sesiunea de COMPARAT (overlay temporar, distinct de tot restul)
CMP_RGB = (91, 155, 213)
HVN = "#26c6da"         # cyan - High Volume Nodes (suport/rezistenta puternice)
LVN = "#8593a0"         # gri-albastrui - Low Volume Nodes (goluri de volum)
ABSORPTION = "#f5c542"  # galben - marker Absorption (sa sara in ochi, categorie proprie)
EXHAUSTION = "#ff6b4a"  # coral/rosu-portocaliu - marker Exhaustion (climax, avertisment reversal)
# "Ieri" = o singura familie AMBER (nu albastru) ca sa nu concureze cu restul culorilor
PRIOR_POC = "#e0b74e"   # auriu - POC-ul sesiunii precedente (yPOC)
PRIOR_VA = "#b08a3a"    # auriu inchis - Value Area de ieri (yVAH/yVAL)
PRIOR_VA_BAND = (224, 183, 78, 26)  # box amber discret peste Value Area de ieri (zona reper NY open)
PRIOR_HL = "#8a7134"    # amber stins - High/Low sesiune precedenta (PDH/PDL)

QSS = f"""
QMainWindow, QWidget {{
    background-color: {BG};
    color: {TEXT};
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
}}
#TopBar {{
    background-color: {PANEL};
    border-bottom: 1px solid {BORDER};
}}
#TopBar QLabel {{ color: {TEXT_DIM}; }}
#Title {{ color: {TEXT}; font-size: 14px; font-weight: 700; letter-spacing: 0.3px; }}
#FieldLabel {{
    color: {TEXT_DIM};
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    padding-left: 2px;
}}
#Sep {{ color: {BORDER}; background: {BORDER}; max-width: 1px; margin: 2px 4px; }}
#WarnLabel {{ color: {VWAP}; font-size: 12px; }}
#GearBtn {{
    background-color: {PANEL2};
    border: 1px solid {BORDER};
    border-radius: 6px;
    color: {TEXT_DIM};
    padding: 1px 5px;
}}
#GearBtn:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
#VPDialog {{ background-color: {PANEL}; }}
#VPDialog QLabel {{ color: {TEXT_DIM}; }}
QComboBox {{
    background-color: {PANEL2};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 3px 8px;
    color: {TEXT};
    min-height: 20px;
}}
QComboBox:hover {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{
    background-color: {PANEL2};
    color: {TEXT};
    selection-background-color: {ACCENT};
    border: 1px solid {BORDER};
    outline: none;
}}
QComboBox::drop-down {{ border: none; width: 18px; }}
QCheckBox {{ color: {TEXT}; spacing: 6px; }}
QCheckBox::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {BORDER};
    border-radius: 4px;
    background: {PANEL2};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
#StatCard {{
    background-color: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
#StatLabel {{ color: {TEXT_DIM}; font-size: 11px; }}
#StatValue {{ color: {TEXT}; font-size: 16px; font-weight: 600; }}
#LayerBar {{
    background-color: {PANEL};
    border-top: 1px solid {BORDER};
}}
#LayerBar QLabel {{ color: {TEXT_DIM}; }}
#ReplayBar {{
    background-color: {PANEL};
    border-top: 1px solid {BORDER};
}}
#ReplayBar QLabel {{ color: {TEXT_DIM}; }}
#ReplayPos {{ color: {TEXT}; font-weight: 600; }}
#ReplayBar QPushButton {{
    background-color: {PANEL2};
    border: 1px solid {BORDER};
    border-radius: 14px;
    padding: 5px 12px;
    color: {TEXT};
}}
#ReplayBar QPushButton:hover {{ border-color: {ACCENT}; }}
#ReplayBar QPushButton:disabled {{ color: {TEXT_DIM}; }}
#ReplayBar QPushButton:checked {{ background-color: {PANEL2}; border-color: {ACCENT}; color: {ACCENT}; }}
#ReplayToggle {{ font-weight: 600; }}
#ReplayToggle:checked {{
    background-color: {POC};
    border-color: {POC};
    color: #0a0a0a;
}}
#ReplayBar QLineEdit {{
    background-color: {PANEL2};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 8px;
    color: {TEXT};
}}
QSlider::groove:horizontal {{
    height: 6px;
    background: {BORDER};
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {ACCENT};
    width: 18px;
    height: 18px;
    margin: -6px 0;
    border-radius: 9px;
    border: 2px solid {PANEL};
}}
QSlider::handle:horizontal:hover {{ background: #ffb84d; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 3px; }}
#DrawBar {{
    background-color: {PANEL};
    border-right: 1px solid {BORDER};
}}
#DrawBar QPushButton {{
    background-color: {PANEL2};
    border: 1px solid {BORDER};
    border-radius: 6px;
    color: {TEXT};
    font-size: 14px;
}}
#DrawBar QPushButton:hover {{ border-color: {ACCENT}; }}
#DrawBar QPushButton:checked {{
    background-color: {ACCENT};
    color: #0a0a0a;
    border-color: {ACCENT};
}}
"""
