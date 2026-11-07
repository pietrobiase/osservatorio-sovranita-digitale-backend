import sys
import sqlite3
import pandas as pd
import logging

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common

# Configurazione logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Data della run: creazione del record e ultima visita condividono
# lo stesso formato delle altre tabelle.
CURRENT_CRAWL = datetime.now(ZoneInfo("Europe/Rome")).strftime("%Y-%m-%d %H:%M:%S")

# Lista paesi UE (in formato nome inglese GeoIP)
EU_COUNTRIES = {
    "Austria", "Belgium", "Bulgaria", "Croatia", "Cyprus", "Czechia",
    "Denmark", "Estonia", "Finland", "France", "Germany", "Greece",
    "Hungary", "Ireland", "Italy", "Latvia", "Lithuania", "Luxembourg",
    "Malta", "Netherlands", "Poland", "Portugal", "Romania",
    "Slovakia", "Slovenia", "Spain", "Sweden"
}

# Continente per paese extra UE. Serve solo come fallback: per
# alcuni range anycast (CDN) GeoLite2 non ha il paese ma ha il
# paese di registrazione, e il continente va ricavato da li'.
# L'UE e' gia' coperta da EU_COUNTRIES, quindi qui bastano i
# paesi fuori UE. Chiavi in formato nome inglese GeoIP.
CONTINENT_EXTRA_UE = {
    # Europa
    "United Kingdom": "Europe", "Switzerland": "Europe",
    "Norway": "Europe", "Iceland": "Europe", "Serbia": "Europe",
    "North Macedonia": "Europe", "Montenegro": "Europe",
    "Albania": "Europe", "Bosnia and Herzegovina": "Europe",
    "Moldova": "Europe", "Ukraine": "Europe", "Belarus": "Europe",
    "Russia": "Europe", "Turkey": "Europe", "Georgia": "Europe",
    "Armenia": "Europe", "Azerbaijan": "Europe",
    # America
    "United States": "North America", "Canada": "North America",
    "Mexico": "North America", "Guatemala": "North America",
    "Costa Rica": "North America", "Panama": "North America",
    "Dominican Republic": "North America", "Jamaica": "North America",
    "Trinidad and Tobago": "North America", "Puerto Rico": "North America",
    "Brazil": "South America", "Argentina": "South America",
    "Chile": "South America", "Colombia": "South America",
    "Peru": "South America", "Uruguay": "South America",
    "Paraguay": "South America", "Bolivia": "South America",
    "Ecuador": "South America", "Venezuela": "South America",
    # Asia
    "Japan": "Asia", "China": "Asia", "South Korea": "Asia",
    "Taiwan": "Asia", "India": "Asia", "Singapore": "Asia",
    "Hong Kong": "Asia", "Indonesia": "Asia", "Malaysia": "Asia",
    "Thailand": "Asia", "Vietnam": "Asia", "Philippines": "Asia",
    "United Arab Emirates": "Asia", "Israel": "Asia",
    "Saudi Arabia": "Asia", "Iran": "Asia", "Pakistan": "Asia",
    "Bangladesh": "Asia", "Sri Lanka": "Asia", "Kazakhstan": "Asia",
    # Oceania
    "Australia": "Oceania", "New Zealand": "Oceania",
    # Africa
    "South Africa": "Africa", "Egypt": "Africa", "Morocco": "Africa",
    "Tunisia": "Africa", "Algeria": "Africa", "Nigeria": "Africa",
    "Kenya": "Africa", "Ghana": "Africa"
}

CONTINENT_BY_COUNTRY = dict.fromkeys(EU_COUNTRIES, "Europe")
CONTINENT_BY_COUNTRY.update(CONTINENT_EXTRA_UE)

# Paesi per cui il continente non e' mappato: si segnala una
# volta sola, cosi' il dato resta visibile senza rumore.
_unknown_continents = set()


def continent_for(country_name):
    """
    Continente di un paese, per il fallback su registered_country.
    None se il paese non e' mappato.
    """
    if not country_name:
        return None

    name = country_name.strip()

    continente = CONTINENT_BY_COUNTRY.get(name)

    if continente is None and name not in _unknown_continents:
        _unknown_continents.add(name)
        logger.warning(
            "Continente non mappato per il paese '%s': "
            "country resta valorizzato, continent no. "
            "Aggiungerlo a CONTINENT_EXTRA_UE.",
            name
        )

    return continente


def classify_cluster(registered_country: str) -> str:
    """
    Classifica il cluster in base al nome del paese (GeoIP registered_country).

    Senza paese di registrazione il cluster e' 'unknown': un IP
    non classificabile non va etichettato come extra-UE, che
    affermerebbe un dato che il database non contiene.
    """
    if not registered_country or not registered_country.strip():
        return "unknown"

    country = registered_country.strip()

    # Normalizzazione minima (GeoIP usa già capitalizzazione coerente)
    if country == "Italy":
        return "IT"
    elif country == "United States":
        return "USA"
    elif country in EU_COUNTRIES:
        return "UE"
    else:
        return "Extra UE"


