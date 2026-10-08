"""
pdf_reporte.py
Genera los reportes PDF del sistema (horario semanal, brecha de personal, métricas,
personal, disponibilidad, permisos) con reportlab + matplotlib para las gráficas.
Diseño propio: tipografía Poppins, paleta de marca KFC, encabezado tipo "hero" oscuro,
tarjetas de KPI con acento de color, y gráficas reales en vez de solo tablas.
"""

import os
import tempfile
from datetime import date

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.patches import FancyBboxPatch

from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                                  Image, HRFlowable, PageBreak, KeepTogether, Flowable)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from db import listar_empleados, obtener_disponibilidad, DIAS_SEMANA
from generador_horarios import (
    _demanda_por_dia, _ventana_disponibilidad, generar_horario_semana, estimar_nivel_servicio_real,
    HORARIO_OPERATIVO_INICIO, HORARIO_OPERATIVO_FIN,
)
from costos import calcular_costo_horario

# ============================================================================
# Paleta y tipografía -- mismos tonos que la interfaz web (ver static/style.css)
# ============================================================================

INK = colors.HexColor("#14161C")
INK_SOFT = colors.HexColor("#3A3E4A")
PAPER = colors.HexColor("#F3F2EE")
BORDE = colors.HexColor("#E3E1DB")
TEXTO_MUTED = colors.HexColor("#6B6E76")
SIGNAL = colors.HexColor("#C8102E")       # rojo de marca KFC
SIGNAL_DARK = colors.HexColor("#9E0B22")
AMBAR = colors.HexColor("#B8791A")
AMBAR_BG = colors.HexColor("#FBF1DE")
VERDE = colors.HexColor("#2C7A54")
VERDE_BG = colors.HexColor("#E3F1E9")
AZUL = colors.HexColor("#3B7DD8")
AZUL_BG = colors.HexColor("#EAF2FB")

# Paleta vibrante para tarjetas de color sólido (inspirada en dashboards modernos,
# pero manteniendo el rojo KFC como protagonista)
MORADO_VIVO = colors.HexColor("#6C5CE7")
AZUL_VIVO = colors.HexColor("#3B6FE0")
TEAL_VIVO = colors.HexColor("#1BA787")
NARANJA_VIVO = colors.HexColor("#E8622C")
HEX_MORADO_VIVO = "#6C5CE7"
HEX_AZUL_VIVO = "#3B6FE0"
HEX_TEAL_VIVO = "#1BA787"
HEX_NARANJA_VIVO = "#E8622C"

# Hex planos (para matplotlib, que no entiende los objetos colors.HexColor de reportlab)
HEX_INK = "#14161C"
HEX_SIGNAL = "#C8102E"
HEX_AMBAR = "#B8791A"
HEX_VERDE = "#2C7A54"
HEX_AZUL = "#3B7DD8"
HEX_MUTED = "#9A9CA3"
HEX_BORDE = "#E3E1DB"

LOGO_PATH = os.path.join(os.path.dirname(__file__), "static", "assets", "kfc-logo.png")

# ---- Tipografía Poppins (empaquetada en static/fonts/ -- funciona en Windows/Mac/Linux
#      por igual, no depende de que el sistema operativo la tenga instalada) ----
_FUENTES_DIR = os.path.join(os.path.dirname(__file__), "static", "fonts")
_POPPINS = {
    "Poppins": f"{_FUENTES_DIR}/Poppins-Regular.ttf",
    "Poppins-Medium": f"{_FUENTES_DIR}/Poppins-Medium.ttf",
    "Poppins-Bold": f"{_FUENTES_DIR}/Poppins-Bold.ttf",
    "Poppins-Light": f"{_FUENTES_DIR}/Poppins-Light.ttf",
}
_FUENTE_DISPONIBLE = all(os.path.exists(p) for p in _POPPINS.values())

if _FUENTE_DISPONIBLE:
    for nombre, ruta in _POPPINS.items():
        try:
            pdfmetrics.registerFont(TTFont(nombre, ruta))
        except Exception:
            _FUENTE_DISPONIBLE = False
            break

F_REGULAR = "Poppins" if _FUENTE_DISPONIBLE else "Helvetica"
F_MEDIUM = "Poppins-Medium" if _FUENTE_DISPONIBLE else "Helvetica-Bold"
F_BOLD = "Poppins-Bold" if _FUENTE_DISPONIBLE else "Helvetica-Bold"
F_LIGHT = "Poppins-Light" if _FUENTE_DISPONIBLE else "Helvetica"

if _FUENTE_DISPONIBLE:
    for ruta in _POPPINS.values():
        try:
            fm.fontManager.addfont(ruta)
        except Exception:
            pass
    plt.rcParams["font.family"] = "Poppins"
plt.rcParams["axes.edgecolor"] = HEX_BORDE
plt.rcParams["text.color"] = HEX_INK
plt.rcParams["axes.labelcolor"] = HEX_INK

_styles = getSampleStyleSheet()
TITULO_STYLE = ParagraphStyle("TituloKFC", parent=_styles["Title"], fontName=F_BOLD,
                               textColor=colors.white, fontSize=19, leading=22, spaceAfter=2)
EYEBROW_STYLE = ParagraphStyle("Eyebrow", parent=_styles["Normal"], fontName=F_MEDIUM,
                                textColor=colors.HexColor("#D8869A"), fontSize=8.5, spaceAfter=3)
SUBTITULO_STYLE = ParagraphStyle("Subtitulo", parent=_styles["Normal"], fontName=F_REGULAR,
                                  textColor=colors.HexColor("#B8BCC6"), fontSize=9, spaceAfter=0)
H2_STYLE = ParagraphStyle("H2", parent=_styles["Heading2"], fontName=F_BOLD, textColor=INK,
                           fontSize=13, spaceBefore=18, spaceAfter=8)
NORMAL_SMALL_STYLE = ParagraphStyle("NormalSmall", parent=_styles["Normal"], fontName=F_REGULAR,
                                     fontSize=9, textColor=INK, leading=13)
NOTA_STYLE = ParagraphStyle("Nota", parent=NORMAL_SMALL_STYLE, fontSize=8, textColor=TEXTO_MUTED)
FOOTER_STYLE = ParagraphStyle("Footer", parent=_styles["Normal"], fontName=F_REGULAR,
                               fontSize=8, textColor=TEXTO_MUTED, alignment=1)

ESTILO_TABLA = [
    ("FONTNAME", (0, 0), (-1, 0), F_MEDIUM),
    ("FONTNAME", (0, 1), (-1, -1), F_REGULAR),
    ("BACKGROUND", (0, 0), (-1, 0), INK),
    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
    ("FONTSIZE", (0, 0), (-1, -1), 9),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PAPER]),
    ("TOPPADDING", (0, 0), (-1, -1), 6),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ("LINEBELOW", (0, 0), (-1, -2), 0.4, BORDE),
]

# Mantener el nombre viejo por compatibilidad con cualquier referencia externa
ESTILO_TABLA_HEADER_NEGRO = ESTILO_TABLA
ROJO_KFC = SIGNAL
NEGRO = INK
GRIS = TEXTO_MUTED
GRIS_CLARO = PAPER


def _color_por_umbral(pct: float) -> str:
    """Verde >=95%, ámbar 85-95%, rojo <85% -- mismos umbrales que el dashboard web."""
    if pct >= 95:
        return HEX_VERDE
    if pct >= 85:
        return HEX_AMBAR
    return HEX_SIGNAL


def _color_rl_por_umbral(pct: float):
    if pct >= 95:
        return VERDE
    if pct >= 85:
        return AMBAR
    return SIGNAL


