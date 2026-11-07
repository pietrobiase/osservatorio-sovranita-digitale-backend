#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate_reportPDF.py
Genera un report PDF dall'Osservatorio Sovranità Digitale.

Il documento è discorsivo: le tabelle sono di supporto al ragionamento,
non il contenuto. Un PDF di sole tabelle riporterebbe i numeri che il
frontend già mostra, senza dire nulla su cosa significhino.

Non interroga il database: legge lo stat.json prodotto da
07 - StatsJson/StatJson.py. Se le due parti non sono allineate sullo
schema il fallimento deve essere esplicito, perché un PDF con numeri
sbagliati è più difficile da notare di un PDF che non esiste.

Nessun valore è scritto alla mano: tutto deriva da stat.json, perché il
dato si ricalcola a ogni run e un numero fisso nel testo diventa falso
alla prima esecuzione successiva.
"""

from __future__ import annotations
import logging
import math
import re
import sys
from pathlib import Path
from datetime import datetime
import json

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, PageBreak, Spacer,
    KeepTogether,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common

JSON_PATH = common.frontend_file("stat.json")

BASE_DIR = Path(__file__).resolve().parent
REPORT_DIR = BASE_DIR / "report"
LOG_DIR = BASE_DIR / "logs"

TODAY = datetime.now().strftime("%Y%m%d")
PDF_PATH = REPORT_DIR / f"{TODAY}-report-osservatorio.pdf"
LOG_PATH = LOG_DIR / f"{TODAY}-report-osservatorio.log"

ACCENTO = HexColor("#2E86AB")
ACCENTO_SCURO = HexColor("#003366")
ZEBRA = HexColor("#f5f5f5")

# Larghezza utile della pagina: A4 (21cm) meno i margini dichiarati
# in create_pdf(). Le larghezze delle colonne devono sommare a
# questa, altrimenti reportlab le riscala da sole e il testo
# va a capo dove non deve.
LARGHEZZA = 17.4 * cm
COL_KPI = 7.4 * cm
COL_DESCR = 6.6 * cm
COL_VALORE = 3.4 * cm


def setup_logger():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
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


class DatiNonValidi(Exception):
    """stat.json non ha la struttura che il report si aspetta"""


def load_json():
    """Legge stat.json e ne verifica la struttura minima"""
    json_file = Path(JSON_PATH)

    if not json_file.is_absolute():
        json_file = BASE_DIR / json_file

    log.info(f"Path completo del file JSON: {json_file}")

    if not json_file.exists():
        raise FileNotFoundError(f"File JSON non trovato: {json_file}")

    log.info(f"Legge file JSON: {json_file}")

    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    try:
        sezioni = data["kpi"]["sections"]
    except (KeyError, TypeError) as e:
        raise DatiNonValidi(
            f"manca kpi.sections in {json_file}: {e}"
        ) from e

    if not isinstance(sezioni, dict) or not sezioni:
        raise DatiNonValidi("kpi.sections è vuota o non è un dizionario")

    log.info(f"Sezioni disponibili: {', '.join(sezioni)}")

    return data


# --------------------------------------------------------------------------
# Accesso ai dati
#
# Le card sono un contratto identificato dall'id (vedi 8.3 del README).
# L'ordine nell'array dipende dall'ordine delle colonne in StatJson.py,
# quindi indicizzare per posizione produrrebbe un report con numeri
# sbagliati senza sollevare alcun errore.
# --------------------------------------------------------------------------

def sezione(data, sez_id):
    """Restituisce una sezione, o None se non esiste"""
    s = data.get("kpi", {}).get("sections", {}).get(sez_id)
    if s is None:
        log.warning(f"Sezione '{sez_id}' assente da stat.json")
    return s


def card(sez, card_id):
    """Cerca una card per id, con warning se non c'è"""
    if sez is None:
        return None
    for c in sez.get("cards", []):
        if c.get("id") == card_id:
            return c
    log.warning(
        f"Card '{card_id}' assente dalla sezione "
        f"'{sez.get('title', '?')}'"
    )
    return None


def valore(card, default=None):
    """Valore di una card, o default se la card non c'è"""
    if card is None:
        return default
    return card.get("value", default)


def numero(v, default=None):
    """
    Valore come float, o default se non convertibile.

    NaN e +/-inf non sono numeri utilizzabili: float() li accetta
    senza eccezione, quindi senza un controllo esplicito finivano
    stampati come 'nan' e 'inf' nel PDF, presentandoli come misure
    quando invece indicano un calcolo corrotto a monte. Qui valgono
    la stessa cosa di un valore assente.
    """
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if math.isnan(f) or math.isinf(f):
        return default
    return f


# --------------------------------------------------------------------------
# Formattazione
# --------------------------------------------------------------------------

def _separatore_migliaia(s):
    """
    Applica la notazione italiana: punto per le migliaia, virgola per i
    decimali (1.234.567,89).

    Convenzione gia' presente nel progetto, in
    06 - BuildGeojson/old/Contratti_geojson.py (format_italian_number),
    e quella prevista dallo standard UNI EN ISO 5964-2 per l'italiano.
    Lo spazio come separatore delle migliae' e' ammesso ma si presta a
    confusione: in un PDF giustificato puo' andare a capo, e
    ricomparendo accanto a valori in percentuale si legge come una
    separazione fra parole e non fra cifre.

    La stringa che arriva da format() usa la virgola per le migliae' e
    il punto per i decimali, quindi i due separatori vanno scambiati
    insieme. Lo scambio passa per un segnaposto: sostituire la virgola
    per prima la convertirebbe nel separatore dei decimali appena
    rilasciato.
    """
    segnaposto = "\x00"
    return (
        s.replace(",", segnaposto)
        .replace(".", ",")
        .replace(segnaposto, ".")
    )


def fmt_num(v, decimali=1):
    """Numero in formato italiano: 1.234,6"""
    f = numero(v)
    if f is None:
        return "n.d."
    return _separatore_migliaia(f"{f:,.{decimali}f}")


def fmt_intero(v):
    """Intero in formato italiano: 23.746"""
    f = numero(v)
    if f is None:
        return "n.d."
    return _separatore_migliaia(f"{f:,.0f}")


