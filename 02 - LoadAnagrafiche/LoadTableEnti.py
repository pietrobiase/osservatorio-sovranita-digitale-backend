import sys
import re
import sqlite3
import pandas as pd

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common
import change_history



# =========================================================
# COLONNE DA ESCLUDERE
# =========================================================

COLONNE_DA_ESCLUDERE = [
    "mail3",
    "Tipo_Mail3",
    "mail4",
    "Tipo_Mail4",
    "mail5",
    "Tipo_Mail5",
    "Url_facebook",
    "Url_linkedin",
    "Url_twitter",
    "Url_youtube",
    "Codice_natura",
    "Codice_ateco",
    "Codice_MIUR",
    "acronimo",
    "Nome_responsabile",
    "Cognome_responsabile",
    "Titolo_responsabile",
    "Codice_comune_ISTAT",
    "Codice_catastale_comune",
    "Acronimo",
    "Codice_fiscale_ente"
]


# =========================================================
# CHIAVE E CAMPI PRESERVATI
# =========================================================

CHIAVE_ENTE = "Codice_IPA"

# Campi giÃ  valorizzati (geocoding / provincia) che non
# devono essere sovrascritti in fase di sincronizzazione
CAMPI_PRESERVATI = [
    "lat",
    "lon",
    "provincia"
]

# =========================================================
# INVALIDAZIONE CACHE DNS
# =========================================================

# Campi la cui modifica rende obsoleti i record DNS gia'
# raccolti. Il dominio e' l'unico input dei crawler DNS:
# se cambia, i record vanno cancellati e rigenerati.
CAMPAGNA_INVALIDANTE = {
    "Sito_istituzionale",
}

# Tabelle DNS dipendenti dal dominio dell'ente.
TABELLE_DNS_DA_INVALIDARE = ("enti_mx", "enti_ns", "enti_cname")

# Numero massimo di codici per statement DELETE.
# Evita di superare il limite di variabili SQLite.
LOTTO_CANCELLAZIONE = 500

# Provenienza registrata nello storico delle modifiche.
NOME_SCRIPT = Path(__file__).name

# Tipo di operazione registrato nello storico: questo script
# scrive in `change_history_mod` solo le righe prodotte da un
# UPDATE con campi realmente cambiati, cioe' operazioni MOD.
TIPO_OPERAZIONE_STORICO = "MOD"

# Se True, mostra cosa verrebbe cancellato senza
# eseguire nessun DELETE. Da usare per le verifiche.
DRY_RUN = False

# Se True, allinea la tabella ai Codice_IPA presenti nel file
# sorgente: i record assenti vengono marcati come DEL (o
# cancellati se la colonna `stato` non esiste).
ALLINEA_AL_FILE = True

# Se True, in caso di modifica a Sito_istituzionale o di
# allineamento con stato DEL, cancella i record DNS
# correlati in enti_mx, enti_ns, enti_cname.
INVALIDA_DNS_SU_MOD_CONTATTI = True
INVALIDA_DNS_SU_DEL = True


# =========================================================
# PULIZIA SITO ISTITUZIONALE
# =========================================================

def pulisci_sito(url):
    """
    Pulisce gli URL:

    Esempi:
    https://www.comune.it/     -> comune.it
    http://comune.it/index     -> comune.it
    WWW.COMUNE.IT              -> comune.it
    comune.it/                 -> comune.it

    Restituisce:
    - dominio pulito
    - None se valore non valido
    """

    if pd.isna(url):
        return None

    url = str(url).strip()

    if not url:
        return None

    # Rimuove valori inutili
    if url.lower() in ["nan", "none", "null"]:
        return None

    # Lowercase
    url = url.lower()

    # Rimuove protocollo
    url = re.sub(
        r"^https?://",
        "",
        url,
        flags=re.IGNORECASE
    )

    # Rimuove www.
    url = re.sub(
        r"^www\.",
        "",
        url,
        flags=re.IGNORECASE
    )

    # Rimuove tutto dopo /
    url = url.split("/")[0]

    # Rimuove eventuale porta
    url = url.split(":")[0]

    # Rimuove spazi interni
    url = url.strip()

    # Validazione minima
    if "." not in url:
        return None

    return url


# =========================================================
# FORMATTA CAP
# =========================================================