# ============================================================================
# Documento, encabezado "hero" y pie de página
# ============================================================================

def _crear_documento(salida: str, apaisado: bool = False) -> SimpleDocTemplate:
    tamano = landscape(letter) if apaisado else letter
    return SimpleDocTemplate(salida, pagesize=tamano, topMargin=0, bottomMargin=1.6*cm,
                              leftMargin=1.8*cm, rightMargin=1.8*cm)


def _numero_pagina(canvas, doc):
    canvas.saveState()
    canvas.setFont(F_REGULAR, 8)
    canvas.setFillColor(TEXTO_MUTED)
    canvas.drawRightString(doc.pagesize[0] - 1.8*cm, 1.0*cm, f"Página {canvas.getPageNumber()}")
    canvas.restoreState()


class _HeroHeader(Flowable):
    """Banda oscura de encabezado (logo + eyebrow + título + subtítulo), a todo el ancho
    de la página, incluyendo los márgenes -- por eso el documento se crea con
    topMargin=0 y este flowable calcula su propio ancho completo."""

    def __init__(self, ancho_pagina, eyebrow, titulo, subtitulo):
        super().__init__()
        self.ancho_pagina = ancho_pagina
        self.eyebrow = eyebrow
        self.titulo = titulo
        self.subtitulo = subtitulo
        self.alto = 2.7 * cm

    def wrap(self, availWidth, availHeight):
        return (self.ancho_pagina, self.alto)

    def draw(self):
        c = self.canv
        c.saveState()
        # La banda se dibuja empezando en x = -margen izquierdo para llegar al borde real
        x0 = -1.8 * cm
        c.setFillColor(INK)
        c.rect(x0, 0, self.ancho_pagina, self.alto, stroke=0, fill=1)
        # Franja de acento roja al pie de la banda
        c.setFillColor(SIGNAL)
        c.rect(x0, 0, self.ancho_pagina, 0.09*cm, stroke=0, fill=1)

        logo_x = x0 + 0.9*cm
        if os.path.exists(LOGO_PATH):
            logo_h = 1.35*cm
            c.saveState()
            c.setFillColor(colors.white)
            c.roundRect(logo_x, self.alto/2 - logo_h/2, logo_h, logo_h, 4, stroke=0, fill=1)
            c.drawImage(LOGO_PATH, logo_x + 0.12*cm, self.alto/2 - logo_h/2 + 0.12*cm,
                        width=logo_h - 0.24*cm, height=logo_h - 0.24*cm,
                        preserveAspectRatio=True, mask="auto")
            c.restoreState()
            texto_x = logo_x + 1.35*cm + 0.5*cm
        else:
            texto_x = logo_x

        c.setFillColor(colors.HexColor("#D8869A"))
        c.setFont(F_MEDIUM, 8.5)
        c.drawString(texto_x, self.alto/2 + 0.52*cm, self.eyebrow)
        c.setFillColor(colors.white)
        c.setFont(F_BOLD, 18)
        c.drawString(texto_x, self.alto/2 - 0.06*cm, self.titulo)
        c.setFillColor(colors.HexColor("#B8BCC6"))
        c.setFont(F_REGULAR, 9)
        c.drawString(texto_x, self.alto/2 - 0.56*cm, self.subtitulo)
        c.restoreState()


def _encabezado(eyebrow: str, titulo: str, subtitulo: str, ancho_pagina) -> list:
    return [_HeroHeader(ancho_pagina, eyebrow, titulo, subtitulo), Spacer(1, 16)]


def _pie_pagina() -> list:
    return [
        Spacer(1, 20),
        HRFlowable(width="100%", color=BORDE, thickness=1),
        Spacer(1, 6),
        Paragraph(
            f"Sistema de Gestión de Personal y Horarios — Call Center &nbsp;&middot;&nbsp; "
            f"Desarrollado por Sergio Ortiz &nbsp;&middot;&nbsp; © {date.today().year}",
            FOOTER_STYLE),
    ]


# ============================================================================
# Tarjetas de KPI (fila de recuadros con acento de color, como el dashboard web)
# ============================================================================

class _TarjetaKPI(Flowable):
    """Una tarjeta de KPI de color sólido, esquinas redondeadas -- como las tarjetas de
    saldo de un dashboard moderno: número grande en blanco, etiqueta chica arriba."""

    def __init__(self, ancho, alto, label, valor, color):
        super().__init__()
        self.ancho = ancho
        self.alto = alto
        self.label = label
        self.valor = valor
        self.color = color

    def wrap(self, availWidth, availHeight):
        return (self.ancho, self.alto)

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(self.color)
        c.roundRect(0, 0, self.ancho, self.alto, 8, stroke=0, fill=1)
        # Un tono más oscuro del mismo color, como acento decorativo en la esquina
        c.setFillColorRGB(1, 1, 1, alpha=0.14)
        c.circle(self.ancho - 14, self.alto - 14, 26, stroke=0, fill=1)

        texto_label = Paragraph(self.label, ParagraphStyle(
            "KpiLabelBlanco", fontName=F_MEDIUM, fontSize=8.5,
            textColor=colors.Color(1, 1, 1, alpha=0.88), leading=11))
        w, h = texto_label.wrap(self.ancho - 24, self.alto)
        texto_label.drawOn(c, 12, self.alto - h - 12)

        c.setFillColor(colors.white)
        c.setFont(F_BOLD, 19)
        c.drawString(12, 12, str(self.valor))
        c.restoreState()


def _tarjetas_kpi(items: list, ancho_total, alto: float = 2.1*cm) -> Table:
    """items: lista de dicts {label, valor, color (opcional, colors.HexColor)}.
    Fila de tarjetas de color sólido con esquinas redondeadas."""
    n = len(items)
    gap = 0.28 * cm
    ancho_col = (ancho_total - gap * (n - 1)) / n
    fila = [_TarjetaKPI(ancho_col, alto, it["label"], it["valor"], it.get("color", INK)) for it in items]
    colwidths = [ancho_col] * n
    # Insertar columnas angostas como "gap" entre tarjetas
    t = Table([fila], colWidths=colwidths, spaceAfter=0)
    t.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (0, -2), gap),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


# ============================================================================
# Gráficas (matplotlib, estilo propio -- Poppins, paleta de marca, sin bordes de más)
# ============================================================================

def _estilizar_ejes(ax):
    for spine in ["top", "right", "left"]:
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color(HEX_BORDE)
    ax.tick_params(axis="both", length=0)
    ax.grid(axis="y", color=HEX_BORDE, linewidth=0.7, zorder=0)
    ax.set_axisbelow(True)


