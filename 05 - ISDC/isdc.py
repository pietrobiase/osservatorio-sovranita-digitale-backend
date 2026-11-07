import sys
import sqlite3
import pandas as pd
import math
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common


# =========================================================
# LOGGING (STILE ORIGINALE RICCO)
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("isdc_scores.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("ISDC")


# =========================================================
# TIME (ROMA)
# =========================================================

def get_last_crawl():
    return datetime.now(
        ZoneInfo("Europe/Rome")
    ).strftime("%Y-%m-%d %H:%M:%S")


# =========================================================
# COSTANTI
# =========================================================

EU = {
    "austria","belgium","bulgaria","croatia","cyprus",
    "czechia","denmark","estonia","finland","france",
    "germany","greece","hungary","ireland",
    "latvia","lithuania","luxembourg","malta",
    "netherlands","poland","portugal","romania",
    "slovakia","slovenia","spain","sweden"
}

HYPERSCALERS = {
    "google","gmail","microsoft","azure",
    "amazon","aws","oracle","alibaba","ibm"
}

GLOBAL_CDNS = {
    "cloudflare","akamai","fastly","edgesuite","cdn77"
}


# =========================================================
# SORGENTI
# =========================================================
#
# Le viste POI_MX / POI_CNAME / POI_NS leggevano le vecchie
# tabelle comuni_*. Qui si legge direttamente dalle tabelle
# per ente, con la stessa cardinalita' (una riga per ente) e
# gli stessi join, cosi' i punteggi restano confrontabili:
# MX e CNAME con join interni, NS con join a sinistra perche'
# ns_asn e ns_ip possono essere NULL.

# Ogni sorgente e' definita UNA volta sola, come coppia
# (colonne, FROM+JOIN). Da qui nascono due query:
#
#   MX_SQL e affini  ->  la lettura per un singolo ente
#   gate EXISTS      ->  lo stesso join applicato in coda
#
# Il gate puo' quindi richiedere esattamente i dati che il
# punteggio sa leggere, senza rischiare che le due copie si
# disallineino in futuro. Se un join cambia, cambia anche la
# condizione di ammissione.

DNS_SOURCES = {

    "enti_mx": {
        "select": """
            a.asn_organization,
            i.country_name,
            i.continent,
            e.mx AS host
        """,
        "from": """
            FROM enti_mx e
            JOIN asn a        ON a.asn_number = e.asn_number
            JOIN ip_country i ON i.ip = e.mx_ip
        """,
    },

    "enti_cname": {
        "select": """
            a.asn_organization,
            i.country_name,
            i.continent,
            e.tls_issuer,
            e.cname_final AS host
        """,
        "from": """
            FROM enti_cname e
            JOIN asn a        ON a.asn_number = e.cname_asn
            JOIN ip_country i ON i.ip = e.cname_ip
        """,
    },

    "enti_ns": {
        "select": """
            a.asn_organization,
            i.country_name,
            i.continent,
            e.ns_primary AS host
        """,
        "from": """
            FROM enti_ns e
            LEFT JOIN asn a        ON a.asn_number = e.ns_asn
            LEFT JOIN ip_country i ON i.ip = e.ns_ip
        """,
    },
}


def _source_query(tabella, enti=("e.codice_IPA = ?",)):
    """
    Compone la SELECT di una sorgente. `enti` e' la clausola di
    filtro sull'ente: la coda la passa come alias della coda,
    il calcolo come parametro.
    """

    src = DNS_SOURCES[tabella]
    return f"SELECT{src['select']}{src['from']}WHERE {enti[0]}"


MX_SQL = _source_query("enti_mx")
CNAME_SQL = _source_query("enti_cname")
NS_SQL = _source_query("enti_ns")


# =========================================================
# HELPERS
# =========================================================

def n(x):

    """
    Normalizza un valore testuale in minuscolo.

    I NULL arrivano da pandas come NaN, e `NaN or ""` restituisce
    NaN (NaN e' truthy): senza questo controllo la stringa "nan"
    entrerebbe nel matching delle parole chiave.
    """

    if x is None:
        return ""

    s = str(x).strip().lower()

    if s in ("nan", "none", "null"):
        return ""

    return s


def contains_any(text, values):
    s = n(text)
    return any(v in s for v in values)


# =========================================================
# GEO SCORE
# =========================================================

# Paesi extra-europei con penalita' esplicita.
#
# Vanno valutati PRIMA del continente: MaxMind classifica la
# Russia nel continente europeo, quindi un controllo
# `continent == "europe"` prima di questo la renderebbe indistinguibile
# da Francia o Germania. L'ordine dei controlli e' parte del
# calcolo, non un dettaglio di stile.
SANCTIONED = {
    "china",
    "russia"
}


def geo_score(country, continent):

    c = n(country)
    t = n(continent)

    if c == "italy":
        score = 1.0

    elif c in EU:
        score = 0.85

    elif c in SANCTIONED:
        score = 0.25

    elif t == "europe":
        score = 0.70

    elif t in ["north america","south america","africa","asia","oceania"]:
        score = 0.50

    else:
        score = 0.30

    logger.debug(f"GEO_SCORE {c}/{t} -> {score}")
    return score


# =========================================================
# INFRA SCORE
# =========================================================

def infra_score(asn, host):

    """
    Giudizio sulla natura del provider.

    `asn`   nome dell'organizzazione che gestisce l'ASN
    `host`  hostname dell'infrastruttura valutata
            (mx, ns_primary, cname_final)

    Entrambi alimentano lo stesso matching: e' l'host a dire se
    l'infrastruttura e' davvero ospitata in Italia, non il nome
    dell'ASN, che puo' essere italiano mentre il servizio e'
    interamente overseas.
    """

    s = n(asn) + " " + n(host)
    score = 0.5

    reasons = []

    if contains_any(s, HYPERSCALERS):
        score -= 0.30
        reasons.append("hyperscaler")

    if contains_any(s, GLOBAL_CDNS):
        score -= 0.20
        reasons.append("cdn")

    if ".it" in s or "italia" in s:
        score += 0.25
        reasons.append("italy_host")

    if any(x in s for x in ["gov","comune","ministero","regione","provincia","enti"]):
        score += 0.35
        reasons.append("public")

    final = max(0.0, min(1.0, score))

    logger.debug(f"INFRA_SCORE {asn} -> {final} reasons={reasons}")

    return final


# =========================================================
# TLS SCORE
# =========================================================

def tls_score(issuer):

    i = n(issuer)

    if not i:
        return 0.5
    if contains_any(i, HYPERSCALERS):
        return 0.2
    if "let's encrypt" in i:
        return 0.7
    if any(x in i for x in ["digicert","globalsign","sectigo"]):
        return 0.85
    return 0.5


# =========================================================
# COVERAGE
# =========================================================

def coverage(n_rows):

    if n_rows == 0:
        return 0.4
    if n_rows == 1:
        return 0.7
    if n_rows == 2:
        return 0.9
    return 1.0


def apply_coverage(score, cov):
    return score * cov + 50 * (1 - cov)


def sigmoid(x, k=8, x0=0.6):
    return 100 / (1 + math.exp(-k * (x - x0)))


# =========================================================
# BONUS / MALUS (TRACCIATO COMPLETO)
# =========================================================

def sovereignty_bonus(mx_df, cn_df, ns_df):

    logger.info("\n================ BONUS/MALUS ================\n")

    bonus = 0
    malus = 0
    reasons = {"bonus": [], "malus": []}

    dfs = [d for d in [mx_df, cn_df, ns_df] if d is not None and not d.empty]

    if not dfs:
        logger.warning("EMPTY DATASET BONUS/MALUS")
        return 0, 0, reasons

    all_df = pd.concat(dfs, ignore_index=True)

    all_df["asn"] = all_df.get("asn_organization","").fillna("").str.lower()
    all_df["country"] = all_df.get("country_name","").fillna("").str.lower()
    all_df["continent"] = all_df.get("continent","").fillna("").str.lower()

    logger.info("BONUS DATA SAMPLE:\n%s", all_df.head(10))

    # hyperscaler
    h = all_df["asn"].apply(lambda x: contains_any(x, HYPERSCALERS)).mean()
    logger.info(f"HYPERSCALER_RATIO={h:.2f}")

    if h >= 0.8:
        malus -= 20
    elif h >= 0.5:
        malus -= 15
    elif h >= 0.25:
        malus -= 10

    # CDN
    c = all_df["asn"].apply(lambda x: contains_any(x, GLOBAL_CDNS)).mean()
    logger.info(f"CDN_RATIO={c:.2f}")

    if c >= 0.5:
        malus -= 10

    # geo
    it = (all_df["country"] == "italy").mean()
    eu = all_df["country"].isin(EU).mean()

    logger.info(f"ITALY={it:.2f} EU={eu:.2f}")

    if it >= 0.5:
        bonus += 8
    if eu >= 0.95:
        bonus += 6

    logger.info(f"BONUS={bonus} MALUS={malus}")

    return bonus, malus, reasons


# =========================================================
# TABELLA
# =========================================================
#
# La chiave e' codice_IPA. codice_istat non puo' esserlo:
# in enti_contatti e' NULL per la meta' degli enti e non e'
# univoco, perche' piu' enti condividono lo stesso codice
# ISTAT. Resta come colonna informative per i raggruppamenti.

CREATE_SQL = """
    CREATE TABLE IF NOT EXISTS isdc_scores (
        codice_IPA TEXT PRIMARY KEY NOT NULL,
        codice_istat INTEGER,
        denominazione_ita TEXT,
        dominio TEXT,
        ISDC_mx REAL,
        ISDC_cname REAL,
        ISDC_dns REAL,
        ISDC_totale REAL,
        ISDC_band TEXT,
        bonus REAL,
        malus REAL,
        last_crawl TEXT
    )
"""


def ensure_isdc_table(conn):
    """
    Allinea isdc_scores allo schema per ente.

    Se la tabella esiste gia' con codice_IPA non si tocca nulla.
    Altrimenti e' la tabella legacy, calcolata sul modello
    comuni_* e indicizzata da codice_istat: quei punteggi non
    sono confrontabili con quelli per ente, quindi non si
    travasa. Vanno in isdc_scores_legacy, da ripristinare a
    mano se servono.

    La tabella viene copiata e poi rilasciata invece che
    rinominata: un RENAME in SQLite riscrive i riferimenti
    nelle viste, quindi POI_ISDC e le STAT_ punterebbero
    alla tabella legacy e sembrerebbero funzionare con dati
    vecchi. Cosi' restano legate a isdc_scores e falliscono
    in modo visibile se non sono piu' compatibili.
    """

    colonne = [r[1] for r in conn.execute("PRAGMA table_info(isdc_scores)")]

    if not colonne:
        conn.execute(CREATE_SQL)
        conn.commit()
        logger.info("Tabella isdc_scores creata (schema per ente).")
        return

    if "codice_IPA" in colonne:
        return

    legacy = conn.execute("SELECT COUNT(*) FROM isdc_scores").fetchone()[0]

    conn.execute("DROP TABLE IF EXISTS isdc_scores_legacy")
    conn.execute("CREATE TABLE isdc_scores_legacy AS SELECT * FROM isdc_scores")
    conn.execute("DROP TABLE isdc_scores")
    conn.execute(CREATE_SQL)
    conn.commit()

    logger.warning(
        "isdc_scores migrate allo schema per ente. "
        f"{legacy} righe legacy (codice_istat) copiate in "
        "isdc_scores_legacy: non confrontabili con i punteggi "
        "per ente, vanno ricalcolati o scartati. La copia non "
        "conserva la PK, serve solo come archivio."
    )


# =========================================================
# SAVE
# =========================================================

def save(conn, df, table):

    last_crawl = get_last_crawl()

    logger.info(f"SAVING {len(df)} RECORDS LAST_CRAWL={last_crawl}")

    if df.empty:
        return

    conn.executemany(f"""
        INSERT INTO {table} (
            codice_IPA,
            codice_istat,
            denominazione_ita,
            dominio,
            ISDC_mx,
            ISDC_cname,
            ISDC_dns,
            ISDC_totale,
            ISDC_band,
            bonus,
            malus,
            last_crawl
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(codice_IPA) DO UPDATE SET
            codice_istat=excluded.codice_istat,
            denominazione_ita=excluded.denominazione_ita,
            dominio=excluded.dominio,
            ISDC_mx=excluded.ISDC_mx,
            ISDC_cname=excluded.ISDC_cname,
            ISDC_dns=excluded.ISDC_dns,
            ISDC_totale=excluded.ISDC_totale,
            ISDC_band=excluded.ISDC_band,
            bonus=excluded.bonus,
            malus=excluded.malus
    """, [
        (
            r["codice_ipa"],
            r["codice_istat"],
            r["denominazione_ita"],
            r["dominio"],
            round(r["ISDC_mx"], 2),
            round(r["ISDC_cname"], 2),
            round(r["ISDC_dns"], 2),
            round(r["ISDC_totale"], 2),
            r["ISDC_band"],
            r["bonus"],
            r["malus"],
            last_crawl
        )
        for r in df.to_dict("records")
    ])

    conn.commit()


# =========================================================
# BAND ORIGINALE
# =========================================================

def band(x):

    if x <= 40:
        return "Sovranità digitale fragile"
    if x <= 60:
        return "Dipendenza infrastrutturale"
    if x <= 78:
        return "Infrastruttura eterogenea"
    return "Infrastruttura sovrana"


# =========================================================
# MAIN (CON LOG COMPLETO PER STEP)
# =========================================================
# CODA DI ELABORAZIONE
# =========================================================
#
# {GATE} viene sostituito dai filtri EXISTS sulle sorgenti
# richieste, o rimosso se il gate e' disabilitato.

QUEUE_SQL_BASE = """
    SELECT
        c.Codice_IPA AS codice_ipa,
        c.Codice_ISTAT AS codice_istat,
        c.Denominazione_ente AS denominazione,
        c.Sito_istituzionale AS dominio
    FROM enti_contatti c
    LEFT JOIN isdc_scores s ON c.Codice_IPA = s.codice_IPA
    WHERE s.codice_IPA IS NULL
      AND c.Sito_istituzionale IS NOT NULL
      AND TRIM(c.Sito_istituzionale) != ''
      {GATE}
    ORDER BY c.Codice_IPA
    LIMIT ?
"""


def build_queue_sql(required):

    """
    Costruisce la query di coda applicando il gate di
    ammissione: l'ente deve superare la stessa lettura che il
    calcolo farà dopo, su TUTTE le tabelle in `required`.

    Il punto non è che la riga esista, è che restituisca dati.
    Un ente con una riga in enti_mx ma con mx_ip assente da
    ip_country fa zero righe in MX_SQL e riceverebbe il
    valore neutro 42.40: una misura che sembra tale e non lo
    è. Per questo il gate riusa le FROM/JOIN di DNS_SOURCES.

    I nomi arrivano da config.yaml e sono gia' stati validati
    da common.isdc_required_tables() contro una lista chiusa,
    quindi qui non serve escaping: accettare un nome arbitrario
    trasformerebbe il controllo in una porta aperta.
    """

    if not required:

        logger.warning(
            "GATE DISABILITATO: nessuna tabella richiesta. "
            "Gli enti senza dati utilizzabili verranno valutati "
            "con il valore neutro 42.40."
        )

        return QUEUE_SQL_BASE.replace("{GATE}", "")

    filtri = "\n          AND ".join(
        f"EXISTS (SELECT 1{DNS_SOURCES[t]['from']}"
        f"WHERE e.codice_IPA = c.Codice_IPA)"
        for t in required
    )

    # Il segnaposto {GATE} sta su una riga propria senza "AND":
    # va aggiunto qui, altrimenti il primo filtro risulta
    # attaccato alla condizione precedente.
    return QUEUE_SQL_BASE.replace("{GATE}", "AND " + filtri)


def main():

    conn = sqlite3.connect(common.db_path())
    limit = common.max_run()

    ensure_isdc_table(conn)

    logger.info(f"START ENGINE LIMIT={limit}")

    # ------------------------------------------------------
    # GATE DI AMMISSIONE
    # ------------------------------------------------------
    #
    # Tre condizioni, tutte necessarie:
    #
    # - sito istituzionale valorizzato: un ente senza dominio
    #   non puo' avere MX, NS o CNAME, la pipeline DNS lo
    #   scarta comunque;
    # - record su tutte le tabelle in isdc_required_tables:
    #   senza questo controllo l'ente verrebbe valutato con
    #   raw=0.5 e apply_coverage(0.5, 0.4) = 42.40, un numero
    #   che sembra una misura ma non lo e';
    # - nessuna riga in isdc_scores: la coda e' incrementale,
    #   un punteggio non viene mai ricalcolato da solo. Per
    #   rivalutare un ente va cancellata la sua riga.
    #
    # ORDER BY rende i lotti riproducibili fra un giro e
    # l'altro, dato che LIMIT senza ordinamento darebbe
    # sempre gli stessi record.

    required = common.isdc_required_tables()

    logger.info(
        f"GATE tabelle richieste: "
        f"{', '.join(required) if required else '(nessuna)'}"
    )

    queue_sql = build_queue_sql(required)

    # Il confronto candidati/ammessi e' fatto senza LIMIT,
    # altrimenti la differenza confonderebbe i record scartati
    # dal gate con quelli semplicemente tagliati dal limite di run.
    TUTTI = 10 ** 9

    candidati = len(pd.read_sql_query(
        QUEUE_SQL_BASE.replace("{GATE}", ""),
        conn,
        params=(TUTTI,),
    ))

    ammessi_totale = len(pd.read_sql_query(
        queue_sql,
        conn,
        params=(TUTTI,),
    ))

    scartati = candidati - ammessi_totale

    logger.info(
        f"CODA {candidati} enti con sito e senza score "
        f"-> {ammessi_totale} ammessi dal gate, "
        f"{scartati} scartati per dati DNS mancanti"
    )

    to_process = pd.read_sql_query(
        queue_sql,
        conn,
        params=(limit,),
    )

    logger.info(f"IN CODA {len(to_process)} enti da processare")

    results = []

    for i, row in to_process.iterrows():

        code = row.codice_ipa

        logger.info("\n==============================")
        logger.info(f"PROCESS {code} - {row.denominazione} - {row.dominio}")
        logger.info("==============================")

        mx = pd.read_sql_query(MX_SQL, conn, params=(code,))
        cn = pd.read_sql_query(CNAME_SQL, conn, params=(code,))
        ns = pd.read_sql_query(NS_SQL, conn, params=(code,))

        logger.info(f"MX rows={len(mx)} CNAME rows={len(cn)} NS rows={len(ns)}")

        # MX
        if len(mx):
            geo = mx.apply(lambda x: geo_score(x.country_name, x.continent), axis=1).max()
            infra = mx.apply(lambda x: infra_score(x.asn_organization, x.host), axis=1).mean()
            raw_mx = geo * 0.6 + infra * 0.4
        else:
            raw_mx = 0.5

        mx_final = apply_coverage(sigmoid(raw_mx), coverage(len(mx)))

        # CNAME
        if len(cn):
            geo = cn.apply(lambda x: geo_score(x.country_name, x.continent), axis=1).max()
            infra = cn.apply(lambda x: infra_score(x.asn_organization, x.host), axis=1).mean()
            tls = cn["tls_issuer"].apply(tls_score).mean()
            raw_cn = geo * 0.5 + infra * 0.3 + tls * 0.2
        else:
            raw_cn = 0.5

        cn_final = apply_coverage(sigmoid(raw_cn), coverage(len(cn)))

        # DNS
        if len(ns):
            geo = ns.apply(lambda x: geo_score(x.country_name, x.continent), axis=1).max()
            infra = ns.apply(lambda x: infra_score(x.asn_organization, x.host), axis=1).mean()
            raw_ns = geo * 0.6 + infra * 0.4
        else:
            raw_ns = 0.5

        ns_final = apply_coverage(sigmoid(raw_ns), coverage(len(ns)))

        bonus, malus, reasons = sovereignty_bonus(mx, cn, ns)

        total = mx_final * 0.4 + cn_final * 0.35 + ns_final * 0.25
        total = max(0, min(100, total + bonus + malus))

        logger.info(f"FINAL SCORE={total:.2f} BONUS={bonus} MALUS={malus}")

        results.append({
            "codice_ipa": code,
            "codice_istat": None if pd.isna(row.codice_istat) else int(row.codice_istat),
            "denominazione_ita": row.denominazione,
            "dominio": row.dominio,
            "ISDC_mx": mx_final,
            "ISDC_cname": cn_final,
            "ISDC_dns": ns_final,
            "ISDC_totale": total,
            "ISDC_band": band(total),
            "bonus": bonus,
            "malus": malus
        })

    save(conn, pd.DataFrame(results), "isdc_scores")
    conn.close()

    logger.info("DONE")


if __name__ == "__main__":
    main()