def formatta_cap(valore):
    """
    Converte il CAP in stringa
    mantenendo gli zeri iniziali.
    """

    if pd.isna(valore):
        return None

    valore = str(valore).strip()

    if not valore:
        return None

    # Rimuove .0 finale
    valore = re.sub(r"\.0$", "", valore)

    # Solo numeri
    valore = re.sub(r"\D", "", valore)

    # Padding a 5 cifre
    if valore:
        valore = valore.zfill(5)

    return valore


# =========================================================
# SCHEMA
# =========================================================

def schema_tabella(conn, table_name):

    """
    Ritorna {colonna: tipo} per la tabella indicata.
    """

    return {
        row[1]: (row[2] or "").upper()
        for row in conn.execute(
            f'PRAGMA table_info("{table_name}")'
        )
    }


def pulisci_valore(value):

    """
    Normalizza un valore pandas per SQLite.
    NaN / valori vuoti diventano NULL.
    """

    if value is None:
        return None

    if isinstance(value, str):
        value = value.strip()
        return value or None

    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    return value


def adatta_valore(value, tipo_colonna):

    """
    Converte il valore secondo l'affinitÃ  dichiarata
    dalla colonna (es. INTEGER su Codice_ISTAT).
    """

    value = pulisci_valore(value)

    if value is None:
        return None

    if "INT" in tipo_colonna and isinstance(value, str):

        if re.fullmatch(r"-?\d+", value):
            return int(value)

    return value


# =========================================================
# PROVINCIA DA CAP
# =========================================================

def carica_mappa_province(conn):

    """
    Costruisce la mappa {cap: denominazione_provincia}
    a partire dalla tabella comuni_cap.

    Un CAP puÃ² comparire su piÃ¹ comuni: si mantiene
    la prima provincia trovata.
    """

    mappa = {}

    for cap, provincia in conn.execute("""
        SELECT
            cap,
            denominazione_provincia
        FROM comuni_cap
        WHERE cap IS NOT NULL
          AND denominazione_provincia IS NOT NULL
    """):

        try:
            chiave = str(int(cap))
        except (TypeError, ValueError):
            continue

        mappa.setdefault(chiave, provincia)

    return mappa


def risolvi_provincia(cap, mappa_province):

    """
    Dato un CAP restituisce la provincia associata,
    oppure None se il CAP non Ã¨ censito.
    """

    cap = pulisci_valore(cap)

    if cap is None:
        return None

    if isinstance(cap, str) and re.fullmatch(r"\d+", cap):
        cap = str(int(cap))

    return mappa_province.get(str(cap))


# =========================================================
# ALLINEAMENTO AL FILE SORGENTE
# =========================================================

def allinea_al_file(conn, table_name, df, dry_run=False):
    """
    Marca come DEL i record il cui Codice_IPA non compare
    nel file sorgente.

    Se la colonna 'stato' non esiste, effettua la cancellazione
    per retrocompatibilita'.

    Se un record viene marcato/cancellato come DEL e
    INVALIDA_DNS_SU_DEL e' attivo, i record DNS correlati in
    enti_mx, enti_ns, enti_cname vengono eliminati.
    """

    if CHIAVE_ENTE not in df.columns:
        raise KeyError(f"'{CHIAVE_ENTE}' non e' una colonna del dataframe")

    schema = schema_tabella(conn, table_name)

    codici_file = {codice for codice in (pulisci_valore(v) for v in df[CHIAVE_ENTE]) if codice}
    codici_tabella = [row[0] for row in conn.execute(f'SELECT DISTINCT "{CHIAVE_ENTE}" FROM "{table_name}" WHERE "{CHIAVE_ENTE}" IS NOT NULL')]

    da_cancellare = sorted(c for c in codici_tabella if c not in codici_file)
    if not da_cancellare:
        print("Allineamento: nessun record obsoleto da marcare")
        return {"cancellati": 0, "codici": [], "dns": {}}

    print(f"Record obsoleti (assenti dal file): {len(da_cancellare)}")

    res_dns = {"eliminati": {}}

    if dry_run:
        if INVALIDA_DNS_SU_DEL:
            res_dns = invalida_dns_per_codici(conn, da_cancellare, dry_run=True)

        print("DRY RUN: nessuna modifica eseguita")
        print("  anteprima:", ", ".join(da_cancellare[:10]))

        if res_dns["eliminati"]:
            print("  DNS da rimuovere:")
            for tabella, cnt in res_dns["eliminati"].items():
                print(f"    {tabella}: {cnt} record")

        return {
            "cancellati": 0,
            "codici": da_cancellare,
            "dns": res_dns["eliminati"]
        }

    cancellati = 0

    for i in range(0, len(da_cancellare), LOTTO_CANCELLAZIONE):
        lotto = da_cancellare[i:i + LOTTO_CANCELLAZIONE]
        segnaposto = ", ".join("?" for _ in lotto)

        if "stato" in schema:
            cur = conn.execute(
                f'UPDATE "{table_name}" SET "stato" = ? '
                f'WHERE "{CHIAVE_ENTE}" IN ({segnaposto})',
                ["DEL"] + lotto
            )
        else:
            cur = conn.execute(
                f'DELETE FROM "{table_name}" '
                f'WHERE "{CHIAVE_ENTE}" IN ({segnaposto})',
                lotto
            )

        cancellati += cur.rowcount

    conn.commit()

    print(f"Record marcati/cancellati come DEL: {cancellati}")

    if INVALIDA_DNS_SU_DEL:
        res_dns = invalida_dns_per_codici(conn, da_cancellare)

        if res_dns["eliminati"]:
            print("Invalidazione DNS per stato DEL:")
            for tabella, cnt in res_dns["eliminati"].items():
                print(f"  {tabella}: {cnt} record rimossi")

    return {
        "cancellati": cancellati,
        "codici": da_cancellare,
        "dns": res_dns["eliminati"]
    }