def _guardar_temp(fig) -> str:
    ruta = tempfile.NamedTemporaryFile(delete=False, suffix=".png").name
    fig.savefig(ruta, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return ruta


def _grafico_cobertura_semana(por_dia: dict, dias: list = None) -> str:
    """Barras de % de contestación estimado por día, coloreadas por umbral (verde/ámbar/rojo),
    con etiqueta de valor encima de cada barra -- la gráfica más importante del reporte."""
    dias = dias or DIAS_SEMANA
    valores = [por_dia.get(d, {}).get("sl_estimado_pct") or 0 for d in dias]
    colores = [_color_por_umbral(v) for v in valores]

    fig, ax = plt.subplots(figsize=(10.4, 2.7), dpi=170)
    barras = ax.bar(dias, valores, color=colores, width=0.6, zorder=3)
    ax.axhline(95, color=HEX_MUTED, linestyle=(0, (4, 3)), linewidth=1, zorder=2)
    ax.text(len(dias) - 0.55, 98.5, "Meta 95%", fontsize=8, color=HEX_MUTED, ha="right")
    for barra, v in zip(barras, valores):
        ax.text(barra.get_x() + barra.get_width()/2, v + 1.4, f"{v:.0f}%",
                 ha="center", fontsize=9.5, fontweight="bold", color=HEX_INK)
    ax.set_ylim(0, 108)
    ax.set_title("Cobertura estimada por día", fontsize=12, color=HEX_INK, loc="left",
                 fontweight="bold", pad=14)
    ax.tick_params(axis="x", labelsize=9.5)
    ax.tick_params(axis="y", labelsize=8)
    _estilizar_ejes(ax)
    fig.tight_layout()
    return _guardar_temp(fig)


def _grafico_costo_desglose(costo: dict) -> str:
    """Donut chart del desglose de costo semanal por categoría, con el total en el centro
    -- mismo lenguaje visual que un dashboard financiero moderno."""
    d = costo.get("desglose", {})
    categorias = [
        ("Horas normales", d.get("base_hora_normal_equivalente", 0), HEX_INK),
        ("Recargo nocturno", d.get("recargo_nocturno", 0), HEX_AMBAR),
        ("Recargo dominical", d.get("extra_por_recargo_dominical", 0), HEX_AZUL_VIVO),
        ("Transporte", d.get("subsidio_transporte", 0), HEX_TEAL_VIVO),
    ]
    categorias = [c for c in categorias if c[1] > 0]
    if not categorias:
        categorias = [("Total", costo.get("total_semana", 0), HEX_INK)]
    total = sum(c[1] for c in categorias)

    fig, ax = plt.subplots(figsize=(5.6, 3.6), dpi=170)
    valores = [c[1] for c in categorias]
    colores = [c[2] for c in categorias]
    wedges, _ = ax.pie(valores, colors=colores, startangle=90, counterclock=False,
                        wedgeprops=dict(width=0.38, edgecolor="white", linewidth=3))
    ax.text(0, 0.10, f"${total:,.0f}", ha="center", va="center", fontsize=13.5,
             fontweight="bold", color=HEX_INK, family="Poppins" if _FUENTE_DISPONIBLE else None)
    ax.text(0, -0.16, "costo total semana", ha="center", va="center", fontsize=8, color=HEX_MUTED)
    ax.set_title("Desglose del costo semanal", fontsize=12, color=HEX_INK, loc="left",
                 fontweight="bold", pad=6, x=-0.32)

    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for _, _, c in categorias]
    labels = [f"{n}  ·  ${v:,.0f} ({v/total*100:.0f}%)" for n, v, _ in categorias]
    ax.legend(handles, labels, loc="center left", bbox_to_anchor=(1.05, 0.5),
               frameon=False, fontsize=9)
    ax.set_aspect("equal")
    fig.tight_layout()
    return _guardar_temp(fig)


def _grafico_linea_pct_contestadas(serie_diaria: list) -> str:
    fechas = [d["fecha"][5:] for d in serie_diaria]
    valores = [d["pct_contestadas"] for d in serie_diaria]

    fig, ax = plt.subplots(figsize=(10.4, 3.0), dpi=170)
    ax.plot(fechas, valores, color=HEX_SIGNAL, marker="o", markersize=4, linewidth=2.2, zorder=3)
    ax.fill_between(range(len(fechas)), valores, min(valores) - 3 if valores else 0,
                     color=HEX_SIGNAL, alpha=0.08, zorder=1)
    ax.axhline(90, color=HEX_MUTED, linestyle=(0, (4, 3)), linewidth=1, zorder=2)
    ymin = min(75, min(valores) - 5) if valores else 75
    ax.set_ylim(ymin, 101)
    ax.set_title("% de contestación por día", fontsize=12, color=HEX_INK, loc="left",
                 fontweight="bold", pad=14)
    ax.tick_params(axis="x", labelsize=7.5, rotation=55)
    ax.tick_params(axis="y", labelsize=8)
    _estilizar_ejes(ax)
    fig.tight_layout()
    return _guardar_temp(fig)


def _grafico_barras_por_hora(por_hora: list) -> str:
    horas = [f"{int(h['hora_del_dia'])}h" for h in por_hora]
    contestadas = [h["llamadas_contestadas_prom_dia"] for h in por_hora]
    abandonadas = [h["llamadas_abandonadas_prom_dia"] for h in por_hora]

    fig, ax = plt.subplots(figsize=(10.4, 3.0), dpi=170)
    x = range(len(horas))
    ax.bar(x, contestadas, color=HEX_INK, label="Contestadas", width=0.62, zorder=3)
    ax.bar(x, abandonadas, bottom=contestadas, color=HEX_SIGNAL, label="Abandonadas", width=0.62, zorder=3)
    ax.set_xticks(list(x))
    ax.set_xticklabels(horas, fontsize=7.5)
    ax.tick_params(axis="y", labelsize=8)
    ax.set_title("Llamadas por hora del día (promedio)", fontsize=12, color=HEX_INK, loc="left",
                 fontweight="bold", pad=14)
    ax.legend(fontsize=8.5, frameon=False, loc="upper right")
    _estilizar_ejes(ax)
    fig.tight_layout()
    return _guardar_temp(fig)


def _grafico_barras_dia_semana(resumen_dia: list) -> str:
    dias = [d["dia_semana"] for d in resumen_dia]
    valores = [d["contestadas_promedio"] for d in resumen_dia]

    fig, ax = plt.subplots(figsize=(10.4, 3.0), dpi=170)
    barras = ax.bar(dias, valores, color=HEX_SIGNAL, width=0.55, zorder=3)
    for barra, v in zip(barras, valores):
        ax.text(barra.get_x() + barra.get_width()/2, v + max(valores)*0.02, f"{v:.0f}",
                 ha="center", fontsize=8.5, color=HEX_INK)
    ax.set_title("Promedio de llamadas contestadas por día de la semana", fontsize=12,
                 color=HEX_INK, loc="left", fontweight="bold", pad=14)
    ax.tick_params(axis="x", labelsize=9)
    ax.tick_params(axis="y", labelsize=8)
    _estilizar_ejes(ax)
    fig.tight_layout()
    return _guardar_temp(fig)


def _grafico_heatmap_llamadas(desglose) -> str:
    """Mapa de calor hora x día -- de un vistazo, dónde y cuándo se concentran las llamadas."""
    import numpy as np
    horas_presentes = sorted(desglose["hora_del_dia"].unique())
    matriz = np.zeros((len(horas_presentes), len(DIAS_SEMANA)))
    indice_hora = {h: i for i, h in enumerate(horas_presentes)}
    indice_dia = {d: i for i, d in enumerate(DIAS_SEMANA)}
    for _, r in desglose.iterrows():
        if r["dia_semana"] in indice_dia:
            matriz[indice_hora[r["hora_del_dia"]], indice_dia[r["dia_semana"]]] = r["llamadas_contestadas_prom_dia"]

    fig, ax = plt.subplots(figsize=(10.4, 5.2), dpi=170)
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list("kfc", ["#FFFFFF", "#F5C1C9", HEX_SIGNAL])
    im = ax.imshow(matriz, aspect="auto", cmap=cmap)
    ax.set_xticks(range(len(DIAS_SEMANA)))
    ax.set_xticklabels(DIAS_SEMANA, fontsize=9)
    ax.set_yticks(range(len(horas_presentes)))
    ax.set_yticklabels([f"{int(h):02d}:00" for h in horas_presentes], fontsize=8)
    ax.set_title("Mapa de calor: llamadas contestadas por hora y día (promedio)", fontsize=12,
                 color=HEX_INK, loc="left", fontweight="bold", pad=14)
    for i in range(len(horas_presentes)):
        for j in range(len(DIAS_SEMANA)):
            v = matriz[i, j]
            if v > 0:
                color_txt = "white" if v > matriz.max() * 0.6 else HEX_INK
                ax.text(j, i, f"{v:.0f}", ha="center", va="center", fontsize=7, color=color_txt)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(length=0)
    fig.tight_layout()
    return _guardar_temp(fig)


