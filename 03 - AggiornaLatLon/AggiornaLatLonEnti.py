import sys
import time
import sqlite3
import argparse

from pathlib import Path

from geopy.geocoders import Nominatim
from geopy.exc import (
    GeocoderTimedOut,
    GeocoderServiceError
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common


# ==========================================
# COSTRUZIONE INDIRIZZO
# ==========================================

def costruisci_indirizzo(row):
    """
    Costruisce una stringa indirizzo
    utilizzando i campi disponibili.
    """

    parti = []

    campi = [
        "indirizzo",
        "CAP"
    ]

    for campo in campi:

        valore = row[campo]

        if valore is not None:

            valore = str(valore).strip()

            if valore:
                parti.append(valore)

    # Aggiunge Italia per migliorare geocoding
    parti.append("Italia")

    return ", ".join(parti)


# ==========================================
# GEOLOCALIZZAZIONE
# ==========================================

def geocodifica_indirizzo(geolocator, indirizzo):
    """
    Restituisce (lat, lon)
    oppure (None, None)
    """

    try:

        location = geolocator.geocode(
            indirizzo,
            timeout=15
        )

        if location:

            return (
                location.latitude,
                location.longitude
            )

        return (None, None)

    except (
        GeocoderTimedOut,
        GeocoderServiceError,
        Exception
    ) as e:

        print(
            f"Errore geocoding: {indirizzo}"
        )

        print(str(e))

        return (None, None)


# ==========================================
# GEOCODING DA GEONAMES
# ==========================================

def carica_geonames(cursor):
    """
    Mappa {CAP: (lat, lon)} dalla tabella Geonames.

    In GeoNames lo stesso CAP compare piu' volte, una per ogni
    localita' che lo condivide (es. 39040 ha 141 righe). La
    prima occorrenza trovata vince, cioe' lo stesso criterio
    di un LIMIT 1.

    La scansione e' unica e il risultato resta in memoria: un
    lookup per ogni ente sarebbe invece una scansione completa
    della tabella a ogni giro, che senza indice su postal_code
    e' il costo dominante.
    """

    mappa = {}

    query = """
        SELECT postal_code, latitude, longitude
        FROM Geonames
        WHERE postal_code IS NOT NULL
        ORDER BY rowid
    """

    for postal_code, lat, lon in cursor.execute(query):

        cap = str(postal_code).strip()

        if not cap or cap in mappa:
            continue

        if lat is None or lon is None:
            continue

        mappa[cap] = (lat, lon)

    return mappa


# ==========================================
# MAIN
# ==========================================

def aggiorna_coordinate(ritentativa=False, geonames=False, max_run=None):

    """
    Geolocalizza gli enti.

    Senza argomenti lavora sulle coordinate mai calcolate
    (NULL/NULL). Con ritentativa=True rilegge invece gli enti
    gia' stati tentati e falliti (lat/lon = -1), utile se
    l'indirizzo e' stato corretto nel file di input o se il
    geocoder ha cambiato risposta.

    I due stati non vanno mescolati in un'unica coda: i NULL
    sono il lavoro vero e proprio, i -1 sono un caso eccezionale
    da riesaminare a mano.

    Con geonames=True si lavora ancora sui -1, ma senza rete:
    il CAP dell'ente viene cercato nella tabella Geonames e, se
    trovato, la sua coppia lat/lon sostituisce la sentinella.
    L'indirizzo non viene usato, quindi non conta che sia sporco
    o incompleto: basta il CAP.
    """

    # --------------------------------------
    # Carica configurazione YAML
    # --------------------------------------

    db_name = common.db_path()

    # Numero massimo record per esecuzione
    if max_run is None:
        max_run = common.max_run()

    # --------------------------------------
    # Connessione database
    # --------------------------------------

    conn = sqlite3.connect(db_name)

    # Row factory per accesso nome colonna
    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()

    # --------------------------------------
    # Recupera record da geolocalizzare
    # --------------------------------------
    #
    # I due stati delle coordinate sono definiti in common.py:
    # COORD_IN_CODA_SQL per il lavoro normale, la sentinel -1 per
    # le ritentative. Non vanno mescolati.

    if ritentativa or geonames:

        query = """
            SELECT
                rowid,
                *
            FROM enti_contatti
            WHERE
                lat = ?
                AND lon = ?
            ORDER BY rowid
            LIMIT ?
        """

        cursor.execute(
            query,
            (
                common.COORD_NON_TROVATA,
                common.COORD_NON_TROVATA,
                max_run
            )
        )

        if geonames:

            print(
                "Modalita' GeoNames: solo enti gia' tentati e "
                "falliti (lat/lon = -1), risolti sul CAP."
            )

        else:

            print(
                "Modalita' ritentativa: solo enti gia' tentati e "
                "falliti (lat/lon = -1)."
            )

    else:

        query = f"""
            SELECT
                rowid,
                *
            FROM enti_contatti
            WHERE
                {common.COORD_IN_CODA_SQL}
            ORDER BY rowid
            LIMIT ?
        """

        cursor.execute(query, (max_run,))

        print(
            "Modalita' normale: solo enti con coordinate mai "
            "calcolate (NULL)."
        )

    records = cursor.fetchall()

    if not records:

        if geonames:
            print("Nessun record da georeferenziare via GeoNames.")
        elif ritentativa:
            print("Nessun record da ritentare.")
        else:
            print("Nessun record da geolocalizzare.")

        stato = common.stato_coordinate(conn)

        print(
            f"Stato attuale -> mai calcolate: "
            f"{stato['mai_calcolate']}, "
            f"non trovate: {stato['non_trovate']}, "
            f"pubblicabili: {stato['pubblicabili']}"
        )

        conn.close()

        return

    print(
        f"Record da elaborare: {len(records)}"
    )

    # --------------------------------------
    # Sorgente delle coordinate
    # --------------------------------------

    mappa_geonames = {}

    if geonames:

        mappa_geonames = carica_geonames(cursor)

        print(
            f"CAP distinti nella tabella Geonames: "
            f"{len(mappa_geonames)}"
        )

    else:

        geolocator = Nominatim(
            user_agent="User-Agent: EntiGeocoder/1.0 (pietro@pietrobiase.it)"
        )

    # --------------------------------------
    # Elaborazione record
    # --------------------------------------

    aggiornati = 0
    non_trovati = 0

    for index, row in enumerate(records, start=1):

        try:

            print(
                f"\n[{index}/{len(records)}]"
            )

            if geonames:

                cap = row["CAP"]

                cap = "" if cap is None else str(cap).strip()

                print(
                    f"CAP: {cap}"
                )

                lat, lon = mappa_geonames.get(
                    cap,
                    (None, None)
                )

            else:

                indirizzo = costruisci_indirizzo(row)

                print(
                    f"Ricerca: {indirizzo}"
                )

                lat, lon = geocodifica_indirizzo(
                    geolocator,
                    indirizzo
                )

            # ----------------------------------
            # Coordinate trovate
            # ----------------------------------

            if lat is not None and lon is not None:

                update_query = """
                    UPDATE enti_contatti
                    SET
                        lat = ?,
                        lon = ?
                    WHERE rowid = ?
                """

                cursor.execute(
                    update_query,
                    (
                        lat,
                        lon,
                        row["rowid"]
                    )
                )

                conn.commit()

                aggiornati += 1

                print(
                    f"Coordinate trovate:"
                )

                print(
                    f"lat={lat} lon={lon}"
                )

            # ----------------------------------
            # Coordinate NON trovate
            # ----------------------------------

            else:

                # In modalita' ritentativa e GeoNames l'ente e'
                # gia' a -1: riscrivere la stessa sentinel e' un
                # no-op, si evita solo di contarlo come nuovo
                # fallimento.
                if not ritentativa and not geonames:

                    update_query = """
                        UPDATE enti_contatti
                        SET
                            lat = ?,
                            lon = ?
                        WHERE rowid = ?
                    """

                    cursor.execute(
                        update_query,
                        (
                            common.COORD_NON_TROVATA,
                            common.COORD_NON_TROVATA,
                            row["rowid"]
                        )
                    )

                    conn.commit()

                    print("Impostati lat=-1 e lon=-1")

                non_trovati += 1

                print("Coordinate non trovate.")

            # ----------------------------------
            # Rate limit Nominatim
            # ----------------------------------

            if not geonames:
                time.sleep(1)

        except Exception as e:

            print(
                "Errore durante elaborazione record"
            )

            print(str(e))

    # --------------------------------------
    # Chiusura
    # --------------------------------------

    stato = common.stato_coordinate(conn)

    conn.close()

    print("\n===================================")

    print(
        f"Coordinate aggiornate: {aggiornati}"
    )

    print(
        f"Coordinate non trovate: {non_trovati}"
    )

    print(
        f"Stato finale -> mai calcolate: "
        f"{stato['mai_calcolate']}, "
        f"non trovate: {stato['non_trovate']}, "
        f"pubblicabili: {stato['pubblicabili']}"
    )

    print("Fine elaborazione.")


# ==========================================
# ENTRY POINT
# ==========================================

if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description=(
            "Geolocalizza gli enti di enti_contatti. "
            "Senza opzioni lavora sulle coordinate mai calcolate."
        )
    )

    parser.add_argument(
        "--update",
        action="store_true",
        help=(
            "Rilegge gli enti gia' tentati e falliti "
            "(lat/lon = -1) invece di quelli mai calcolati"
        )
    )

    parser.add_argument(
        "--geonames",
        action="store_true",
        help=(
            "Georeferenzia gli enti gia' tentati e falliti "
            "(lat/lon = -1) usando la tabella Geonames sul CAP, "
            "senza contattare il geocoder"
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

    aggiorna_coordinate(
        ritentativa=args.update,
        geonames=args.geonames,
        max_run=args.max_run
    )
