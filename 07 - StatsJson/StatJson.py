import sys
import sqlite3
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common

# ============================================
# CONFIG
# ============================================
#
# Il dataset di partenza e' enti_contatti, non piu' la
# tabella dei comuni: ogni riferimento a "comuni" qui
# sotto e' un residuo della versione precedente.
#
# Le query NON filtrano le coordinate: le statistiche
# descrivono gli enti, georeferenziati o no. Il filtro
# lat/lon vive solo in Generate_geojson.py, perche' un
# punto senza posizione non e' disegnabile ma l'ente
# esiste e ha un'infrastruttura reale.

DB_PATH = common.db_path()
OUTPUT_JSON = common.frontend_file("stat.json")
HISTORY_JSON = common.frontend_file("change_history.json")

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


class FonteNonDisponibile(Exception):
    """
    Una tabella che lo script considera obbligatoria non
    esiste o non e' interrogabile.

    Non viene silenziata: restituire 0 per una tabella
    rinominata o caduta fa scrivere un JSON con KPI
    apparentemente validi e tutti a zero, che nessuno
    nota fino a quando un grafico risulta vuoto.
    """


# ============================================
# TRACCE
# ============================================
#
# stat.json viene letto da pagine che non segnalano nulla
# quando un KPI manca o vale zero: un grafico vuoto e' un
# sintomo, la causa e' un'intestazione di tabella cambiata
# due mesi prima. Per questo ogni query lascia traccia del
# valore ottenuto e a fine run i controlli di coerenza
# dicono esplicitamente se i numeri tornano.
#
# Il conteggio delle query serve a notare un KPI sparito
# dal JSON: se le query sono le stesse ma le card sono
# meno, qualcosa e' stato tolto.

_query_n = 0


def traccia_query(label, valore, ms):
    global _query_n
    _query_n += 1
    logging.info(f"  [{_query_n:02d}] {label:<28} = {valore}  ({ms:.0f} ms)")


def traccia(msg):
    logging.info(msg)


def controllo(descrizione, esito, dettaglio=""):
    """
    Un controllo di coerenza fra KPI.

    Non solleva: il JSON e' comunque utile anche con un
    controllo rosso, e bloccarlo nasconderebbe gli altri
    problemi. Il rosso resta pero' nel log e nel codice di
    uscita, cosi' la pipeline non continua in silenzio.
    """

    if esito:
        logging.info(f"  OK   {descrizione}")
    else:
        logging.error(f"  KO   {descrizione}{' -> ' + dettaglio if dettaglio else ''}")

    return esito


# ============================================
# SAFE HELPERS
# ============================================

def safe_fetch_one(cursor, query, label="query"):
    try:
        cursor.execute(query)
        row = cursor.fetchone()
        return row if row else (0,)
    except sqlite3.Error as e:
        logging.error(f"{label}: {e}")
        return (0,)


def safe_fetch_all(cursor, query, label="query"):
    try:
        cursor.execute(query)
        return cursor.fetchall()
    except sqlite3.Error as e:
        logging.error(f"{label}: {e}")
        return []


def fetch_one_required(cursor, query, label="query", params=()):
    """
    Come safe_fetch_one, ma su errore si ferma.

    Usata per le query la cui risposta e' il KPI stesso:
    se falliscono, il valore non e' 0, e' ignoto, e va
    detto subito.
    """

    t0 = time.perf_counter()

    try:
        cursor.execute(query, params)
        row = cursor.fetchone()

    except sqlite3.Error as e:

        traccia_query(label, "ERRORE", (time.perf_counter() - t0) * 1000)

        logging.error(f"{label}: {e}")

        raise FonteNonDisponibile(f"{label}: {e}")

    risultato = row if row else (0,)

    traccia_query(label, risultato, (time.perf_counter() - t0) * 1000)

    return risultato


def fetch_all_required(cursor, query, label="query", params=()):
    """
    Come fetch_one_required, per le query che restituiscono
    piu' righe.
    """

    t0 = time.perf_counter()

    try:
        cursor.execute(query, params)
        rows = cursor.fetchall()

    except sqlite3.Error as e:

        traccia_query(label, "ERRORE", (time.perf_counter() - t0) * 1000)

        logging.error(f"{label}: {e}")

        raise FonteNonDisponibile(f"{label}: {e}")

    traccia_query(label, f"{len(rows)} righe", (time.perf_counter() - t0) * 1000)

    return rows


def round_safe(value, digits=2):
    try:
        return round(float(value), digits) if value is not None else 0
    except:
        return 0


def pct(n, tot):
    """
    Quota percentuale di n sul totale, a 2 decimali.

    Il denominatore e' sempre il totale della vista POI della
    dimensione (POI_MX, POI_NS, POI_CNAME), cosi' le tre
    sezioni MX/NS/CNAME si possono confrontare fra loro.
    """

    return round_safe(n * 100.0 / tot, 2) if tot else 0


# ============================================
# HELPERS LISTE
# ============================================

def build_asn_list(rows):
    if not rows:
        return ""
    return "|".join([f"{r[1]} ({r[2]})" for r in rows])


def build_categoria_list(rows):
    """
    Lista "Nome (count)" delle categorie IPA di ente.

    Stesso formato di build_asn_list, cosi' il frontend la
    rende con la stessa tabella (nome + conteggio + quota).
    Il separatore '|' non compare nei nomi (verificato in fase
    di costruzione della vista).
    """

    if not rows:
        return ""

    return "|".join([
        f"{(nome or 'Non classificati')} ({n})"
        for nome, n in rows
    ])