# ============================================================================
# Reporte: Horario Semanal
# ============================================================================

def generar_pdf_horario(fecha_lunes: date, target_service_level: float = 0.95, shrinkage: float = 0.10,
                         db_path: str = "callcenter.db", max_occupancy: float = 0.85, semanas_base: list = None,
                         mostrar_costos: bool = True, salida: str = "reporte_horario.pdf") -> str:
    """PDF del horario generado: tarjetas de KPI, gráfica de cobertura por día, desglose de
    costo, y el cuadrante completo de turnos. 'mostrar_costos=False' genera la versión para
    enviar al equipo, sin ningún valor monetario."""
    resultado = generar_horario_semana(fecha_lunes, db_path=db_path, target_service_level=target_service_level,
                                        shrinkage=shrinkage, max_occupancy=max_occupancy, semanas_base=semanas_base)
    costo = calcular_costo_horario(resultado, db_path=db_path)
    nivel_servicio = estimar_nivel_servicio_real(resultado)
    horas_trabajadas = [h for h in resultado["horas_semana"].values() if h > 0]
    promedio_horas = round(sum(horas_trabajadas) / len(horas_trabajadas), 1) if horas_trabajadas else 0
    huecos = len([a for a in resultado["alertas"] if "faltan" in a])

    doc = _crear_documento(salida, apaisado=True)
    ancho_util = doc.pagesize[0] - doc.leftMargin - doc.rightMargin
    rutas_temp = []

    titulo = "Horario Semanal" + ("" if mostrar_costos else " · Equipo")
    story = _encabezado("PLANEACIÓN DE TURNOS", titulo,
                         f"Semana del {fecha_lunes.isoformat()}   |   Meta de servicio {int(target_service_level*100)}%"
                         f"   |   Generado el {date.today().isoformat()}", doc.pagesize[0])

    # ---- Tarjetas de KPI ----
    sl_pct = nivel_servicio["sl_estimado_semana_pct"]
    kpis = [
        {"label": "% Contestación (semana)", "valor": f"{sl_pct}%", "color": _color_rl_por_umbral(sl_pct)},
        {"label": "Horas-persona programadas", "valor": f"{sum(resultado['horas_semana'].values()):.0f}h", "color": AZUL_VIVO},
        {"label": "Horas sin cubrir", "valor": str(huecos), "color": SIGNAL if huecos > 0 else VERDE},
        {"label": "Horas/sem promedio", "valor": f"{promedio_horas}h", "color": TEAL_VIVO},
    ]
    if mostrar_costos:
        kpis.insert(1, {"label": "Costo total semana", "valor": f"${costo['total_semana']:,.0f}", "color": MORADO_VIVO})
    story.append(_tarjetas_kpi(kpis, ancho_util))
    story.append(Spacer(1, 16))

    # ---- Gráfica de cobertura por día ----
    ruta = _grafico_cobertura_semana(nivel_servicio["por_dia"])
    rutas_temp.append(ruta)
    story.append(Image(ruta, width=ancho_util, height=ancho_util * 2.7/10.4))

    # ---- Desglose de costo (solo si aplica) ----
    if mostrar_costos and costo.get("total_semana", 0) > 0:
        ruta = _grafico_costo_desglose(costo)
        rutas_temp.append(ruta)
        ancho_donut = ancho_util * 0.42
        img = Image(ruta, width=ancho_donut, height=ancho_donut * 3.6/5.6)
        img.hAlign = "LEFT"
        story.append(img)

    story.append(PageBreak())

    # ---- Cuadrante de turnos ----
    story.append(Paragraph("Cuadrante de turnos", H2_STYLE))
    motivos_abrev = {"no_disponible": "No disp.", "sin_informacion": "Sin info",
                      "libre_no_requerido": "Libre", "tope_semanal_alcanzado": "Tope sem.",
                      "descanso_asignado": "Descanso"}
    filas_horario = [["Asesor"] + DIAS_SEMANA + ["Horas/sem"]]
    for nombre, dias in resultado["horario"].items():
        fila = [nombre]
        for dia in DIAS_SEMANA:
            info = dias.get(dia, {"motivo": "?"})
            if "turnos" in info:
                def _texto_turno(t):
                    base = f"{t['inicio']:02d}-{t['fin']:02d}h{'*' if t.get('excepcion') else ''}"
                    if t.get("almuerzo_horas"):
                        ai, af = t["almuerzo_inicio"], t["almuerzo_inicio"] + t["almuerzo_horas"]
                        base += f" (alm. {ai:02d}-{af:02d}h)"
                    return base
                fila.append("+".join(_texto_turno(t) for t in info["turnos"]))
            else:
                motivo = info.get("motivo", "?")
                if motivo.startswith("permiso:"):
                    fila.append(motivo.replace("permiso:", "").capitalize())
                else:
                    fila.append(motivos_abrev.get(motivo, motivo))
        fila.append(f"{resultado['horas_semana'][nombre]:.0f}h")
        filas_horario.append(fila)

    t2 = Table(filas_horario, colWidths=[3.6*cm] + [2.7*cm]*7 + [2*cm], repeatRows=1)
    t2.setStyle(TableStyle(ESTILO_TABLA + [("FONTSIZE", (0, 0), (-1, -1), 7.5)]))
    story.append(t2)
    story.append(Paragraph("* turno de excepción por debajo del mínimo diario, asignado para no dejar la hora sin cobertura",
                            NOTA_STYLE))

    story.extend(_pie_pagina())
    doc.build(story, onFirstPage=_numero_pagina, onLaterPages=_numero_pagina)

    for ruta in rutas_temp:
        if os.path.exists(ruta):
            os.remove(ruta)
    return salida


# ============================================================================
# Reporte: Brecha de Personal
# ============================================================================

