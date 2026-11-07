from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import argparse
import sqlite3
import pandas as pd
import dns.resolver
import socket
import ssl
import logging
import sys
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import common
import change_history

# Normalizzazione del dominio e declinazioni da tentare.
# Stesse funzioni usate da get_ns.py e get_mx.py: vedi
# dominio.py per il perche' e per le regole.
from dominio import canonicalizza_dominio, declinazioni

# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger(__name__)

# =========================================================
# LAST CRAWL TIMESTAMP
# =========================================================

CURRENT_CRAWL = datetime.now(ZoneInfo("Europe/Rome")).strftime("%Y-%m-%d %H:%M:%S")

logger.info(f"[CRAWL] Timestamp: {CURRENT_CRAWL}")

# =========================================================
# DNS RESOLVER
# =========================================================

resolver = dns.resolver.Resolver()

resolver.timeout = 10
resolver.lifetime = 10

resolver.nameservers = [
    "8.8.8.8",
    "1.1.1.1"
]

# =========================================================
# DNS GENERICO
# =========================================================

def resolve(domain, record_type):

    if not domain:

        logger.warning(
            f"resolve() saltato: dominio nullo [{record_type}]"
        )

        return []

    try:

        logger.info(
            f"[DNS] Resolving {record_type} -> {domain}"
        )

        answers = resolver.resolve(domain, record_type)

        results = [
            str(r).rstrip(".")
            for r in answers
        ]

        logger.info(
            f"[DNS] {record_type} OK {domain} -> {results}"
        )

        return results

    except dns.resolver.NoAnswer:

        logger.warning(
            f"[DNS] NoAnswer {record_type} -> {domain}"
        )

    except dns.resolver.NXDOMAIN:

        logger.warning(
            f"[DNS] NXDOMAIN -> {domain}"
        )

    except dns.resolver.Timeout:

        logger.warning(
            f"[DNS] Timeout {record_type} -> {domain}"
        )

    except Exception as e:

        logger.error(
            f"[DNS] Errore {record_type} {domain}: {e}"
        )

    return []

# =========================================================
# A RECORD
# =========================================================

def get_ip(domain):

    if not domain:
        return None

    try:

        logger.info(f"[A] Risoluzione IP per {domain}")

        records = resolve(domain, "A")

        if not records:

            logger.warning(
                f"[A] Nessun A record trovato per {domain}"
            )

            return None

        ip = records[0]

        logger.info(f"[A] {domain} -> {ip}")

        return ip

    except Exception as e:

        logger.error(
            f"[A] Errore get_ip({domain}): {e}"
        )

    return None

# =========================================================
# TRACE CNAME
# =========================================================

def trace_cname(domain, max_depth=10):

    logger.info(
        f"[CNAME] Avvio trace CNAME per {domain}"
    )

    current = domain

    visited = set()

    chain = []

    try:

        for depth in range(max_depth):

            logger.info(
                f"[CNAME] Depth={depth} Current={current}"
            )

            if current in visited:

                logger.warning(
                    f"[CNAME] Loop rilevato: {current}"
                )

                break

            visited.add(current)

            cname_records = resolve(current, "CNAME")

            if not cname_records:

                logger.info(
                    f"[CNAME] Nessun CNAME trovato per {current}"
                )

                break

            cname = cname_records[0]

            logger.info(
                f"[CNAME] {current} -> {cname}"
            )

            chain.append(cname)

            current = cname

    except Exception as e:

        logger.error(
            f"[CNAME] Errore trace_cname({domain}): {e}"
        )

    logger.info(f"[CNAME] Finale={current}")

    logger.info(f"[CNAME] Chain={chain}")

    return current, chain

# =========================================================
# TLS
# =========================================================
#
# IP e issuer si leggono con una sola connessione.
#
# Il codice precedente ne usava due: una per l'IP, una per il
# certificato, e in entrambe ritornava None se qualcosa
# falliva. Ma l'IP di un server TLS si conosce gia' dopo
# l'handshake TCP, prima di qualsiasi operazione sui
# certificati. Se il wrap_socket solleva, quell'IP veniva
# buttato via insieme a tutto il resto, e tls_ip finiva NULL
# per enti che di TLS hanno un indirizzo perfettamente noto.
#
# tls_ip e tls_issuer hanno quindi semantica diversa:
#   - tls_ip     -> l'host che termina TLS sulla 443.
#                   Vero anche con certificato scaduto,
#                   self-signed o su un altro nome.
#   - tls_issuer -> chi ha emesso il certificato. Richiede
#                   un handshake riuscito.