def slug(text):
    """
    Identificatore stabile per un valore di Tipologia.

    Il frontend indicizza i KPI per id, quindi l'id non
    puo' contenere spazi, accenti o apostrofi.
    """

    s = str(text).strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_") or "non_classificato"


# ============================================
# MAIN
# ============================================

def build_json():

    t_start = time.perf_counter()

    ko = 0

    traccia("")
    traccia("=" * 72)
    traccia("STATJSON - generazione delle statistiche")
    traccia("=" * 72)
    traccia(f"Database : {DB_PATH}")
    traccia(f"Output   : {OUTPUT_JSON}")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    traccia("")
    traccia("Interrogazione del database")
    traccia("-" * 72)

    # ============================================
    # BASE DATA
    # ============================================
    #
    # Il denominatore di tutto il resto: gli enti
    # censiti. Entita' e non comuni: piu' enti possono
    # stare nello stesso comune, quindi contare i comuni
    # sottostima il perimetro reale (su 4251 enti con
    # ISDC, solo 995 hanno un codice ISTAT).

    total_enti = fetch_one_required(
        cur,
        "SELECT COUNT(*) FROM enti_contatti",
        "enti censiti"
    )[0]

    enti_con_isdc = fetch_one_required(
        cur,
        "SELECT COUNT(DISTINCT codice_IPA) FROM POI_ISDC",
        "enti con ISDC"
    )[0]

    # I conteggi arrivano dalle viste POI_*, non dalle tabelle
    # enti_ns / enti_mx / enti_cname: le viste sono il
    # perimetro effettivo delle mappe (record con provider e
    # posizione risolti) e portano con se asn_organization,
    # country_name, continent e cluster_registered_country,
    # che sono le colonne su cui si costruiscono i KPI
    # MX / NS / CNAME della sezione successiva.
    #
    # Su 22.890 record di base POI_MX ne conta 20.922 e
    # POI_CNAME 21.870: la differenza sono gli enti per cui
    # l'indirizzo IP non e' ancora mappabile a un provider.

    total_ns = fetch_one_required(
        cur,
        "SELECT COUNT(*) FROM POI_NS",
        "record NS"
    )[0]

    total_mx = fetch_one_required(
        cur,
        "SELECT COUNT(*) FROM POI_MX",
        "record MX"
    )[0]

    total_cname = fetch_one_required(
        cur,
        "SELECT COUNT(*) FROM POI_CNAME",
        "record CNAME"
    )[0]

    total_datacenter = fetch_one_required(
        cur,
        "SELECT COUNT(*) FROM datacenter",
        "datacenter censiti"
    )[0]

    # ============================================
    # TIPOLOGIE
    # ============================================
    #
    # Una card per ogni cluster di Tipologia, letta dal
    # database invece che scritta a mano: se in futuro
    # compare una tipologia nuova, la card compare da
    # sola e nessuno deve ricordarsi di aggiornarla.
    #
    # TRIM serve perche' in entrata ci sono valori con
    # spazi finali, che altrimenti diventerebbero due
    # cluster distinti con lo stesso nome.

    tipologie = fetch_all_required(
        cur,
        """
            SELECT TRIM(Tipologia), COUNT(*)
            FROM enti_contatti
            GROUP BY TRIM(Tipologia)
            ORDER BY COUNT(*) DESC, TRIM(Tipologia)
        """,
        "tipologie di ente"
    )

    # ============================================
    # CATEGORIE DI ENTE (IPA)
    # ============================================
    #
    # Classificazione piu' fine della Tipologia: la categoria
    # IPA dell'ente (enti_categorie.Nome_categoria), agganciata
    # via enti_contatti.Codice_Categoria. Stessa struttura della
    # Tipologia (dipendente dai dati, non scritta a mano), ma con
    # ~53 valori: troppi per una griglia di card, quindi il
    # frontend la mostra come tabella ranking in una sezione
    # dedicata. La somma dei conteggi e' total_enti: e' il
    # denominatore delle quote.

    categorie = fetch_all_required(
        cur,
        """
            SELECT TRIM(c.Nome_categoria), COUNT(*)
            FROM enti_contatti e
            LEFT JOIN enti_categorie c
                ON c.Codice_categoria = e.Codice_Categoria
            GROUP BY TRIM(c.Nome_categoria)
            ORDER BY COUNT(*) DESC, TRIM(c.Nome_categoria)
        """,
        "categorie di ente"
    )

    # ============================================
    # LOCK-IN
    # ============================================
    #
    # Le tre categorie sono mutuamente esclusive, ma non
    # coprono tutti gli enti: 107 enti hanno un ASN NULL
    # su una delle tre dimensioni (il CNAME non e' ancora
    # stato risolto). Con '=' e '!=' quelle righe non
    # soddisfano nessuna delle tre condizioni e sparirebbero
    # dai grafici: sommano infatti a 4144 su 4251.
    #
    # Non si usa 'IS' / 'IS NOT' per chiuderle dentro,
    # perche' dire "distribuzione completa" quando il
    # terzo ASN e' sconosciuto sarebbe un'affermazione
    # non verificata. Vengono invece contate a parte.

    lockin_high = fetch_one_required(cur, """
        SELECT COUNT(*) FROM POI_ISDC
        WHERE ASN_mx = ASN_ns AND ASN_ns = ASN_cname
    """, "lock-in alto")[0]

    lockin_partial = fetch_one_required(cur, """
        SELECT COUNT(*) FROM POI_ISDC
        WHERE (ASN_mx = ASN_ns OR ASN_ns = ASN_cname OR ASN_mx = ASN_cname)
        AND NOT (ASN_mx = ASN_ns AND ASN_ns = ASN_cname)
    """, "lock-in parziale")[0]

    distributed_count = fetch_one_required(cur, """
        SELECT COUNT(*) FROM POI_ISDC
        WHERE ASN_mx != ASN_ns
          AND ASN_ns != ASN_cname
          AND ASN_mx != ASN_cname
    """, "distribuzione completa")[0]

    lockin_unknown = fetch_one_required(cur, """
        SELECT COUNT(*) FROM POI_ISDC
        WHERE ASN_mx IS NULL OR ASN_ns IS NULL OR ASN_cname IS NULL
    """, "lock-in non determinabile")[0]

    if lockin_high + lockin_partial + distributed_count + lockin_unknown != enti_con_isdc:
        logging.error(
            "Le categorie di lock-in non coprono tutti gli enti "
            "valutati: controllare i NULL sugli ASN"
        )
    else:
        traccia(
            f"  ->  lock-in: {lockin_high} alto + {lockin_partial} parziale + "
            f"{distributed_count} distribuito + {lockin_unknown} non "
            f"determinabile = {enti_con_isdc} enti valutati"
        )

    # ============================================
    # ASN
    # ============================================
    #
    # Tutte le metriche di concentrazione contano gli
    # ENTI (codice_IPA), non i comuni: il dataset e' di
    # enti e 3256 enti su 4251 non hanno codice ISTAT,
    # quindi aggregare per comune azzererebbe quasi tutto.

    asn_slots = fetch_one_required(cur, """
        SELECT COUNT(*) FROM (
            SELECT ASN_mx as asn FROM POI_ISDC WHERE ASN_mx IS NOT NULL
            UNION ALL
            SELECT ASN_ns FROM POI_ISDC WHERE ASN_ns IS NOT NULL
            UNION ALL
            SELECT ASN_cname FROM POI_ISDC WHERE ASN_cname IS NOT NULL
        )
    """, "slot ASN")[0]

    unique_asn = fetch_one_required(cur, """
        SELECT COUNT(DISTINCT asn) FROM (
            SELECT ASN_mx as asn FROM POI_ISDC WHERE ASN_mx IS NOT NULL
            UNION
            SELECT ASN_ns FROM POI_ISDC WHERE ASN_ns IS NOT NULL
            UNION
            SELECT ASN_cname FROM POI_ISDC WHERE ASN_cname IS NOT NULL
        )
    """, "ASN unici")[0]

    # Quota del primo ASN: enti che lo usano su almeno
    # una delle tre dimensioni, sugli enti con ASN noto.
    top_asn_share = fetch_one_required(cur, f"""
        SELECT MAX(cnt) * 100.0 / {enti_con_isdc}
        FROM (
            SELECT asn, COUNT(DISTINCT codice_IPA) cnt
            FROM (
                SELECT codice_IPA, ASN_mx as asn FROM POI_ISDC WHERE ASN_mx IS NOT NULL
                UNION ALL SELECT codice_IPA, ASN_ns FROM POI_ISDC WHERE ASN_ns IS NOT NULL
                UNION ALL SELECT codice_IPA, ASN_cname FROM POI_ISDC WHERE ASN_cname IS NOT NULL
            )
            GROUP BY asn
        )
    """, "quota primo ASN")[0]

    top_5_asn = fetch_all_required(cur, """
        SELECT t.asn,
               COALESCE(a.asn_organization, 'ASN ' || t.asn),
               t.enti
        FROM (
            SELECT asn, COUNT(DISTINCT codice_IPA) enti
            FROM (
                SELECT codice_IPA, ASN_mx as asn FROM POI_ISDC WHERE ASN_mx IS NOT NULL
                UNION ALL SELECT codice_IPA, ASN_ns FROM POI_ISDC WHERE ASN_ns IS NOT NULL
                UNION ALL SELECT codice_IPA, ASN_cname FROM POI_ISDC WHERE ASN_cname IS NOT NULL
            )
            GROUP BY asn
        ) t
        LEFT JOIN asn a ON a.asn_number = t.asn
        ORDER BY t.enti DESC
        LIMIT 5
    """, "top 5 ASN")

    # HHI: le quote sono calcolate sugli SLOT ASN
    # (ente x dimensione), quindi il denominatore e' il
    # numero di slot, non il numero di enti. Con il
    # numero di enti come denominatore l'indice
    # superava 1, che per un indice normalizzato e'
    # impossibile.
    herfindahl = fetch_one_required(cur, f"""
        SELECT SUM(POWER(freq * 1.0 / {asn_slots}, 2))
        FROM (
            SELECT asn, COUNT(*) freq
            FROM (
                SELECT ASN_mx as asn FROM POI_ISDC WHERE ASN_mx IS NOT NULL
                UNION ALL SELECT ASN_ns FROM POI_ISDC WHERE ASN_ns IS NOT NULL
                UNION ALL SELECT ASN_cname FROM POI_ISDC WHERE ASN_cname IS NOT NULL
            )
            GROUP BY asn
        )
    """, "HHI ASN")[0]

    # ============================================
    # ISDC
    # ============================================

    isdc_stats = fetch_one_required(cur, """
        SELECT AVG(ISDC_totale), MIN(ISDC_totale), MAX(ISDC_totale)
        FROM isdc_scores
    """, "statistiche ISDC")

    high_score_count = fetch_one_required(cur,
        "SELECT COUNT(*) FROM isdc_scores WHERE ISDC_totale >= 78",
        "ISDC sovrano")[0]

    critical_score_count = fetch_one_required(cur,
        "SELECT COUNT(*) FROM isdc_scores WHERE ISDC_totale < 40",
        "ISDC fragile")[0]

    # ============================================
    # DNS / TLS
    # ============================================

    dns_equal = fetch_one_required(cur, """
        SELECT COUNT(*) FROM POI_ISDC
        WHERE ASN_mx = ASN_ns AND ASN_ns = ASN_cname
    """, "DNS centralizzati")[0]

    fragmented_dns = fetch_one_required(cur, """
        SELECT COUNT(*) FROM POI_ISDC
        WHERE ASN_mx != ASN_ns
          AND ASN_ns != ASN_cname
          AND ASN_mx != ASN_cname
    """, "DNS distribuiti")[0]

    tls_letsencrypt = fetch_one_required(cur, """
        SELECT COUNT(*) FROM POI_ISDC
        WHERE LOWER(tls_issuer) LIKE '%let''s encrypt%'
    """, "certificati Let's Encrypt")[0]

    bands = fetch_all_required(cur, """
        SELECT ISDC_band,
               COUNT(*),
               ROUND(COUNT(*) * 100.0 /
               (SELECT COUNT(*) FROM isdc_scores), 2)
        FROM isdc_scores
        GROUP BY ISDC_band
        ORDER BY COUNT(*) DESC
    """, "band ISDC")

    # ============================================
    # CLOUD
    # ============================================

    hyperscaler_si = fetch_one_required(cur, """
        SELECT COUNT(*) FROM POI_ISDC
        WHERE hyperscaler = 'SI'
    """, "enti su hyperscaler")[0]

    hyperscaler_pct = fetch_one_required(cur, """
        SELECT ROUND(
            100.0 * SUM(CASE WHEN hyperscaler='SI' THEN 1 ELSE 0 END) /
            COUNT(*), 2
        )
        FROM POI_ISDC
    """, "quota hyperscaler")[0]

    # ============================================
    # POSTA / NAMESERVER / WEB (viste POI)
    # ============================================
    #
    # Ogni dimensione segue lo stesso schema: totale, quota
    # in Italia, quota fuori UE, metrica specifica e ranking
    # dei provider. Le quote derivano da
    # cluster_registered_country di ip_country, che classifica
    # gia' ogni IP in IT / UE / USA / Extra UE: e' la stessa
    # informazione di residenza dei dati che le mappe
    # mostrano al click, aggregata qui nel backend.
    #
    # I provider arrivano da asn_organization della vista POI,
    # non da un join aggiuntivo: POI_NS usa un left join, quindi
    # puo' avere 850 righe senza provider, mostrate come
    # "Non identificato" nel ranking invece di sparire.

    def cluster_distribution(view):
        return fetch_all_required(cur, f"""
            SELECT COALESCE(cluster_registered_country, '(non mappato)'),
                   COUNT(*)
            FROM {view}
            GROUP BY cluster_registered_country
            ORDER BY COUNT(*) DESC
        """, f"cluster {view}")

    def provider_ranking(view, limit=5):
        return fetch_all_required(cur, f"""
            SELECT COALESCE(asn_organization, 'Non identificato') AS provider,
                   COUNT(*) AS enti
            FROM {view}
            GROUP BY provider
            ORDER BY COUNT(*) DESC, provider
            LIMIT {limit}
        """, f"provider {view}")

    def top_provider(view):
        return fetch_one_required(cur, f"""
            SELECT COALESCE(asn_organization, 'Non identificato'),
                   COUNT(*)
            FROM {view}
            GROUP BY asn_organization
            ORDER BY COUNT(*) DESC,
                     COALESCE(asn_organization, '')
            LIMIT 1
        """, f"provider principale {view}")

    mx_clusters = cluster_distribution("POI_MX")
    ns_clusters = cluster_distribution("POI_NS")
    cname_clusters = cluster_distribution("POI_CNAME")

    def quota_fuori_UE(cluster_rows):
        m = {k: v for k, v in cluster_rows}
        return m.get("IT", 0), m.get("USA", 0) + m.get("Extra UE", 0)

    mx_italia, mx_fuori_ue = quota_fuori_UE(mx_clusters)
    ns_italia, ns_fuori_ue = quota_fuori_UE(ns_clusters)
    cname_italia, cname_fuori_ue = quota_fuori_UE(cname_clusters)

    mx_ranking = provider_ranking("POI_MX")
    ns_ranking = provider_ranking("POI_NS")
    cname_ranking = provider_ranking("POI_CNAME")

    # Metrica specifica MX: la posta elettronica e' la
    # dimensione su cui gli hyperscaler USA pesano di piu'
    # (Google gestisce da solo il 29% degli MX).
    mx_hyperscaler = fetch_one_required(cur, """
        SELECT COUNT(*) FROM POI_MX
        WHERE asn_organization LIKE '%amazon%'
           OR asn_organization LIKE '%microsoft%'
           OR asn_organization LIKE '%google%'
    """, "MX su hyperscaler USA")[0]

    # Metrica specifica NS: il nameserver e' il punto singolo
    # di fallimento piu' critico, quindi conta quanto e'
    # concentrato sul provider principale.
    ns_top = top_provider("POI_NS")

    # Metrica specifica CNAME: il certificato TLS del sito
    # dice chi emette e quindi chi puo' intercettare il
    # traffico web dell'ente.
    r_cname_le = cur.execute("""
        SELECT COUNT(*) FROM POI_CNAME
        WHERE LOWER(COALESCE(tls_issuer,'')) LIKE '%encrypt%'
    """).fetchone()
    if r_cname_le is None:
        cname_letsencrypt = 0
        # Il contatore dei KO e' inizializzato all'inizio di
        # build_json(): qui la query ha gia' risposto, quindi
        # l'unico caso e' una risposta vuota.
        ko += 1
    else:
        cname_letsencrypt = r_cname_le[0]

    conn.close()

    # ============================================
    # JSON OUTPUT
    # ============================================

    # Una card per cluster di Tipologia. La somma dei
    # count e' sempre uguale a total_enti: e' il controllo
    # che i due numeri abbiano lo stesso perimetro.
    tipologie_cards = [
        {
            "id": f"enti_{slug(t)}",
            "title": t if t else "Non classificati",
            "subtitle": (
                f"{round_safe(n * 100.0 / (total_enti[0] if isinstance(total_enti, (tuple,list)) else total_enti), 1)}% "
                f"degli enti censiti"
            ),
            "value": n,
            "value_type": "count"
        }
        for t, n in tipologie
    ]

    for t, n in tipologie:
        nome = (t or "(non classificata)")
        if len(nome) > 56:
            nome = nome[:53] + "..."
        traccia(
            f"  tipologia  {nome:<56} {n:>6}  "
            f"{round_safe(n * 100.0 / (total_enti[0] if isinstance(total_enti, (tuple,list)) else total_enti), 1):>5}%"
        )

    result = {
        "dataset": "STATS",
        "generated_at": datetime.utcnow().isoformat(),

        "kpi": {
            "total_enti": enti_con_isdc[0] if isinstance(enti_con_isdc, (tuple,list)) else enti_con_isdc,
            "sections": {

                "base_dati": {
                    "title": "Base dati",
                    "cards": [
                        {
                            "id": "total_enti",
                            "title": "Enti censiti",
                            "subtitle": "Enti presenti nel dataset",
                            "value": total_enti[0] if isinstance(total_enti, (tuple,list)) else total_enti,
                            "value_type": "count"
                        },
                        {
                            "id": "enti_con_isdc",
                            "title": "Enti valutati",
                            "subtitle": "Enti con indice di sovranita calcolato",
                            "value": enti_con_isdc[0] if isinstance(enti_con_isdc, (tuple,list)) else enti_con_isdc,
                            "value_type": "count"
                        },
                        {
                            "id": "total_ns",
                            "title": "Record NS",
                            "subtitle": "Name server analizzati",
                            "value": total_ns[0] if isinstance(total_ns, (tuple,list)) else total_ns,
                            "value_type": "count"
                        },
                        {
                            "id": "total_mx",
                            "title": "Record MX",
                            "subtitle": "Mail exchanger analizzati",
                            "value": total_mx[0] if isinstance(total_mx, (tuple,list)) else total_mx,
                            "value_type": "count"
                        },
                        {
                            "id": "total_cname",
                            "title": "Record CNAME",
                            "subtitle": "Alias DNS analizzati",
                            "value": total_cname[0] if isinstance(total_cname, (tuple,list)) else total_cname,
                            "value_type": "count"
                        },
                        {
                            "id": "total_datacenter",
                            "title": "Datacenter censiti",
                            "subtitle": "Datacenter presenti nel dataset",
                            "value": total_datacenter[0] if isinstance(total_datacenter, (tuple,list)) else total_datacenter,
                            "value_type": "count"
                        }
                    ]
                },

                "tipologie": {
                    "title": "Tipologie di ente",
                    "cards": tipologie_cards
                },

                "categorie": {
                    "title": "Categorie di ente",
                    "cards": [
                        {
                            "id": "categorie_enti",
                            "title": "Categorie di ente",
                            "subtitle": (
                                "Numero di enti per categoria IPA, "
                                "sul totale degli enti censiti"
                            ),
                            "value": build_categoria_list(categorie),
                            "value_type": "list",
                            "list_label": "Categoria",
                            "total": total_enti[0] if isinstance(total_enti, (tuple,list)) else total_enti
                        }
                    ]
                },

                "mx": {
                    "title": "Posta elettronica (MX)",
                    "cards": [
                        {
                            "id": "mx_enti",
                            "title": "Enti con MX identificato",
                            "subtitle": "Enti con record MX e provider risolto",
                            "value": total_mx[0] if isinstance(total_mx, (tuple,list)) else total_mx,
                            "value_type": "count"
                        },
                        {
                            "id": "mx_italia",
                            "title": "MX ospitati in Italia",
                            "subtitle": f"{mx_italia} enti",
                            "value": pct(mx_italia, total_mx[0] if isinstance(total_mx, (tuple,list)) else total_mx),
                            "value_type": "percentage"
                        },
                        {
                            "id": "mx_fuori_ue",
                            "title": "MX fuori dall'UE",
                            "subtitle": f"{mx_fuori_ue} enti (USA e Extra UE)",
                            "value": pct(mx_fuori_ue, total_mx[0] if isinstance(total_mx, (tuple,list)) else total_mx),
                            "value_type": "percentage"
                        },
                        {
                            "id": "mx_hyperscaler",
                            "title": "MX su hyperscaler USA",
                            "subtitle": "Google, Microsoft o Amazon",
                            "value": pct(mx_hyperscaler[0] if isinstance(mx_hyperscaler, (tuple,list)) else mx_hyperscaler, total_mx[0] if isinstance(total_mx, (tuple,list)) else total_mx),
                            "value_type": "percentage"
                        },
                        {
                            "id": "mx_provider_ranking",
                            "title": "Top provider MX",
                            "subtitle": "Provider ASN della posta elettronica, sul totale degli enti con MX",
                            "value": build_categoria_list(mx_ranking),
                            "value_type": "list",
                            "list_label": "Provider",
                            "total": total_mx[0] if isinstance(total_mx, (tuple,list)) else total_mx
                        }
                    ]
                },

                "ns": {
                    "title": "Nameserver (NS)",
                    "cards": [
                        {
                            "id": "ns_enti",
                            "title": "Enti con NS identificato",
                            "subtitle": "Enti con record NS e provider risolto",
                            "value": total_ns[0] if isinstance(total_ns, (tuple,list)) else total_ns,
                            "value_type": "count"
                        },
                        {
                            "id": "ns_italia",
                            "title": "NS ospitati in Italia",
                            "subtitle": f"{ns_italia} enti",
                            "value": pct(ns_italia, total_ns[0] if isinstance(total_ns, (tuple,list)) else total_ns),
                            "value_type": "percentage"
                        },
                        {
                            "id": "ns_fuori_ue",
                            "title": "NS fuori dall'UE",
                            "subtitle": f"{ns_fuori_ue} enti (USA e Extra UE)",
                            "value": pct(ns_fuori_ue, total_ns[0] if isinstance(total_ns, (tuple,list)) else total_ns),
                            "value_type": "percentage"
                        },
                        {
                            "id": "ns_provider_top",
                            "title": "Concentrazione sul provider principale",
                            "subtitle": f"{ns_top[0]} - {ns_top[1]} enti",
                            "value": pct(ns_top[1], total_ns[0] if isinstance(total_ns, (tuple,list)) else total_ns),
                            "value_type": "percentage"
                        },
                        {
                            "id": "ns_provider_ranking",
                            "title": "Top provider NS",
                            "subtitle": "Provider ASN dei nameserver, sul totale degli enti con NS",
                            "value": build_categoria_list(ns_ranking),
                            "value_type": "list",
                            "list_label": "Provider",
                            "total": total_ns[0] if isinstance(total_ns, (tuple,list)) else total_ns
                        }
                    ]
                },

                "cname": {
                    "title": "Web e certificati (CNAME)",
                    "cards": [
                        {
                            "id": "cname_enti",
                            "title": "Enti con CNAME identificato",
                            "subtitle": "Enti con record CNAME e provider risolto",
                            "value": total_cname[0] if isinstance(total_cname, (tuple,list)) else total_cname,
                            "value_type": "count"
                        },
                        {
                            "id": "cname_italia",
                            "title": "CNAME ospitati in Italia",
                            "subtitle": f"{cname_italia} enti",
                            "value": pct(cname_italia, total_cname[0] if isinstance(total_cname, (tuple,list)) else total_cname),
                            "value_type": "percentage"
                        },
                        {
                            "id": "cname_fuori_ue",
                            "title": "CNAME fuori dall'UE",
                            "subtitle": f"{cname_fuori_ue} enti (USA e Extra UE)",
                            "value": pct(cname_fuori_ue, total_cname[0] if isinstance(total_cname, (tuple,list)) else total_cname),
                            "value_type": "percentage"
                        },
                        {
                            "id": "cname_lets_encrypt",
                            "title": "Certificati Let's Encrypt",
                            "subtitle": f"{cname_letsencrypt} enti",
                            "value": pct(cname_letsencrypt, total_cname[0] if isinstance(total_cname, (tuple,list)) else total_cname),
                            "value_type": "percentage"
                        },
                        {
                            "id": "cname_provider_ranking",
                            "title": "Top provider CNAME",
                            "subtitle": "Provider ASN dei servizi web, sul totale degli enti con CNAME",
                            "value": build_categoria_list(cname_ranking),
                            "value_type": "list",
                            "list_label": "Provider",
                            "total": total_cname[0] if isinstance(total_cname, (tuple,list)) else total_cname
                        }
                    ]
                },

                "sovranita_digitale": {
                    "title": "Indice di Sovranita Digitale",
                    "cards": [
                        {"id": "isdc_avg", "title": "ISDC medio", "subtitle": "Indice medio", "value": round_safe(isdc_stats[0]), "value_type": "score"},
                        {"id": "isdc_max", "title": "ISDC massimo", "subtitle": "Indice massimo", "value": isdc_stats[2], "value_type": "score"},
                        {"id": "isdc_min", "title": "ISDC minimo", "subtitle": "Indice minimo", "value": isdc_stats[1], "value_type": "score"},
                        {"id": "high_score", "title": "Infrastruttura sovrana", "subtitle": "ISDC >= 78", "value": high_score_count[0] if isinstance(high_score_count, (tuple,list)) else high_score_count, "value_type": "count"},
                        {"id": "critical_score", "title": "Sovranita fragile", "subtitle": "ISDC < 40", "value": critical_score_count[0] if isinstance(critical_score_count, (tuple,list)) else critical_score_count, "value_type": "count"}
                    ]
                },

                "lockin": {
                    "title": "Vendor lock-in",
                    "cards": [
                        {"id": "lockin_high", "title": "Lock-in alto", "subtitle": "ASN uguali su MX/NS/CNAME", "value": lockin_high, "value_type": "count"},
                        {"id": "lockin_partial", "title": "Lock-in parziale", "subtitle": "Almeno due ASN coincidono", "value": lockin_partial, "value_type": "count"},
                        {"id": "distributed", "title": "Distribuzione completa", "subtitle": "ASN diversi", "value": distributed_count, "value_type": "count"},
                        {"id": "lockin_unknown", "title": "Non determinabile", "subtitle": "ASN mancante su una dimensione", "value": lockin_unknown, "value_type": "count"}
                    ]
                },

                "provider": {
                    "title": "Concentrazione ASN",
                    "cards": [
                        {"id": "unique_asn", "title": "ASN unici", "subtitle": "Diversita infrastrutturale", "value": unique_asn[0] if isinstance(unique_asn, (tuple,list)) else unique_asn, "value_type": "count"},
                        {"id": "top_asn_share", "title": "Dominanza ASN", "subtitle": "Quota enti sul primo ASN", "value": round_safe(top_asn_share), "value_type": "percentage"},
                        {"id": "top_5_asn", "title": "Top ASN", "subtitle": "Provider piu usati dagli enti", "value": build_asn_list(top_5_asn), "value_type": "list", "list_label": "Provider (ASN)", "total": enti_con_isdc[0] if isinstance(enti_con_isdc, (tuple,list)) else enti_con_isdc},
                        {"id": "herfindahl", "title": "HHI ASN", "subtitle": "Concentrazione infrastrutturale", "value": round_safe(herfindahl, 4), "value_type": "index"}
                    ]
                },

                "resilienza": {
                    "title": "Resilienza",
                    "cards": [
                        {"id": "dns_equal", "title": "DNS centralizzati", "subtitle": "Enti con MX=NS=CNAME", "value": dns_equal[0] if isinstance(dns_equal, (tuple,list)) else dns_equal, "value_type": "count"},
                        {"id": "fragmented_dns", "title": "DNS distribuiti", "subtitle": "Enti con ASN differenti", "value": fragmented_dns[0] if isinstance(fragmented_dns, (tuple,list)) else fragmented_dns, "value_type": "count"}
                    ]
                },

                "cloud": {
                    "title": "Cloud & hyperscaler",
                    "cards": [
                        {
                            "id": "hyperscaler_pct",
                            "title": "Dipendenza hyperscaler",
                            "subtitle": "Quota enti su cloud globale",
                            "value": hyperscaler_pct[0] if isinstance(hyperscaler_pct, (tuple,list)) else hyperscaler_pct,
                            "value_type": "percentage"
                        },
                        {
                            "id": "hyperscaler_si",
                            "title": "Enti su hyperscaler",
                            "subtitle": "Amazon, Google o Microsoft",
                            "value": hyperscaler_si[0] if isinstance(hyperscaler_si, (tuple,list)) else hyperscaler_si,
                            "value_type": "count"
                        }
                    ]
                },

                "dns_tls": {
                    "title": "TLS",
                    "cards": [
                        {
                            "id": "lets_encrypt",
                            "title": "Let's Encrypt",
                            "subtitle": "Certificati TLS automatici",
                            "value": tls_letsencrypt[0] if isinstance(tls_letsencrypt, (tuple,list)) else tls_letsencrypt,
                            "value_type": "count"
                        }
                    ]
                }
            }
        },

        "bands": [{"band": r[0], "count": r[1], "pct": r[2]} for r in bands]
    }

    traccia("")
    traccia("Controlli di coerenza")
    traccia("-" * 72)

    somma_tipologie = sum(n for _, n in tipologie)
    ko += not controllo(
        "la somma delle tipologie e' uguale agli enti censiti",
        somma_tipologie == (total_enti[0] if isinstance(total_enti, (tuple,list)) else total_enti),
        f"{somma_tipologie} != {total_enti}"
    )

    somma_categorie = sum(n for _, n in categorie)
    ko += not controllo(
        "la somma delle categorie e' uguale agli enti censiti",
        somma_categorie == (total_enti[0] if isinstance(total_enti, (tuple,list)) else total_enti),
        f"{somma_categorie} != {total_enti}"
    )

    somma_lockin = lockin_high + lockin_partial + distributed_count + lockin_unknown
    ko += not controllo(
        "le categorie di lock-in coprono tutti gli enti valutati",
        somma_lockin == (enti_con_isdc[0] if isinstance(enti_con_isdc, (tuple,list)) else enti_con_isdc),
        f"{somma_lockin} != {enti_con_isdc}"
    )

    somma_bands = sum(r[1] for r in bands)
    ko += not controllo(
        "le band ISDC coprono tutti gli enti valutati",
        somma_bands == (enti_con_isdc[0] if isinstance(enti_con_isdc, (tuple,list)) else enti_con_isdc),
        f"{somma_bands} != {enti_con_isdc}"
    )

    somma_pct = sum(r[2] for r in bands)
    ko += not controllo(
        "le percentuali delle band sommano a 100",
        abs(somma_pct - 100.0) < 0.05,
        f"{round_safe(somma_pct, 2)}%"
    )

    ko += not controllo(
        "l'HHI ASN e' un indice normalizzato",
        0 < herfindahl <= 1.0,
        f"{round_safe(herfindahl, 4)}: un HHI oltre 1 significa denominatore sbagliato"
    )

    ko += not controllo(
        "la quota del primo ASN e' una percentuale",
        0 <= (top_asn_share[0] if isinstance(top_asn_share, (tuple,list)) else top_asn_share) <= 100.0,
        f"{round_safe(top_asn_share, 2)}%"
    )

    for nome, rows, totale in (
        ("MX", mx_clusters, total_mx[0] if isinstance(total_mx, (tuple,list)) else total_mx),
        ("NS", ns_clusters, total_ns[0] if isinstance(total_ns, (tuple,list)) else total_ns),
        ("CNAME", cname_clusters, total_cname[0] if isinstance(total_cname, (tuple,list)) else total_cname),
    ):
        somma = sum(v for _, v in rows)
        ko += not controllo(
            f"i cluster geografici {nome} coprono tutti gli enti",
            somma == totale,
            f"{somma} != {totale}"
        )

    ko += not controllo(
        "gli MX su hyperscaler USA non superano il totale MX",
        0 < (mx_hyperscaler[0] if isinstance(mx_hyperscaler, (tuple,list)) else mx_hyperscaler) <= (total_mx[0] if isinstance(total_mx, (tuple,list)) else total_mx),
        f"{mx_hyperscaler} / {total_mx}"
    )

    ko += not controllo(
        "i certificati Let's Encrypt non superano il totale CNAME",
        0 < cname_letsencrypt <= (total_cname[0] if isinstance(total_cname, (tuple,list)) else total_cname),
        f"{cname_letsencrypt} / {total_cname}"
    )

    ko += not controllo(
        "il provider NS principale non supera il totale NS",
        0 < ns_top[1] <= (total_ns[0] if isinstance(total_ns, (tuple,list)) else total_ns),
        f"{ns_top[0]} = {ns_top[1]} / {total_ns}"
    )

    conteggi_zero = [
        (c["id"], sez)
        for sez, s in result["kpi"]["sections"].items()
        for c in s["cards"]
        if c["value_type"] == "count" and c["value"] == 0
    ]

    if conteggi_zero:
        for cid, sez in conteggi_zero:
            logging.error(
                f"  KO   conteggio a zero: {cid} (sezione {sez}) -> verificare che la tabella esista e non sia vuota"
            )
        ko += len(conteggi_zero)
    else:
        logging.info("  OK   nessun conteggio a zero")

    ids = [c["id"] for s in result["kpi"]["sections"].values() for c in s["cards"]]
    duplicati = sorted({i for i in ids if ids.count(i) > 1})
    ko += not controllo(
        "gli id dei KPI sono univoci",
        not duplicati,
        f"duplicati: {', '.join(duplicati)}"
    )

    if ko:
        logging.error(
            f"  {ko} controlli KO: il JSON e' stato scritto comunque, ma i valori vanno verificati prima di pubblicarlo"
        )
    else:
        logging.info("  Tutti i controlli superati")

    traccia("")
    traccia(f"Query eseguite: {_query_n}")
    traccia(
        f"Durata aggregazione: {(time.perf_counter() - t_start) * 1000:.0f} ms"
    )

    return result, ko