def generar_pdf_brecha_personal(fecha_lunes: date, target_service_level: float = 0.95,
                                 shrinkage: float = 0.10, db_path: str = "callcenter.db",
                                 horas_contrato_nuevo: float = 36, max_occupancy: float = 0.85,
                                 salida: str = "reporte_brecha_personal.pdf") -> str:
    empleados = listar_empleados(db_path=db_path)
    demanda = _demanda_por_dia(db_path, target_service_level, shrinkage, max_occupancy=max_occupancy)
    total_requerido = sum(sum(h.values()) for h in demanda.values())
    capacidad_maxima = sum(e["horas_max_semana"] for e in empleados)

    resultado_horario = generar_horario_semana(fecha_lunes, db_path=db_path, target_service_level=target_service_level,
                                                shrinkage=shrinkage, max_occupancy=max_occupancy)
    costo = calcular_costo_horario(resultado_horario, db_path=db_path)
    nivel_servicio = estimar_nivel_servicio_real(resultado_horario)

    detalle_por_dia = []
    for dia in DIAS_SEMANA:
        requerido_dia = sum(c["requeridos"] for c in resultado_horario["cobertura"][dia].values())
        programado_dia = sum(c["programados"] for c in resultado_horario["cobertura"][dia].values())
        deficit_dia = max(0, requerido_dia - programado_dia)
        pct = round((programado_dia / requerido_dia) * 100, 1) if requerido_dia > 0 else 100.0
        detalle_por_dia.append({"dia": dia, "requerido": requerido_dia, "programado": programado_dia,
                                 "deficit": deficit_dia, "pct": pct})

    deficit_total_real = sum(d["deficit"] for d in detalle_por_dia)
    asesores_recomendados = -(-deficit_total_real // horas_contrato_nuevo) if deficit_total_real else 0
    brecha = deficit_total_real

    franjas_criticas = []
    for dia in DIAS_SEMANA:
        for h, c in resultado_horario["cobertura"][dia].items():
            if c["requeridos"] > 0 and c["requeridos"] > c["programados"]:
                franjas_criticas.append({
                    "dia": dia, "hora": h, "deficit": c["requeridos"] - c["programados"],
                    "pct_corto": round((c["requeridos"] - c["programados"]) / c["requeridos"] * 100, 1),
                })
    franjas_criticas = sorted(franjas_criticas, key=lambda d: -d["pct_corto"])[:6]

    doc = _crear_documento(salida)
    ancho_util = doc.pagesize[0] - doc.leftMargin - doc.rightMargin
    rutas_temp = []
    story = _encabezado("DIMENSIONAMIENTO DE PERSONAL", "Brecha de Personal",
                         f"Semana del {fecha_lunes.isoformat()}   |   Meta {int(target_service_level*100)}%"
                         f"   |   Shrinkage {int(shrinkage*100)}%   |   Generado el {date.today().isoformat()}",
                         doc.pagesize[0])

    # ---- Tarjetas de KPI ----
    kpis = [
        {"label": "% Contestación real esperado", "valor": f"{nivel_servicio['sl_estimado_semana_pct']}%",
         "color": _color_rl_por_umbral(nivel_servicio['sl_estimado_semana_pct'])},
        {"label": "Déficit real total", "valor": f"{brecha:.0f}h", "color": SIGNAL if brecha > 0 else VERDE},
        {"label": "Asesores recomendados", "valor": str(int(asesores_recomendados)),
         "color": SIGNAL if asesores_recomendados > 0 else VERDE},
        {"label": "Costo semanal actual", "valor": f"${costo['total_semana']:,.0f}", "color": MORADO_VIVO},
    ]
    story.append(_tarjetas_kpi(kpis, ancho_util))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "Esta tabla corre el generador de horarios REAL con estos parámetros (no una estimación "
        "teórica) — el % cubierto y el déficit reflejan exactamente lo que pasaría si generas el "
        "horario ahora mismo con esta configuración.",
        ParagraphStyle("Concl", parent=NORMAL_SMALL_STYLE, spaceBefore=10, spaceAfter=4)))

    # ---- Gráfica: requerido vs. programado por día ----
    fig, ax = plt.subplots(figsize=(7.2, 3.0), dpi=170)
    x = range(len(DIAS_SEMANA))
    req = [d["requerido"] for d in detalle_por_dia]
    prog = [d["programado"] for d in detalle_por_dia]
    ax.bar([i - 0.19 for i in x], req, width=0.38, color=HEX_MUTED, label="Requerido", zorder=3)
    colores_prog = [_color_por_umbral(d["pct"]) for d in detalle_por_dia]
    ax.bar([i + 0.19 for i in x], prog, width=0.38, color=colores_prog, label="Programado real", zorder=3)
    ax.set_xticks(list(x))
    ax.set_xticklabels(DIAS_SEMANA, fontsize=8.5)
    ax.tick_params(axis="y", labelsize=8)
    ax.set_title("Requerido vs. programado real, por día (agente-horas)", fontsize=12, color=HEX_INK,
                 loc="left", fontweight="bold", pad=14)
    ax.legend(fontsize=8, frameon=False, loc="upper right")
    _estilizar_ejes(ax)
    fig.tight_layout()
    ruta = _guardar_temp(fig)
    rutas_temp.append(ruta)
    story.append(Image(ruta, width=ancho_util, height=ancho_util * 3.0/7.2))

    # ---- Detalle por día ----
    story.append(Paragraph("Cobertura real esperada por día", H2_STYLE))
    filas_detalle = [["Día", "Requerido", "Programado real", "% cubierto", "Déficit", "Estado"]]
    for f in detalle_por_dia:
        estado = "Cubierto" if f["pct"] >= 95 else ("Ajustado" if f["pct"] >= 85 else "Crítico")
        filas_detalle.append([f["dia"], f"{f['requerido']}h", f"{f['programado']}h", f"{f['pct']}%",
                               f"{f['deficit']}h" if f["deficit"] > 0 else "—", estado])
    t2 = Table(filas_detalle, colWidths=[3*cm, 2.6*cm, 3*cm, 2.6*cm, 2.4*cm, 2.4*cm], repeatRows=1)
    estilo_t2 = list(ESTILO_TABLA) + [("ALIGN", (1, 0), (-1, -1), "CENTER")]
    for i, f in enumerate(detalle_por_dia, start=1):
        color_estado = VERDE if f["pct"] >= 95 else (AMBAR if f["pct"] >= 85 else SIGNAL)
        estilo_t2.append(("TEXTCOLOR", (5, i), (5, i), color_estado))
        estilo_t2.append(("FONTNAME", (5, i), (5, i), F_BOLD))
        if f["deficit"] > 0:
            estilo_t2.append(("TEXTCOLOR", (4, i), (4, i), SIGNAL))
    t2.setStyle(TableStyle(estilo_t2))
    story.append(t2)

    if franjas_criticas:
        filas_franjas = [["Día", "Hora", "Faltan", "% del requerido sin cubrir"]]
        for f in franjas_criticas:
            filas_franjas.append([f["dia"], f"{f['hora']}:00", str(f["deficit"]), f"{f['pct_corto']}%"])
        t2b = Table(filas_franjas, colWidths=[3.5*cm, 3*cm, 3*cm, 5.5*cm])
        t2b.setStyle(TableStyle(ESTILO_TABLA + [
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("TEXTCOLOR", (3, 1), (3, 1), SIGNAL), ("FONTNAME", (3, 1), (3, 1), F_BOLD),
        ]))
        story.append(KeepTogether([
            Paragraph("Franjas más críticas (día + hora específica)", H2_STYLE),
            Paragraph(
                "Ordenadas por qué tan corto queda cada franja en <b>proporción</b>, no en número "
                "absoluto. Al buscar candidatos, prioriza que su disponibilidad real cubra estas "
                "franjas específicas.", NORMAL_SMALL_STYLE),
            Spacer(1, 6), t2b,
        ]))

    story.extend(_pie_pagina())
    doc.build(story, onFirstPage=_numero_pagina, onLaterPages=_numero_pagina)

    for ruta in rutas_temp:
        if os.path.exists(ruta):
            os.remove(ruta)
    return salida


# ============================================================================
# Reporte: Métricas
# ============================================================================

