import sys
import sqlite3
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common

# ============================================================
# CONFIG
# ============================================================

DB_PATH = common.db_path()

# ============================================================
# CONFIGURAZIONE TIPI
# ============================================================

RECORD_CONFIG = {

    # NOTA: i filtri geografici stanno QUI e non in Crea_View.sql.
    # Le viste alimentano anche StatJson.py, dove contano TUTTI gli
    # enti con punteggio ISDC, georeferenziati o no: filtrarle
    # rimuoverebbe ~570 enti dalle metriche di sovranita'.
    # Qui invece siamo nel produttore di mappe, quindi un ente senza
    # posizione semplicemente non viene disegnato.

    "MX": {
        "table": "POI_MX",
        "output": "poi_mx.geojson",

        "custom_fields": [
            "mx"
        ],

        "mode": "standard"
    },

    "NS": {
        "table": "POI_NS",
        "output": "poi_ns.geojson",

        "custom_fields": [
            "ns_primary"
        ],

        "mode": "standard"
    },

    "CNAME": {
        "table": "POI_CNAME",
        "output": "poi_cname.geojson",

        "custom_fields": [
            "tls_issuer",
            "tls_type"
        ],

        # La colonna non si chiama "cname": senza questa
        # dichiarazione il campo finiva fuori dal GeoJSON in
        # silenzio e la mappa CNAME non mostrava il CNAME.
        "primary_field": "cname_final",

        "mode": "standard"
    },
    
    "DATACENTER": {
        "table": "POI_DATACENTER",
        "output": "poi_datacenter.geojson",

        # Anche i datacenter hanno una tabella separata
        # (AggiornaLatLonDatacenter.py) con la stessa
        # sentinel -1: oggi non ce ne sono, ma il filtro
        # evita che se ne aggiungano senza accorgercene.

        "custom_fields": [
            "Nome",
            "Proprietario",
            "Indirizzo",
            "Città",
            "tipo"
        ],

        "mode": "custom"
    },

    # ========================================================
    # ISDC
    # ========================================================

    "ISDC": {
        "table": "POI_ISDC",
        "output": "poi_isdc.geojson",
        
        "mode": "isdc"
    }

}

# ============================================================
# OUTPUT DIRECTORY
# ============================================================

OUTPUT_DIR = common.frontend_dir()

# ============================================================
# DATABASE
# ============================================================


class FonteNonDisponibile(Exception):
    """
    Vista o tabella non leggibile.

    Una sola fonte che non risponde non deve far fallire
    l'intera fase: si salta quel layer, si segnala e si va
    avanti con gli altri. Il caso tipico e' una vista che non
    e' stata ancora creata, perche' Crea_View.sql non e' stato
    eseguito: senza questo controllo i GeoJSON successivi
    resterebbero indietro di giorni rispetto agli altri e
    nessuno se ne accorgerebbe.
    """


def fetch_poi_data(conn, table_name):
    """
    Legge dati da tabella/view.

    Solleva FonteNonDisponibile se la sorgente non esiste o
    non e' interrogabile, invece di lasciar propagare
    sqlite3.OperationalError.

    Non applica nessun filtro sulle coordinate: il GeoJSON
    deve contenere tutti i punti, anche quelli non
    georeferenziati (lat/lon assenti o -1). In precedenza qui
    c'era un WHERE sulle sole coordinate pubblicabili, che
    escludeva gli enti non localizzati: la mappa non li
    mostrava e la differenza rispetto alla vista non era
    visibile.
    """

    query = f"SELECT * FROM {table_name}"

    try:

        cursor = conn.execute(query)

    except sqlite3.OperationalError as e:

        raise FonteNonDisponibile(
            f"{table_name}: {e}"
        ) from e

    except sqlite3.DatabaseError as e:

        raise FonteNonDisponibile(
            f"{table_name}: file non leggibile ({e})"
        ) from e

    return cursor.fetchall()


# ============================================================
# UTILS
# ============================================================


def row_values(row):
    """
    Riga sqlite3.Row -> dizionario con chiavi normalizzate.

    Le viste non sono coerenti nel nome della colonna chiave:
    POI_MX, POI_NS e POI_CNAME la dichiarano "Codice_IPA",
    POI_ISDC "codice_IPA". La ricerca per nome di sqlite3.Row e'
    case-insensitive, ma keys() non lo e': un controllo del tipo
    `if "codice_IPA" in row.keys()` su quelle viste restituisce
    False e la proprieta' verrebbe scritta come null senza che
    nulla fallisca. Qui le chiavi diventano minuscole una volta
    sola, cosi' il nome non conta piu'.
    """

    return {
        key.lower(): row[key]
        for key in row.keys()
    }