def esporta_change_history(conn=None):
    """
    Esporta l'intera tabella change_history_mod in JSON.

    Il file viene scritto nella stessa cartella di stat.json
    (comune.frontend_file). Per questa prima implementazione
    non viene applicato nessun filtro.
    """

    close_conn = False
    if conn is None:
        conn = sqlite3.connect(DB_PATH)
        close_conn = True

    cur = conn.cursor()

    try:
        cur.execute(
            """
            SELECT *
            FROM change_history_mod
            ORDER BY id
            """
        )

        rows = cur.fetchall()

        if cur.description is None:
            colonne = []
        else:
            colonne = [d[0] for d in cur.description]

        record = [
            {colonne[i]: r[i] for i in range(len(colonne))}
            for r in rows
        ]

        payload = {
            "dataset": "CHANGE_HISTORY",
            "generated_at": datetime.utcnow().isoformat(),
            "count": len(record),
            "records": record
        }

        HISTORY_JSON.parent.mkdir(parents=True, exist_ok=True)

        with open(HISTORY_JSON, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        size_kb = HISTORY_JSON.stat().st_size / 1024

        traccia(
            f"change_history.json generato -> {HISTORY_JSON}  "
            f"({len(record)} righe, {size_kb:.1f} KB)"
        )
        return payload

    except Exception as e:
        logging.error(f"Esportazione change_history_mod fallita: {e}")
        raise
    finally:
        if close_conn and conn:
            conn.close()


# ============================================
# MAIN
# ============================================

if __name__ == "__main__":

    t0 = time.perf_counter()

    try:

        data, ko = build_json()

        traccia("")
        traccia("Riepilogo dei KPI scritti")
        traccia("-" * 72)

        for sez_id, sez in data["kpi"]["sections"].items():

            traccia(f"  [{sez_id}]")

            for c in sez["cards"]:

                valore = str(c["value"])
                if len(valore) > 58:
                    valore = valore[:55] + "..."

                traccia(
                    f"    {c['id']:<48} {c['value_type']:<11} {valore}"
                )

        traccia("")
        traccia(f"  top-level: kpi.total_enti = "
                f"{data['kpi']['total_enti']}, "
                f"bands = {len(data['bands'])}")

        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        size_kb = Path(OUTPUT_JSON).stat().st_size / 1024

        traccia("")
        traccia("=" * 72)
        traccia(f"JSON generato -> {OUTPUT_JSON}  ({size_kb:.1f} KB)")
        traccia(
            f"Durata totale: {(time.perf_counter() - t0) * 1000:.0f} ms"
        )

        try:
            traccia("")
            traccia("Esportazione change history")
            traccia("-" * 72)
            conn_ch = sqlite3.connect(DB_PATH)
            esporta_change_history(conn_ch)
            conn_ch.close()
        except Exception as e:
            logging.error(f"Impossibile esportare change_history.json: {e}")

        if ko:
            traccia(f"ESITO: scritto con {ko} controlli KO")
            sys.exit(1)

        traccia("ESITO: OK")

    except FonteNonDisponibile as e:
        logging.critical(f"Fonte dati non disponibile: {e}")
        traccia("ESITO: KO, nessun JSON scritto")
        sys.exit(1)

    except Exception as e:
        logging.critical(f"Errore fatale: {e}")
        traccia("ESITO: KO, nessun JSON scritto")
        sys.exit(1)
