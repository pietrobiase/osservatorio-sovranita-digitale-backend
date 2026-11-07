import sys
import sqlite3
import pandas as pd

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common


# =========================================================
# IMPORTAZIONE EXCEL -> SQLITE
# =========================================================

def importa_excel_in_sqlite():

    db_name = common.db_path()

    files = common.input_files("files")

    print(f"Database: {db_name}")

    for table_name, source in files.items():

        print(f"Base dir input: {source.parent}")

        if not source.exists():

            print(f"File '{source}' non trovato.")
            continue

        try:

            # Legge il file Excel
            df = pd.read_excel(source)

            # Salva nel DB sovrascrivendo la tabella esistente
            conn = sqlite3.connect(db_name)
            df.to_sql(table_name, conn, if_exists='replace', index=False)
            conn.commit()
            conn.close()

            print(f"Tabella '{table_name}' aggiornata correttamente da {source.name}.")

        except Exception as e:

            print(f"Errore nell'elaborazione di {source}: {e}")


if __name__ == "__main__":

    importa_excel_in_sqlite()