def get_tls_info(domain, permissive=False):

    """
    Ritorna (ip, issuer) per un host.

    `permissive` disattiva la verifica di catena e hostname.
    Non e' il default perche' cambia il significato di
    tls_issuer: un certificato che non si verifica non e' la
    stessa cosa di un certificato emesso da una CA note, e i
    record gia' in tabella sono stati raccolti con la
    verifica attiva.
    """

    if not domain:
        return (None, None)

    ctx = ssl.create_default_context()

    if permissive:

        ctx.check_hostname = False

        ctx.verify_mode = ssl.CERT_NONE

        logger.info(
            f"[TLS] Verifica disattivata per {domain} "
            f"(modalita' permissiva)"
        )

    try:

        logger.info(
            f"[TLS] Connessione TLS -> {domain}:443"
        )

        with socket.create_connection(
            (domain, 443),
            timeout=8
        ) as sock:

            # Disponibile subito: e' l'IP del peer TCP e non
            # dipende dal certificato.
            ip = sock.getpeername()[0]

            logger.info(
                f"[TLS] Peer IP {domain} -> {ip}"
            )

            try:

                with ctx.wrap_socket(
                    sock,
                    server_hostname=domain
                ) as ssock:

                    cert = ssock.getpeercert() or {}

            except ssl.SSLError as e:

                # L'handshake e' fallito ma l'IP c'e'. Si
                # restituisce quello: e' l'informazione che
                # tls_ip deve rappresentare. tls_issuer resta
                # None perche' il certificato non e' stato
                # letto.
                logger.warning(
                    f"[TLS] Handshake fallito su {domain} "
                    f"({e}), ma l'IP resta utilizzabile: {ip}"
                )

                return (ip, None)

        issuer = dict(
            x[0]
            for x in cert.get("issuer", [])
        )

        organization = issuer.get(
            "organizationName"
        )

        logger.info(
            f"[TLS] Issuer {domain} -> {organization}"
        )

        return (ip, organization)

    except Exception as e:

        logger.error(
            f"[TLS] Errore TLS {domain}: {e}"
        )

    return (None, None)

# =========================================================
# RISOLUZIONE SU DECLINAZIONI
# =========================================================
#
# Ogni stadio della pipeline (A, CNAME, TLS) prova le
# declinazioni del dominio in ordine e si ferma alla prima
# che dà un risultato. Le declinazioni sono indipendenti
# per stadio: il dominio nudo puo' dare l'A record mentre il
# TLS e' valido solo su www, e in quel caso tls_ip
# proviene da un nome diverso da a_record. E' il comportamento
# corretto: i due campi descrivono due interrogazioni
# diverse, non una stessa risposta.

def risolvi_a(host, decl):

    """
    Primo A record trovato fra le declinazioni.
    """

    for h in decl:

        ip = get_ip(h)

        if ip:

            if h != host:

                logger.info(
                    f"[FALLBACK] A record trovato su {h} "
                    f"invece che su {host}"
                )

            return (ip, h)

    return (None, None)


def risolvi_cname(host, decl):

    """
    Catena CNAME del dominio.

    Si preferisce la prima declinazione che espone una
    catena vera. Se nessuna la espone si conserva la prima
    declinazione tentata: senza CNAME, cname_final coincide
    con il dominio di partenza, che e' la semantica che
    avevano i record precedenti.
    """

    primo = None

    for h in decl:

        finale, catena = trace_cname(h)

        if catena:

            if h != host:

                logger.info(
                    f"[FALLBACK] CNAME trovato su {h} "
                    f"invece che su {host}"
                )

            return (finale, catena, h)

        if primo is None:

            primo = (finale, catena, h)

    return primo