def _tabelle_dns_esistenti(conn):
    """
    Restituisce le tabelle DNS da invalidare che esistono
    davvero nel database, per evitare errori su istanze
    parziali.
    """

    presenti = set()

    for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):

        presenti.add(row[0])

    return [t for t in TABELLE_DNS_DA_INVALIDARE if t in presenti]


def invalida_dns_per_codici(conn, codici, dry_run=False):
    """
    Cancella i record DNS per i Codice_IPA indicati da
    enti_mx, enti_ns, enti_cname.

    I codici passati sono già puliti e unici.
    """

    if not codici:

        return {"eliminati": {}}

    conn_dns = _tabelle_dns_esistenti(conn)

    if not conn_dns:

        return {"eliminati": {}}

    eliminati = {}

    if dry_run:

        for tabella in conn_dns:

            cnt = 0

            for i in range(0, len(codici), LOTTO_CANCELLAZIONE):

                lotto = codici[i:i + LOTTO_CANCELLAZIONE]

                segnaposto = ", ".join("?" for _ in lotto)

                r = conn.execute(
                    f'SELECT COUNT(*) FROM "{tabella}" '
                    f'WHERE "{CHIAVE_ENTE}" IN ({segnaposto})',
                    lotto
                ).fetchone()

                cnt += r[0] if r else 0

            if cnt:

                eliminati[tabella] = cnt

        return {"eliminati": eliminati}

    for tabella in conn_dns:

        cnt = 0

        for i in range(0, len(codici), LOTTO_CANCELLAZIONE):

            lotto = codici[i:i + LOTTO_CANCELLAZIONE]

            segnaposto = ", ".join("?" for _ in lotto)

            cur = conn.execute(
                f'DELETE FROM "{tabella}" '
                f'WHERE "{CHIAVE_ENTE}" IN ({segnaposto})',
                lotto
            )

            cnt += cur.rowcount

        if cnt:

            eliminati[tabella] = cnt

    conn.commit()

    return {"eliminati": eliminati}

