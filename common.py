"""
Percorsi e configurazione condivisi da tutta la pipeline.

Ogni script vive in una sottocartella di `main/`, quindi
PROJECT_ROOT (la cartella che contiene questo modulo) è
anche la radice del progetto.

Uso tipico in uno script:

    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    import common

Nessun percorso della pipeline va più scritto a mano:
tutto passa da qui, così rinominare una cartella non
rompe nulla.
"""

from __future__ import annotations

import functools
import logging
from pathlib import Path

import yaml


logger = logging.getLogger(__name__)


# =========================================================
# LAYOUT DEL PROGETTO
# =========================================================

PROJECT_ROOT = Path(__file__).resolve().parent

CONFIG_DIR = PROJECT_ROOT / "01 - Config"

INPUT_DIR = PROJECT_ROOT / "00 - Input"

DATABASE_DIR = PROJECT_ROOT / "database"

FRONTEND_ROOT = (
    PROJECT_ROOT.parent.parent
    / "osservatorio-sovranita-digitale-frontend"
)

FRONTEND_DATA_DIR = FRONTEND_ROOT / "main" / "osservatorio" / "data"

GEOIP_DIR = PROJECT_ROOT / "04 - QueryDNS"


# =========================================================
# PATH
# =========================================================

def resolve(path, *basi) -> Path:

    """
    Rende assoluto un percorso configurato.

    - percorso assoluto: restituito invariato
    - percorso relativo: risolto in ordine rispetto a
      le basi ricevute, PROJECT_ROOT, CONFIG_DIR

    Vince il primo candidato che esiste. Se nessuno
    esiste, viene restituito il primo calcolato, così
    l'errore emerge dal chiamante con un path sensato.
    """

    p = Path(path)

    if p.is_absolute():

        return p

    candidati = [
        (base / p).resolve()
        for base in (*basi, PROJECT_ROOT, CONFIG_DIR)
    ]

    for candidato in candidati:

        if candidato.exists():

            return candidato

    return candidati[0]


# =========================================================
# CONFIGURAZIONE
# =========================================================

@functools.lru_cache(maxsize=None)
def load_config(file_name: str = "config.yaml") -> dict:

    """
    Carica e memoizza un YAML dalla cartella config.
    """

    path = CONFIG_DIR / file_name

    if not path.exists():

        raise FileNotFoundError(
            f"Config non trovato: {path}"
        )

    with open(path, "r", encoding="utf-8") as f:

        return yaml.safe_load(f) or {}


@functools.lru_cache(maxsize=None)
def config() -> dict:

    """
    Configurazione principale della pipeline.
    """

    return load_config("config.yaml")


# =========================================================
# ACCESSORI DERIVATI
# =========================================================

@functools.lru_cache(maxsize=None)
def db_path() -> Path:

    """
    Percorso assoluto del database SQLite.
    """

    return resolve(
        config()["database_name"],
        DATABASE_DIR
    )


@functools.lru_cache(maxsize=None)
def input_dir() -> Path:

    """
    Cartella base dei file di input.
    """

    return resolve(
        config()["input_dir"],
        INPUT_DIR
    )


@functools.lru_cache(maxsize=None)
def max_run() -> int:

    """
    Numero massimo di record elaborati per run.
    """

    return int(config().get("max_run", 100))


# =========================================================
# GATE DI AMMISSIONE AL CALCOLO ISDC
# =========================================================
#
# Un ente entra nel calcolo ISDC solo se ha gia' dei record
# su TUTTE le tabelle indicate qui.
#
# Senza questo controllo un ente privo di dati verrebbe
# valutato con il valore neutro di apply_coverage (42.40,
# fascia "Dipendenza infrastrutturale"): un numero che sembra
# una misura ma non lo e'. E la coda di isdc.py e' incrementale,
# quindi quel punteggio falso non verrebbe piu' ricalcolato.

KNOWN_DNS_TABLES = (
    "enti_mx",
    "enti_ns",
    "enti_cname",
)


@functools.lru_cache(maxsize=None)
def isdc_required_tables() -> tuple:

    """
    Tabelle che devono esistere tutte perche' un ente entri
    nel calcolo ISDC.

    I nomi sono validati contro KNOWN_DNS_TABLES: arrivano
    dalla configurazione e finiscono in una query SQL, quindi
    non possono essere arbitrari. Un elenco vuoto disattiva il
    controllo (utile solo per il debug).
    """

    tables = config().get("isdc_required_tables")

    if tables is None:

        tables = list(KNOWN_DNS_TABLES)

    if isinstance(tables, str):

        tables = [tables]

    ammessi = []

    for t in tables:

        nome = str(t).strip()

        if nome not in KNOWN_DNS_TABLES:

            raise ValueError(
                f"Tabella non ammessa in isdc_required_tables: {nome!r} "
                f"(ammesse: {', '.join(KNOWN_DNS_TABLES)})"
            )

        if nome not in ammessi:

            ammessi.append(nome)

    return tuple(ammessi)