def quota(parte, totale, decimali=1):
    """
    Percentuale che non esplode quando il denominatore è zero.

    Il vecchio codice faceva parte/totale*100 inline: uno zero a
    denominatore dava ZeroDivisionError e abortiva la generazione
    del PDF per un valore che è semplicemente non definibile.
    """
    p, t = numero(parte), numero(totale)
    if p is None or t is None or t == 0:
        return "n.d."
    return f"{fmt_num(p / t * 100, decimali)}%"


def format_value(card):
    """Formatta il valore di una card in base a value_type"""
    v = card.get("value")
    t = card.get("value_type", "")

    if t == "percentage":
        # value arriva già in percentuale (53.14 = 53,14%)
        return f"{fmt_num(v, 2)}%"
    if t == "score":
        return fmt_num(v, 2)
    if t == "index":
        return fmt_num(v, 4)
    if t == "count":
        return fmt_intero(v)
    if t == "list":
        # Le liste sono serializzate con '|' da StatJson; in tabella
        # il separatore va reso leggibile.
        voci = parse_list(v)
        return "; ".join(voci) if voci else "n.d."
    # Nessun tipo dichiarato, o tipo non previsto: un valore assente
    # resta un'assenza. str(None) stamperebbe 'None' nella tabella,
    # che e' un dettaglio interno di Python, non un dato assente.
    if numero(v) is None and not isinstance(v, str):
        return "n.d."
    return str(v)


def parse_list(value):
    """Divide una lista serializzata con il separatore |"""
    return [i.strip() for i in str(value).split("|") if i.strip()]


def parse_asn(voce):
    """
    Spezza una voce del tipo 'Provider S.p.A. (1234)' in nome e numero.

    Il nome è tutto cio che precede l'ultima parentesi, cosi' un
    nome che contiene già parentesi non viene troncato.
    """
    m = re.match(r"^(.*?)\s*\((\d+)\)\s*$", voce)
    if not m:
        return voce.strip(), None
    return m.group(1).strip(), numero(m.group(2))


def etichetta_hhi(hhi):
    """Descrive l'HHI in base al valore"""
    v = numero(hhi)
    if v is None:
        return "non calcolabile"
    if v >= 0.25:
        return "concentrazione alta"
    if v >= 0.15:
        return "concentrazione moderata"
    return "concentrazione bassa"


def asn_effettivi(hhi):
    """
    Numero effettivo di provider: 1/HHI.

    E' l'inverso di Simpson. Risponde a 'quanti provider equivalenti a
    provider uguali ci sarebbero', che e' la domanda giusta da fare a un
    indice di concentrazione: un HHI basso con un provider dominante
    significa coda lunga di provider minuscoli, non equità.
    """
    v = numero(hhi)
    if v is None or v <= 0:
        return None
    return 1.0 / v


# --------------------------------------------------------------------------
# Blocchi tipografici
# --------------------------------------------------------------------------

def styles():
    """Stili tipografici del documento"""
    s = getSampleStyleSheet()

    titolo = ParagraphStyle(
        name="TitoloRel", parent=s["Title"], fontSize=28,
        textColor=ACCENTO, alignment=TA_CENTER, spaceAfter=20,
    )
    sottotitolo = ParagraphStyle(
        name="SottotitoloRel", parent=s["Heading2"], fontSize=17,
        textColor=ACCENTO, spaceAfter=10, spaceBefore=16,
    )
    sottosezione = ParagraphStyle(
        name="SottosezioneRel", parent=s["Heading3"], fontSize=12.5,
        textColor=ACCENTO_SCURO, spaceAfter=6, spaceBefore=12,
    )
    corpo = ParagraphStyle(
        name="CorpoRel", parent=s["BodyText"], fontSize=10,
        leading=15, alignment=TA_JUSTIFY, spaceAfter=9,
    )
    piccolo = ParagraphStyle(
        name="PiccoloRel", parent=s["BodyText"], fontSize=8.5,
        leading=11, textColor=HexColor("#555555"), spaceAfter=6,
    )
    citazione = ParagraphStyle(
        name="CitazioneRel", parent=corpo, fontSize=9.5, leading=14,
        leftIndent=8, rightIndent=8, textColor=HexColor("#333333"),
        spaceBefore=4, spaceAfter=10,
    )
    cella_stile = ParagraphStyle(
        name="CellaRel", parent=s["BodyText"], fontSize=9, leading=11,
        spaceAfter=0,
    )
    intest = ParagraphStyle(
        name="IntestRel", parent=cella_stile, fontName="Helvetica-Bold",
        textColor=white, fontSize=9.5, leading=11.5,
    )
    voce = ParagraphStyle(
        name="VoceRel", parent=corpo, leftIndent=14, spaceAfter=3,
    )
    didascalia = ParagraphStyle(
        name="DidascaliaRel", parent=piccolo, fontSize=8, leading=10.5,
        spaceBefore=2, spaceAfter=10,
    )

    return {
        "titolo": titolo,
        "sottotitolo": sottotitolo,
        "sottosezione": sottosezione,
        "corpo": corpo,
        "piccolo": piccolo,
        "citazione": citazione,
        "cella": cella_stile,
        "intest": intest,
        "voce": voce,
        "didascalia": didascalia,
    }


def cella(testo, stile):
    """Incapsula il testo in un Paragraph così va a capo nelle colonne"""
    return Paragraph(str(testo), stile)


def _subtitle(c):
    """
    Sottotitolo della card, con il separatore decimale in italiano.

    StatJson.py scrive le quote delle tipologie come stringa con il
    punto ("91.4% degli enti censiti"): la stringa arriva grezza dal
    JSON e, riportata com'e' accanto a numeri in formato italiano,
    sembrerebbe un refuso.
    """
    testo = str(c.get("subtitle", ""))

    def punto(m):
        return m.group(0).replace(".", ",")

    return re.sub(r"(?<=\d)\.(?=\d)", punto, testo)


def _stile_tabella(ultima_totale=False):
    """Stile condiviso da tutte le tabelle"""
    comandi = [
        ("BACKGROUND", (0, 0), (-1, 0), ACCENTO),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9.5),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ROWBACKGROUND", (0, 1), (-1, -1), [white, ZEBRA]),
        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#cccccc")),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]
    if ultima_totale:
        comandi += [
            ("BACKGROUND", (0, -1), (-1, -1), HexColor("#e4e8ec")),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ]
    return TableStyle(comandi)