def pick(values, field, default=None):
    """
    Valore di un campo, default se assente
    """

    return values.get(
        field.lower(),
        default
    )


# ============================================================
# BASE PROPERTIES
# ============================================================


def build_identifiers(values):
    """
    Identificatori dell'ente.

    codice_IPA e' la chiave stabile dell'ente e va per prima:
    e' l'unico identificatore che sopravvive a cambi di
    denominazione, ed e' quello con cui i dati si agganciano fra
    loro (contratti, isdc_scores, tabelle DNS).

    codice_istat resta per compatibilita' con i consumatori
    esistenti, ma non e' una chiave: e' nullo sugli enti non
    comuni.
    """

    properties = {}

    codice_ipa = pick(values, "codice_IPA")

    # POI_DATACENTER non descrive un ente e non ha il codice:
    # non si inventa un campo null.
    if codice_ipa is not None:
        properties["codice_IPA"] = codice_ipa

    properties["codice_istat"] = pick(
        values,
        "codice_istat"
    )

    return properties


def build_base_properties(values):
    """
    Campi base comuni
    """

    properties = build_identifiers(values)

    properties["denominazione"] = pick(
        values,
        "denominazione_ita"
    )

    properties["dominio"] = pick(
        values,
        "dominio"
    )

    # Categoria IPA dell'ente (enti_categorie.Nome_categoria,
    # agganciata via enti_contatti.Codice_Categoria in Crea_View.sql).
    # E' un attributo dell'ente, non dell'infrastruttura, quindi sta
    # nei campi base condivisi da MX/NS/CNAME. Il pick e' case
    # insensitive e la vista espone la colonna come "Nome_categoria".
    properties["nome_categoria"] = pick(
        values,
        "Nome_categoria"
    )

    return properties


# ============================================================
# CUSTOM PROPERTIES
# ============================================================


def build_custom_properties(values, custom_fields):
    """
    Campi custom configurabili.

    La ricerca e' case-insensitive (i nomi di values sono
    normalizzati) ma la chiave in output resta quella di
    custom_fields: e' il nome che il frontend si aspetta di
    leggere, e nel caso dei datacenter e' "Nome", "Proprietario",
    "Citta'" con l'iniziale maiuscola.
    """

    properties = {}

    for field in custom_fields:

        key = field.lower()

        if key in values:

            properties[field] = values[key]

    return properties


# ============================================================
# DYNAMIC PROPERTIES
# ============================================================


def build_dynamic_properties(values, record_type, primary_field):
    """
    Campi specifici del tipo di record.

    `primary_field` e' dichiarato in RECORD_CONFIG invece di
    essere dedotto dal prefisso: la colonna non si chiama sempre
    come il tipo di record, e il CNAME ne e' l'esempio. Con
    "cname" non trovato, il campo restava fuori dal GeoJSON senza
    alcun errore.
    """

    prefix = record_type.lower()

    properties = {}

    if primary_field.lower() in values:

        properties[prefix] = values[primary_field.lower()]

    # (campo nella vista -> campo in output)
    field_mapping = (
        (f"{prefix}_ip", f"{prefix}_ip"),
        ("country_name", f"{prefix}_country"),
        ("continent", f"{prefix}_continent"),
        ("asn_organization", f"{prefix}_organization")
    )

    for source_field, output_field in field_mapping:

        if source_field in values:

            properties[output_field] = values[source_field]

    return properties


# ============================================================
# ISDC PROPERTIES
# ============================================================