def sincronizza_enti(
    conn,
    table_name,
    df,
    mappa_province,
    batch_size=1000
):

    """
    Sincronizza il dataframe con la tabella usando
    Codice_IPA come chiave:

    - chiave giÃ  presente  -> UPDATE di tutti i campi
      tranne lat, lon e provincia
    - chiave assente       -> INSERT di un nuovo record
      con lat/lon NULL e provincia risolta dal CAP

    Se la colonna `stato` esiste, viene gestita cosÃ¬:

    - INSERT            -> stato = "INS"
    - UPDATE con almeno un campo realmente cambiato
                        -> stato = "MOD"
    - UPDATE senza differenze
                        -> stato = "STA"
    - stato sorgente "DEL" -> stato = "DEL" e invalidazione DNS
    - record assenti dal file -> stato = "DEL" (in allinea_al_file)

    Non cancella nulla: l'allineamento al file Ã¨
    gestito da allinea_al_file(), chiamata a parte
    solo se ALLINEA_AL_FILE Ã¨ attivo.

    Le modifiche dei record MOD finiscono anche nello storico
    (change_history): una riga per ogni campo che ha cambiato
    valore, con il valore precedente e quello nuovo.

    Se il valore di Sito_istituzionale cambia in un record MOD,
    oppure il record e' marcato con stato DEL, i record DNS
    correlati vengono cancellati da enti_mx, enti_ns e
    enti_cname (se le rispettive costanti di invalidazione sono
    attive).
    """

    schema = schema_tabella(conn, table_name)

    campi = [
        col for col in df.columns
        if col in schema
        and col not in CAMPI_PRESERVATI
        and col != "stato"
    ]

    if CHIAVE_ENTE not in campi:

        raise KeyError(
            f"'{CHIAVE_ENTE}' non Ã¨ una colonna valida di '{table_name}'"
        )

    campi_aggiornabili = [
        col for col in campi if col != CHIAVE_ENTE
    ]

    campi_preservati_presenti = [
        col for col in CAMPI_PRESERVATI if col in schema
    ]

    campi_insert = campi + campi_preservati_presenti

    # La colonna `stato` Ã¨ gestita dal sincronizzatore:
    # su INSERT viene valorizzata a "INS".
    if "stato" in schema and "stato" not in campi_insert:
        campi_insert = campi_insert + ["stato"]

    print(f"Campi sincronizzati: {len(campi_aggiornabili)}")
    print(f"Campi preservati: {', '.join(campi_preservati_presenti) or 'nessuno'}")

    # -------------------------------------------------
    # CHIAVI GIA' PRESENTI
    # -------------------------------------------------

    esistenti = {
        row[0]
        for row in conn.execute(
            f'SELECT "{CHIAVE_ENTE}" FROM "{table_name}" '
            f'WHERE "{CHIAVE_ENTE}" IS NOT NULL'
        )
    }

    print(f"Chiavi giÃ  presenti in tabella: {len(esistenti)}")

    sql_update = (
        f'UPDATE "{table_name}" SET '
        + ", ".join(
            f'"{col}" = ?' for col in campi_aggiornabili
        )
        + f' WHERE "{CHIAVE_ENTE}" = ?'
    )

    sql_update_with_stato = None
    if "stato" in schema:
        sql_update_with_stato = (
            f'UPDATE "{table_name}" SET '
            + ", ".join(
                f'"{col}" = ?' for col in campi_aggiornabili
            )
            + ', "stato" = ?'
            + f' WHERE "{CHIAVE_ENTE}" = ?'
        )

    sql_insert = (
        f'INSERT INTO "{table_name}" ('
        + ", ".join(f'"{col}"' for col in campi_insert)
        + ") VALUES ("
        + ", ".join("?" for _ in campi_insert)
        + ")"
    )

    aggiornati = 0
    inseriti = 0
    scartati = 0
    provincia_risolta = 0
    provincia_mancata = 0
    modificati = 0
    stabili = 0
    righe_storico = 0
    storico_accumulato = []

    def valori_record(row, per_insert):

        """
        Restituisce (valori_sql, provincia) dove
        `provincia` Ã¨ None se non richiesto o non risolta.

        Su insert, se la colonna `stato` Ã¨ presente in schema
        viene valorizzata a "INS".
        """

        campi_valori = campi if per_insert else campi_aggiornabili

        valori = [
            adatta_valore(row.get(col), schema.get(col, ""))
            for col in campi_valori
        ]

        if not per_insert:
            return valori, None

        provincia = None

        for col in campi_insert[len(campi):]:

            if col == "provincia":

                provincia = risolvi_provincia(
                    row.get("CAP"),
                    mappa_province
                )

                valori.append(provincia)

            elif col == "stato":

                valori.append("INS")

            else:

                valori.append(None)

        return valori, provincia

    # -------------------------------------------------
    # STORICO DELLE MODIFICHE
    # -------------------------------------------------

    change_history.ensure_table(conn)

    data_elaborazione = change_history.adesso()

    # -------------------------------------------------
    # INVALIDAZIONE DNS
    # -------------------------------------------------

    dns_da_invalidare_mod = set()
    dns_da_invalidare_del = set()

    # -------------------------------------------------
    # VALORI CORRENTI (confronto MOD / no-MOD)
    # -------------------------------------------------
    #
    # I valori attuali servono a due cose: decidere se un
    # record e' MOD o STA, e scrivere nello storico il valore
    # precedente di ogni campo che cambia.

    valori_correnti = {}

    if campi_aggiornabili:
        cur = conn.execute(
            f'SELECT "{CHIAVE_ENTE}", '
            + ", ".join(f'"{c}"' for c in campi_aggiornabili)
            + f' FROM "{table_name}"'
        )
        for db_row in cur:
            valori_correnti[db_row[0]] = db_row[1:]

    # -------------------------------------------------
    # CICLO RIGHE
    # -------------------------------------------------

    for row in df.to_dict("records"):

        codice_ipa = pulisci_valore(row.get(CHIAVE_ENTE))

        if not codice_ipa:

            scartati += 1
            continue

        stato_input = pulisci_valore(row.get("stato"))
        is_del = (
            isinstance(stato_input, str)
            and stato_input.strip().upper() == "DEL"
        )

        if is_del:
            dns_da_invalidare_del.add(codice_ipa)

        if codice_ipa in esistenti:

            valori, _ = valori_record(row, per_insert=False)

            # I campi che cambiano sono calcolati una volta sola:
            # servono sia per decidere MOD o STA, sia per lo
            # storico. Se il valore precedente non e' noto il
            # record resta MOD come prima, ma non c'e' nulla da
            # scrivere nello storico: il valore precedente
            # sarebbe inventato.
            vecchio = valori_correnti.get(codice_ipa)

            modifiche_riga = []

            if campi_aggiornabili and vecchio is not None and len(vecchio) == len(valori):

                modifiche_riga = change_history.confronta(
                    vecchio,
                    valori,
                    campi_aggiornabili
                )

                is_mod = bool(modifiche_riga)

            else:

                is_mod = True

            if sql_update_with_stato:

                stato_record = (
                    "DEL" if is_del
                    else ("MOD" if is_mod else "STA")
                )

                conn.execute(
                    sql_update_with_stato,
                    valori + [stato_record, codice_ipa]
                )

                if is_mod:
                    modificati += 1
                else:
                    stabili += 1

                aggiornati += 1

            elif is_mod:

                conn.execute(sql_update, valori + [codice_ipa])

                modificati += 1
                aggiornati += 1

            # -------------------------------------------------
            # STORICO DELLE MODIFICHE
            # -------------------------------------------------

            if is_mod and modifiche_riga:

                righe = change_history.costruisci_righe(
                    nome_tabella=table_name,
                    chiave_nome=CHIAVE_ENTE,
                    chiave_valore=codice_ipa,
                    modifiche=modifiche_riga,
                    data=data_elaborazione,
                    script=NOME_SCRIPT,
                    tipo_operazione=TIPO_OPERAZIONE_STORICO
                )

                storico_accumulato.extend(righe)

                righe_storico += len(righe)

            # -------------------------------------------------
            # INVALIDAZIONE DNS PER CAMBIO DOMINIO
            # -------------------------------------------------

            if is_mod and modifiche_riga:

                for nome_campo, _, _ in modifiche_riga:

                    if nome_campo in CAMPAGNA_INVALIDANTE:

                        dns_da_invalidare_mod.add(codice_ipa)
                        break


        else:

            valori, provincia = valori_record(row, per_insert=True)

            conn.execute(sql_insert, valori)

            esistenti.add(codice_ipa)
            inseriti += 1

            if provincia:
                provincia_risolta += 1
            else:
                provincia_mancata += 1

        if (aggiornati + inseriti) % batch_size == 0:

            change_history.inserisci(conn, storico_accumulato)

            storico_accumulato.clear()

            conn.commit()

            print(f"  ... elaborate {aggiornati + inseriti} righe")

    change_history.inserisci(conn, storico_accumulato)

    storico_accumulato.clear()

    conn.commit()

    # -------------------------------------------------
    # APPLICA INVALIDAZIONE DNS
    # -------------------------------------------------

    dns_da_invalidare = set()

    if INVALIDA_DNS_SU_MOD_CONTATTI:
        dns_da_invalidare.update(dns_da_invalidare_mod)

    if INVALIDA_DNS_SU_DEL:
        dns_da_invalidare.update(dns_da_invalidare_del)

    if dns_da_invalidare:

        res_dns = invalida_dns_per_codici(conn, sorted(dns_da_invalidare))

        if res_dns["eliminati"]:

            print("Invalidazione DNS per cambio Sito_istituzionale o stato DEL:")

            for tabella, cnt in res_dns["eliminati"].items():

                print(f"  {tabella}: {cnt} record rimossi")


    if scartati:

        print(f"Record scartati (chiave vuota): {scartati}")

    print(f"Record aggiornati: {aggiornati}")
    print(f"Record inseriti: {inseriti}")
    if "stato" in schema:
        print(f"Record modificati (MOD): {modificati}")
        print(f"Record stabili (STA): {stabili}")
    print(f"  Provincia risolta dal CAP: {provincia_risolta}")
    print(f"  Provincia non trovata: {provincia_mancata}")
    print(f"  Righe di storico registrate: {righe_storico}")

    return {
        "aggiornati": aggiornati,
        "inseriti": inseriti,
        "scartati": scartati,
        "modificati": modificati,
        "stabili": stabili,
        "righe_storico": righe_storico
    }


