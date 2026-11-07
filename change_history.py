"""
Storico delle modifiche ai dati delle tabelle.

Il database non contiene solo l'ultimo stato: la serie delle
modifiche serve a capire come e' stato costruito un dato e a
distinguere un valore stabile da uno che e' cambiato senza che
nessuno se ne accorga.

La tabella `change_history_mod` registra una riga per ogni campo
che ha cambiato valore, e solo per le operazioni di tipo MOD:

- INSERT: non esiste un valore precedente, niente da confrontare;
- STA: il record e' identico, non c'e' nessuna modifica;
- MOD: i campi interessati sono quelli che cambiano.

    data          - timestamp ISO dell'elaborazione
    nome_tabella  - tabella modificata
    nome_campo    - colonna modificata
    valore_old    - valore precedente (NULL se il campo era assente)
    valore_new    - valore nuovo (NULL se il campo e' stato rimosso)
    chiave_nome   - colonna della chiave del record
    chiave_valore - valore della chiave del record
    script        - script che ha prodotto la modifica
    tipo_operazione - tipo di operazione che ha generato la riga
                      (oggi sempre "MOD": lo storico registra solo
                      le modifiche, non gli inserimenti)

I valori sono conservati come testo: il tipo puo' cambiare fra
un caricamento e l'altro e la storia deve poter rappresentare
qualunque valore senza perdere informazioni. Un valore assente
e' NULL, che resta distinguibile dalla stringa vuota.

`chiave_nome` e `chiave_valore` non sono un extra decorativo:
senza di loro la storia direbbe che un campo e' cambiato, ma non
su quale record, e con piu' tabelle i valori non sarebbero
attribuibili.

Il modulo e' agnostico rispetto alla tabella: la stessa API
serve per `enti_contatti` e per qualunque tabella che verra'
aggiunta in futuro.
"""

from __future__ import annotations

import logging

from datetime import datetime


logger = logging.getLogger(__name__)


# =========================================================
# TABELLA
# =========================================================

TABELLA_STORICO = "change_history_mod"

SCHEMA_STORICO = f"""
CREATE TABLE IF NOT EXISTS {TABELLA_STORICO} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data TEXT NOT NULL,
    nome_tabella TEXT NOT NULL,
    nome_campo TEXT NOT NULL,
    valore_old TEXT,
    valore_new TEXT,
    chiave_nome TEXT,
    chiave_valore TEXT,
    script TEXT,
    tipo_operazione TEXT
)
"""

INDICI_STORICO = (
    f"CREATE INDEX IF NOT EXISTS idx_{TABELLA_STORICO}_tabella_data "
    f"ON {TABELLA_STORICO} (nome_tabella, data)",

    f"CREATE INDEX IF NOT EXISTS idx_{TABELLA_STORICO}_chiave "
    f"ON {TABELLA_STORICO} (nome_tabella, chiave_valore)",
)

COLONNE_STORICO = (
    "data",
    "nome_tabella",
    "nome_campo",
    "valore_old",
    "valore_new",
    "chiave_nome",
    "chiave_valore",
    "script",
    "tipo_operazione",
)


# =========================================================
# FUNZIONI DI BASE
# =========================================================

def adesso() -> str:
    """
    Timestamp ISO dell'istante corrente, in ora locale.

    La timezone e' esplicita: due caricamenti in due momenti
    diversi restano distinguibili anche se l'ora legale cambia
    nel mezzo.
    """

    return datetime.now().astimezone().isoformat(
        timespec="seconds"
    )


def a_testo(valore) -> str | None:
    """
    Converte un valore in testo per lo storico.

    None resta None, che e' diverso dalla stringa vuota: un
    campo assente e un campo valorizzato con "" non si
    confondono.
    """

    if valore is None:

        return None

    return str(valore)


def ensure_table(conn) -> None:
    """
    Crea la tabella dello storico e i suoi indici, se mancano.

    Idempotente: puo' essere chiamata all'inizio di ogni
    caricamento senza effetti collaterali.

    `CREATE TABLE IF NOT EXISTS` non aggiunge colonne a una
    tabella gia' esistente: `tipo_operazione` e' stata
    introdotta dopo, quindi va migrata esplicitamente per le
    istanze create prima. Fallita in silenzio, ogni INSERT che
    la cita cadrebbe.
    """

    cur = conn.cursor()

    cur.execute(SCHEMA_STORICO)

    colonne = {
        row[1]
        for row in cur.execute(f"PRAGMA table_info({TABELLA_STORICO})")
    }

    if "tipo_operazione" not in colonne:

        cur.execute(
            f"ALTER TABLE {TABELLA_STORICO} "
            f"ADD COLUMN tipo_operazione TEXT"
        )

    for indice in INDICI_STORICO:

        cur.execute(indice)

    conn.commit()