# =========================================================
# STATO DELLE COORDINATE
# =========================================================
#
# lat/lon hanno tre stati distinti e non intercambiabili:
#
#   NULL  -> mai calcolate. L'ente non e' ancora stato
#            interrogato, e' in coda.
#   -1.0  -> calcolate e FALLITE. Il geocoder ha risposto
#            senza risultato. Non e' una coordinata: [-1, -1]
#            e' un punto valido del golfo di Guinea, quindi
#            finiva disegnato come un ammasso di marker
#            sovrapposti in ogni layer.
#   >= 0  -> calcolate con successo, mappabili.
#
# La distinzione serve perche' statistiche e mappa non hanno
# gli stessi requisiti: un ente non georeferenziato non puo'
# essere disegnato, ma ha comunque un'infrastruttura DNS reale
# e deve contare nelle metriche. Filtrare in Crea_View.sql
# eliminerebbe quegli enti anche da stat.json.

COORD_NON_TROVATA = -1.0

# Filtro per la sola rappresentazione grafica. Da usare nei
# consumer che producono mappe, mai in quelli che misurano.
COORD_PUBBLICABILI_SQL = "lat >= 0 AND lon >= 0"

# Coda di AggiornaLatLonEnti.py: solo le coordinate mai
# calcolate. I -1 sono terminali, non rientrano.
COORD_IN_CODA_SQL = "lat IS NULL AND lon IS NULL"


def coordinate_plottable(lat, lon) -> bool:

    """
    True se la coppia produce un punto GeoJSON utile.
    """

    try:

        return float(lat) >= 0 and float(lon) >= 0

    except (TypeError, ValueError):

        return False


def stato_coordinate(conn, tabella: str = "enti_contatti") -> dict:

    """
    Conteggio dei tre stati delle coordinate.

    E' l'unico modo per accorgersi che il backlog dei -1 e'
    cresciuto: il valore non genera errori da nessuna parte,
    quindi senza questo controllo resta invisibile.
    """

    return dict(zip(
        ("mai_calcolate", "non_trovate", "pubblicabili"),
        conn.execute(
            f"""
            SELECT
                SUM({COORD_IN_CODA_SQL}),
                SUM(lat = {COORD_NON_TROVATA} AND lon = {COORD_NON_TROVATA}),
                SUM({COORD_PUBBLICABILI_SQL})
            FROM {tabella}
            """
        ).fetchone()
    ))


def input_file(key: str, sezione: str = "files") -> Path:

    """
    Percorso assoluto di un file di input dichiarato in
    config. Esempio: input_file("enti_contatti", "files_enti")
    """

    return resolve(
        config()[sezione][key],
        input_dir()
    )


def input_files(sezione: str = "files") -> dict:

    """
    Mappa {chiave: percorso assoluto} dei file di input.
    """

    return {
        key: input_file(key, sezione)
        for key in config().get(sezione, {})
    }


def frontend_file(name: str) -> Path:

    """
    Percorso di un file di output lato frontend.
    """

    return FRONTEND_DATA_DIR / name


def frontend_dir() -> Path:

    """
    Cartella di output lato frontend, creata se manca.
    """

    FRONTEND_DATA_DIR.mkdir(parents=True, exist_ok=True)

    return FRONTEND_DATA_DIR


# =========================================================
# TABELLA ASN
# =========================================================

ASN_SCHEMA = """
    CREATE TABLE IF NOT EXISTS asn (
        asn_number INTEGER PRIMARY KEY,
        asn_organization TEXT,
        last_crawl TEXT
    )
"""


def ensure_asn_table(conn) -> None:

    """
    Garantisce che `asn` esista e abbia `last_crawl`.

    La tabella era già in produzione senza quella colonna, e
    `CREATE TABLE IF NOT EXISTS` su una tabella esistente non
    aggiunge nulla: serve una migrazione esplicita. Fallita in
    silenzio, la colonna continuerebbe a mancare e ogni
    scrittura di `last_crawl` cadrebbe.
    """

    cur = conn.cursor()

    cur.execute(ASN_SCHEMA)

    colonne = {
        r[1] for r in cur.execute("PRAGMA table_info(asn)")
    }

    if "last_crawl" not in colonne:

        cur.execute("ALTER TABLE asn ADD COLUMN last_crawl TEXT")

    conn.commit()