def tabella(righe, larghezze, stili, ultima_totale=False):
    """Costruisce una tabella con intestazione ripetuta a ogni pagina"""
    t = Table(righe, colWidths=larghezze, repeatRows=1)
    t.setStyle(_stile_tabella(ultima_totale))
    return t


def tabella_kpi(cards, stili):
    """Tabella KPI: solo per l'appendice, dove serve il quadro completo"""
    righe = [[
        cella("KPI", stili["intest"]),
        cella("Descrizione", stili["intest"]),
        cella("Valore", stili["intest"]),
    ]]
    for c in cards:
        righe.append([
            cella(c.get("title", c.get("id", "")), stili["cella"]),
            cella(_subtitle(c), stili["cella"]),
            cella(format_value(c), stili["cella"]),
        ])
    t = Table(
        righe,
        colWidths=[COL_KPI, COL_DESCR, COL_VALORE],
        repeatRows=1,
    )
    t.setStyle(_stile_tabella())
    t.setStyle(TableStyle([
        ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
    ]))
    return t


def tabella_bands(bands, stili, denominatore):
    """
    Fasce ISDC con conteggio e percentuale.

    Le percentuali arrivano da stat.json e non sono ricalcolate: le ha
    gia' calcolate StatJson.py sul denominatore corretto (enti con
    ISDC). Ricalcolarle qui produceva 7,2% dove il valore vero e' 40,2%,
    perche' il vecchio codice divideva per il censimento.
    """
    righe = [[
        cella("Fascia", stili["intest"]),
        cella("Enti", stili["intest"]),
        cella("Quota", stili["intest"]),
    ]]
    for b in bands:
        righe.append([
            cella(b.get("band", ""), stili["cella"]),
            cella(fmt_intero(b.get("count", 0)), stili["cella"]),
            cella(
                f"{fmt_num(numero(b.get('pct'), 0), 2)}%",
                stili["cella"],
            ),
        ])
    totale = sum(numero(b.get("count"), 0) or 0 for b in bands)
    righe.append([
        cella("Totale enti valutati", stili["intest"]),
        cella(fmt_intero(totale), stili["intest"]),
        cella(quota(totale, denominatore), stili["intest"]),
    ])

    t = Table(
        righe,
        colWidths=[LARGHEZZA - 8.2 * cm, 4.1 * cm, 4.1 * cm],
        repeatRows=1,
    )
    t.setStyle(_stile_tabella(ultima_totale=True))
    t.setStyle(TableStyle([
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
    ]))
    return t


def tabella_perimetro(voci, stili):
    """Piccola tabella di raccordo fra censimento e campione"""
    righe = [[
        cella("Insieme", stili["intest"]),
        cella("Enti", stili["intest"]),
        cella("Sul censimento", stili["intest"]),
    ]]
    for etichetta, n, base in voci:
        righe.append([
            cella(etichetta, stili["cella"]),
            cella(fmt_intero(n), stili["cella"]),
            cella(quota(n, base), stili["cella"]),
        ])
    t = Table(
        righe,
        colWidths=[LARGHEZZA - 8.2 * cm, 4.1 * cm, 4.1 * cm],
        repeatRows=1,
    )
    t.setStyle(_stile_tabella())
    t.setStyle(TableStyle([("ALIGN", (1, 0), (-1, -1), "RIGHT")]))
    return t


def didascalia(testo, stili):
    return Paragraph(f"<i>{testo}</i>", stili["didascalia"])


# --------------------------------------------------------------------------
# Raccolta dei dati necessari al ragionamento
# --------------------------------------------------------------------------

def raccogli(data):
    """
    Estrae dal JSON i valori usati nel testo.

    Tutto in un posto solo: se una card manca, il testo che la usa
    salta quel passaggio invece di stampare 'n.d.' in mezzo a una frase.
    """
    s_base = sezione(data, "base_dati")
    s_sovr = sezione(data, "sovranita_digitale")
    s_lock = sezione(data, "lockin")
    s_prov = sezione(data, "provider")
    s_cloud = sezione(data, "cloud")
    s_res = sezione(data, "resilienza")
    s_tls = sezione(data, "dns_tls")

    d = {
        "censimento": numero(valore(card(s_base, "total_enti"))),
        "con_isdc": numero(data.get("kpi", {}).get("total_enti")),
        "record_ns": numero(valore(card(s_base, "total_ns"))),
        "record_mx": numero(valore(card(s_base, "total_mx"))),
        "record_cname": numero(valore(card(s_base, "total_cname"))),
        "datacenter": numero(valore(card(s_base, "total_datacenter"))),

        "isdc_avg": numero(valore(card(s_sovr, "isdc_avg"))),
        "isdc_max": numero(valore(card(s_sovr, "isdc_max"))),
        "isdc_min": numero(valore(card(s_sovr, "isdc_min"))),
        "sovrana": numero(valore(card(s_sovr, "high_score"))),
        "fragile": numero(valore(card(s_sovr, "critical_score"))),

        "lock_alto": numero(valore(card(s_lock, "lockin_high"))),
        "lock_parziale": numero(valore(card(s_lock, "lockin_partial"))),
        "lock_distribuito": numero(valore(card(s_lock, "distributed"))),
        "lock_nc": numero(valore(card(s_lock, "lockin_unknown"))),

        "asn_unici": numero(valore(card(s_prov, "unique_asn"))),
        "asn_quota": numero(valore(card(s_prov, "top_asn_share"))),
        "hhi": numero(valore(card(s_prov, "herfindahl"))),
        "asn_top": [
            parse_asn(v)
            for v in parse_list(valore(card(s_prov, "top_5_asn"), ""))
        ],

        "hyper_pct": numero(valore(card(s_cloud, "hyperscaler_pct"))),
        "hyper_si": numero(valore(card(s_cloud, "hyperscaler_si"))),

        "dns_equal": numero(valore(card(s_res, "dns_equal"))),
        "dns_frammentato": numero(valore(card(s_res, "fragmented_dns"))),

        "lets_encrypt": numero(valore(card(s_tls, "lets_encrypt"))),

        "bands": data.get("bands") or [],
        "sezioni": data.get("kpi", {}).get("sections", {}),
        "generated_at": data.get("generated_at", ""),
        "dataset": data.get("dataset", ""),
    }

    # somma delle quattro categorie di lock-in: se non torna sul
    # denominatore, le percentuali successive non hanno significato
    categorie = [
        d["lock_alto"], d["lock_parziale"],
        d["lock_distribuito"], d["lock_nc"],
    ]
    if all(c is not None for c in categorie):
        d["lock_totale"] = sum(categorie)
        d["lock_coerente"] = (
            d["con_isdc"] is not None
            and abs(d["lock_totale"] - d["con_isdc"]) < 0.5
        )
    else:
        d["lock_totale"] = None
        d["lock_coerente"] = None

    d["asn_effettivi"] = asn_effettivi(d["hhi"])

    # somma dei primi cinque ASN: se supera il campione significa che
    # gli stessi enti compaiono su piu' provider
    conteggi = [n for _, n in d["asn_top"] if n is not None]
    if conteggi:
        d["asn_top_somma"] = sum(conteggi)
    else:
        d["asn_top_somma"] = None

    return d


