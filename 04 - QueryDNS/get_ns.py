#!/usr/bin/env python3

import sqlite3
import pandas as pd
import dns.resolver
import socket
import logging
import sys
import argparse
import traceback

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import common
import change_history

# Normalizzazione del dominio e declinazioni da tentare.
# Stesse funzioni usate da get_cname.py e get_mx.py: vedi
# dominio.py per il perche' e per le regole.
from dominio import canonicalizza_dominio, declinazioni

# ===========================
# Logging avanzato + verbose
# ===========================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger(__name__)

# ===========================
# TIMEZONE ROMA
# ===========================

CURRENT_CRAWL = datetime.now(
    ZoneInfo("Europe/Rome")
).strftime("%Y-%m-%d %H:%M:%S")

logger.info(f"[CRAWL] Timestamp inizio: {CURRENT_CRAWL}")

# ===========================================================
# NAMESPACES DEL REGISTRO
# ===========================================================
#
# Nameserver che amministrano un registro di nomi invece
# dell'ente che ha delegato sotto quell'apex.
#
# Il caso italiano: 6953 scuole hanno il dominio sotto
# .edu.it e 65 enti sotto .gov.it. Queste zone non sono
# tenant: sono le categorie che il Registro .it delega,
# e i loro nameserver sono a.dns.it, m.dns.it, r.dns.it.
#
# Senza questo controllo il fallback apex assegnerebbe a
# tutti quei 7018 record lo stesso nameserver del registro.
# Non e' falso in senso stretto, quei nameserver servono
# davvero quelle zone, ma non e' un dato dell'ente: e'
# identico per tutti, quindi non distingue un'ente che
# gestisce il proprio DNS da uno che dipende dal registro, e
# finirebbe nel calcolo ISDC come se fosse
# l'infrastruttura dell'amministrazione.

_NS_REGISTRY = frozenset({
    "a.dns.it",
    "m.dns.it",
    "r.dns.it",
    "dns.edu.it",
})

_APEX_REGISTRY = frozenset({
    "edu.it",
    "gov.it",
})

# ===========================
# ASN lookup
# ===========================

def get_asn_info(ip, reader):

    if not ip:
        logger.debug("ASN: IP vuoto → None")
        return (None, None)

    try:

        logger.debug(f"ASN: lookup IP {ip}")

        record = reader._db_reader.get(ip)

        if not record:

            logger.warning(
                f"ASN: nessun record ASN per IP {ip}"
            )

            return (None, None)

        asn = record.get('autonomous_system_number')
        org = record.get('autonomous_system_organization')

        logger.info(
            f"ASN: {ip} → ASN={asn} ORG={org}"
        )

        return (asn, org)

    except Exception as e:

        logger.error(
            f"ASN: errore lookup ASN per IP {ip}: {e}"
        )

        return (None, None)

# ===========================
# NS lookup
# ===========================

def get_primary_ns(domain):

    resolver = dns.resolver.Resolver()

    resolver.timeout = 10
    resolver.lifetime = 10

    resolver.nameservers = [
        '8.8.8.8',
        '1.1.1.1'
    ]

    logger.debug(
        f"NS: lookup dominio {domain}"
    )

    try:

        answers = resolver.resolve(domain, 'NS')

        ns_records = sorted([
            str(r.target).rstrip('.')
            if hasattr(r, 'target')
            else str(r).rstrip('.')
            for r in answers
        ])

        if not ns_records:

            logger.warning(
                f"NS: nessun NS trovato per {domain}"
            )

            return None

        primary_ns = ns_records[0]

        logger.info(
            f"NS: trovato {primary_ns} per {domain}"
        )

        return primary_ns

    except dns.resolver.NoAnswer:

        # Caso normale e non un errore: il nome esiste ma non
        # e' l'apex di una zona, quindi non ha record NS
        # propri. Su un sottodominio questa e' la risposta
        # normale, non un guasto. La risoluzione dei genitori
        # la fa apex_ns().
        logger.debug(
            f"NS: {domain} esiste ma non e' apex di zona "
            f"(NoAnswer)"
        )

        return None

    except dns.resolver.NXDOMAIN:

        logger.debug(
            f"NS: {domain} non esiste (NXDOMAIN)"
        )

        return None

    except Exception as e:

        logger.error(
            f"NS: errore risoluzione NS per {domain}: {e}"
        )

        return None