def upsert_asn(conn, asn_number, asn_organization, last_crawl) -> bool:

    """
    Inserisce un ASN se assente.

    Restituisce True solo se la riga è stata creata adesso,
    così il chiamante può contare i nuovi ASN senza doppio
    conteggio. `last_crawl` ha semantica di data di primo
    inserimento: un ASN già presente non viene toccato, perché
    la data deve dire quando l'ASN è entrato in tabella e non
    quando è stato osservato l'ultima volta.

    Valori non interi vengono scartati: `INSERT OR IGNORE`
    non assorbe un datatype mismatch, che SQLite solleva
    comunque e farebbe fallire l'intera transazione.
    """

    try:

        numero = int(asn_number)

    except (TypeError, ValueError):

        return False

    if numero <= 0:

        return False

    # int() tronca i float: 1.5 diventerebbe 1, un ASN
    # sbagliato scritto silenziosamente in tabella.
    if isinstance(asn_number, float) and asn_number != numero:

        return False

    if isinstance(asn_number, str) and str(numero) != asn_number.strip():

        return False

    cur = conn.cursor()

    cur.execute(
        """
        INSERT OR IGNORE INTO asn
            (asn_number, asn_organization, last_crawl)
        VALUES (?, ?, ?)
        """,
        (numero, asn_organization, last_crawl),
    )

    nuovo = cur.rowcount > 0

    return nuovo


# =========================================================
# CAMPI CALCOLATI VUOTI
# =========================================================

# Le colonne calcolate dai tre crawler DNS possono essere
# assenti in due modi, non solo uno: NULL e stringa vuota.
# Il caso reale e' `mx=''` su csi_piem, che un semplice
# `IS NULL` non intercetta.
#
# Il motivo e' che questi campi sono gia' stati scritti da una
# versione dello script che scriveva il risultato di un lookup
# come stringa vuota invece di lasciare il campo a NULL. Le
# due cose per un consumatore sono equivalenti: nessun dato.
#
# Le stringhe vuote vanno pero' trattate solo dove il dato e'
# testuale. Su una colonna numerica la coda continuerebbe a
# considerare mancante priorita'=0, perche' TRIM(CAST(0 AS
# TEXT))='' e il conteggio dei campi pieni crollerebbe: un
# MX con priorita' 0 e' perfettamente valido.
CAMPI_TESTO_DNS = frozenset({
    "a_record", "cname_final", "cname_ip",
    "tls_ip", "tls_issuer", "tls_type",
    "ns_primary", "ns_ip",
    "mx", "mx_ip",
})


def campo_vuoto(colonna: str) -> str:

    """
    Espressione SQL vera quando la colonna non ha un dato
    utilizzabile, per una colonna calcolata dai crawler DNS.

    NULL e stringa vuota sono lo stesso segnale di "non
    raccolto", ma solo per le colonne testuali: su una
    numerica un valore 0 e' un valore reale e va contato come
    campo pieno.

    Accetta il nome con o senza prefisso di tabella, perche'
    la stessa espressione viene usata nella coda (nome
    nudo) e negli ON CONFLICT (tabella.colonna): senza
    questo, 'enti_mx.mx' non risulta in CAMPI_TESTO_DNS e
    verrebbe trattata come numerica.
    """

    nome = colonna.rsplit(".", 1)[-1]

    if nome in CAMPI_TESTO_DNS:

        return f"NULLIF(TRIM({colonna}), '') IS NULL"

    return f"{colonna} IS NULL"


def condizione_coda(colonne: tuple) -> str:

    """
    WHERE del --retry: tiene i record incompleti, cioe' quelli
    con almeno un campo calcolato assente.
    """

    return " OR ".join(campo_vuoto(c) for c in colonne)


def conteggio_campi_pieni(colonne: tuple) -> str:

    """
    Quanti campi calcolati un record ha gia'.

    Va usato come ORDER BY **decrescente**: i record con piu'
    dati hanno piu' probabilita' di essere completabili, quindi
    devono stare davanti ai record interamente vuoti.

    Restituisce 0 per un record completamente vuoto e
    len(colonne) per uno completo, e tratta la stringa vuota come
    assente, coerentemente con `campo_vuoto()`.

    La somma usa '+' e non una lista tra parentesi perche' in
    SQLite '(a, b, c)' e' una row value, non un elenco.

    Attenzione a `NOT x IS NULL`: in SQLite non vale
    "x non e' NULL" ma "x e' NULL", perche' `IS` lega piu' forte
    di `NOT`. Infatti `NOT NULLIF(TRIM(col), '') IS NULL` vale 1
    quando il campo e' valorizzato. Se un giorno si volesse il
    conteggio degli assenti, va negato con `x IS NULL`, non con
    `NOT x IS NULL`.
    """

    return " + ".join(
        f"(NOT {campo_vuoto(c)})" for c in colonne
    )