def grigi_dati(d):
    """
    Dice al lettore quanto si può prendere sul serio il documento.

    Una nota di perimetro all'inizio vale più di una avvertenza
    ripetuta in ogni pagina: se il campione è un quinto del censimento,
    il lettore deve saperlo prima di leggere la prima conclusione.
    """
    avvisi = []

    if d["lock_coerente"] is False:
        avvisi.append(
            "Le categorie di lock-in sommano a un valore diverso dagli "
            "enti con ISDC: le quote che seguono sono indicative e vanno "
            "verificate prima della diffusione."
        )
    if d["censimento"] and d["con_isdc"]:
        if d["con_isdc"] > d["censimento"]:
            avvisi.append(
                "Il numero di enti con ISDC supera il censimento: la "
                "query di aggregazione e il conteggio degli enti usano "
                "criteri diversi."
            )
    return avvisi


# --------------------------------------------------------------------------
# Contenuto
# --------------------------------------------------------------------------

def build_content(data):
    """Costruisce il contenuto del report"""
    stili = styles()
    content = []
    d = raccogli(data)

    generato = d["generated_at"]
    data_rif = generato.split("T")[0] if generato else "n.d."

    # ---------------- Copertina ----------------
    content.append(Paragraph("Report Sovranità Digitale", stili["titolo"]))
    content.append(Paragraph(
        "Osservatorio sulla Sovranità Digitale in Italia",
        stili["sottotitolo"],
    ))
    content.append(Paragraph(
        f"Dati al {data_rif} &middot; dataset {d['dataset'] or 'n.d.'}",
        stili["piccolo"],
    ))
    content.append(Spacer(1, 1.2 * cm))
    content.append(Paragraph(
        "Il documento interpreta i KPI dell'Osservatorio. Le tabelle "
        "sostengono il ragionamento; il quadro completo dei valori è "
        "in appendice.",
        stili["piccolo"],
    ))
    content.append(PageBreak())

    # ---------------- Sintesi ----------------
    content += sezione_sintesi(d, stili)
    content.append(PageBreak())

    # ---------------- Perimetro ----------------
    content += sezione_perimetro(d, stili)

    # ---------------- Distribuzione ISDC ----------------
    content += sezione_isdc(d, stili)

    # ---------------- Lock-in ----------------
    content += sezione_lockin(d, stili)

    # ---------------- Concentrazione ----------------
    content += sezione_asn(d, stili)

    # ---------------- Cloud e resilienza ----------------
    content += sezione_cloud(d, stili)

    # ---------------- Limiti ----------------
    content += sezione_limiti(d, stili)

    # ---------------- Appendice ----------------
    content.append(PageBreak())
    content += appendice(d, stili)

    return content


