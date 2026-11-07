import sqlite3
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common

# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger("DELETE_COMUNE")

# =========================================================
# CONNECT DB
# =========================================================

def connect_db(db_name):

    logger.info(f"Connessione database -> {db_name}")

    try:

        conn = sqlite3.connect(db_name)

        conn.row_factory = sqlite3.Row

        logger.info("Database connesso")

        return conn

    except Exception as e:

        logger.critical(f"Errore connessione DB: {e}")
        sys.exit(1)

# =========================================================
# COUNT RECORDS
# =========================================================

def count_records(cursor, table, codice_istat):

    sql = f"""
        SELECT COUNT(*) as total
        FROM {table}
        WHERE codice_istat = ?
    """

    row = cursor.execute(
        sql,
        (codice_istat,)
    ).fetchone()

    return row["total"]

# =========================================================
# DELETE RECORDS
# =========================================================

def delete_records(cursor, table, codice_istat):

    logger.info(
        f"DELETE -> {table} -> codice_istat={codice_istat}"
    )

    sql = f"""
        DELETE FROM {table}
        WHERE codice_istat = ?
    """

    cursor.execute(
        sql,
        (codice_istat,)
    )

    logger.info(
        f"Righe eliminate da {table}: {cursor.rowcount}"
    )

# =========================================================
# MAIN
# =========================================================

def main():

    logger.info("======================================")
    logger.info("DELETE RECORDS COMUNE")
    logger.info("======================================")

    # -----------------------------------------------------

    conn = connect_db(
        common.db_path()
    )

    cursor = conn.cursor()

    tables = [
        "comuni_mx",
        "comuni_ns",
        "comuni_cname",
        "isdc_scores"
    ]

    # -----------------------------------------------------
    # LOOP PRINCIPALE
    # -----------------------------------------------------

    while True:

        codice_input = input(
            "\nInserisci codice_istat da eliminare (Q per uscire): "
        ).strip()

        # uscita
        if codice_input.upper() == "Q":

            logger.info("Richiesta uscita utente")

            break

        # validazione
        if not codice_input.isdigit():

            logger.error(
                "Codice ISTAT non valido. Inserire un numero oppure Q per uscire."
            )

            continue

        codice_istat = int(codice_input)

        logger.info(
            f"Codice ISTAT selezionato -> {codice_istat}"
        )

        # -------------------------------------------------
        # CONTEGGIO RECORD
        # -------------------------------------------------

        logger.info("Conteggio record da eliminare")

        total_global = 0

        for table in tables:

            total = count_records(
                cursor,
                table,
                codice_istat
            )

            total_global += total

            logger.info(
                f"{table} -> {total} record"
            )

        # -------------------------------------------------

        if total_global == 0:

            logger.warning(
                "Nessun record trovato"
            )

            continue

        # -------------------------------------------------
        # CONFERMA
        # -------------------------------------------------

        confirm = input(
            f"\nTrovati {total_global} record. Confermi eliminazione? (si/no): "
        ).strip().lower()

        if confirm != "si":

            logger.warning(
                "Operazione annullata"
            )

            continue

        # -------------------------------------------------
        # DELETE
        # -------------------------------------------------

        try:

            for table in tables:

                delete_records(
                    cursor,
                    table,
                    codice_istat
                )

            conn.commit()

            logger.info(
                "Commit completato"
            )

        except Exception as e:

            logger.exception(
                f"Errore durante DELETE -> {e}"
            )

            conn.rollback()

            logger.warning(
                "Rollback eseguito"
            )

    # -----------------------------------------------------
    # CHIUSURA
    # -----------------------------------------------------

    conn.close()

    logger.info(
        "Connessione chiusa"
    )

    logger.info(
        "Programma terminato"
    )

# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    main()