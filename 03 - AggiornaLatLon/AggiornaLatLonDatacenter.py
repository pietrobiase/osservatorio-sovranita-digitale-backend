import sys
import time
import sqlite3

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
        "Indirizzo",
        "CAP",
        "Città"
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
# MAIN
# ==========================================

def aggiorna_coordinate():

    # --------------------------------------
    # Carica configurazione YAML
    # --------------------------------------

    db_name = common.db_path()

    # Numero massimo record per esecuzione
    max_run = common.max_run()

    # --------------------------------------
    # Connessione database
    # --------------------------------------

    conn = sqlite3.connect(db_name)

    # Row factory per accesso nome colonna
    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()

    # --------------------------------------
    # Recupera record senza coordinate
    # --------------------------------------

    query = """
        SELECT
            rowid,
            *
        FROM datacenter
        WHERE
            lat IS NULL
            AND lon IS NULL
        LIMIT ?
    """

    cursor.execute(query, (max_run,))

    records = cursor.fetchall()

    if not records:

        print(
            "Nessun record da geolocalizzare."
        )

        conn.close()

        return

    print(
        f"Record da elaborare: {len(records)}"
    )

    # --------------------------------------
    # Geolocator
    # --------------------------------------

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

            indirizzo = costruisci_indirizzo(row)

            print(
                f"\n[{index}/{len(records)}]"
            )

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
                    UPDATE datacenter
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

                update_query = """
                    UPDATE datacenter
                    SET
                        lat = -1,
                        lon = -1
                    WHERE rowid = ?
                """

                cursor.execute(
                    update_query,
                    (
                        row["rowid"],
                    )
                )

                conn.commit()

                non_trovati += 1

                print(
                    "Coordinate non trovate."
                )

                print(
                    "Impostati lat=-1 e lon=-1"
                )

            # ----------------------------------
            # Rate limit Nominatim
            # ----------------------------------

            time.sleep(1)

        except Exception as e:

            print(
                "Errore durante elaborazione record"
            )

            print(str(e))

    # --------------------------------------
    # Chiusura
    # --------------------------------------

    conn.close()

    print("\n===================================")

    print(
        f"Coordinate aggiornate: {aggiornati}"
    )

    print(
        f"Coordinate non trovate: {non_trovati}"
    )

    print("Fine elaborazione.")


# ==========================================
# ENTRY POINT
# ==========================================

if __name__ == "__main__":
    aggiorna_coordinate()