def sezione_sintesi(d, stili):
    """Sintese in prosa: cosa dice il dato, non quanto e'"""
    out = [Paragraph("Sintesi", stili["sottotitolo"])]

    # Il primo paragrafo apre il report: se il dato non c'e' la frase
    # non viene accorciata, perche' un'apertura sottomessa su un
    # campione assente fa capire subito che il resto e' sospeso.
    if numero(d["con_isdc"]) is None:
        out.append(Paragraph(
            "L'Osservatorio misura la sovranità digitale degli enti pubblici "
            "e a partecipazione pubblica. Nel file caricato il numero degli "
            "enti con un indice calcolato non è disponibile, quindi le "
            "sezioni che seguono non descrivono un campione reale.",
            stili["corpo"],
        ))
    else:
        # La seconda frase si costruisce dalle sole estremita' presenti.
        # Un'estremita' assente viene taciuta invece di essere riempita
        # con 'n.d.': altrimenti il testo annuncerebbe un massimo o un
        # minimo che non e' mai stato calcolato.
        media = numero(d["isdc_avg"])
        massimo = numero(d["isdc_max"])
        minimo = numero(d["isdc_min"])

        if media is None and massimo is None and minimo is None:
            frase = "I valori dell'indice non sono disponibili."
        else:
            # Il soggetto della frase dipende da cosa manca: 'la media'
            # se l'indice medio c'e', 'l'indice' altrimenti.
            soggetto = "L'indice medio" if media is not None else "L'indice"
            if media is not None:
                frase = f"{soggetto} è <b>{fmt_num(media, 2)}</b>"
            else:
                frase = soggetto

            # Con la media assente il soggetto non ha un verbo:
            # 'L'indice medio e' 64,0' regge, 'L'indice' da solo no.
            # Si predica quindi l'esistenza dell'estremita' ('ha').
            if media is not None:
                # La media ha gia' il suo verbo: l'estremita' si
                # introduce con una virgola, non con 'ha'.
                if massimo is not None and minimo is not None:
                    frase += (
                        f", con valori che vanno da un minimo di "
                        f"{fmt_num(minimo, 2)} a un massimo di "
                        f"{fmt_num(massimo, 2)}"
                    )
                elif massimo is not None:
                    frase += f", con un valore massimo di {fmt_num(massimo, 2)}"
                elif minimo is not None:
                    frase += f", con un valore minimo di {fmt_num(minimo, 2)}"
            else:
                if massimo is not None and minimo is not None:
                    frase += (
                        f" ha valori che vanno da un minimo di "
                        f"{fmt_num(minimo, 2)} a un massimo di "
                        f"{fmt_num(massimo, 2)}"
                    )
                elif massimo is not None:
                    frase += f" ha un valore massimo di {fmt_num(massimo, 2)}"
                elif minimo is not None:
                    frase += f" ha un valore minimo di {fmt_num(minimo, 2)}"
            frase += "."

        out.append(Paragraph(
            f"L'Osservatorio misura la sovranità digitale di "
            f"<b>{fmt_intero(d['con_isdc'])}</b> enti pubblici e a "
            f"partecipazione pubblica, sui quali è stato possibile "
            f"ricostruire l'infrastruttura DNS e calcolare l'indice di "
            f"sovranità. {frase}",
            stili["corpo"],
        ))

    if d["sovrana"] is not None and d["con_isdc"]:
        out.append(Paragraph(
            f"La lettura aggregata è rassicurante: <b>{fmt_intero(d['sovrana'])}</b> "
            f"enti, pari al {quota(d['sovrana'], d['con_isdc'])}, si collocano nella "
            f"fascia di infrastruttura sovrana. Il rischio è concentrato in una "
            f"minoranza, non distribuito: gli enti nella fascia più fragile sono "
            f"{fmt_intero(d['fragile'])}, {quota(d['fragile'], d['con_isdc'])}. "
            f"Una politica di sostegno mirata su quella fascia avrebbe un costo "
            f"molto inferiore a un intervento generale.",
            stili["corpo"],
        ))

    if d["hyper_pct"] is not None:
        out.append(Paragraph(
            f"Il punto debole è la dipendenza dai grandi provider: "
            f"<b>{fmt_num(d['hyper_pct'], 2)}%</b> degli enti analizzati usa "
            f"almeno un servizio di Amazon, Google o Microsoft. È un dato "
            f"che nessun indicatore di lock-in sui ASN mostra, perché riguarda "
            f"i servizi ospitati e non il routing.",
            stili["corpo"],
        ))

    if d["hhi"] is not None and d["asn_effettivi"] is not None:
        out.append(Paragraph(
            f"La concentrazione degli ASN, misurata con l'indice di Herfindahl "
            f"normalizzato, è <b>{fmt_num(d['hhi'], 4)}</b>: {etichetta_hhi(d['hhi'])}. "
            f"Tradotto in numero effettivo di provider, l'insieme equivale a circa "
            f"<b>{fmt_num(d['asn_effettivi'], 1)}</b> provider di pari dimensione. "
            f"È un indice basso, e su questo punto il report non segnala "
            f"concentrazione.",
            stili["corpo"],
        ))

    if d["asn_quota"] is not None:
        out.append(Paragraph(
            f"Quella lettura richiede però una precisazione, perché è il punto in "
            f"cui un indice aggregato può ingannare: un singolo provider copre il "
            f"<b>{fmt_num(d['asn_quota'], 2)}%</b> degli enti. Un HHI basso con un "
            f"provider a quasi metà del campione non significa mercato equo, "
            f"significa un leader e una coda lunga di provider minori. È la "
            f"distinzione fra <i>concentrazione complessiva</i> e "
            f"<i>concentrazione del primo attore</i>, e per un ente che deve "
            f"valutare una migrazione la seconda è quella che conta.",
            stili["corpo"],
        ))

    if grigi_dati(d):
        out.append(Spacer(1, 0.2 * cm))
        out.append(Paragraph(
            "Avvertenza: " + " ".join(grigi_dati(d)),
            stili["citazione"],
        ))

    return out


def sezione_perimetro(d, stili):
    """Il campione e il censimento non sono la stessa cosa"""
    out = [Paragraph("Il perimetro di osservazione", stili["sottotitolo"])]

    if d["censimento"] is None:
        out.append(Paragraph(
            "Il censimento degli enti non è disponibile in stat.json.",
            stili["corpo"],
        ))
        return out

    if d["con_isdc"] is None:
        out.append(Paragraph(
            f"L'anagrafica censisce <b>{fmt_intero(d['censimento'])}</b> enti.",
            stili["corpo"],
        ))
        return out

    out.append(Paragraph(
        f"L'anagrafica censisce <b>{fmt_intero(d['censimento'])}</b> enti, ma "
        f"solo <b>{fmt_intero(d['con_isdc'])}</b> hanno un indice di sovranità "
        f"calcolato, ossia il <b>{quota(d['con_isdc'], d['censimento'], 1)}</b> "
        f"del censimento. Tutte le percentuali di questo report si riferiscono a "
        f"questo campione, non alla popolazione: sono elaborazioni di un "
        f"quinto degli enti censiti.",
        stili["corpo"],
    ))

    if d["con_isdc"] < d["censimento"]:
        out.append(Paragraph(
            "Il motivo è tecnico e va detto con chiarezza, perché un campione "
            "parziale introduce un bias di selezione che nessuna tablica può "
            "correggere: l'indice richiede dati DNS e un indirizzo risolvibile "
            "all'indirizzo IP, quindi gli enti senza record di name server non "
            "entrano. Se l'assenza di dati DNS è correlata a tipologie di ente "
            "particolari, le quote osservate non sono estendibili al censimento "
            "come se lo fossero.",
            stili["corpo"],
        ))

    voci = [
        ("Enti censiti", d["censimento"], d["censimento"]),
        ("Enti con indice calcolato", d["con_isdc"], d["censimento"]),
    ]
    if d["datacenter"] is not None:
        voci.append(("Datacenter censiti", d["datacenter"], d["censimento"]))

    out.append(tabella_perimetro(voci, stili))
    out.append(didascalia(
        "Il campione effettivo è sensibilmente più piccolo del censimento: "
        "è la prima cosa da tenere a mente leggendo le sezioni seguenti.",
        stili,
    ))

    # composizione tipologica, se le card ci sono
    s_base = d["sezioni"].get("base_dati", {})
    # Solo le card che descrivono una Tipologia dell'anagrafica. Il
    # prefisso 'enti_' non basta: anche enti_con_isdc inizia con
    # 'enti_' ma non e' una tipologia, e sommarla agli altri totali
    # avrebbe fatto eccedere la somma oltre il censimento.
    tipi = [
        c for c in s_base.get("cards", [])
        if c.get("id", "").startswith("enti_")
        and c.get("id") != "enti_con_isdc"
    ]
    if tipi:
        out.append(Paragraph(
            "La composizione del censimento", stili["sottosezione"],
        ))
        somma_tipi = sum(numero(c.get("value"), 0) or 0 for c in tipi)
        out.append(Paragraph(
            f"Il censimento è dominato dalle {_max_tipologia(tipi)}, che da sole "
            f"rappresentano {quota(_valore_max(tipi), d['censimento'])} degli enti. "
            f"Le categorie sono lette dalla colonna <i>Tipologia</i> "
            f"dell'anagrafica e generate dinamicamente: se in futuro compare una "
            f"nuova tipologia, compare anche la sua quota. Sommano a "
            f"{fmt_intero(somma_tipi)} enti"
            + (
                f", pari al censimento."
                if d["censimento"]
                and abs(somma_tipi - d["censimento"]) < 0.5
                else f", su {fmt_intero(d['censimento'])} censiti: "
                     f"la differenza indica tipologie non classificate."
            ),
            stili["corpo"],
        ))

    return out