def lookup_ip(reader, ip):
    """
    Geolocalizza un IP e restituisce la riga da scrivere.

    country_source dice da dove arrivano i campi paese:
      geoip     - GeoLite2 ha il paese
      registered- paese assente in GeoLite2, preso dalla
                  registrazione (tipico dei range anycast)
      unknown   - nessuna delle due fonti
    """
    response = reader.country(ip)

    registered = response.registered_country

    registered_name = registered.name if registered else None
    registered_code = registered.iso_code if registered else None

    country_code = response.country.iso_code if response.country else None
    country_name = response.country.name if response.country else None
    continent = response.continent.name if response.continent else None

    if country_code:
        country_source = "geoip"

    elif registered_code or registered_name:
        # Fallback: il range e' anycast e GeoLite2 non ha il
        # paese, ma ha il paese di registrazione.
        country_code = registered_code
        country_name = registered_name
        continent = continent or continent_for(registered_name)
        country_source = "registered"

    else:
        country_source = "unknown"

    return {
        'ip': ip,
        'country_code': country_code,
        'country_name': country_name,
        'continent': continent,
        'registered_country': registered_name,
        'cluster_registered_country': classify_cluster(registered_name),
        'country_source': country_source,
        'last_crawl': CURRENT_CRAWL
    }


def process_ip_geo():
    db_name = common.db_path()
    conn = sqlite3.connect(db_name)

    # 1. Creazione tabella
    conn.execute('''
        CREATE TABLE IF NOT EXISTS ip_country (
            ip TEXT PRIMARY KEY,
            country_code TEXT,
            country_name TEXT,
            continent TEXT,
            registered_country TEXT,
            cluster_registered_country TEXT,
            country_source TEXT,
            last_crawl TEXT
        )
    ''')

    # 1b. Migrazione: le colonne sono state aggiunte dopo la
    #     creazione della tabella, quindi qui si portano avanti.
    for colonna in ("last_crawl", "country_source"):
        try:
            conn.execute(f"ALTER TABLE ip_country ADD COLUMN {colonna} TEXT")
            logger.info(f"Colonna {colonna} aggiunta a ip_country.")
        except sqlite3.OperationalError:
            pass  # gia' presente

    # 2. IP referenziati dalle tabelle enti_*.
    #    La lista e' l'unica fonte di verita per scegliere cosa
    #    processare: un IP viene valutato solo se e' referenziato.
    referenziati = '''
        SELECT mx_ip AS ip FROM enti_mx
        WHERE mx_ip IS NOT NULL AND mx_ip != ''
        UNION
        SELECT ns_ip FROM enti_ns
        WHERE ns_ip IS NOT NULL AND ns_ip != ''
        UNION
        SELECT cname_ip FROM enti_cname
        WHERE cname_ip IS NOT NULL AND cname_ip != ''
        UNION
        SELECT a_record FROM enti_cname
        WHERE a_record IS NOT NULL AND a_record != ''
        UNION
        SELECT tls_ip FROM enti_cname
        WHERE tls_ip IS NOT NULL AND tls_ip != ''
    '''

    # 3. Da geolocalizzare: i nuovi, piu' le righe precedenti
    #    al fallback, che hanno country_source NULL e quindi
    #    non hanno ancora subito alcuna valutazione. Il secondo
    #    caso serve a riparare le righe gia' in tabella: senza,
    #    resterebbero con country_code NULL per sempre, dato che
    #    il filtro sui nuovi IP non le raggiunge piu'.
    query = f'''
        SELECT DISTINCT r.ip
        FROM ({referenziati}) r
        LEFT JOIN ip_country i ON i.ip = r.ip
        WHERE i.ip IS NULL
           OR i.country_source IS NULL
    '''

    ips_to_process = pd.read_sql_query(query, conn)
    logger.info(f"Trovati {len(ips_to_process)} IP da processare.")

    # La dipendenza si valida subito, anche senza lavoro da
    # fare: un mmdb mancante e' un errore di configurazione e
    # deve emergere a ogni run, non solo a coda piena.
    common.open_geoip('GeoLite2-Country.mmdb').close()

    # 4. GeoIP lookup
    results = []

    if not ips_to_process.empty:

        with common.open_geoip('GeoLite2-Country.mmdb') as reader:
            for ip in ips_to_process['ip']:
                try:
                    results.append(lookup_ip(reader, ip))

                except Exception as e:
                    logger.warning(f"Errore geolocalizzazione IP {ip}: {e}")

    # 5. Scrittura su DB. L'upsert aggiorna anche le righe
    #    esistenti da riparare; country_source NULL garantisce
    #    che una riga venga rivalutata una volta sola.
    if results:
        conn.executemany(
            '''
                INSERT INTO ip_country (
                    ip, country_code, country_name, continent,
                    registered_country, cluster_registered_country,
                    country_source, last_crawl
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ip) DO UPDATE SET
                    country_code = excluded.country_code,
                    country_name = excluded.country_name,
                    continent = excluded.continent,
                    registered_country = excluded.registered_country,
                    cluster_registered_country = excluded.cluster_registered_country,
                    country_source = excluded.country_source
            ''',
            [
                (
                    r['ip'], r['country_code'], r['country_name'],
                    r['continent'], r['registered_country'],
                    r['cluster_registered_country'], r['country_source'],
                    r['last_crawl']
                )
                for r in results
            ]
        )
        logger.info(f"Processati e salvati {len(results)} IP.")

        for source, n in conn.execute(
            "SELECT country_source, COUNT(*) n FROM ip_country "
            "GROUP BY country_source ORDER BY n DESC"
        ):
            logger.info(f"  country_source={source}: {n} IP")

    conn.commit()
    logger.info("Scrittura completata.")

    conn.close()


if __name__ == "__main__":
    process_ip_geo()