def risolvi_tls(host, decl, permissive=False):

    """
    TLS del dominio, provando le declinazioni.

    Si accetta la prima declinazione che fornisce un IP: un
    issuer assente non e' motivo per continuare a provare,
    perche' l'host e' lo stesso e il certificato manco.
    """

    for h in decl:

        ip, issuer = get_tls_info(h, permissive)

        if ip:

            if h != host:

                logger.info(
                    f"[FALLBACK] TLS raggiunto su {h} "
                    f"invece che su {host}"
                )

            return (ip, issuer, h)

    return (None, None, None)

# =========================================================
# TLS CLASSIFICATION
# =========================================================

def classify_issuer(issuer):

    if not issuer:
        return "unknown"

    i = issuer.lower()

    if any(x in i for x in [
        "let's encrypt",
        "actalis",
        "globalsign",
        "digicert",
        "sectigo"
    ]):
        return "public_ca"

    if "cloudflare" in i:
        return "cdn_cloudflare"

    if "google" in i:
        return "cloud_google"

    if "amazon" in i:
        return "cloud_aws"

    if "microsoft" in i:
        return "cloud_azure"

    if "gogetssl" in i:
        return "ca_reseller"

    return "unknown"

# =========================================================
# ASN LOOKUP
# =========================================================

def get_asn_info(ip, reader):

    if not ip:

        logger.warning(
            "[ASN] ASN lookup saltato: IP nullo"
        )

        return (None, None)

    try:

        logger.info(
            f"[ASN] Lookup ASN -> {ip}"
        )

        record = reader._db_reader.get(ip)

        if not record:

            logger.warning(
                f"[ASN] Nessun ASN trovato per {ip}"
            )

            return (None, None)

        asn_number = record.get(
            "autonomous_system_number"
        )

        asn_org = record.get(
            "autonomous_system_organization"
        )

        logger.info(
            f"[ASN] {ip} -> ASN={asn_number} ORG={asn_org}"
        )

        return (asn_number, asn_org)

    except Exception as e:

        logger.error(
            f"[ASN] Errore lookup ASN {ip}: {e}"
        )

    return (None, None)

# =========================================================
# MAIN
# =========================================================