def conserva_valore(
    tabella: str,
    colonna: str,
    tipo: str,
    vuoti: tuple = (),
) -> str:

    """
    Espressione per l'ON CONFLICT del solo --retry: il valore
    appena risolto **sovrascrive** quello in tabella, ma solo se
    e' un valore reale.

    Il retry serve anche a correggere dati raccolti in passato:
    un MX puo' cambiare, un certificato puo' essere rinnovato
    con un altro issuer, un nameserver puo' essere spostato. Se
    il valore gia' presente avesse la precedenza, il retry non
    correggerebbe mai nulla e risolverebbe solo metà del
    problema.

    La parte conservativa resta pero' necessaria, e' l'unica
    cosa che rende il retry sicuro: se la risoluzione di oggi
    non produce niente (timeout, NXDOMAIN transitorio,
    nessun record di quel tipo) il valore precedente non
    viene azzerato. Un record non deve perdere informazioni per
    il solo fatto che oggi la rete non ha risposto.

    Sulle colonne testuali il confronto passa da NULLIF, cosi'
    una stringa vuota non vale come dato. Il NULLIF e' applicato
    solo al valore nuovo: e' quello che decide se c'e' qualcosa
    di reale da scrivere.

        COALESCE(NULLIF(TRIM(excluded.col), ''), tabella.col)

    Se il nuovo e' vuoto o assente si prende il vecchio grezzo,
    senza NULLIF: cosi' il segnaposto mx='' di csi_piem resta
    '' e non diventa NULL, e il record non cambia letterale
    pur restando incompleto e in coda.

    Alcune colonne hanno un valore sentinella che significa
    "non determinato" pur essendo una stringa non vuota, e che
    quindi sopravviveresti a NULLIF. Il caso reale e'
    enti_cname.tls_type: classify_issuer() restituisce
    'unknown' quando il certificato non e' stato ottenuto o
    non e' riconoscibile, e una stringa piena come 'unknown'
    avrebbe cancellato una classificazione vera. Con
    `vuoti=("unknown",)` il sentinella viene trattato come
    un'assenza e il valore precedente resta.

    I NULLIF sono annidati e l'ordine conta: il sentinella va
    eliminato per primo, altrimenti '' continuerebbe a passare
    come dato reale.

        NULLIF(NULLIF(TRIM(excluded.col), 'unknown'), '')

    Sulle colonne numeriche non serve NULLIF: 0 e' un valore
    reale (priorita 0, ASN 0) e non un'assenza. In quel caso il
    0 viene scritto, che e' il comportamento corretto.
    """

    if tipo == "testo":

        espressione = f"TRIM(excluded.{colonna})"

        for sentinella in vuoti:

            espressione = (
                f"NULLIF({espressione}, '{sentinella}')"
            )

        return (
            f"COALESCE(NULLIF({espressione}, ''),"
            f" {tabella}.{colonna})"
        )

    return f"COALESCE(excluded.{colonna}, {tabella}.{colonna})"


# =========================================================
# DATABASE GEOIP
# =========================================================

def geoip_path(name: str) -> Path:

    """
    Percorso assoluto di un database GeoLite2.

    I file stanno in `04 - QueryDNS`. Con un path relativo
    l'apertura fallirebbe appena lo script non gira da li',
    quindi qui il percorso e' sempre assoluto.
    """

    return GEOIP_DIR / name


def open_geoip(name: str):

    """
    Apre un database GeoLite2.

    Termina con codice di uscita 1 se il file manca, non e'
    leggibile o GeoIP2 non e' installato: una dipendenza
    assente e' un errore di configurazione e non deve
    degradare in silenzio lasciando la pipeline a metà.
    """

    path = geoip_path(name)

    try:

        import geoip2.database

    except ImportError:

        logger.critical(
            "GeoIP2 non installato: pip install geoip2"
        )

        raise SystemExit(1)

    if not path.exists():

        logger.critical("Database GeoIP non trovato: %s", path)

        raise SystemExit(1)

    try:

        reader = geoip2.database.Reader(str(path))

    except Exception as e:

        logger.critical(
            "Database GeoIP non leggibile: %s (%s)", path, e
        )

        raise SystemExit(1)

    # geoip2 carica i metadati in modo pigro: un file corrotto
    # supera la costruzione e fallisce solo alla prima lettura,
    # che senza lavoro da fare non arriva mai. La sonda forza
    # subito l'errore.
    #
    # Uso `_db_reader.get()` e non i metodi tipizzati: il
    # GeoLite2-ASN in uso e' di tipo "asn ipvAll" e per quello
    # `reader.asn()` solleva TypeError. L'accessor raw e' quello
    # che usano gia' le pipeline e funziona con qualunque tipo
    # di database. Restituisce None se l'IP non c'e', quindi un
    # semplice "IP assente" non viene scambiato per un errore.
    try:

        reader._db_reader.get("8.8.8.8")

    except Exception as e:

        logger.critical(
            "Database GeoIP non valido: %s (%s)", path, e
        )

        reader.close()

        raise SystemExit(1)

    logger.info("Database GeoIP aperto: %s", path)

    return reader
