import csv
import sys
import sqlite3

from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common


# =========================================================
# GEONAMES -> SQLITE
# =========================================================
#
# Il dump dei codici postali di GeoNames (IT.txt) non ha riga
# di intestazione: i nomi delle colonne sono ricavati dalla
# specifica ufficiale (00 - Input/geonames/readme.txt) e
# restano da confermare a mano.

COLONNE = [
    "country_code",   # iso country code, 2 caratteri
    "postal_code",    # varchar(20)
    "place_name",     # varchar(180)
    "admin_name1",    # 1a suddivisione (stato)
    "admin_code1",    # codice della 1a suddivisione
    "admin_name2",    # 2a suddivisione (provincia)
    "admin_code2",    # codice della 2a suddivisione
    "admin_name3",    # 3a suddivisione (comune)
    "admin_code3",    # codice della 3a suddivisione
    "latitude",       # latitudine stimata (wgs84)
    "longitude",      # longitudine stimata (wgs84)
    "accuracy",       # 1=stimata, 4=geonameid, 6=centroide
]

# Campi convertiti in numero: lat/lon sono coordinate e
# accuracy e' un livello. Tutto il resto resta testo, cosi'
# i codici postali con zeri iniziali non vengono alterati.
CAMPI_NUMERICI = ("latitude", "longitude", "accuracy")

TABELLA = "Geonames"

FILE_SORGENTE = Path("geonames") / "IT.txt"


def importa_geonames_in_sqlite():

    db_name = common.db_path()

    source = common.input_dir() / FILE_SORGENTE

    print(f"Database: {db_name}")
    print(f"File sorgente: {source}")

    if not source.exists():

        print(f"File '{source}' non trovato.")
        return

    # dtype=str + keep_default_na=False: i valori vuoti restano
    # stringhe vuote (non NaN) e i CAP con zeri iniziali sono
    # conservati come testo. QUOTE_NONE: il dump e' tab-separato
    # puro, le virgolette non hanno significato speciale.
    df = pd.read_csv(
        source,
        sep="\t",
        header=None,
        names=COLONNE,
        dtype=str,
        keep_default_na=False,
        encoding="utf-8",
        quoting=csv.QUOTE_NONE,
    )

    for campo in CAMPI_NUMERICI:

        df[campo] = pd.to_numeric(df[campo], errors="coerce")

    print(f"Righe lette: {len(df)}")

    conn = sqlite3.connect(db_name)

    try:

        df.to_sql(
            TABELLA,
            conn,
            if_exists="replace",
            index=False
        )

        conn.commit()

    finally:

        conn.close()

    print(
        f"Tabella '{TABELLA}' aggiornata correttamente "
        f"da {source.name}."
    )


if __name__ == "__main__":

    importa_geonames_in_sqlite()
