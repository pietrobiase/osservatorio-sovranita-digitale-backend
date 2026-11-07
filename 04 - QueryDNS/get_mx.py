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
# Stesse funzioni usate da get_cname.py e get_ns.py: vedi
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

# ===========================
# ASN lookup
# ===========================

def get_asn_info(ip, reader):

    if not ip:
        logger.debug(f"ASN: IP vuoto → None")
        return (None, None)

    try:
        logger.debug(f"ASN: lookup IP {ip}")
        record = reader._db_reader.get(ip)

        if not record:
            logger.warning(f"ASN: nessun record per IP {ip}")
            return (None, None)

        asn = record.get('autonomous_system_number')
        org = record.get('autonomous_system_organization')

        logger.debug(f"ASN {ip}: {asn} – {org or 'unknown'}")
        return (asn, org)

    except Exception as e:
        logger.error(f"ASN: errore per IP {ip}: {e}")
        return (None, None)


# ===========================
# MX lookup
# ===========================

def get_mx_data(domain):

    resolver = dns.resolver.Resolver()
    resolver.timeout = 10
    resolver.lifetime = 10
    resolver.nameservers = ['8.8.8.8', '1.1.1.1']

    logger.debug(f"MX: lookup dominio {domain}")

    try:
        answers = resolver.resolve(domain, 'MX')

        mx_records = sorted(
            [(str(r.exchange).rstrip('.'), r.preference) for r in answers],
            key=lambda x: x[1]
        )

        if not mx_records:
            logger.warning(f"MX: nessun record MX per {domain}")
            return (None, None)

        # cerca prima MX buono senza antispam
        for mx_host, priority in mx_records:
            if 'antispam' not in mx_host.lower():
                logger.info(f"MX: trovato {mx_host} (priorità {priority}) per {domain}")
                return (mx_host, priority)

        # se non è stato trovato MX "pulito", usa il primo
        mx_host, priority = mx_records[0]
        logger.info(f"MX: uso mx {mx_host} (priorità {priority}, con antispam) per {domain}")
        return (mx_host, priority)

    except dns.resolver.NoAnswer:

        # Caso normale: il nome esiste ma non ha record MX.
        # Non e' un errore e non e' un NXDOMAIN, quindi non
        # viene loggato come warning: su un dominio senza
        # servizio di posta e' la risposta attesa.
        logger.debug(f"MX: {domain} esiste ma non ha record MX")
        return (None, None)

    except dns.resolver.NXDOMAIN:

        logger.debug(f"MX: {domain} non esiste (NXDOMAIN)")
        return (None, None)

    except Exception as e:
        logger.error(f"MX: errore risoluzione {domain}: {e}")
        return (None, None)


def risolvi_mx(dominio):
    """
    Cerca un record MX sulle declinazioni del dominio.

    Restituisce (mx_host, priorita, host_usato).

    Nota: a differenza di NS e CNAME, l'MX NON si eredita
    dall'apex superiore. RFC 5321 prevede che un dominio senza
    MX usi il proprio A record come implicit MX, non quello
    del padre. Copiare l'MX di 'example.it' su
    'comune.example.it' produrrebbe un dato falso: il
    comune non usa quel server di posta, e il nome del
    provider finirebbe nelle statistiche di concentrazione
    come se fosse sua infrastruttura.

    Per NS il fallback apex e' invece corretto, perche' la
    delegazione e' vera: get_ns.py lo applica.
    """

    for h in declinazioni(dominio):

        mx_host, priorita = get_mx_data(h)

        if mx_host:

            return (mx_host, priorita, h)

        logger.info(f"[FALLBACK] nessun MX su {h}")

    return (None, None, None)


# ===========================
# IP lookup (hostname → IP)
# ===========================

def get_ip(hostname):

    if not hostname:
        logger.debug("IP: hostname vuoto → None")
        return None

    try:
        logger.debug(f"IP: resolve hostname {hostname}")
        ip = socket.gethostbyname(hostname)
        logger.info(f"IP: {hostname} → {ip}")
        return ip

    except Exception as e:
        logger.warning(f"IP: impossibile risolvere {hostname}: {e}")
        return None


# ===========================
# MAIN
# ===========================