def build_isdc_properties(values):
    """
    Properties specifiche POI_ISDC.

    Raggruppate per dimensione: punteggio, ASN e organizzazione
    dello stesso canale sono vicine, cosi' il popup si costruisce
    leggendo tre blocchi invece di dodici campi sparsi. La
    dimensione e' calcolata in isdc.py e senza di qui la mappa
    puo' colorare solo sul totale.

    isdc_mx, isdc_dns e isdc_cname hanno il significato di 7.5,
    vedi il capitolo 7 del README. ASN_mx/ns/cname sono i numeri
    di ASN grezzi, utili per il lock-in.
    """

    properties = build_identifiers(values)

    properties.update({

        "denominazione_ita": pick(
            values,
            "denominazione_ita"
        ),

        "dominio": pick(
            values,
            "dominio"
        ),

        # Categoria IPA dell'ente, come nelle mappe MX/NS/CNAME.
        "nome_categoria": pick(
            values,
            "Nome_categoria"
        ),

        # ----------------------------------------------------
        # CANALE MX
        # ----------------------------------------------------

        "isdc_mx": pick(
            values,
            "isdc_mx"
        ),

        "asn_mx": pick(
            values,
            "ASN_mx"
        ),

        "organization_mx": pick(
            values,
            "ORGANIZATION_mx"
        ),

        # ----------------------------------------------------
        # CANALE NS
        # ----------------------------------------------------

        "isdc_dns": pick(
            values,
            "isdc_dns"
        ),

        "asn_ns": pick(
            values,
            "ASN_ns"
        ),

        "organization_ns": pick(
            values,
            "ORGANIZATION_ns"
        ),

        # ----------------------------------------------------
        # CANALE CNAME
        # ----------------------------------------------------

        "isdc_cname": pick(
            values,
            "isdc_cname"
        ),

        "asn_cname": pick(
            values,
            "ASN_cname"
        ),

        "organization_cname": pick(
            values,
            "ORGANIZATION_cname"
        ),

        "tls_issuer": pick(
            values,
            "tls_issuer"
        ),

        "isdc_totale": pick(
            values,
            "ISDC_totale"
        ),

        "isdc_band": pick(
            values,
            "ISDC_band"
        ),

        "hyperscaler": (
            "SI" if pick(values, "hyperscaler") in ("SI", 1, True) else "NO"
        )

    })

    return properties


# ============================================================
# FEATURE
# ============================================================


def build_feature(lat, lon, properties):

    """
    Incapsula Feature GeoJSON.

    Se lat/lon sono assenti il punto non e' georeferenziato, ma
    resta comunque nel file. La geometria non viene omessa: il
    record compare con le coordinate esplicite
    (-1, -1), cioe' lo stesso sentinella usato nel database per
    "coordinata non trovata". Cosi' il campo e' sempre presente
    e leggibile, e il consumer non deve gestire una geometry
    null.
    """

    if lat is None or lon is None:

        lat = common.COORD_NON_TROVATA
        lon = common.COORD_NON_TROVATA

    return {
        "type": "Feature",

        "geometry": {
            "type": "Point",
            "coordinates": [lon, lat]
        },

        "properties": properties
    }


def row_to_feature(
    row,
    record_type,
    custom_fields=None,
    primary_field=None,
    mode="standard"
):
    """
    Converte riga -> Feature GeoJSON
    """

    values = row_values(row)

    try:

        lat = float(values["lat"])
        lon = float(values["lon"])

    except (KeyError, TypeError, ValueError):

        lat = None
        lon = None

    else:

        # -1 e' il sentinella di "coordinata non trovata": e'
        # un dato, non una posizione reale. Il record resta nel
        # file e la geometria viene marcata con lo stesso
        # sentinella (-1, -1), cosi' il consumer puo'
        # riconoscere i punti non georeferenziati senza dover
        # gestire una geometria assente.
        if not common.coordinate_plottable(lat, lon):

            lat = None
            lon = None

    # MODALITÀ CUSTOM (mode=custom)
    if mode == "custom":

        # Inserisce SOLO i campi presenti in custom_fields
        properties = build_custom_properties(
            values,
            custom_fields or []
        )

        return build_feature(lat, lon, properties)

    # ========================================================
    # MODALITÀ ISDC
    # ========================================================

    if mode == "isdc":

        return build_feature(
            lat,
            lon,
            build_isdc_properties(values)
        )

    # ========================================================
    # MODALITÀ STANDARD
    # ========================================================

    properties = {}

    properties.update(
        build_base_properties(values)
    )

    properties.update(
        build_custom_properties(
            values,
            custom_fields or []
        )
    )

    properties.update(
        build_dynamic_properties(
            values,
            record_type,
            primary_field or record_type
        )
    )

    return build_feature(
        lat,
        lon,
        properties
    )


# ============================================================
# GEOJSON
# ============================================================


def generate_geojson(
    rows,
    record_type,
    custom_fields=None,
    primary_field=None,
    mode="standard"
):
    """
    Genera FeatureCollection
    """

    features = []

    senza_geometria = 0

    for row in rows:

        feature = row_to_feature(
            row,
            record_type,
            custom_fields,
            primary_field,
            mode
        )

        # row_to_feature restituisce sempre una Feature: i
        # record non georeferenziati hanno coordinate
        # (-1, -1) e restano nel file. Il controllo su None e'
        # solo una rete di sicurezza: non deve diventare un modo
        # per escludere i punti.
        if feature is None:

            continue

        coords = feature["geometry"]["coordinates"]

        if not common.coordinate_plottable(coords[1], coords[0]):

            senza_geometria += 1

        features.append(feature)

    return {
        "type": "FeatureCollection",
        "features": features
    }, senza_geometria