# =========================================================
# IMPORTAZIONE EXCEL -> SQLITE
# =========================================================

def importa_excel_in_sqlite():

    # -----------------------------------------------------
    # CONFIG
    # -----------------------------------------------------

    db_name = common.db_path()

    base_dir = common.input_dir()

    config = common.config()

    print(f"Base dir input: {base_dir}")
    print(f"Database: {db_name}")

    # -----------------------------------------------------
    # DB CONNECTION
    # -----------------------------------------------------

    conn = sqlite3.connect(db_name)

    try:

        # -------------------------------------------------
        # CICLO FILE
        # -------------------------------------------------

        for table_name, file_path in config.get("files_enti", {}).items():

            source = common.resolve(file_path, base_dir)

            print("\n" + "=" * 60)
            print(f"ELABORAZIONE: {table_name}")
            print("=" * 60)
            print(f"File sorgente: {source}")

            if not source.exists():

                print(f"File non trovato: {source}")
                continue

            try:

                # -----------------------------------------
                # LETTURA EXCEL
                # -----------------------------------------

                df = pd.read_excel(
                    source,
                    dtype=str
                )

                print(f"Righe lette: {len(df)}")

                # -----------------------------------------
                # NORMALIZZA NOMI COLONNE
                # -----------------------------------------

                df.columns = [
                    col.strip()
                    for col in df.columns
                ]

                # -----------------------------------------
                # PULIZIA SITO
                # -----------------------------------------

                if "Sito_istituzionale" in df.columns:

                    df["Sito_istituzionale"] = (
                        df["Sito_istituzionale"]
                        .apply(pulisci_sito)
                    )

                    siti_validi = (
                        df["Sito_istituzionale"]
                        .notna()
                        .sum()
                    )

                    print(
                        f"Siti validi: {siti_validi}"
                    )

                # -----------------------------------------
                # FORMATTA CAP
                # -----------------------------------------

                if "CAP" in df.columns:

                    df["CAP"] = (
                        df["CAP"]
                        .apply(formatta_cap)
                        .astype("string")
                    )

                # -----------------------------------------
                # RIMOZIONE COLONNE
                # -----------------------------------------

                colonne_presenti = [
                    col
                    for col in COLONNE_DA_ESCLUDERE
                    if col in df.columns
                ]

                if colonne_presenti:

                    df = df.drop(
                        columns=colonne_presenti
                    )

                    print(
                        f"Colonne rimosse: "
                        f"{len(colonne_presenti)}"
                    )

                # -----------------------------------------
                # RIMOZIONE DUPLICATI
                # -----------------------------------------

                df = df.drop_duplicates()

                print(
                    f"Righe finali: {len(df)}"
                )

                # -----------------------------------------
                # MAPPATURA PROVINCE DA CAP
                # -----------------------------------------

                mappa_province = carica_mappa_province(conn)

                print(
                    f"CAP censiti in comuni_cap: "
                    f"{len(mappa_province)}"
                )

                # -----------------------------------------
                # SINCRONIZZA SUL CODICE IPA
                # -----------------------------------------

                sincronizza_enti(
                    conn,
                    table_name,
                    df,
                    mappa_province
                )

                print(
                    f"Tabella '{table_name}' sincronizzata."
                )

                # -----------------------------------------
                # ALLINEA AL FILE SORGENTE
                # -----------------------------------------

                if ALLINEA_AL_FILE:

                    allinea_al_file(
                        conn,
                        table_name,
                        df,
                        dry_run=DRY_RUN
                    )

            except Exception as e:

                print(
                    f"\nERRORE su {source}"
                )

                print(str(e))

    finally:

        conn.close()

    print("\nIMPORTAZIONE COMPLETATA")


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":
    importa_excel_in_sqlite()