def apex_ns(domain):

    """
    Restituisce (apex, ns) risalendo la gerarchia fino a
    trovare una zona con NS propri.

    Serve perche' gli NS esistono solo all'apex della zona:
    'latina.cri.it' non ha record NS, ma e' servita dai
    nameserver di 'cri.it'. Il resolver ricorsivo risponde
    NoAnswer al sottodominio, quindi l'unico modo per
    ottenere i nameserver che lo servono davvero e' salire
    di livello finche' la query torna con dati.

    La risposta non e' un NS "dell'ente" nel senso di una
    zona dedicata: e' il nameserver che amministra la zona
    in cui il dominio si trova. Per 'comune.example.it'
    coincide con quello dell'ente; per
    'scuola.example.it' descrive il provider di example.it.
    Entrambi i casi sono informazione utile, ma non sono la
    stessa cosa, e il log dice quale dei due e' stato usato.
    """

    if not domain:

        return None, None

    parti = domain.split(".")

    # Non si sale sopra il TLD: gli NS del TLD sono quelli
    # del registry, non del tenant.
    while len(parti) > 2:

        parti = parti[1:]

        candidato = ".".join(parti)

        try:

            resolver = dns.resolver.Resolver()

            resolver.timeout = 10
            resolver.lifetime = 10
            resolver.nameservers = ['8.8.8.8', '1.1.1.1']

            risposta = resolver.resolve(candidato, 'NS')

            ns = sorted([
                str(r.target).rstrip('.')
                if hasattr(r, 'target')
                else str(r).rstrip('.')
                for r in risposta
            ])

            if ns:

                # Gli NS del registry descrivono il
                # registro, non l'ente che ha delegato li'.
                # 'scuola.edu.it' e' servita da a.dns.it, ma
                # a.dns.it e' il registry del .it: e' uguale
                # per tutte le 6953 scuole e non dice nulla
                # sulla loro infrastruttura. Registrandolo,
                # l'indicatore di sovranita' misurerebbe il
                # registro e non l'amministrazione.
                if is_registry(ns[0], candidato):

                    logger.info(
                        f"NS: apex {candidato} usa i nameserver "
                        f"del registry ({ns[0]}): scartato, non "
                        f"descrive l'infrastruttura dell'ente"
                    )

                    return None, None

                logger.info(
                    f"NS: {domain} senza NS propri, apex "
                    f"{candidato} -> {ns[0]}"
                )

                return candidato, ns[0]

        except dns.resolver.NoAnswer:

            # Zona intermedia senza NS: si sale ancora.
            continue

        except Exception:

            # NXDOMAIN o timeout: risalire oltre produrrebbe
            # NS piu' lontani e sempre meno pertinenti.
            break

    return None, None


def is_registry(ns, apex):
    """
    True se i nameserver appartengono a un registro di
    nomi, non al tenant che ha delegato sotto quell'apex.

    Nel caso italiano i registri hanno nomi riconoscibili:
    il .it e' servito dai dns.it di Registro .it, e le
    categorie delegate edu.it e gov.it usano gli stessi
    nameserver. Un altro nome pubblico del .it sarebbe
    falso positivo solo se coincidesse, e in quel caso
    sarebbe comunque il registry a rispondere.
    """

    return (
        ns in _NS_REGISTRY
        or apex in _APEX_REGISTRY
    )

# ===========================
# IP lookup
# ===========================

def get_ip(hostname):

    if not hostname:

        logger.debug(
            "IP: hostname vuoto → None"
        )

        return None

    try:

        logger.debug(
            f"IP: resolve hostname {hostname}"
        )

        ip = socket.gethostbyname(hostname)

        logger.info(
            f"IP: {hostname} → {ip}"
        )

        return ip

    except Exception as e:

        logger.warning(
            f"IP: impossibile risolvere "
            f"{hostname}: {e}"
        )

        return None