# ============================================================
# OUTPUT
# ============================================================


def save_geojson(data, output_file):
    """
    Salva GeoJSON
    """

    with open(output_file, "w", encoding="utf-8") as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# DEBUG
# ============================================================


def print_table_columns(rows, table_name):
    """
    Debug colonne disponibili
    """

    if not rows:
        return

    print(f"\nColonne disponibili in {table_name}:")

    for col in rows[0].keys():
        print(f" - {col}")


# ============================================================
# PROCESSING
# ============================================================


def process_record_type(conn, record_type, config):
    """
    Processa un tipo.

    Ritorna True se il layer e' stato scritto, False se la
    fonte non era disponibile.
    """

    table_name = config["table"]

    output_file = (
        OUTPUT_DIR / config["output"]
    )

    custom_fields = config.get(
        "custom_fields",
        []
    )

    mode = config.get(
        "mode",
        "standard"
    )

    primary_field = config.get(
        "primary_field",
        record_type
    )

    print(f"\n=== Elaborazione {record_type} ===")

    print(f"Tabella: {table_name}")

    print(f"Modalità: {mode}")

    print("\nLettura dati...")

    rows = fetch_poi_data(
        conn,
        table_name
    )

    print(f"Record trovati: {len(rows)}")

    if not rows:

        print(
            "ATTENZIONE: nessun record, il GeoJSON verrebbe "
            "scritto vuoto."
        )

    # ========================================================
    # DEBUG COLONNE
    # ========================================================

    print_table_columns(
        rows,
        table_name
    )

    print("\nGenerazione GeoJSON...")

    geojson, senza_geometria = generate_geojson(
        rows,
        record_type,
        custom_fields,
        primary_field,
        mode
    )

    print(f"Feature generate: {len(geojson['features'])}")

    if senza_geometria:

        print(
            f"Record senza coordinate (inclusi nel file con "
            f"coordinate -1,-1): {senza_geometria}"
        )

    print(f"Salvataggio: {output_file}")

    save_geojson(
        geojson,
        output_file
    )

    print(f"{record_type} completato!")

    return True


# ============================================================
# MAIN
# ============================================================


def main():
    """
    Genera tutti i layer.

    Un layer la cui sorgente non esiste viene saltato e
    segnalato, non blocca gli altri: e' il caso normale quando
    una vista non e' ancora stata creata. Il codice di uscita
    resta pero' diverso da zero se qualcosa e' andato storto,
    cosi' chi lancia la pipeline se ne accorge.
    """

    print("Connessione database...")

    conn = sqlite3.connect(DB_PATH)

    conn.row_factory = sqlite3.Row

    # Conteggio dei tre stati delle coordinate. Senza questo, il
    # backlog dei -1 cresce in silenzio: non produce errori, solo
    # enti che finiscono fuori dalla mappa.
    try:

        stato = common.stato_coordinate(conn)

        print(
            f"Coordinate enti -> mai calcolate: "
            f"{stato['mai_calcolate']}, "
            f"non trovate: {stato['non_trovate']}, "
            f"pubblicabili: {stato['pubblicabili']}"
        )

        if stato["non_trovate"]:

            print(
                f"  Le {stato['non_trovate']} non trovate non "
                f"scomparono dai GeoJSON ma restano in "
                f"stat.json."
            )

    except sqlite3.Error as e:

        print(f"Stato coordinate non disponibile: {e}")

    completati = []
    saltati = []

    try:

        for record_type, config in RECORD_CONFIG.items():

            try:

                if process_record_type(
                    conn,
                    record_type,
                    config
                ):

                    completati.append(record_type)

            except FonteNonDisponibile as e:

                saltati.append(record_type)

                print(
                    f"\nERRORE: {record_type} non generato, "
                    f"fonte non disponibile -> {e}"
                )

                print(
                    "Se la vista non esiste, eseguire "
                    "'05 - ISDC/Crea_View.sql' sul database."
                )

    finally:

        conn.close()

    print("\n" + "=" * 60)

    if completati:

        print(f"Generati ({len(completati)}): {', '.join(completati)}")

    if saltati:

        print(f"Saltati  ({len(saltati)}): {', '.join(saltati)}")

    if saltati:

        print(
            f"\n{len(saltati)} layer non generati: "
            f"i GeoJSON corrispondenti restano quelli precedenti."
        )

        return 1

    print("\nTutti i GeoJSON sono stati generati!")

    return 0


if __name__ == "__main__":

    sys.exit(main())
