#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
report_osservatorio.py
Genera un report PDF professionale dall'Osservatorio Sovranità Digitale
"""

from __future__ import annotations
import logging
import os
import sys
from pathlib import Path
from datetime import datetime
import json
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.colors import HexColor
from reportlab.platypus import SimplePlatypusDoc, Table, TableStyle, Paragraph, PageBreak
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import black, white

# Path configurabile per il file stat.json
JSON_PATH = "../osservatorio-sovranita-digitale-frontend/main/data/stat.json"

BASE_DIR = Path(__file__).resolve().parent
REPORT_DIR = BASE_DIR / "report"
LOG_DIR = BASE_DIR / "logs"

TODAY = datetime.now().strftime("%Y%m%d")
PDF_PATH = REPORT_DIR / f"{TODAY}-report-osservatorio.pdf"
LOG_PATH = LOG_DIR / f"{TODAY}-report-osservatorio.log"

def setup_logger():
    LOG_DIR.mkdir(exist_ok=True)
    logger = logging.getLogger("osservatorio")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    sh.setLevel(logging.INFO)
    fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)
    logger.addHandler(sh)
    logger.addHandler(fh)
    return logger

log = setup_logger()

def load_json():
    """Legge il file JSON dal filesystem"""
    json_file = Path(JSON_PATH)
    
    if not json_file.is_absolute():
        json_file = BASE_DIR / json_file
    
    log.info(f"Path completo del file JSON: {json_file}")
    
    if not json_file.exists():
        raise FileNotFoundError(f"File JSON non trovato: {json_file}")
    
    log.info(f"Legge file JSON: {json_file}")
    
    with open(json_file, "r", encoding="utf-8") as f:
        return json.load(f)

def euro(v):
    """Formatta valore in euro"""
    if v >= 1000000000:
        return f"€ {v/1000000000:,.1f} miliardi"
    elif v >= 1000000:
        return f"€ {v/1000000:,.1f} milioni"
    else:
        return f"€ {v:,.0f}"

def format_value(card):
    """Formatta valore based on value_type"""
    v = card["value"]
    t = card.get("value_type", "")
    
    if t == "currency":
        return euro(float(v))
    elif t == "percentage":
        return f"{v}%"
    elif t == "score":
        return f"{v}"
    elif t == "index":
        return f"{v}"
    elif t == "ratio":
        return f"{v}"
    elif t == "count":
        return str(v)
    elif t == "list":
        return v
    return str(v)

def parse_list(value):
    """Parse lista di valori separati da |"""
    rows = []
    for item in str(value).split("|"):
        rows.append(item.strip())
    return rows

def create_bar_chart(data_2024, data_2025, title):
    """Cre grafico a barre verticale per comparazione 2024 vs 2025"""
    drawing = Drawing(400, 200)
    
    bc = VerticalBarChart()
    bc.x = 50
    bc.y = 50
    bc.width = 300
    bc.height = 120
    
    bc.data = [data_2024, data_2025]
    
    bc.strokeColor = black
    bc.fontSize = 10
    bc.color = [HexColor("#2E86AB"), HexColor("#A23B72")]
    
    bc.categoryAxis.title = ""
    bc.categoryAxis.categories = ["2024", "2025"]
    bc.categoryAxis.tickDistance = 10
    
    bc.valueAxis.title = title
    bc.valueAxis.tickDistance = 10
    
    drawing.add(bc)
    return drawing

def build_content(data):
    """Construe contenuto del report"""
    content = []
    
    # Styles
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        name="TitleCustom",
        parent=styles["Title"],
        fontSize=28,
        textColor=HexColor("#2E86AB"),
        alignment=TA_CENTER,
        spaceAfter=20
    )
    
    subtitle_style = ParagraphStyle(
        name="SubtitleCustom",
        parent=styles["Heading2"],
        fontSize=18,
        textColor=HexColor("#2E86AB"),
        spaceAfter=10,
        spaceBefore=15
    )
    
    heading_style = ParagraphStyle(
        name="HeadingCustom",
        parent=styles["Heading3"],
        fontSize=14,
        textColor=HexColor("#003366"),
        spaceAfter=8,
        spaceBefore=12
    )
    
    body_style = ParagraphStyle(
        name="BodyCustom",
        parent=styles["BodyText"],
        fontSize=10,
        alignment=TA_JUSTIFY,
        spaceAfter=6
    )
    
    small_style = ParagraphStyle(
        name="SmallCustom",
        parent=styles["BodyText"],
        fontSize=8,
        textColor=HexColor("#666666"),
        spaceAfter=4
    )
    
    # Copertina
    content.append(Paragraph("Report Sovranità Digitale", title_style))
    content.append(Paragraph("Osservatorio sulla Sovranità Digitale in Italia", subtitle_style))
    content.append(Paragraph(f"Generato il: {data.get('generated_at', '').split('T')[0]}", body_style))
    content.append(Paragraph("", body_style))
    content.append(Paragraph("Dati relativi all'anno 2024-2025", small_style))
    content.append(PageBreak())
    
    # Executive Summary
    content.append(Paragraph("Executive Summary", subtitle_style))
    
    s = data["kpi"]["sections"]
    
    try:
        isdc = s["sovranita_digitale"]["cards"][0]["value"]
        hyper = s["cloud"]["cards"][0]["value"]
        hhi = s["provider"]["cards"][3]["value"]
        volume = s["contratti"]["cards"][0]["value"]
        
        summary_text = f"""
        L'<b>indice medio di sovranità digitale (ISDC)</b> è <b>{isdc}</b>.
        
        La <b>dipendenza dagli hyperscaler</b> (Amazon, Google, Microsoft) è pari al <b>{hyper}%</b> dei comuni.
        
        L'<b>indice HHI ASN</b> (concentrazione infrastrutturale) è <b>{hhi}</b>, indicando una forte concentrazione.
        
        Il <b>volume economico totale</b> delle gare ICT analizzate è <b>{euro(volume)}</b>.
        """
        content.append(Paragraph(summary_text, body_style))
    except Exception as e:
        log.warning(f"Sintesi non disponibile: {e}")
        content.append(Paragraph("Sintesi non disponibile.", body_style))
    
    content.append(PageBreak())
    
    # Base Dati
    content.append(Paragraph("Base Dati", subtitle_style))
    base_dati = s["base_dati"]
    
    table_data = [["KPI", "Descrizione", "Valore"]]
    for card in base_dati["cards"]:
        table_data.append([card["title"], card["subtitle"], str(card["value"])])
    
    table = Table(table_data)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#2E86AB")),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ROWBACKGROUND", (0, 1), (-1, -1), [white, HexColor("#f5f5f5")]),
        ("GRID", (0, 0), (-1, -1), 1, black),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    content.append(table)
    content.append(Paragraph("", body_style))
    
    # Indice di Sovranità Digitale
    content.append(Paragraph("Indice di Sovranità Digitale", subtitle_style))
    sovranita = s["sovranita_digitale"]
    
    table_data = [["KPI", "Descrizione", "Valore"]]
    for card in sovranita["cards"]:
        table_data.append([card["title"], card["subtitle"], format_value(card)])
    
    table = Table(table_data)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#2E86AB")),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ROWBACKGROUND", (0, 1), (-1, -1), [white, HexColor("#f5f5f5")]),
        ("GRID", (0, 0), (-1, -1), 1, black),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    content.append(table)
    content.append(Paragraph("", body_style))
    
    # Distribuzione ISDC
    content.append(Paragraph("Distribuzione ISDC", heading_style))
    
    high_score = sovranita["cards"][3]["value"]
    critical_score = sovranita["cards"][4]["value"]
    total = data["kpi"]["total_comuni"]
    
    content.append(Paragraph(
        f"<b>Infrastruttura sovrana (ISDC ≥ 78):</b> {high_score} comuni ({high_score/total*100:,.1f}%)",
        body_style
    ))
    content.append(Paragraph(
        f"<b>Sovranità fragile (ISDC < 40):</b> {critical_score} comuni ({critical_score/total*100:,.1f}%)",
        body_style
    ))
    content.append(Paragraph("", body_style))
    
    # Vendor Lock-in
    content.append(Paragraph("Vendor Lock-in", subtitle_style))
    lockin = s["lockin"]
    
    table_data = [["KPI", "Descrizione", "Valore"]]
    for card in lockin["cards"]:
        table_data.append([card["title"], card["subtitle"], str(card["value"])])
    
    table = Table(table_data)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#2E86AB")),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ROWBACKGROUND", (0, 1), (-1, -1), [white, HexColor("#f5f5f5")]),
        ("GRID", (0, 0), (-1, -1), 1, black),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    content.append(table)
    content.append(Paragraph("", body_style))
    
    # Concentrazione ASN
    content.append(Paragraph("Concentrazione ASN", subtitle_style))
    provider = s["provider"]
    
    table_data = [["KPI", "Descrizione", "Valore"]]
    for card in provider["cards"]:
        if card.get("value_type") == "list":
            content.append(Paragraph(f"<b>{card['title']}</b>: {card['subtitle']}", heading_style))
            for row in parse_list(card["value"]):
                content.append(Paragraph(f"  • {row}", body_style))
        else:
            table_data.append([card["title"], card["subtitle"], format_value(card)])
    
    non_list_rows = [r for r in table_data if len(r) == 3 and r[0] != "KPI"]
    if non_list_rows:
        table_data_clean = [["KPI", "Descrizione", "Valore"]] + non_list_rows
        table = Table(table_data_clean)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), HexColor("#2E86AB")),
            ("TEXTCOLOR", (0, 0), (-1, 0), white),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
            ("ROWBACKGROUND", (0, 1), (-1, -1), [white, HexColor("#f5f5f5")]),
            ("GRID", (0, 0), (-1, -1), 1, black),
            ("PADDING", (0, 0), (-1, -1), 6),
        ]))
        content.append(table)
    content.append(Paragraph("", body_style))
    
    # Cloud & Hyperscaler
    content.append(Paragraph("Cloud & Hyperscaler", subtitle_style))
    cloud = s["cloud"]
    
    table_data = [["KPI", "Descrizione", "Valore"]]
    for card in cloud["cards"]:
        table_data.append([card["title"], card["subtitle"], format_value(card)])
    
    table = Table(table_data)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#2E86AB")),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ROWBACKGROUND", (0, 1), (-1, -1), [white, HexColor("#f5f5f5")]),
        ("GRID", (0, 0), (-1, -1), 1, black),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    content.append(table)
    content.append(Paragraph("", body_style))
    
    # Grafico Procurement 2024 vs 2025
    content.append(Paragraph("Tender ICT: 2024 vs 2025", subtitle_style))
    
    if "trend_procurement" in data and len(data["trend_procurement"]) >= 2:
        trend = data["trend_procurement"]
        totale_2024 = trend[0]["totale"]
        totale_2025 = trend[1]["totale"]
        
        content.append(Paragraph(
            f"<b>Gare ICT 2024:</b> {totale_2024} | <b>Gare ICT 2025:</b> {totale_2025} "
            f"(<b>+{((totale_2025-totale_2024)/totale_2024*100):,.1f}%</b>)",
            body_style
        ))
        
        drawing = create_bar_chart(totale_2024, totale_2025, "Numero gare ICT")
        content.append(drawing)
        content.append(Paragraph("", body_style))
    
    # Grafico Valore Economico 2024 vs 2025
    content.append(Paragraph("Valore Economico Gare ICT: 2024 vs 2025", subtitle_style))
    
    if "valore_economico_per_anno" in data and len(data["valore_economico_per_anno"]) >= 2:
        valore = data["valore_economico_per_anno"]
        v_2024 = valore[0]["totale"]
        v_2025 = valore[1]["totale"]
        
        content.append(Paragraph(
            f"<b>2024:</b> {euro(v_2024)} | <b>2025:</b> {euro(v_2025)} "
            f"(<b>+{((v_2025-v_2024)/v_2024*100):,.1f}%</b>)",
            body_style
        ))
        
        drawing = create_bar_chart(v_2024/1000000, v_2025/1000000, "Milioni di €")
        content.append(drawing)
        content.append(Paragraph("", body_style))
    
    # Resilienza
    content.append(Paragraph("Resilienza", subtitle_style))
    resilienza = s["resilienza"]
    
    table_data = [["KPI", "Descrizione", "Valore"]]
    for card in resilienza["cards"]:
        table_data.append([card["title"], card["subtitle"], str(card["value"])])
    
    table = Table(table_data)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#2E86AB")),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ROWBACKGROUND", (0, 1), (-1, -1), [white, HexColor("#f5f5f5")]),
        ("GRID", (0, 0), (-1, -1), 1, black),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    content.append(table)
    content.append(Paragraph("", body_style))
    
    # Bande di Distribuzione
    content.append(Paragraph("Distribuzione Bande di Dipendenza", subtitle_style))
    
    if data.get("bands"):
        table_data = [["Banda", "Count", "%"]]
        for b in data["bands"]:
            table_data.append([b["band"], str(b["count"]), f"{b['pct']}%"])
        
        table = Table(table_data)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), HexColor("#2E86AB")),
            ("TEXTCOLOR", (0, 0), (-1, 0), white),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
            ("ROWBACKGROUND", (0, 1), (-1, -1), [white, HexColor("#f5f5f5")]),
            ("GRID", (0, 0), (-1, -1), 1, black),
            ("PADDING", (0, 0), (-1, -1), 6),
        ]))
        content.append(table)
        content.append(Paragraph("", body_style))
    
    # Gare ICT
    content.append(Paragraph("Gare ICT - Dettagli", subtitle_style))
    contratti = s["contratti"]
    
    table_data = [["KPI", "Descrizione", "Valore"]]
    for card in contratti["cards"]:
        if card.get("value_type") == "list":
            content.append(Paragraph(f"<b>{card['title']}</b>: {card['subtitle']}", heading_style))
            for row in parse_list(card["value"]):
                content.append(Paragraph(f"  • {row}", body_style))
        else:
            table_data.append([card["title"], card["subtitle"], format_value(card)])
    
    non_list_rows = [r for r in table_data if len(r) == 3 and r[0] != "KPI"]
    if non_list_rows:
        table_data_clean = [["KPI", "Descrizione", "Valore"]] + non_list_rows
        table = Table(table_data_clean)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), HexColor("#2E86AB")),
            ("TEXTCOLOR", (0, 0), (-1, 0), white),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
            ("ROWBACKGROUND", (0, 1), (-1, -1), [white, HexColor("#f5f5f5")]),
            ("GRID", (0, 0), (-1, -1), 1, black),
            ("PADDING", (0, 0), (-1, -1), 6),
        ]))
        content.append(table)
    
    content.append(Paragraph("", body_style))
    
    # TLS
    content.append(Paragraph("TLS - Certificati", subtitle_style))
    dns_tls = s["dns_tls"]
    
    table_data = [["KPI", "Descrizione", "Valore"]]
    for card in dns_tls["cards"]:
        table_data.append([card["title"], card["subtitle"], str(card["value"])])
    
    table = Table(table_data)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#2E86AB")),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ROWBACKGROUND", (0, 1), (-1, -1), [white, HexColor("#f5f5f5")]),
        ("GRID", (0, 0), (-1, -1), 1, black),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    content.append(table)
    
    return content

def create_pdf(data):
    """Crea PDF dal contenuto"""
    REPORT_DIR.mkdir(exist_ok=True)
    
    doc = SimplePlatypusDoc(PDF_PATH, pagesize=A4)
    
    content = build_content(data)
    
    doc.addPageTemplates([])
    doc.build(content)
    
    log.info(f"Creato {PDF_PATH}")

def main():
    log.info("Legge dataset dal filesystem")
    data = load_json()
    log.info("Generazione contenuto PDF")
    create_pdf(data)
    log.info(f"Report completato: {PDF_PATH}")

if __name__ == "__main__":
    main()