def main(ritentativa=False, max_run=None, ricalcola=False):

    logger.info("=== START MX PIPELINE ===")

    if ritentativa and ricalcola:
        logger.error("Usare --retry o --recalculate, non entrambi")
        return

    if ritentativa:

        logger.info(
            "[RETRY] Modalita' ritentativa: riprovo i record "
            "in enti_mx con mx, priorita, mx_ip o asn_number NULL"
        )
    elif ricalcola:

        logger.info(
            "[RECALCULATE] Modalita' ricalcolo: rileggo enti_contatti e "
            "ricalcolo ex novo da enti_mx ordinati per last_crawl ASC"
        )

    # CONFIG
    config = common.config()

    # DB
    db_path = common.db_path()
    logger.info(f"DB: connetto a {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    change_history.ensure_table(conn)

    NOME_SCRIPT = Path(__file__).name
    NOME_TABELLA = "enti_mx"
    CHIAVE_NOME = "codice_IPA"
    CAMPI_STORICO = (
        "codice_istat",
        "dominio",
        "mx",
        "priorita",
        "mx_ip",
        "asn_number",
    )

    # TABLES
    logger.info("DB: creo/verifico tabelle")
    # La chiave è il solo codice_IPA. codice_istat è
    # opzionale: molti enti non comunali non ne hanno.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS enti_mx (
            codice_IPA TEXT PRIMARY KEY NOT NULL,
            codice_istat INTEGER,
            dominio TEXT,
            mx TEXT,
            priorita INTEGER,
            mx_ip TEXT,
            asn_number INTEGER,
            last_crawl TEXT
        )
    """)

    common.ensure_asn_table(conn)

    # La dipendenza si valida subito, prima di leggere la coda e
    # prima di ogni early-return: un mmdb mancante e' un errore
    # di configurazione e deve emergere a ogni run, non solo a
    # coda piena.
    asn_reader = common.open_geoip("GeoLite2-ASN.mmdb")

    # SELECT LIMITATA
    limit = max_run if max_run is not None else config.get('max_run', 10)
    logger.info(f"Limit: {limit} record massimo per questa run")

    # I campi calcolati che possono restare NULL. Sono la
    # condizione di coda del --retry: se uno di questi manca,
    # il record e' incompleto e vale la pena ritentarlo.
    #
    # mx e priorita vanno insieme: un MX trovato senza
    # priorita' non e' un MX utilizzabile.
    campi_in_coda = (
        "mx",
        "priorita",
        "mx_ip",
        "asn_number",
    )

    # Serve al COALESCE del retry: distingue le colonne
    # testuali dalle numeriche, perche' una stringa vuota e'
    # un dato assente mentre priorita'=0 e' un dato reale.
    tipo_campi = {
        "mx": "testo",
        "priorita": "intero",
        "mx_ip": "testo",
        "asn_number": "intero",
    }

    if ritentativa:

        # La coda si legge da enti_mx, non da enti_contatti:
        # sono record gia' elaborati dei quali si deve
        # recuperare una parte.
        condizione = common.condizione_coda(campi_in_coda)

        # `last_crawl` e' il criterio PRINCIPALE e rende la coda
        # rotante.
        campi_pieni = common.conteggio_campi_pieni(campi_in_coda)

        query = f"""
            SELECT
                codice_IPA AS codice_ipa,
                codice_istat AS codice_istat,
                dominio
            FROM enti_mx
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
            FROM enti_mx t
            LEFT JOIN enti_contatti c ON c.Codice_IPA = t.codice_IPA
            ORDER BY t.last_crawl ASC, t.codice_IPA
            LIMIT ?
        """
        df = pd.read_sql_query(query, conn, params=(limit,))

    else:

        # Gli alias servono: SQLite restituisce in
        # cursor.description i nomi dichiarati nella
        # tabella (Codice_IPA, non codice_IPA).
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
                SELECT codice_IPA FROM enti_mx
              )
            LIMIT ?
        """
        df = pd.read_sql_query(query, conn, params=(limit,))

    if not ricalcola and not ritentativa:
        logger.info("Query: eseguo selezione enti da processare")
    elif ritentativa:
        logger.info("Query: eseguo selezione enti da processare")
    elif ricalcola:
        logger.info("Query: eseguo selezione enti da processare per recalc")

    to_process = len(df)
    logger.info(f"RECAP: in coda {to_process} record da processare")

    if to_process == 0:
        logger.info("NESSUN nuovo record da processare, esco rapidamente.")
        asn_reader.close()
        conn.close()
        return

    # ASN DB
    results = []
    inserted_asn = 0
    total = to_process
    processed = 0
    skipped = 0
    recuperati = 0
    deleted_count = 0

    logger.info(f"LOOP: inizio loop su {total} record...")

    if ricalcola:
        # Per tracciare cambiamenti e cancellazioni
        old_rows = {}
        for r in df.itertuples():
            old_rows[r.codice_ipa] = dict(cursor.execute(
                "SELECT * FROM enti_mx WHERE codice_IPA = ?",
                (r.codice_ipa,)
            ).fetchone() or {})

    for i, row in df.iterrows():

        dominio_grezzo = None

        try:

            codice_ipa = row['codice_ipa']

            codice_istat = row['codice_istat']

            if ricalcola:
                dominio_grezzo_contatti = row['dominio_grezzo_contatti']
                # Se non esiste in enti_contatti o vuoto -> DELETE
                if dominio_grezzo_contatti is None or str(dominio_grezzo_contatti).strip() == '':
                    old = old_rows.get(codice_ipa) or {}
                    # Registra storico DEL per campi valorizzati
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
                    cursor.execute("DELETE FROM enti_mx WHERE codice_IPA = ?", (codice_ipa,))
                    cursor.execute("UPDATE enti_mx SET last_crawl = ? WHERE codice_IPA = ?", (CURRENT_CRAWL, codice_ipa))
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
                        cursor.execute("UPDATE enti_mx SET last_crawl = ? WHERE codice_IPA = ?", (CURRENT_CRAWL, codice_ipa))
                    except Exception:
                        pass
                continue

            # La declinazione con www entra come secondo
            # tentativo: il comportamento sul dominio come
            # scritto nel DB non cambia.
            decl = declinazioni(dominio)

            logger.info(f"[DECLINAZIONI] {' | '.join(decl)}")

            # MX
            mx_host, priority, host_mx = risolvi_mx(dominio)
            logger.debug(f" → MX host={mx_host}, priorità={priority} (da {host_mx})")

            # IP MX
            mx_ip = None
            asn_number = None
            asn_org = None

            if mx_host:
                mx_ip = get_ip(mx_host)

                # Un MX senza IP non e' utilizzabile per il
                # join con ip_country in isdc.py. Se
                # l'exchange non ha address record si tenta
                # il www del nome stesso.
                if not mx_ip:

                    for h in declinazioni(mx_host):

                        mx_ip = get_ip(h)

                        if mx_ip:

                            logger.info(f"[FALLBACK] MX IP trovato su {h}")

                            break

            if mx_ip:
                asn_number, asn_org = get_asn_info(mx_ip, asn_reader)
            else:
                logger.warning(f" → Nessun IP MX per {dominio} (mx_host={mx_host})")

            # aggiorna ASN table
            if asn_number and asn_number != 0:
                try:
                    if common.upsert_asn(
                        conn, asn_number, asn_org, CURRENT_CRAWL
                    ):
                        inserted_asn += 1
                        logger.info(f" → ASN {asn_number} inserito")
                    else:
                        logger.debug(
                            f" → ASN {asn_number} già presente"
                        )
                except Exception as e:
                    logger.error(f"ASN: errore inserimento {asn_number}: {e}")

            # In --retry il record viene scritto anche quando non
            # ha guadagnato nulla. Scrivere gli stessi NULL non
            # cambia i dati in tabella, ma aggiorna last_crawl,
            # che e' la data di ultimo tentativo: e' questo che
            # fa ruotare la coda (ORDER BY last_crawl ASC).
            # Senza la scrittura il record non uscirebbe mai dal
            # primo blocco e verrebbe riprovato per sempre.
            campi = (mx_host, priority, mx_ip, asn_number)

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

            # salva risultato. `dominio` conserva il valore
            # ridotto, non quello grezzo: i record precedenti
            # hanno gia' il nome di host pulito e la colonna
            # deve restare confrontabile con loro. Il fallback
            # non altera il dominio memorizzato, perche' mx,
            # priorita' e mx_ip dicono gia' da quale nome sono
            # stati ricavati.
            results.append({
                "codice_IPA": codice_ipa,
                "codice_istat": (
                    int(codice_istat)
                    if pd.notna(codice_istat)
                    else None
                ),
                "dominio": dominio,
                "mx": mx_host,
                "priorita": priority,
                "mx_ip": mx_ip,
                "asn_number": asn_number,
                "last_crawl": CURRENT_CRAWL
            })

            processed += 1

            # LOGGING parziale
            if processed % 50 == 0:
                logger.info(f"[PROGRESS] elaborati {processed}/{total}, skip={skipped}")

        except Exception as e:

            logger.error(
                f"[FATAL DOMAIN ERROR] {dominio_grezzo!r}: {e}"
            )

            traceback.print_exc()

    logger.info(f"[LOOP COMPLETO] elaborati {processed}, skip {skipped}, nuovi ASN {inserted_asn}")

    # UPSERT
    logger.info("DB: INIZIO UPSERT enti_mx")
    updated_count = 0

    if ritentativa:

        colonna = {
            c: common.conserva_valore("enti_mx", c, tipo_campi[c])
            for c in campi_in_coda
        }

    else:

        colonna = {c: f"excluded.{c}" for c in campi_in_coda}

    for r in results:

        codice_ipa = r["codice_IPA"]

        try:
            # Snapshot prima
            old = dict(cursor.execute("SELECT * FROM enti_mx WHERE codice_IPA = ?", (codice_ipa,)).fetchone() or {})

            cursor.execute("""
                INSERT INTO enti_mx (
                    codice_IPA,
                    codice_istat,
                    dominio,
                    mx,
                    priorita,
                    mx_ip,
                    asn_number,
                    last_crawl
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(codice_IPA) DO UPDATE SET
                    codice_istat = excluded.codice_istat,
                    dominio      = excluded.dominio,
                    mx           = {mx},
                    priorita     = {priorita},
                    mx_ip        = {mx_ip},
                    asn_number   = {asn_number},
                    last_crawl   = excluded.last_crawl
            """.format(
                mx=colonna["mx"],
                priorita=colonna["priorita"],
                mx_ip=colonna["mx_ip"],
                asn_number=colonna["asn_number"],
            ), (
                r["codice_IPA"],
                r["codice_istat"],
                r["dominio"],
                r["mx"],
                r["priorita"],
                r["mx_ip"],
                r["asn_number"],
                r["last_crawl"]
            ))

            # Snapshot dopo e storico
            new = dict(cursor.execute("SELECT * FROM enti_mx WHERE codice_IPA = ?", (codice_ipa,)).fetchone() or {})
            if old:  # solo UPDATE genera storico
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
            logger.debug(f"UPD: enti_mx {codice_ipa} salvato")

        except Exception as e:

            logger.error(
                f"DB: errore upsert per codice_IPA={codice_ipa}: {e}"
            )

    conn.commit()

    # CLOSE
    if ricalcola:
        logger.info(f"DB: commit completato. Aggiornati {updated_count} record in enti_mx, cancellati {deleted_count}, skip {skipped}")
    else:
        logger.info(f"DB: commit completato. Aggiornati {updated_count} record in enti_mx")
    logger.info(f"ASN: {inserted_asn} nuovi ASN inseriti/aggiornati")

    # Va fatto prima del CLEANUP: il conteggio usa la stessa
    # connessione, e su una connessione chiusa sqlite3 solleva
    # 'Cannot operate on a closed database'. Lo stesso errore
    # chiuse il --retry di get_cname.py ed e' stato corretto
    # li' prima che si replicasse qui.
    if ritentativa:

        logger.info(f"[RETRY] Record con almeno un dato: {recuperati}")

        residui = cursor.execute(
            f"""
            SELECT COUNT(*) FROM enti_mx
            WHERE {common.condizione_coda(campi_in_coda)}
            """
        ).fetchone()[0]

        logger.info(
            f"[RETRY] Record ancora incompleti in tabella: {residui}"
        )

    asn_reader.close()

    conn.close()

    logger.info("=== COMPLETATO MX PIPELINE ===")
    logger.info(f"Totali elaborati: {processed} / {total} (skip: {skipped})")


# ===========================
# ENTRYPOINT
# ===========================

if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description=(
            "Raccoglie record MX, priorita', IP e ASN per gli "
            "enti di enti_contatti. Ogni dominio viene tentato "
            "come e' scritto nel database, poi con il prefisso "
            "www. L'MX non viene cercato sull'apex superiore: "
            "non si eredita (RFC 5321)."
        )
    )

    parser.add_argument(
        "--retry",
        action="store_true",
        help=(
            "Riprova i record gia' in enti_mx che hanno mx, "
            "priorita, mx_ip o asn_number NULL, invece di "
            "prendere enti nuovi da enti_contatti"
        )
    )

    parser.add_argument(
        "--recalculate",
        action="store_true",
        dest="recalculate",
        help=(
            "Ricalcola ex novo i record presenti in enti_mx "
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