def main(ritentativa=False, max_run=None, tls_permissive=False, ricalcola=False):

    if ritentativa and ricalcola:
        logger.error("Usare --retry o --recalculate, non entrambi")
        sys.exit(1)

    if ritentativa:

        logger.info("=================================================")
        logger.info("MODALITA' RITENTATIVA: record con campi NULL")
        logger.info("=================================================")
    elif ricalcola:

        logger.info("=================================================")
        logger.info("MODALITA' RICALCOLO: rileggo enti_contatti e ricalcolo ex novo")
        logger.info("=================================================")

    else:

        logger.info("=================================================")
        logger.info("AVVIO PIPELINE CNAME + TLS + ASN")
        logger.info("=================================================")

    if tls_permissive:

        logger.warning(
            "[TLS] Modalita' permissiva: catena e hostname non "
            "verificati. tls_issuer raccogliera' emittenti di "
            "certificati non verificabili."
        )

    # =====================================================
    # CONFIG
    # =====================================================

    try:

        config = common.config()

        db_name = common.db_path()

        logger.info(
            f"[CONFIG] Database: {db_name}"
        )

    except Exception as e:

        logger.critical(
            f"[CONFIG] Errore caricamento config: {e}"
        )

        sys.exit(1)

    # =====================================================
    # DB CONNECTION
    # =====================================================

    try:

        conn = sqlite3.connect(db_name)

        conn.row_factory = sqlite3.Row

        cursor = conn.cursor()

        logger.info(
            f"[DB] Connesso a {db_name}"
        )

    except Exception as e:

        logger.critical(
            f"[DB] Errore connessione DB: {e}"
        )

        sys.exit(1)

    change_history.ensure_table(conn)

    NOME_SCRIPT = Path(__file__).name
    NOME_TABELLA = "enti_cname"
    CHIAVE_NOME = "codice_IPA"
    CAMPI_STORICO = (
        "codice_istat",
        "dominio",
        "a_record",
        "a_asn",
        "cname_final",
        "cname_ip",
        "cname_asn",
        "tls_ip",
        "tls_asn",
        "tls_issuer",
        "tls_type",
    )

    # =====================================================
    # ASN DB
    # =====================================================

    asn_reader = common.open_geoip("GeoLite2-ASN.mmdb")

    # =====================================================
    # CREATE TABLES
    # =====================================================

    try:

        logger.info("[DB] Verifica tabelle")

        cursor.execute("""

            CREATE TABLE IF NOT EXISTS enti_cname (

                codice_IPA TEXT PRIMARY KEY NOT NULL,
                codice_istat INTEGER,

                dominio TEXT,

                a_record TEXT,
                a_asn INTEGER,

                cname_final TEXT,
                cname_ip TEXT,
                cname_asn INTEGER,

                tls_ip TEXT,
                tls_asn INTEGER,

                tls_issuer TEXT,
                tls_type TEXT,

                last_crawl TEXT
            )

        """)

        common.ensure_asn_table(conn)

        logger.info("[DB] Tabelle OK")

    except Exception as e:

        logger.critical(
            f"[DB] Errore creazione tabelle: {e}"
        )

        sys.exit(1)

    # =====================================================
    # QUERY
    # =====================================================

    limit = config.get("max_run", 10)

    if max_run is not None:

        limit = max_run

    logger.info(f"[DB] LIMIT = {limit}")

    campi_in_coda = (
        "a_record",
        "a_asn",
        "cname_ip",
        "cname_asn",
        "tls_ip",
        "tls_asn",
        "tls_issuer",
    )

    tipo_campi = {
        "a_record": "testo",
        "a_asn": "intero",
        "cname_ip": "testo",
        "cname_asn": "intero",
        "tls_ip": "testo",
        "tls_asn": "intero",
        "tls_issuer": "testo",
        "cname_final": "testo",
        "tls_type": "testo",
    }

    if ritentativa:

        condizione = common.condizione_coda(campi_in_coda)
        campi_pieni = common.conteggio_campi_pieni(campi_in_coda)
        query = f"""
            SELECT
                codice_IPA AS codice_ipa,
                codice_istat AS codice_istat,
                dominio
            FROM enti_cname
            WHERE {condizione}
            ORDER BY last_crawl ASC, ({campi_pieni}) DESC, codice_IPA
            LIMIT ?
        """
        try:
            df = pd.read_sql_query(query, conn, params=(limit,))
            logger.info(f"[DB] Record trovati: {len(df)}")
        except Exception as e:
            logger.critical(f"[DB] Errore query: {e}")
            sys.exit(1)

    elif ricalcola:

        query = """
            SELECT
                t.codice_IPA AS codice_ipa,
                t.codice_istat AS codice_istat,
                c.Sito_istituzionale AS dominio_grezzo_contatti
            FROM enti_cname t
            LEFT JOIN enti_contatti c ON c.Codice_IPA = t.codice_IPA
            ORDER BY t.last_crawl ASC, t.codice_IPA
            LIMIT ?
        """
        try:
            df = pd.read_sql_query(query, conn, params=(limit,))
            logger.info(f"[DB] Record trovati: {len(df)}")
        except Exception as e:
            logger.critical(f"[DB] Errore query: {e}")
            sys.exit(1)

    else:

        query = """
            SELECT codice_IPA AS codice_ipa, codice_istat AS codice_istat, sito_istituzionale AS dominio
            FROM enti_contatti
            WHERE sito_istituzionale IS NOT NULL
              AND sito_istituzionale != ''
              AND codice_IPA IS NOT NULL
              AND codice_IPA != ''
              AND (codice_IPA NOT IN (
                    SELECT codice_IPA FROM enti_cname
                   )
                  )
            LIMIT ?
        """
        try:
            df = pd.read_sql_query(query, conn, params=(limit,))
            logger.info(f"[DB] Record trovati: {len(df)}")
        except Exception as e:
            logger.critical(f"[DB] Errore query: {e}")
            sys.exit(1)

    if df.empty:

        logger.info(
            "[DB] Nessun record da processare"
        )
        asn_reader.close()
        conn.close()
        return

    # =====================================================
    # LOOP
    # =====================================================

    results = []

    inserted_asn = 0

    recuperati = 0
    processed = 0
    skipped = 0
    deleted_count = 0

    if ricalcola:
        old_rows = {}
        for r in df.itertuples():
            old_rows[r.codice_ipa] = dict(cursor.execute(
                "SELECT * FROM enti_cname WHERE codice_IPA = ?",
                (r.codice_ipa,)
            ).fetchone() or {})

    for i, row in df.iterrows():

        dominio_grezzo = None

        try:

            codice_ipa = row["codice_ipa"]

            codice_istat = row["codice_istat"]

            if ricalcola:
                dominio_grezzo_contatti = row["dominio_grezzo_contatti"]
                if dominio_grezzo_contatti is None or str(dominio_grezzo_contatti).strip() == '':
                    old = old_rows.get(codice_ipa) or {}
                    del_mods = []
                    for c in CAMPI_STORICO:
                        v_old = old.get(c)
                        if v_old is not None and str(v_old).strip() != '':
                            del_mods.append((c, v_old, None))
                    if del_mods:
                        righe_h = change_history.costruisci_righe(
                            NOME_TABELLA, CHIAVE_NOME, codice_ipa, del_mods,
                            script=NOME_SCRIPT, tipo_operazione='DEL'
                        )
                        change_history.inserisci(conn, righe_h)
                    cursor.execute("DELETE FROM enti_cname WHERE codice_IPA = ?", (codice_ipa,))
                    deleted_count += 1
                    processed += 1
                    continue
                dominio_grezzo = dominio_grezzo_contatti
            else:
                dominio_grezzo = row["dominio"]

            # sito_istituzionale e' un campo libero e puo'
            # contenere URL, percorsi o porte. Il resolver
            # accetta solo un nome di host, quindi la riduzione
            # avviene prima di ogni chiamata di rete.
            dominio = canonicalizza_dominio(dominio_grezzo)

            logger.info("-------------------------------------------------")

            logger.info(
                f"[{i+1}/{len(df)}] codice_IPA={codice_ipa}, "
                f"codice_istat={codice_istat}, "
                f"DOMINIO: {dominio_grezzo!r} -> {dominio!r}"
            )

            logger.info("-------------------------------------------------")

            if not dominio:

                logger.warning(
                    f"[SKIP] Dominio non utilizzabile per "
                    f"codice_IPA={codice_ipa}: {dominio_grezzo!r}"
                )

                skipped += 1
                if ricalcola:
                    try:
                        cursor.execute("UPDATE enti_cname SET last_crawl = ? WHERE codice_IPA = ?", (CURRENT_CRAWL, codice_ipa))
                    except Exception:
                        pass
                continue

            # La declinazione con www entra solo come secondo
            # tentativo, quindi il comportamento sul dominio
            # come scritto nel DB non cambia.
            decl = declinazioni(dominio)

            logger.info(
                f"[DECLINAZIONI] {' | '.join(decl)}"
            )

            # =================================================
            # A RECORD
            # =================================================

            logger.info("[L1] A RECORD")

            a_record, host_a = risolvi_a(dominio, decl)

            a_asn, a_org = get_asn_info(
                a_record,
                asn_reader
            )

            # =================================================
            # ASN INSERT
            # =================================================

            if a_asn:

                try:

                    if common.upsert_asn(
                        conn, a_asn, a_org, CURRENT_CRAWL
                    ):

                        inserted_asn += 1

                        logger.info(
                            f"[ASN] Inserito nuovo ASN {a_asn}"
                        )

                except Exception as e:

                    logger.error(
                        f"[ASN] Errore insert ASN {a_asn}: {e}"
                    )

            # =================================================
            # CNAME
            # =================================================

            logger.info("[L2] CNAME")

            cname_final, cname_chain, host_cname = risolvi_cname(
                dominio, decl
            )

            # cname_ip si risolve sul nome finale della catena,
            # non sulle declinazioni del dominio: la catena ha
            # gia' indicato il nome a cui puntare, e rifare
            # le declinazioni su un nome terzo produrrebbe
            # coppie host/ASN non corrispondenti.
            cname_ip = get_ip(cname_final)

            if not cname_ip:

                # Caso reale: la catena punta a un nome senza
                # A record. Si tenta il www del nome finale.
                for h in declinazioni(cname_final):

                    cname_ip = get_ip(h)

                    if cname_ip:

                        logger.info(
                            f"[FALLBACK] cname_ip trovato su {h}"
                        )

                        break

            cname_asn, cname_org = get_asn_info(
                cname_ip,
                asn_reader
            )

            if cname_asn:

                try:

                    if common.upsert_asn(
                        conn, cname_asn, cname_org, CURRENT_CRAWL
                    ):

                        inserted_asn += 1

                        logger.info(
                            f"[ASN] Inserito nuovo ASN {cname_asn}"
                        )

                except Exception as e:

                    logger.error(
                        f"[ASN] Errore insert ASN CNAME {cname_asn}: {e}"
                    )

            # =================================================
            # TLS
            # =================================================

            logger.info("[L3] TLS")

            tls_ip, tls_issuer, host_tls = risolvi_tls(
                dominio, decl, tls_permissive
            )

            tls_asn, tls_org = get_asn_info(
                tls_ip,
                asn_reader
            )

            if tls_asn:

                try:

                    if common.upsert_asn(
                        conn, tls_asn, tls_org, CURRENT_CRAWL
                    ):

                        inserted_asn += 1

                        logger.info(
                            f"[ASN] Inserito nuovo ASN {tls_asn}"
                        )

                except Exception as e:

                    logger.error(
                        f"[ASN] Errore insert ASN TLS {tls_asn}: {e}"
                    )

            tls_type = classify_issuer(tls_issuer)

            # =================================================
            # ESITO
            # =================================================
            #
            # In --retry il record viene scritto anche quando
            # non ha guadagnato nulla. Scrivere lo stesso NULL
            # sui campi che erano NULL non cambia i dati in
            # tabella, ma aggiorna last_crawl, che è la data di
            # ultimo tentativo: è questo che fa ruotare la coda
            # (ORDER BY last_crawl ASC). Senza la scrittura il
            # record non uscirebbe mai dal primo blocco e
            # verrebbe riprovato per sempre.

            campi = (
                a_record, a_asn,
                cname_ip, cname_asn,
                tls_ip, tls_asn, tls_issuer,
            )

            risolto = any(c is not None for c in campi)

            if ritentativa and not risolto:

                logger.warning(
                    f"[RETRY] Nessun campo recuperato per "
                    f"codice_IPA={codice_ipa}, dominio={dominio}: "
                    f"resta incompleto, ma il tentativo viene "
                    f"datato e il record torna in fondo alla coda"
                )

            if risolto:

                recuperati += 1

            # =================================================
            # RESULT
            # =================================================
            #
            # `dominio` conserva il valore ridotto, non
            # quello grezzo: i record precedenti hanno
            # già il nome di host pulito e la colonna deve
            # restare confrontabile con loro. Il fallback su
            # www non altera il dominio memorizzato, perché
            # cname_final, a_record e tls_ip dicono già da
            # quale nome sono stati ricavati.

            results.append({

                "codice_IPA": codice_ipa,
                "codice_istat": (
                    int(codice_istat)
                    if pd.notna(codice_istat)
                    else None
                ),
                "dominio": dominio,

                "a_record": a_record,
                "a_asn": a_asn,

                "cname_final": cname_final,
                "cname_ip": cname_ip,
                "cname_asn": cname_asn,

                "tls_ip": tls_ip,
                "tls_asn": tls_asn,

                "tls_issuer": tls_issuer,
                "tls_type": tls_type,

                "last_crawl": CURRENT_CRAWL
            })

            logger.info(
                f"[OK] Elaborazione completata per {dominio} "
                f"(A={host_a}, CNAME={host_cname}, TLS={host_tls})"
            )
            processed += 1

        except Exception as e:

            logger.error(
                f"[FATAL DOMAIN ERROR] {dominio_grezzo!r}: {e}"
            )

            traceback.print_exc()

    # =====================================================
    # WRITE
    # =====================================================

    try:

        logger.info(
            "[WRITE] Scrittura risultati DB"
        )

        written = 0

        # In --retry l'upsert non deve mai cancellare un dato
        # che era gia' presente. La coda contiene record in
        # parte completi, e una risoluzione fallita oggi
        # (un timeout, un NXDOMAIN transitorio) non puo'
        # azzerare un a_record raccolto mesi fa: il record
        # uscirebbe dalla coda con meno informazioni di
        # quante ne aveva. COALESCE tiene il valore esistente
        # quando quello nuovo e' assente.
        #
        # Le colonne aggiornate sono tutte, anche quelle fuori
        # coda come cname_final e tls_type: se il retry non
        # le tocca restano comunque in tabella.
        campi_aggiornate = (
            "a_record", "a_asn",
            "cname_final", "cname_ip", "cname_asn",
            "tls_ip", "tls_asn",
            "tls_issuer", "tls_type",
        )

        if ritentativa:

            colonna = {
                c: common.conserva_valore(
                    "enti_cname", c, tipo_campi[c],
                    # 'unknown' e' il fallback di
                    # classify_issuer(): non significa che il
                    # certificato e' sconosciuto, ma che non si
                    # e' riusciti a Guardarlo. Senza questo la
                    # stringa, essendo non vuota, passava il
                    # NULLIF e un retry senza rete cancellava
                    # una classificazione reale:
                    # public_ca -> unknown.
                    vuoti=("unknown",)
                        if c == "tls_type" else (),
                )
                for c in campi_aggiornate
            }

            # cname_final non e' un dato ma una conseguenza
            # della risoluzione: risolvi_cname() restituisce la
            # prima declinazione tentata quando non trova
            # alcuna catena CNAME, quindi ritorna sempre un
            # valore. Se il retry non ha scoperto una catena
            # nuova non ha nulla da dire su questo campo, e il
            # fallback locale sovrascriverebbe il CNAME vero
            # risolto in precedenza (www.esempio.it ->
            # esempio.it). Senza catena si congela il valore
            # di tabella.
            if not cname_chain:

                colonna["cname_final"] = "enti_cname.cname_final"

        else:

            colonna = {c: f"excluded.{c}" for c in campi_aggiornate}

        for rec in results:

            try:
                old = dict(cursor.execute("SELECT * FROM enti_cname WHERE codice_IPA = ?", (rec["codice_IPA"],)).fetchone() or {})

                cursor.execute("""

                    INSERT INTO enti_cname (

                        codice_IPA,
                        codice_istat,
                        dominio,

                        a_record,
                        a_asn,

                        cname_final,
                        cname_ip,
                        cname_asn,

                        tls_ip,
                        tls_asn,

                        tls_issuer,
                        tls_type,

                        last_crawl

                    )

                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

                    ON CONFLICT(codice_IPA) DO UPDATE SET

                        codice_istat = excluded.codice_istat,
                        dominio      = excluded.dominio,

                        a_record     = {a_record},
                        a_asn        = {a_asn},

                        cname_final  = {cname_final},
                        cname_ip     = {cname_ip},
                        cname_asn    = {cname_asn},

                        tls_ip       = {tls_ip},
                        tls_asn      = {tls_asn},

                        tls_issuer   = {tls_issuer},
                        tls_type     = {tls_type},

                        last_crawl   = excluded.last_crawl

                """.format(
                    a_record=colonna["a_record"],
                    a_asn=colonna["a_asn"],
                    cname_final=colonna["cname_final"],
                    cname_ip=colonna["cname_ip"],
                    cname_asn=colonna["cname_asn"],
                    tls_ip=colonna["tls_ip"],
                    tls_asn=colonna["tls_asn"],
                    tls_issuer=colonna["tls_issuer"],
                    tls_type=colonna["tls_type"],
                ), (

                    rec["codice_IPA"],
                    rec["codice_istat"],
                    rec["dominio"],

                    rec["a_record"],
                    rec["a_asn"],

                    rec["cname_final"],
                    rec["cname_ip"],
                    rec["cname_asn"],

                    rec["tls_ip"],
                    rec["tls_asn"],

                    rec["tls_issuer"],
                    rec["tls_type"],

                    rec["last_crawl"]

                ))

                new = dict(cursor.execute("SELECT * FROM enti_cname WHERE codice_IPA = ?", (rec["codice_IPA"],)).fetchone() or {})
                if old:
                    vecchio_vals = [old.get(c) for c in CAMPI_STORICO]
                    nuovo_vals = [new.get(c) for c in CAMPI_STORICO]
                    mods = change_history.confronta(vecchio_vals, nuovo_vals, CAMPI_STORICO)
                    if mods:
                        righe_h = change_history.costruisci_righe(
                            NOME_TABELLA, CHIAVE_NOME, rec["codice_IPA"], mods,
                            script=NOME_SCRIPT, tipo_operazione='MOD'
                        )
                        change_history.inserisci(conn, righe_h)

                written += 1

            except Exception as e:

                logger.error(
                    f"[WRITE] Errore upsert per "
                    f"codice_IPA={rec['codice_IPA']}: {e}"
                )

        conn.commit()

        if ricalcola:
            logger.info(f"[WRITE] Inseriti/Aggiornati {written} record in enti_cname, cancellati {deleted_count}, skip {skipped}")
        else:
            logger.info(f"[WRITE] Inseriti/Aggiornati {written} record in enti_cname")
        logger.info(f"[WRITE] Nuovi ASN inseriti: {inserted_asn}")

    except Exception as e:

        logger.critical(
            f"[WRITE] Errore scrittura DB: {e}"
        )

        raise SystemExit(1)

    # =====================================================
    # RESIDUI
    # =====================================================
    #
    # Va fatto prima del CLEANUP: il conteggio usa la stessa
    # connessione, e su una connessione chiusa sqlite3 solleva
    # 'Cannot operate on a closed database'. Essendo in coda
    # dopo la chiusura, il --retry finiva con un traceback
    # nonostante avesse appena scritto e committato i dati.

    if ritentativa:

        logger.info(
            f"[RETRY] Record con almeno un dato: {recuperati}"
        )

        campi = (
            "a_record", "a_asn", "cname_ip", "cname_asn",
            "tls_ip", "tls_asn", "tls_issuer",
        )

        residui = cursor.execute(
            f"""
            SELECT COUNT(*) FROM enti_cname
            WHERE {common.condizione_coda(campi)}
            """
        ).fetchone()[0]

        logger.info(
            f"[RETRY] Record ancora incompleti in tabella: {residui}"
        )

    # =====================================================
    # CLEANUP
    # =====================================================

    try:

        asn_reader.close()

        conn.close()

        logger.info(
            "[CLEANUP] Risorse chiuse"
        )

    except Exception as e:

        logger.warning(
            f"[CLEANUP] Errore cleanup: {e}"
        )

    logger.info("=================================================")
    logger.info("PIPELINE COMPLETATA")
    logger.info("=================================================")