def generar_pdf_metricas(fecha_inicio: str = None, fecha_fin: str = None,
                          hora_inicio: int = None, hora_fin: int = None,
                          db_path: str = "callcenter.db", salida: str = "reporte_metricas.pdf") -> str:
    from agregados_llamadas import metricas_generales, resumen_simple_por_dia_semana, resumen_por_dia_semana_y_hora

    m = metricas_generales(db_path=db_path, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
                            hora_inicio=hora_inicio, hora_fin=hora_fin)
    resumen_dia = resumen_simple_por_dia_semana(db_path=db_path, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin)
    desglose = resumen_por_dia_semana_y_hora(db_path=db_path, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin)

    rango_txt = ""
    if fecha_inicio or fecha_fin:
        rango_txt = f"   |   Rango: {fecha_inicio or '...'} a {fecha_fin or '...'}"
    if hora_inicio is not None or hora_fin is not None:
        rango_txt += f"   |   Horas: {hora_inicio if hora_inicio is not None else '00'}:00-{hora_fin if hora_fin is not None else '23'}:00"

    doc = _crear_documento(salida, apaisado=True)
    ancho_util = doc.pagesize[0] - doc.leftMargin - doc.rightMargin
    story = _encabezado("DESEMPEÑO DEL CALL CENTER", "Métricas",
                         f"Generado el {date.today().isoformat()}{rango_txt}", doc.pagesize[0])

    if m is None:
        story.append(Paragraph("No hay llamadas para el filtro seleccionado.", NORMAL_SMALL_STYLE))
        doc.build(story, onFirstPage=_numero_pagina, onLaterPages=_numero_pagina)
        return salida

    rutas_temp = []

    # ---- Tarjetas de KPI ----
    kpis = [
        {"label": "Llamadas totales", "valor": f"{m['total_llamadas']:,}", "color": AZUL_VIVO},
        {"label": "% Contestadas", "valor": f"{m['pct_contestadas']}%",
         "color": _color_rl_por_umbral(m['pct_contestadas'])},
        {"label": "Abandonadas", "valor": f"{m['abandonadas']:,}", "color": SIGNAL},
        {"label": "TMO promedio", "valor": f"{int(m['tmo_promedio_seg']//60)}:{int(m['tmo_promedio_seg']%60):02d}", "color": MORADO_VIVO},
        {"label": "Espera prom. antes de abandonar", "valor": f"{m['espera_promedio_abandono_seg']:.0f}s", "color": TEAL_VIVO},
    ]
    story.append(_tarjetas_kpi(kpis, ancho_util))
    story.append(Spacer(1, 14))

    # ---- Gráficas ----
    if m.get("serie_diaria"):
        ruta = _grafico_linea_pct_contestadas(m["serie_diaria"])
        rutas_temp.append(ruta)
        story.append(Image(ruta, width=ancho_util, height=ancho_util * 3.0/10.4))

    if m.get("por_hora"):
        ruta = _grafico_barras_por_hora(m["por_hora"])
        rutas_temp.append(ruta)
        story.append(Image(ruta, width=ancho_util, height=ancho_util * 3.0/10.4))

    story.append(PageBreak())

    if resumen_dia:
        ruta = _grafico_barras_dia_semana(resumen_dia)
        rutas_temp.append(ruta)
        story.append(Image(ruta, width=ancho_util, height=ancho_util * 3.0/10.4))
        story.append(Spacer(1, 10))

    if not desglose.empty:
        ruta = _grafico_heatmap_llamadas(desglose)
        rutas_temp.append(ruta)
        story.append(Image(ruta, width=ancho_util * 0.72, height=ancho_util * 0.72 * 5.2/10.4))

    story.append(PageBreak())

    # ---- Promedio por día de la semana ----
    story.append(Paragraph("Promedio por día de la semana", H2_STYLE))
    filas_dia = [["Día", "Días obs.", "Contestadas prom.", "Mín–Máx", "Abandonadas prom.", "% Caídas prom.", "TMO"]]
    for d in resumen_dia:
        tmo = d["tmo_seg_promedio"]
        filas_dia.append([
            d["dia_semana"], str(d["dias_observados"]), f"{d['contestadas_promedio']:.0f}",
            f"{d['contestadas_min']}–{d['contestadas_max']}", f"{d['abandonadas_promedio']:.0f}",
            f"{d.get('pct_caidas_promedio', 0):.1f}%",
            f"{int(tmo//60)}:{int(tmo%60):02d}",
        ])
    t2 = Table(filas_dia, colWidths=[2.3*cm, 1.7*cm, 3.3*cm, 2.6*cm, 3.3*cm, 2.6*cm, 1.7*cm], repeatRows=1)
    estilo_t2 = list(ESTILO_TABLA)
    for i, d in enumerate(resumen_dia, start=1):
        if d.get("pct_caidas_promedio", 0) > 10:
            estilo_t2.append(("TEXTCOLOR", (5, i), (5, i), SIGNAL))
            estilo_t2.append(("FONTNAME", (5, i), (5, i), F_BOLD))
    t2.setStyle(TableStyle(estilo_t2))
    story.append(t2)
    story.append(Spacer(1, 16))

    if not desglose.empty:
        from erlang import required_agents
        story.append(Paragraph("Desglose por franja horaria y día (llamadas contestadas / TMO / asesores necesarios)", H2_STYLE))
        orden_dias = DIAS_SEMANA
        horas_presentes = sorted(desglose["hora_del_dia"].unique())
        indice = {(r["dia_semana"], r["hora_del_dia"]): r for _, r in desglose.iterrows()}

        filas_matriz = [["Franja"] + orden_dias]
        for h in horas_presentes:
            fila = [f"{int(h):02d}:00"]
            for dia in orden_dias:
                r = indice.get((dia, h))
                if r is not None:
                    tmo = r["tmo_seg_prom"]
                    calc = required_agents(calls=round(r["llamadas_contestadas_prom_dia"]),
                                            aht_seconds=tmo if tmo > 0 else 150)
                    fila.append(f"{r['llamadas_contestadas_prom_dia']:.0f} ({int(tmo//60)}:{int(tmo%60):02d}) · {calc.agents_final} ag.")
                else:
                    fila.append("—")
            filas_matriz.append(fila)

        t3 = Table(filas_matriz, colWidths=[2.2*cm] + [3.25*cm]*7, repeatRows=1)
        t3.setStyle(TableStyle(ESTILO_TABLA + [("FONTSIZE", (0, 0), (-1, -1), 7)]))
        story.append(t3)

    story.extend(_pie_pagina())
    doc.build(story, onFirstPage=_numero_pagina, onLaterPages=_numero_pagina)

    for ruta in rutas_temp:
        if os.path.exists(ruta):
            os.remove(ruta)
    return salida


# ============================================================================
# Reportes: Personal, Disponibilidad, Permisos (más simples, mismo sistema visual)
# ============================================================================

def generar_pdf_personal(db_path: str = "callcenter.db", salida: str = "reporte_personal.pdf") -> str:
    from validar_disponibilidad import validar_todos

    empleados = listar_empleados(db_path=db_path)
    validacion = {v["empleado"]: v for v in validar_todos(db_path=db_path)}
    con_alertas = sum(1 for e in empleados if validacion.get(e["nombre"], {}).get("alertas"))

    doc = _crear_documento(salida)
    ancho_util = doc.pagesize[0] - doc.leftMargin - doc.rightMargin
    story = _encabezado("DATOS BASE", "Personal",
                         f"{len(empleados)} asesores activos   |   Generado el {date.today().isoformat()}",
                         doc.pagesize[0])

    kpis = [
        {"label": "Asesores activos", "valor": str(len(empleados)), "color": AZUL_VIVO},
        {"label": "Con alertas de disponibilidad", "valor": str(con_alertas),
         "color": SIGNAL if con_alertas > 0 else VERDE},
    ]
    story.append(_tarjetas_kpi(kpis, ancho_util))
    story.append(Spacer(1, 16))

    filas = [["Asesor", "Cédula", "Horas/día", "Horas/semana", "Estado"]]
    for e in empleados:
        val = validacion.get(e["nombre"])
        estado = "Revisar" if (val and val["alertas"]) else "OK"
        filas.append([
            e["nombre"], e.get("cedula") or "—",
            f"{e['horas_min_dia']:.0f}–{e['horas_max_dia']:.0f}h",
            f"{e['horas_min_semana']:.0f}–{e['horas_max_semana']:.0f}h",
            estado,
        ])

    t = Table(filas, colWidths=[5.5*cm, 3*cm, 2.7*cm, 3*cm, 2.3*cm], repeatRows=1)
    estilo = list(ESTILO_TABLA)
    for i, e in enumerate(empleados, start=1):
        val = validacion.get(e["nombre"])
        color_estado = SIGNAL if (val and val["alertas"]) else VERDE
        estilo.append(("TEXTCOLOR", (4, i), (4, i), color_estado))
        estilo.append(("FONTNAME", (4, i), (4, i), F_BOLD))
    t.setStyle(TableStyle(estilo))
    story.append(t)
    story.extend(_pie_pagina())

    doc.build(story, onFirstPage=_numero_pagina, onLaterPages=_numero_pagina)
    return salida