def _valore_max(tipi):
    valori = [numero(c.get("value"), 0) or 0 for c in tipi]
    return max(valori) if valori else None


def _max_tipologia(tipi):
    if not tipi:
        return "enti"
    migliore = max(tipi, key=lambda c: numero(c.get("value"), 0) or 0)
    return migliore.get("title", "enti").lower()


def sezione_isdc(d, stili):
    """Distribuzione dell'indice, letta come forma e non come media"""
    out = [Paragraph("La forma della distribuzione", stili["sottotitolo"])]

    if not d["bands"]:
        out.append(Paragraph(
            "Le fasce di distribuzione non sono disponibili in stat.json.",
            stili["corpo"],
        ))
        return out

    # Se la media non e' disponibile la frase che la confronta con la
    # forma della distribuzione non regge: dire "il valore medio di
    # n.d." presenta un'assenza come se fosse una misura. Si tiene
    # l'argomento della media, che resta valido, senza il dato.
    if numero(d["isdc_avg"]) is None:
        out.append(Paragraph(
            "Una media dice poco su una distribuzione: e' compatibile sia con "
            "una massa compatta di enti medio-sovrani sia con due gruppi "
            "equi, uno fragile e uno solido. Le fasce distinguono i due casi.",
            stili["corpo"],
        ))
    else:
        out.append(Paragraph(
            "Una media dice poco su una distribuzione: il valore medio di "
            f"{fmt_num(d['isdc_avg'], 2)} e' compatibile sia con una massa "
            f"compatta di enti medio-sovrani sia con due gruppi equi, uno "
            f"fragile e uno solido. Le fasce distinguono i due casi.",
            stili["corpo"],
        ))

    ordinate = sorted(
        d["bands"],
        key=lambda b: numero(b.get("count"), 0) or 0,
        reverse=True,
    )
    maggiore = ordinate[0] if ordinate else None
    minore = ordinate[-1] if len(ordinate) > 1 else None

    if maggiore and minore and maggiore is not minore:
        out.append(Paragraph(
            f"La fascia più popolata è <b>{maggiore.get('band', '?').lower()}</b> "
            f"con {fmt_intero(maggiore.get('count'))} enti "
            f"({fmt_num(numero(maggiore.get('pct'), 0), 2)}%), mentre la fascia "
            f"opposta conta {fmt_intero(minore.get('count'))} enti "
            f"({fmt_num(numero(minore.get('pct'), 0), 2)}%). La sproporzione "
            f"tra le due è di circa "
            f"{fmt_num((numero(maggiore.get('count'), 0) or 0) / (numero(minore.get('count'), 1) or 1), 1)} "
            f"a uno: il quadro complessivo è solido, e il rischio è concentrato.",
            stili["corpo"],
        ))

    out.append(tabella_bands(d["bands"], stili, d["con_isdc"]))
    out.append(didascalia(
        "Le percentuali sono calcolate da StatJson.py sul numero di enti con "
        "ISDC, non sul censimento: il totale in fondo è quindi la base reale "
        "delle quote.",
        stili,
    ))

    if d["sovrana"] is not None and d["fragile"] is not None:
        out.append(Paragraph(
            f"Il dato più utile per una scelta operativa è la coppia "
            f"{fmt_intero(d['sovrana'])} contro {fmt_intero(d['fragile'])}: gli "
            f"enti ad alta sovranità sono {fmt_num((numero(d['sovrana'], 0) or 0) / (numero(d['fragile'], 1) or 1), 1)} "
            f"quanti quelli fragili. Un intervento di rafforzamento non deve "
            f"quindi ripartire equamente, ma seguire la coda fragile, che è "
            f"minoritaria e misurabile.",
            stili["corpo"],
        ))

    return out