# =========================================================
# ENTRYPOINT
# =========================================================

if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description=(
            "Raccoglie A record, catena CNAME, TLS e ASN per "
            "gli enti di enti_contatti. "
            "Ogni dominio viene gia' tentato come e' scritto "
            "nel database, poi con il prefisso www."
        )
    )

    parser.add_argument(
        "--retry",
        action="store_true",
        help=(
            "Riprova i record gia' in enti_cname che hanno "
            "a_record, a_asn, cname_ip, cname_asn, tls_ip, "
            "tls_asn o tls_issuer NULL, invece di prendere "
            "enti nuovi da enti_contatti"
        )
    )

    parser.add_argument(
        "--recalculate",
        action="store_true",
        dest="recalculate",
        help=(
            "Ricalcola ex novo i record presenti in enti_cname "
            "rileggendo il dominio da enti_contatti"
        )
    )

    parser.add_argument(
        "--max-run",
        type=int,
        default=None,
        help=(
            "Numero massimo di record da elaborare "
            "(default: max_run da config.yaml)"
        )
    )

    parser.add_argument(
        "--tls-permissive",
        action="store_true",
        help=(
            "Non verificare catena e hostname del certificato. "
            "Recupera tls_issuer anche da certificati "
            "self-signed, scaduti o emessi per un altro nome, "
            "ma il dato non e' piu' confrontabile con quello "
            "raccolto senza questa opzione"
        )
    )

    args = parser.parse_args()

    main(
        ritentativa=args.retry,
        max_run=args.max_run,
        tls_permissive=args.tls_permissive,
        ricalcola=args.recalculate,
    )