# ===========================
# MAIN
# ===========================

def main(ritentativa=False, max_run=None, ricalcola=False):

    logger.info(
        "=== START NS PIPELINE ==="
    )

    if ritentativa and ricalcola:
        logger.error("Usare --retry o --recalculate, non entrambi")
        return

    if ritentativa:

        logger.info(
            "[RETRY] Modalita' ritentativa: riprovo i record "
            "in enti_ns con ns_primary, ns_ip o ns_asn NULL"
        )
    elif ricalcola:

        logger.info(
            "[RECALCULATE] Modalita' ricalcolo: rileggo enti_contatti e "
            "ricalcolo ex novo da enti_ns ordinati per last_crawl ASC"
        )

    # =======================
    # CONFIG
    # =======================

    config = common.config()

    # =======================
    # DB
    # =======================

    db_path = common.db_path()

    logger.info(
        f"DB: connetto a {db_path}"
    )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    change_history.ensure_table(conn)

    NOME_SCRIPT = Path(__file__).name
    NOME_TABELLA = "enti_ns"
    CHIAVE_NOME = "codice_IPA"
    CAMPI_STORICO = (
        "codice_istat",
        "dominio",
        "ns_primary",
        "ns_ip",
        "ns_asn",
    )

    # =======================
    # TABLES
    # =======================

    logger.info(
        "DB: creo/verifico tabelle"
    )

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS enti_ns (
            codice_IPA TEXT PRIMARY KEY NOT NULL,
            codice_istat INTEGER,
            dominio TEXT,
            ns_primary TEXT,
            ns_ip TEXT,
            ns_asn INTEGER,
            last_crawl TEXT
        )
    """)

    common.ensure_asn_table(conn)

    # La dipendenza si valida subito
    asn_reader = common.open_geoip("GeoLite2-ASN.mmdb")

    # =======================
    # SELECT LIMITATA
    # =======================

    limit = max_run if max_run is not None else config.get('max_run', 10)

    logger.info(
        f"Limit: {limit} record massimo per questa run"
    )

    campi_in_coda = (
        "ns_primary",
        "ns_ip",
        "ns_asn",
    )

    tipo_campi = {
        "ns_primary": "testo",
        "ns_ip": "testo",
        "ns_asn": "intero",
    }

    if ritentativa:

        condizione = common.condizione_coda(campi_in_coda)
        campi_pieni = common.conteggio_campi_pieni(campi_in_coda)

        query = f"""
            SELECT
                codice_IPA AS codice_ipa,
                codice_istat AS codice_istat,
                dominio
            FROM enti_ns
            WHERE {condizione}
            ORDER BY last_crawl ASC, ({campi_pieni}) DESC, codice_IPA
            LIMIT ?
        """
        df = pd.read_sql_query(query, conn, params=(limit,))

    elif ricalcola:

        query = """
            SELECT
                t.codice_IPA AS codice_ipa,
                t.codice_istat AS codice_istat,
                c.Sito_istituzionale AS dominio_grezzo_contatti
            FROM enti_ns t
            LEFT JOIN enti_contatti c ON c.Codice_IPA = t.codice_IPA
            ORDER BY t.last_crawl ASC, t.codice_IPA
            LIMIT ?
        """
        df = pd.read_sql_query(query, conn, params=(limit,))

    else:

        query = """
            SELECT
                codice_IPA AS codice_ipa,
                codice_istat AS codice_istat,
                sito_istituzionale AS dominio
            FROM enti_contatti
            WHERE sito_istituzionale IS NOT NULL
              AND sito_istituzionale != ''
              AND codice_IPA IS NOT NULL
              AND codice_IPA != ''
              AND codice_IPA NOT IN (
                  SELECT codice_IPA FROM enti_ns
              )
            LIMIT ?
        """
        df = pd.read_sql_query(query, conn, params=(limit,))

    if not ricalcola and not ritentativa:
        logger.info("Query: eseguo selezione domini da processare")
    elif ritentativa:
        logger.info("Query: eseguo selezione domini da processare")
    elif ricalcola:
        logger.info("Query: eseguo selezione domini da processare per recalc")

    to_process = len(df)

    logger.info(
        f"RECAP: in coda {to_process} record"
    )

    if to_process == 0:

        logger.info(
            "NESSUN nuovo record da processare."
        )
        asn_reader.close()
        conn.close()

        return

    # =======================
    # VARIABILI
    # =======================

    results = []

    inserted_asn = 0

    total = to_process
    processed = 0
    skipped = 0
    recuperati = 0
    deleted_count = 0

    logger.info(
        f"LOOP: inizio elaborazione "
        f"di {total} record..."
    )

    if ricalcola:
        old_rows = {}
        for r in df.itertuples():
            old_rows[r.codice_ipa] = dict(cursor.execute(
                "SELECT * FROM enti_ns WHERE codice_IPA = ?",
                (r.codice_ipa,)
            ).fetchone() or {})

    # =======================
    # LOOP DOMINI
    # =======================

    for i, row in df.iterrows():

        dominio_grezzo = None

        try:

            codice_ipa = row['codice_ipa']

            codice_istat = row['codice_istat']

            if ricalcola:
                dominio_grezzo_contatti = row['dominio_grezzo_contatti']
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
                    cursor.execute("DELETE FROM enti_ns WHERE codice_IPA = ?", (codice_ipa,))
                    deleted_count += 1
                    processed += 1
                    continue
                dominio_grezzo = dominio_grezzo_contatti
            else:
                dominio_grezzo = row['dominio']

            # sito_istituzionale e' un campo libero: puo'
            # contenere URL, percorsi, porte o caselle di
            # posta. Il resolver accetta solo un nome di host,
            # quindi la riduzione avviene prima di ogni
            # chiamata di rete. Una casella come
            # 'ente@pec.it' verrebbe ridotta a 'pec.it',
            # che e' il nome del provider di posta e non
            # dell'ente: qui viene respinta.
            dominio = canonicalizza_dominio(dominio_grezzo)

            logger.info(
                f"[{i+1}/{total}] PROCESSING "
                f"codice_IPA={codice_ipa}, "
                f"codice_istat={codice_istat}, "
                f"DOMINIO: {dominio_grezzo!r} -> {dominio!r}"
            )

            if not dominio:

                logger.warning(
                    f"Skippo {codice_ipa}: dominio non "
                    f"utilizzabile ({dominio_grezzo!r})"
                )

                skipped += 1
                if ricalcola:
                    try:
                        cursor.execute("UPDATE enti_ns SET last_crawl = ? WHERE codice_IPA = ?", (CURRENT_CRAWL, codice_ipa))
                    except Exception:
                        pass

                continue

            # La declinazione con www entra come secondo
            # tentativo: il comportamento sul dominio come
            # scritto nel DB non cambia.
            decl = declinazioni(dominio)

            logger.info(
                f"[DECLINAZIONI] {' | '.join(decl)}"
            )

            # ===================
            # NS
            # ===================

            ns_primary = None
            host_ns = None
            apex_usato = None

            for h in decl:

                ns_primary = get_primary_ns(h)

                if ns_primary:

                    host_ns = h
                    break

                logger.info(
                    f"[FALLBACK] nessun NS su {h}"
                )

            # Su un sottodominio gli NS non esistono: sono
            # definiti solo all'apex della zona. Se nessuna
            # declinazione ha NS propri, si risale la
            # gerarchia. apex_ns scarta i nameserver del
            # registry, che non descrivono l'ente.
            if not ns_primary:

                apex_usato, ns_primary = apex_ns(dominio)

                if ns_primary:

                    host_ns = apex_usato

            logger.debug(
                f" → NS primary={ns_primary} (host={host_ns})"
            )

            # ===================
            # IP NS
            # ===================

            ns_ip = None

            if ns_primary:

                ns_ip = get_ip(ns_primary)

                # Un NS senza IP non e' utilizzabile per il
                # join con ip_country in isdc.py. Se il
                # nameserver non ha address record si tenta
                # il www del nome stesso, stesso criterio
                # usato per i domini.
                if not ns_ip:

                    for h in declinazioni(ns_primary):

                        ns_ip = get_ip(h)

                        if ns_ip:

                            logger.info(
                                f"[FALLBACK] NS IP trovato su {h}"
                            )

                            break

            # ===================
            # ASN
            # ===================

            ns_asn = None
            ns_asn_org = None

            if ns_ip:

                ns_asn, ns_asn_org = get_asn_info(
                    ns_ip,
                    asn_reader
                )

            else:

                logger.warning(
                    f" → Nessun IP NS per "
                    f"{dominio} "
                    f"(ns={ns_primary})"
                )

            # ===================
            # UPDATE ASN TABLE
            # ===================

            if ns_asn and ns_asn != 0:

                try:

                    if common.upsert_asn(
                        conn, int(ns_asn), ns_asn_org, CURRENT_CRAWL
                    ):

                        inserted_asn += 1

                        logger.debug(
                            f" → ASN {ns_asn} inserito"
                        )

                    else:

                        logger.debug(
                            f" → ASN {ns_asn} già presente"
                        )

                except Exception as e:

                    logger.error(
                        f"ASN: errore inserimento "
                        f"{ns_asn}: {e}"
                    )

            # In --retry il record viene scritto anche quando non
            # ha guadagnato nulla. Scrivere gli stessi NULL non
            # cambia i dati in tabella, ma aggiorna last_crawl,
            # che e' la data di ultimo tentativo: e' questo che
            # fa ruotare la coda (ORDER BY last_crawl ASC).
            # Senza la scrittura il record non uscirebbe mai dal
            # primo blocco e verrebbe riprovato per sempre.
            campi = (ns_primary, ns_ip, ns_asn)

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

            # ===================
            # SALVA RESULT
            # ===================
            #
            # `dominio` conserva il valore ridotto, non
            # quello grezzo: i record precedenti hanno gia'
            # il nome di host pulito e la colonna deve restare
            # confrontabile con loro. Il fallback non altera
            # il dominio memorizzato, perche' ns_primary e
            # ns_ip dicono gia' da quale nome sono stati
            # ricavati.

            results.append({

                "codice_IPA": codice_ipa,

                "codice_istat": (
                    int(codice_istat)
                    if pd.notna(codice_istat)
                    else None
                ),

                "dominio": dominio,

                "ns_primary": ns_primary,

                "ns_ip": ns_ip,

                "ns_asn": (
                    int(ns_asn)
                    if ns_asn
                    else None
                ),

                "last_crawl": CURRENT_CRAWL
            })

            processed += 1

            # ===================
            # LOG PARZIALE
            # ===================

            if processed % 50 == 0:

                logger.info(
                    f"[PROGRESS] elaborati "
                    f"{processed}/{total}, "
                    f"skip={skipped}"
                )

        except Exception as e:

            logger.error(
                f"[FATAL DOMAIN ERROR] {dominio_grezzo!r}: {e}"
            )

            traceback.print_exc()

    logger.info(
        f"[LOOP COMPLETO] "
        f"elaborati {processed}, "
        f"skip {skipped}, "
        f"nuovi ASN {inserted_asn}"
    )

    # =======================
    # UPSERT comuni_ns
    # =======================

    logger.info(
        "DB: INIZIO UPSERT enti_ns"
    )

    updated_count = 0

    if ritentativa:

        colonna = {
            c: common.conserva_valore("enti_ns", c, tipo_campi[c])
            for c in campi_in_coda
        }

    else:

        colonna = {c: f"excluded.{c}" for c in campi_in_coda}

    for r in results:

        codice_ipa = r["codice_IPA"]

        try:
            old = dict(cursor.execute("SELECT * FROM enti_ns WHERE codice_IPA = ?", (codice_ipa,)).fetchone() or {})

            cursor.execute("""
                INSERT INTO enti_ns (
                    codice_IPA,
                    codice_istat,
                    dominio,
                    ns_primary,
                    ns_ip,
                    ns_asn,
                    last_crawl
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(codice_IPA) DO UPDATE SET
                    codice_istat = excluded.codice_istat,
                    dominio     = excluded.dominio,
                    ns_primary  = {ns_primary},
                    ns_ip       = {ns_ip},
                    ns_asn      = {ns_asn},
                    last_crawl  = excluded.last_crawl
            """.format(
                ns_primary=colonna["ns_primary"],
                ns_ip=colonna["ns_ip"],
                ns_asn=colonna["ns_asn"],
            ), (
                r["codice_IPA"],
                r["codice_istat"],
                r["dominio"],
                r["ns_primary"],
                r["ns_ip"],
                int(r["ns_asn"]) if r["ns_asn"] else None,
                r["last_crawl"]
            ))

            new = dict(cursor.execute("SELECT * FROM enti_ns WHERE codice_IPA = ?", (codice_ipa,)).fetchone() or {})
            if old:
                vecchio_vals = [old.get(c) for c in CAMPI_STORICO]
                nuovo_vals = [new.get(c) for c in CAMPI_STORICO]
                mods = change_history.confronta(vecchio_vals, nuovo_vals, CAMPI_STORICO)
                if mods:
                    righe_h = change_history.costruisci_righe(
                        NOME_TABELLA, CHIAVE_NOME, codice_ipa, mods,
                        script=NOME_SCRIPT, tipo_operazione='MOD'
                    )
                    change_history.inserisci(conn, righe_h)

            updated_count += 1

            logger.debug(
                f"UPD: enti_ns {codice_ipa} salvato"
            )

        except Exception as e:

            logger.error(
                f"DB: errore upsert "
                f"per codice_IPA={codice_ipa}: {e}"
            )

    # =======================
    # COMMIT
    # =======================

    conn.commit()

    # =======================
    # CLOSE
    # =======================

    if ricalcola:
        logger.info(
            f"DB: commit completato. Aggiornati {updated_count} record in enti_ns, cancellati {deleted_count}, skip {skipped}"
        )
    else:
        logger.info(
            f"DB: commit completato. "
            f"Aggiornati {updated_count} "
            f"record in enti_ns"
        )

    logger.info(
        f"ASN: {inserted_asn} "
        f"nuovi ASN inseriti"
    )

    # =======================
    # RESIDUI
    # =======================
    #
    # Va fatto prima del CLEANUP: il conteggio usa la stessa
    # connessione, e su una connessione chiusa sqlite3 solleva
    # 'Cannot operate on a closed database'.

    if ritentativa:

        logger.info(
            f"[RETRY] Record con almeno un dato: {recuperati}"
        )

        residui = cursor.execute(
            f"""
            SELECT COUNT(*) FROM enti_ns
            WHERE {common.condizione_coda(campi_in_coda)}
            """
        ).fetchone()[0]

        logger.info(
            f"[RETRY] Record ancora incompleti in tabella: {residui}"
        )

    # =======================
    # CLOSE
    # =======================

    asn_reader.close()

    conn.close()

    logger.info(
        "=== COMPLETATO NS PIPELINE ==="
    )

    logger.info(
        f"Totali elaborati: "
        f"{processed} / {total} "
        f"(skip: {skipped})"
    )

# ===========================
# ENTRYPOINT
# ===========================

if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description=(
            "Raccoglie nameserver primario, IP e ASN per gli "
            "enti di enti_contatti. Ogni dominio viene tentato "
            "come e' scritto nel database, poi con il prefisso "
            "www; se e' un sottodominio si risale fino "
            "all'apex della zona che lo serve, scartando i "
            "nameserver del registro."
        )
    )

    parser.add_argument(
        "--retry",
        action="store_true",
        help=(
            "Riprova i record gia' in enti_ns che hanno "
            "ns_primary, ns_ip o ns_asn NULL, invece di prendere "
            "enti nuovi da enti_contatti"
        )
    )

    parser.add_argument(
        "--recalculate",
        action="store_true",
        dest="recalculate",
        help=(
            "Ricalcola ex novo i record presenti in enti_ns "
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

    args = parser.parse_args()

    main(
        ritentativa=args.retry,
        max_run=args.max_run,
        ricalcola=args.recalculate,
    )