def generar_pdf_disponibilidad(db_path: str = "callcenter.db", salida: str = "reporte_disponibilidad.pdf") -> str:
    empleados = listar_empleados(db_path=db_path)

    doc = _crear_documento(salida)
    story = _encabezado("DATOS BASE", "Disponibilidad",
                         f"{len(empleados)} asesores   |   Generado el {date.today().isoformat()}",
                         doc.pagesize[0])

    dias_abrev = {"Lunes": "Lun", "Martes": "Mar", "Miércoles": "Mié", "Jueves": "Jue",
                  "Viernes": "Vie", "Sábado": "Sáb", "Domingo": "Dom"}
    filas = [["Asesor"] + [dias_abrev[d] for d in DIAS_SEMANA]]
    colores_celda = []

    for e in empleados:
        disp = obtener_disponibilidad(e["id"], db_path=db_path)
        fila = [e["nombre"]]
        fila_color = []
        for dia in DIAS_SEMANA:
            d = disp.get(dia)
            if not d:
                fila.append("—")
                fila_color.append(SIGNAL)
            elif d["tipo"] == "completa":
                fila.append("Completa")
                fila_color.append(VERDE)
            elif d["tipo"] == "rango":
                fila.append(f"{d['hora_inicio']}-{d['hora_fin']}")
                fila_color.append(AZUL)
            elif d["tipo"] == "no_disponible":
                fila.append("No disp.")
                fila_color.append(TEXTO_MUTED)
            else:
                fila.append("Sin info")
                fila_color.append(SIGNAL)
        filas.append(fila)
        colores_celda.append(fila_color)

    t = Table(filas, colWidths=[4*cm] + [2.1*cm]*7, repeatRows=1)
    estilo = list(ESTILO_TABLA) + [("FONTSIZE", (0, 0), (-1, -1), 8), ("ALIGN", (1, 0), (-1, -1), "CENTER")]
    for i, fila_color in enumerate(colores_celda, start=1):
        for j, c in enumerate(fila_color, start=1):
            estilo.append(("TEXTCOLOR", (j, i), (j, i), c))
    t.setStyle(TableStyle(estilo))
    story.append(t)
    story.extend(_pie_pagina())

    doc.build(story, onFirstPage=_numero_pagina, onLaterPages=_numero_pagina)
    return salida


def generar_pdf_permisos(db_path: str = "callcenter.db", salida: str = "reporte_permisos.pdf") -> str:
    from db import listar_permisos

    empleados = {e["id"]: e["nombre"] for e in listar_empleados(db_path=db_path, solo_activos=False)}
    permisos = listar_permisos(db_path=db_path)
    permisos = sorted(permisos, key=lambda p: p["fecha_inicio"])

    doc = _crear_documento(salida)
    story = _encabezado("DATOS BASE", "Permisos y Ausencias",
                         f"{len(permisos)} registros   |   Generado el {date.today().isoformat()}",
                         doc.pagesize[0])

    if permisos:
        filas = [["Asesor", "Tipo", "Desde", "Hasta", "Comentario"]]
        for p in permisos:
            filas.append([
                empleados.get(p["empleado_id"], "—"),
                p["tipo"].replace("_", " ").capitalize(),
                p["fecha_inicio"], p["fecha_fin"], p.get("comentario") or "",
            ])
        t = Table(filas, colWidths=[4*cm, 3*cm, 2.5*cm, 2.5*cm, 4.5*cm], repeatRows=1)
        t.setStyle(TableStyle(ESTILO_TABLA))
        story.append(t)
    else:
        story.append(Paragraph("No hay permisos registrados todavía.", NORMAL_SMALL_STYLE))

    story.extend(_pie_pagina())
    doc.build(story, onFirstPage=_numero_pagina, onLaterPages=_numero_pagina)
    return salida


# ============================================================================
# Reporte Ejecutivo (ranking de criticidad + diagnóstico, metodología de la skill
# "reporte-ejecutivo-pdf": severidad relativa al promedio, no umbrales absolutos)
# ============================================================================