def sezione_lockin(d, stili):
    """Lock-in: lettura per categorie, non per media"""
    out = [Paragraph("Concentrazione del routing", stili["sottotitolo"])]

    if d["lock_totale"] is None:
        out.append(Paragraph(
            "Le categorie di lock-in non sono disponibili in stat.json.",
            stili["corpo"],
        ))
        return out

    out.append(Paragraph(
        f"Il lock-in viene misurato confrontando i numeri AS che un ente espone "
        f"sulle tre dimensioni DNS. Se coincidono, l'ente dipende da un unico "
        f"soggetto per posta, risoluzione e alias. La misura è netta: "
        f"<b>{fmt_intero(d['lock_alto'])}</b> enti "
        f"({quota(d['lock_alto'], d['lock_totale'])}) hanno lo stesso ASN su tutte "
        f"e tre le dimensioni.",
        stili["corpo"],
    ))

    if d["lock_parziale"] is not None and d["lock_distribuito"] is not None:
        out.append(Paragraph(
            f"Una parte ampia, <b>{fmt_intero(d['lock_parziale'])}</b> enti "
            f"({quota(d['lock_parziale'], d['lock_totale'])}), ha invece almeno "
            f"due ASN coincidenti: la dipendenza è parziale ma reale. Solo "
            f"<b>{fmt_intero(d['lock_distribuito'])}</b> enti "
            f"({quota(d['lock_distribuito'], d['lock_totale'])}) espongono ASN "
            f"diversi sulle tre dimensioni, e costituiscono l'unico gruppo "
            f"davvero ridondante dal punto di vista del routing.",
            stili["corpo"],
        ))

    if d["lock_nc"]:
        out.append(Paragraph(
            f"A parte i {fmt_intero(d['lock_nc'])} enti "
            f"({quota(d['lock_nc'], d['lock_totale'])}) per cui la misura non è "
            f"determinabile perché manca l'ASN su una dimensione: sono un gruppo "
            f"trascurabile in termini di peso, ma la loro esistenza segnala che "
            f"la copertura dei dati ASN non è completa e che le quote "
            f"sopra sono sottostimate di poco.",
            stili["corpo"],
        ))

    if d["lock_coerente"]:
        out.append(Paragraph(
            "Il punto da non confondere: una distribuzione ASN diversificata "
            "non implica ridondanza dei servizi. Un ente può avere tre ASN "
            "distinti e dipendere comunque da un unico cloud provider per "
            "ospitare i servizi. Il lock-in da routing e quello da servizio "
            "sono misure diverse, e il secondo emerge dalla sezione sul cloud.",
            stili["corpo"],
        ))

    return out


def sezione_asn(d, stili):
    """Concentrazione ASN, con la distinzione fra indice e primo attore"""
    out = [Paragraph("Chi ospita il traffico", stili["sottotitolo"])]

    if d["asn_unici"] is None:
        out.append(Paragraph(
            "I dati sulla concentrazione ASN non sono disponibili in stat.json.",
            stili["corpo"],
        ))
        return out

    out.append(Paragraph(
        f"Il campione si appoggia a <b>{fmt_intero(d['asn_unici'])}</b> numeri AS "
        f"distinti. La varietà di provider è quindi ampia: un ente medio non "
        f"dipende da un numero limitato di operatori.",
        stili["corpo"],
    ))

    if d["asn_top"]:
        out.append(Paragraph(
            "I provider con maggiore presenza sono:", stili["corpo"],
        ))
        for nome, n in d["asn_top"]:
            if n is None:
                out.append(Paragraph(f"&bull;&nbsp; {nome}", stili["voce"]))
                continue
            out.append(Paragraph(
                f"&bull;&nbsp; <b>{nome}</b> &mdash; {fmt_intero(n)} enti, "
                f"{quota(n, d['con_isdc'])} del campione",
                stili["voce"],
            ))
        out.append(Spacer(1, 0.2 * cm))

    if d["asn_top_somma"] is not None and d["con_isdc"]:
        somma = d["asn_top_somma"]
        if somma > d["con_isdc"]:
            out.append(Paragraph(
                f"Qui c'è un dettaglio che spiega la differenza fra gli indici. "
                f"I primi cinque provider contano complessivamente "
                f"{fmt_intero(somma)} presenze, più dei {fmt_intero(d['con_isdc'])} "
                f"enti del campione: gli stessi enti compaiono su più di un ASN. "
                f"Non sono quindi cinque gruppi disgiunti, e la somma non va letta "
                f"come una quota di mercato.",
                stili["corpo"],
            ))

    if d["hhi"] is not None and d["asn_quota"] is not None:
        out.append(Paragraph(
            f"Mettendo insieme i due indicatori si ottiene il quadro più utile. "
            f"L'Herfindahl normalizzato è {fmt_num(d['hhi'], 4)} "
            f"({etichetta_hhi(d['hhi'])}) e l'equivalente in provider di pari "
            f"dimensione è circa {fmt_num(d['asn_effettivi'], 1)}, eppure il "
            f"primo ASN copre il {fmt_num(d['asn_quota'], 2)}% degli enti. "
            f"L'indice aggregato è basso perché la coda di provider piccoli "
            f"diluisce il peso del leader: la struttura è quella di un mercato con "
            f"un incumbent di rilievo e molti operatori piccoli. Per chi pianifica "
            f"una migrazione la domanda utile non è 'il mercato è concentrato', ma "
            f"'il mio ASN è quello del leader'.",
            stili["corpo"],
        ))

    return out


def sezione_cloud(d, stili):
    """Cloud e resilienza: due segnali che non coincidono"""
    out = [Paragraph("Il nodo che nessun altro indicatore vede", stili["sottotitolo"])]

    if d["hyper_pct"] is not None:
        out.append(Paragraph(
            f"<b>{fmt_num(d['hyper_pct'], 2)}%</b> degli enti analizzati fa uso "
            f"di almeno un servizio di Amazon, Google o Microsoft. In termini "
            f"assoluti sono {fmt_intero(d['hyper_si'])} enti.",
            stili["corpo"],
        ))

    if d["hyper_pct"] is not None and d["lock_alto"] is not None and d["con_isdc"]:
        out.append(Paragraph(
            f"Il confronto con i lock-in da routing è la parte interessante. "
            f"Gli enti con lo stesso ASN su tutte le dimensioni sono "
            f"{fmt_intero(d['lock_alto'])} ({quota(d['lock_alto'], d['con_isdc'])}), "
            f"mentre quelli su hyperscaler sono {fmt_intero(d['hyper_si'])} "
            f"({quota(d['hyper_si'], d['con_isdc'])}): la dipendenza dai grandi "
            f"cloud riguarda circa il doppio degli enti che presentano lock-in "
            f"di routing. Chi misurasse la sovranità digitale solo sul DNS "
            f"vedrebbe un quadro in parte migliore di quanto sia.",
            stili["corpo"],
        ))

    if d["dns_frammentato"] is not None and d["con_isdc"]:
        out.append(Paragraph(
            f"Una lettura corretta richiede però di non confondere i due piani. "
            f"Gli enti con ASN distinti sulle tre dimensioni sono "
            f"{fmt_intero(d['dns_frammentato'])}, e quelli con DNS centralizzato "
            f"{fmt_intero(d['dns_equal'])}. La frammentazione del routing è una "
            f"buona notizia sul piano della resilienza: un guasto a un singolo "
            f"provider non si propaga a tutte le funzioni DNS dell'ente. Non "
            f"dice però nulla sulla dipendenza dai servizi ospitati, che è "
            f"misurata a parte.",
            stili["corpo"],
        ))

    if d["lets_encrypt"] is not None and d["con_isdc"]:
        out.append(Paragraph(
            f"Infine, <b>{fmt_intero(d['lets_encrypt'])}</b> enti "
            f"({quota(d['lets_encrypt'], d['con_isdc'])}) usano certificati "
            f"automatici Let's Encrypt. Il dato va letto con una precisazione: "
            f"l'adozione di un'autorità gratuita e automatizzata è un indicatore "
            f"di igiene operativa e di riduzione del costo, non di sovranità. Un "
            f"certificato emesso da un'autorità occidentale resta soggetto al suo "
            f"rilascio. Se letto come indicatore di indipendenza, suggerirebbe una "
            f"sovranità che il dato non dimostra.",
            stili["corpo"],
        ))

    return out