# =========================================================
# CONFRONTO
# =========================================================

def confronta(vecchio, nuovo, campi) -> list:
    """
    Restituisce i campi il cui valore e' cambiato.

    `vecchio` e `nuovo` sono sequenze allineate a `campi`, che
    e' la lista delle colonne sincronizzate: il confronto e'
    posizionale, quindi i due valori devono provenire dalla
    stessa lista di campi.

    Ogni elemento restituito e' una tupla
    (nome_campo, valore_old, valore_new).
    """

    modifiche = []

    for indice, campo in enumerate(campi):

        if vecchio[indice] != nuovo[indice]:

            modifiche.append((
                campo,
                vecchio[indice],
                nuovo[indice]
            ))

    return modifiche


# =========================================================
# SCRITTURA
# =========================================================

def costruisci_righe(
    nome_tabella,
    chiave_nome,
    chiave_valore,
    modifiche,
    data=None,
    script=None,
    tipo_operazione=None
) -> list:
    """
    Trasforma le modifiche in righe pronte per l'inserimento.

    Il timestamp e' unico per la chiamata: tutte le modifiche
    prodotte da un caricamento condividono lo stesso `data`,
    cosi' una sessione e' riconoscibile come tale. Se non
    viene passato, ne viene generato uno adesso.

    `tipo_operazione` etichetta la riga con l'operazione che
    l'ha prodotta (per esempio "MOD"): la colonna e' stata
    aggiunta dopo, quindi resta NULL per i chiamanti che non
    la valorizzano.

    Una riga per campo modificato: se un record cambia tre
    campi, tre righe.
    """

    if data is None:

        data = adesso()

    righe = []

    for nome_campo, valore_old, valore_new in modifiche:

        righe.append((
            data,
            nome_tabella,
            nome_campo,
            a_testo(valore_old),
            a_testo(valore_new),
            chiave_nome,
            a_testo(chiave_valore),
            script,
            tipo_operazione
        ))

    return righe


def inserisci(conn, righe) -> int:
    """
    Inserisce le righe di storico nella tabella.

    Non fa commit: la transazione resta quella del chiamante,
    cosi' la modifica ai dati e la sua storia vengono
    confermate insieme o non vengono confermate affatto.

    Restituisce il numero di righe inserite.
    """

    if not righe:

        return 0

    conn.executemany(
        f"""
        INSERT INTO {TABELLA_STORICO} (
            {", ".join(COLONNE_STORICO)}
        ) VALUES (
            {", ".join("?" for _ in COLONNE_STORICO)}
        )
        """,
        righe
    )

    return len(righe)


def registra(
    conn,
    nome_tabella,
    chiave_nome,
    chiave_valore,
    modifiche,
    data=None,
    script=None,
    tipo_operazione=None
) -> int:
    """
    Registra le modifiche di un singolo record.

    Comodo per i caricamenti che trattano un record alla
    volta; per i caricamenti in blocco conviene costruire le
    righe e inserirle a lotti con `costruisci_righe()` e
    `inserisci()`.
    """

    righe = costruisci_righe(
        nome_tabella,
        chiave_nome,
        chiave_valore,
        modifiche,
        data=data,
        script=script,
        tipo_operazione=tipo_operazione
    )

    return inserisci(conn, righe)


def conta(conn, nome_tabella=None) -> int:
    """
    Quante righe di storico contiene la tabella, oppure quante
    riguardano una tabella specifica.
    """

    if nome_tabella is None:

        return conn.execute(
            f"SELECT COUNT(*) FROM {TABELLA_STORICO}"
        ).fetchone()[0]

    return conn.execute(
        f"SELECT COUNT(*) FROM {TABELLA_STORICO} "
        f"WHERE nome_tabella = ?",
        (nome_tabella,)
    ).fetchone()[0]