def generar_pdf_ejecutivo(fecha_lunes_referencia: date = None, fecha_inicio: str = None, fecha_fin: str = None,
                           db_path: str = "callcenter.db", salida: str = "reporte_ejecutivo.pdf") -> str:
    """Informe ejecutivo: ranking de días de la semana por criticidad (barra + semáforo)
    y una página de diagnóstico que identifica el pilar más problemático. La severidad de
    cada pilar se mide relativa al promedio del propio período -- no con umbrales fijos --
    para que un período completo malo no marque a todos los días por igual.
    'fecha_inicio'/'fecha_fin' acotan qué llamadas entran al diagnóstico (igual que en
    Métricas); si no se dan, usa todo el histórico cargado."""
    from agregados_llamadas import metricas_generales, resumen_simple_por_dia_semana

    m = metricas_generales(db_path=db_path, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin)
    resumen_dia = resumen_simple_por_dia_semana(db_path=db_path, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin)

    doc = _crear_documento(salida, apaisado=True)
    ancho_util = doc.pagesize[0] - doc.leftMargin - doc.rightMargin
    rango_txt = f"Rango: {fecha_inicio or '...'} a {fecha_fin or '...'}   |   " if (fecha_inicio or fecha_fin) else ""
    story = _encabezado("INFORME EJECUTIVO", "Reporte Ejecutivo",
                         f"Call Center   |   {rango_txt}Generado el {date.today().isoformat()}", doc.pagesize[0])

    if m is None or not resumen_dia:
        story.append(Paragraph("N/D — no hay llamadas cargadas todavía para diagnosticar.", NORMAL_SMALL_STYLE))
        doc.build(story, onFirstPage=_numero_pagina, onLaterPages=_numero_pagina)
        return salida

    # ---- Cobertura real por día, usando el generador real para una semana de referencia ----
    if fecha_lunes_referencia is None:
        fecha_lunes_referencia = date.today()
        fecha_lunes_referencia += __import__("datetime").timedelta(days=(7 - fecha_lunes_referencia.weekday()) % 7 or 7)
    cobertura_por_dia = {}
    try:
        resultado = generar_horario_semana(fecha_lunes_referencia, db_path=db_path)
        for dia in DIAS_SEMANA:
            req = sum(c["requeridos"] for c in resultado["cobertura"][dia].values())
            prog = sum(c["programados"] for c in resultado["cobertura"][dia].values())
            cobertura_por_dia[dia] = round(prog / req * 100, 1) if req > 0 else None
    except Exception:
        cobertura_por_dia = {}

    # ---- Promedios del período, base de la severidad relativa ----
    prom_caidas = sum(d["pct_caidas_promedio"] for d in resumen_dia) / len(resumen_dia)
    prom_tmo = sum(d["tmo_seg_promedio"] for d in resumen_dia) / len(resumen_dia)
    valores_cobertura = [v for v in cobertura_por_dia.values() if v is not None]
    prom_cobertura = sum(valores_cobertura) / len(valores_cobertura) if valores_cobertura else None

    filas = []
    for d in resumen_dia:
        dia = d["dia_semana"]
        caidas = d["pct_caidas_promedio"]
        tmo = d["tmo_seg_promedio"]
        cobertura = cobertura_por_dia.get(dia)
        banderas = []

        if prom_caidas > 0:
            sev = (caidas - prom_caidas) / prom_caidas
            peso = 2 if sev >= 0.5 else (1 if sev >= 0.15 else 0)
            if peso > 0:
                banderas.append({"pilar": "% de caídas", "sev": sev, "peso": peso,
                                  "texto": f"{caidas:.1f}% de caídas frente a {prom_caidas:.1f}% promedio del período"})
        if prom_tmo > 0:
            sev = (tmo - prom_tmo) / prom_tmo
            peso = 2 if sev >= 0.15 else (1 if sev >= 0.05 else 0)
            if peso > 0:
                banderas.append({"pilar": "TMO", "sev": sev, "peso": peso,
                                  "texto": f"TMO de {int(tmo//60)}:{int(tmo%60):02d} frente a {int(prom_tmo//60)}:{int(prom_tmo%60):02d} promedio"})
        if cobertura is not None and prom_cobertura:
            sev = (prom_cobertura - cobertura) / prom_cobertura
            peso = 2 if sev >= 0.15 else (1 if sev >= 0.05 else 0)
            if peso > 0:
                banderas.append({"pilar": "Cobertura real", "sev": sev, "peso": peso,
                                  "texto": f"{cobertura:.1f}% de cobertura frente a {prom_cobertura:.1f}% promedio"})

        banderas.sort(key=lambda b: (-b["peso"], -b["sev"]))
        peso_total = sum(b["peso"] for b in banderas)
        nivel = "CRITICO" if peso_total >= 4 else ("ALTO" if peso_total >= 1 else "CONTROLADO")
        filas.append({"dia": dia, "caidas": caidas, "tmo": tmo, "cobertura": cobertura,
                       "banderas": banderas, "peso_total": peso_total, "nivel": nivel,
                       "problema_principal": banderas[0] if banderas else None})

    filas.sort(key=lambda f: (-f["peso_total"], -(f["problema_principal"]["sev"] if f["problema_principal"] else 0)))

    # ---- Tarjetas de KPI ----
    kpis = [
        {"label": "Llamadas totales", "valor": f"{m['total_llamadas']:,}", "color": AZUL_VIVO},
        {"label": "% Contestadas", "valor": f"{m['pct_contestadas']}%", "color": _color_rl_por_umbral(m['pct_contestadas'])},
        {"label": "Días en nivel crítico", "valor": str(sum(1 for f in filas if f["nivel"] == "CRITICO")), "color": SIGNAL},
        {"label": "Días controlados", "valor": str(sum(1 for f in filas if f["nivel"] == "CONTROLADO")), "color": VERDE},
    ]
    story.append(_tarjetas_kpi(kpis, ancho_util))
    story.append(Spacer(1, 16))

    # ---- Ranking de criticidad ----
    story.append(Paragraph("Ranking de días por criticidad", H2_STYLE))
    story.append(Paragraph(
        "Ordenado de más a menos crítico. La severidad se calcula relativa al promedio del "
        "propio período, no con umbrales fijos -- así, si toda la semana está mal, no se "
        "marcan todos los días por igual.", NORMAL_SMALL_STYLE))
    story.append(Spacer(1, 8))

    filas_tabla = [["Día", "Nivel", "% Caídas", "TMO", "Cobertura real", "Problema principal"]]
    for f in filas:
        pp = f["problema_principal"]
        filas_tabla.append([
            f["dia"], f["nivel"], f"{f['caidas']:.1f}%",
            f"{int(f['tmo']//60)}:{int(f['tmo']%60):02d}",
            f"{f['cobertura']:.1f}%" if f["cobertura"] is not None else "N/D",
            pp["texto"] if pp else "Sin hallazgos",
        ])

    t = Table(filas_tabla, colWidths=[2.2*cm, 2.4*cm, 2.3*cm, 2*cm, 3*cm, 12.4*cm], repeatRows=1)
    estilo = list(ESTILO_TABLA) + [("VALIGN", (0, 0), (-1, -1), "TOP"), ("FONTSIZE", (0, 1), (-1, -1), 8.5)]
    mapa_bg = {"CRITICO": colors.HexColor("#FBE9E1"), "ALTO": colors.HexColor("#FBF1DE"), "CONTROLADO": colors.HexColor("#E3F1E9")}
    mapa_txt = {"CRITICO": SIGNAL, "ALTO": AMBAR, "CONTROLADO": VERDE}
    for i, f in enumerate(filas, start=1):
        estilo.append(("BACKGROUND", (1, i), (1, i), mapa_bg[f["nivel"]]))
        estilo.append(("TEXTCOLOR", (1, i), (1, i), mapa_txt[f["nivel"]]))
        estilo.append(("FONTNAME", (1, i), (1, i), F_BOLD))
        estilo.append(("ALIGN", (1, i), (1, i), "CENTER"))
    t.setStyle(TableStyle(estilo))
    story.append(t)

    story.append(PageBreak())

    # ---- Página de diagnóstico ----
    story.append(Paragraph("Diagnóstico del día más crítico", H2_STYLE))
    peor = filas[0]
    if peor["problema_principal"]:
        pp = peor["problema_principal"]
        acciones = {
            "% de caídas": "revisar la disponibilidad real de asesores ese día y reforzar el piso mínimo de cobertura (ver Brecha de Personal).",
            "TMO": "revisar los procesos o el tipo de solicitud que puede estar alargando la llamada ese día específico.",
            "Cobertura real": "priorizar contratación o cambios de disponibilidad puntualmente para ese día.",
        }
        accion = acciones.get(pp["pilar"], "revisar en detalle los datos de ese día.")
        texto_diagnostico = (
            f"<b>{peor['dia']}</b> es el día más crítico del período (nivel <b>{peor['nivel']}</b>). "
            f"El pilar más afectado es <b>{pp['pilar']}</b>: {pp['texto']}, una desviación de "
            f"{pp['sev']*100:.0f}% respecto al promedio del período. Acción recomendada: {accion}"
        )
    else:
        texto_diagnostico = "Sin indicadores suficientes para diagnosticar — ningún día se desvía de forma relevante del promedio del período."
    story.append(Paragraph(texto_diagnostico, ParagraphStyle("Diag", parent=NORMAL_SMALL_STYLE, fontSize=10.5, leading=15)))
    story.append(Spacer(1, 14))

    if len(filas) > 1 and filas[1]["problema_principal"]:
        segundo = filas[1]
        pp2 = segundo["problema_principal"]
        story.append(Paragraph(
            f"En segundo lugar, <b>{segundo['dia']}</b> (nivel {segundo['nivel']}) muestra {pp2['texto']}.",
            NORMAL_SMALL_STYLE))

    story.extend(_pie_pagina())
    doc.build(story, onFirstPage=_numero_pagina, onLaterPages=_numero_pagina)
    return salida


if __name__ == "__main__":
    import sys
    from datetime import timedelta
    if len(sys.argv) > 1:
        lunes = date.fromisoformat(sys.argv[1])
    else:
        hoy = date.today()
        lunes = hoy + timedelta(days=(7 - hoy.weekday()) % 7 or 7)
    sl = float(sys.argv[2]) if len(sys.argv) > 2 else 0.95
    ruta = generar_pdf_brecha_personal(lunes, target_service_level=sl)
    print(f"PDF generado: {ruta}")