def sezione_limiti(d, stili):
    """Che cosa questo report non dimostra"""
    out = [Paragraph("I limiti di questa lettura", stili["sottotitolo"])]

    punti = []

    if d["censimento"] and d["con_isdc"]:
        punti.append(
            f"Il campione copre il {quota(d['con_isdc'], d['censimento'])} del "
            f"censimento, e la selezione dipende dalla disponibilità di dati "
            f"DNS e di un indirizzo risolvibile. Le quote non sono estendibili "
            f"alla popolazione senza una verifica sulla distribuzione delle "
            f"enti esclusi."
        )

    if d["record_mx"] and d["con_isdc"] and d["record_mx"] > d["con_isdc"]:
        punti.append(
            f"I dati DNS raccolti sono a una cifra tonda "
            f"({fmt_intero(d['record_mx'])} record MX, "
            f"{fmt_intero(d['record_ns'])} NS, {fmt_intero(d['record_cname'])} "
            f"CNAME): è il segnale di una coda di raccolta fermata a un limite "
            f"di sessione, non di una copertura completa. Va verificato prima "
            f"di trattare questi conteggi come popolazione."
        )

    punti.append(
        "Nessun KPI di questo report è incrociato con la dimensione economica "
        "o con la spesa ICT: gli indicatori di procurement sono stati rimossi "
        "da stat.json perché derivavano da una fonte non allineata alla "
        "pipeline. Il report ne risente e non tenta di sostituirli."
    )

    punti.append(
        "Gli indici di lock-in e di concentrazione misurano l'infrastruttura "
        "esposta, non i contratti in essere: un ente con ASN diversificati può "
        "avere impegni contrattuali con un singolo fornitore, e viceversa."
    )

    punti.append(
        "Le misure sono diacroniche ma puntuali: descrivono lo stato al giorno "
        "del dataset e non registrano variazioni nel tempo. Senza una serie "
        "storica non è possibile distinguere un miglioramento da un miglioramento "
        "apparente dovuto a un cambio nella copertura della raccolta."
    )

    for p in punti:
        out.append(Paragraph(f"&bull;&nbsp; {p}", stili["voce"]))

    out.append(Spacer(1, 0.2 * cm))
    out.append(Paragraph(
        "Nessuno di questi limiti invalida i numeri: ne circoscrive l'uso. Un "
        "indicatore con un denominatore esplicito e una base di calcolo nota è "
        "utilizzabile anche se copre un sottoinsieme, purché lo si citi con il "
        "suo denominatore.",
        stili["corpo"],
    ))

    return out


def appendice(d, stili):
    """Quadro completo dei KPI, per chi deve verificare le cifre"""
    out = [Paragraph("Appendice: quadro completo dei KPI", stili["sottotitolo"])]

    out.append(Paragraph(
        "Le sezioni del documento interpretano questi valori. La tabella li "
        "raccoglie per intero, nello stesso ordine di stat.json, così da poter "
        "verificare ogni cifra citata nel testo.",
        stili["piccolo"],
    ))

    for sez_id, sez in d["sezioni"].items():
        cards = sez.get("cards", [])
        if not cards:
            continue
        out.append(KeepTogether([
            Paragraph(sez.get("title", sez_id), stili["sottosezione"]),
            tabella_kpi(cards, stili),
            Spacer(1, 0.4 * cm),
        ]))

    if d["bands"]:
        out.append(Paragraph("Fasce di dipendenza", stili["sottosezione"]))
        out.append(tabella_bands(d["bands"], stili, d["con_isdc"]))

    return out


def _footer(canvas, doc):
    """Numero di pagina e riferimento in fondo a ogni pagina"""
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(HexColor("#666666"))
    canvas.drawString(1.8 * cm, 1.2 * cm, "Osservatorio Sovranità Digitale")
    canvas.drawRightString(A4[0] - 1.8 * cm, 1.2 * cm, f"pag. {doc.page}")
    canvas.restoreState()


def create_pdf(data):
    """Crea il PDF dal contenuto"""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(PDF_PATH),
        pagesize=A4,
        leftMargin=1.8 * cm,
        rightMargin=1.8 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title="Report Osservatorio Sovranità Digitale",
        author="Osservatorio Sovranità Digitale",
        subject=(
            f"Report generato il "
            f"{data.get('generated_at', '').split('T')[0]}"
        ),
    )

    content = build_content(data)
    doc.build(content, onFirstPage=_footer, onLaterPages=_footer)

    log.info(f"Creato {PDF_PATH} ({PDF_PATH.stat().st_size / 1024:.1f} KB)")


def main():
    rc = 0
    try:
        log.info("Legge dataset dal filesystem")
        data = load_json()
        log.info("Generazione contenuto PDF")
        create_pdf(data)
        log.info(f"Report completato: {PDF_PATH}")

    except FileNotFoundError as e:
        log.error(f"{e}")
        log.error("Genera prima lo stat.json con 07 - StatsJson/StatJson.py")
        rc = 1

    except DatiNonValidi as e:
        log.error(f"Dati non validi: {e}")
        log.error(
            "stat.json e' stato prodotto da una versione diversa di "
            "StatJson.py: rigenerarlo"
        )
        rc = 1

    except Exception as e:
        log.exception(f"Errore durante la generazione: {e}")
        rc = 1

    return rc


if __name__ == "__main__":
    sys.exit(main())
