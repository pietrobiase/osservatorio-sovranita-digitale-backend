# Osservatorio SovranitÃƒÂ  Digitale Ã¢â‚¬â€ Backend

Pipeline dati dell'*Osservatorio SovranitÃƒÂ  Digitale*: raccoglie le anagrafiche degli
enti pubblici italiani, interroga DNS e TLS dei loro domini, arricchisce ogni record con
dati ASN e geografici, calcola l'**Indice di SovranitÃƒÂ  Digitale (ISDC)** e infine
produce i GeoJSON e il file di statistiche consumati dal frontend.

Il frontend ÃƒÂ¨ un repository separato e **non esegue mai SQL**: legge esclusivamente i
file JSON/GeoJSON generati da questa pipeline.

---

## 1. Architettura

```
osservatorio-sovranita-digitale-backend/
Ã¢â€Å“Ã¢â€â‚¬Ã¢â€â‚¬ Fonti.txt                     elenco e URL delle fonti dati
Ã¢â€â€Ã¢â€â‚¬Ã¢â€â‚¬ main/                         radice del progetto (contiene common.py)
    Ã¢â€Å“Ã¢â€â‚¬Ã¢â€â‚¬ common.py                 percorsi, configurazione, GeoIP, helper ASN
    Ã¢â€Å“Ã¢â€â‚¬Ã¢â€â‚¬ pipeline.bat              pipeline principale
    Ã¢â€Å“Ã¢â€â‚¬Ã¢â€â‚¬ 00 - Input/               XLSX e dataset di terze parti
    Ã¢â€Å“Ã¢â€â‚¬Ã¢â€â‚¬ 01 - Config/              config.yaml, config_classificazione.yaml
    Ã¢â€Å“Ã¢â€â‚¬Ã¢â€â‚¬ 02 - LoadAnagrafiche/     caricamento anagrafiche
    Ã¢â€Å“Ã¢â€â‚¬Ã¢â€â‚¬ 02_1 - LoadContratti/     ETL gare pubbliche + classificatori
    Ã¢â€Å“Ã¢â€â‚¬Ã¢â€â‚¬ 03 - AggiornaLatLon/      geocoding indirizzi
    Ã¢â€Å“Ã¢â€â‚¬Ã¢â€â‚¬ 04 - QueryDNS/            raccolta MX/NS/CNAME + ASN + geolocalizzazione
    Ã¢â€Å“Ã¢â€â‚¬Ã¢â€â‚¬   dominio.py               normalizzazione dominio e declinazioni (condiviso)
    Ã¢â€Å“Ã¢â€â‚¬Ã¢â€â‚¬ 05 - ISDC/                calcolo ISDC e creazione viste
    Ã¢â€Å“Ã¢â€â‚¬Ã¢â€â‚¬ 06 - BuildGeojson/        generazione GeoJSON
    Ã¢â€Å“Ã¢â€â‚¬Ã¢â€â‚¬ 07 - StatsJson/           generazione statistiche JSON
    Ã¢â€Å“Ã¢â€â‚¬Ã¢â€â‚¬ 08 - ReportPDF/           report PDF
    Ã¢â€Å“Ã¢â€â‚¬Ã¢â€â‚¬ 09 - UtilsClean/          utility di pulizia
    Ã¢â€â€Ã¢â€â‚¬Ã¢â€â‚¬ database/Enti_IT.db       database SQLite (unico punto di veritÃƒÂ )

osservatorio-sovranita-digitale-frontend/
Ã¢â€â€Ã¢â€â‚¬Ã¢â€â‚¬ main/osservatorio/data/       Ã¢â€ Â destinazione di tutti gli output
```

`common.py` centralizza ogni percorso: nessuno script scrive path a mano.

```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common

common.db_path()                  # main/database/Enti_IT.db
common.input_dir()                # main/00 - Input
common.input_file("enti_contatti", "files_enti")
common.frontend_dir()             # <frontend>/main/osservatorio/data (creata se manca)
common.frontend_file("stat.json")
```

Due moduli sono condivisi fra script e meritano di essere noti:

- **`04 - QueryDNS/dominio.py`** &mdash; `canonicalizza_dominio()` e `declinazioni()`, usati
  dai tre crawler DNS. Sta nella cartella degli script e non in `common.py` perche'
  riguarda il DNS, non l'infrastruttura;
- **`common.campo_vuoto()` / `condizione_coda()` / `conteggio_campi_pieni()` /
  `conserva_valore()`** &mdash; costruiscono le parti di SQL che i tre crawler condividono
  nella coda `--retry` e nell'`ON CONFLICT`. Vedi [04](#04-querydns).

Il frontend viene risolto come `PROJECT_ROOT/../../osservatorio-sovranita-digitale-frontend`,
quindi i due repository devono essere **fratelli** nella stessa cartella superiore.

---

## 2. Prerequisiti

- Python 3.10+ (uso di `zoneinfo` per `Europe/Rome`)
- Pacchetti: `pandas`, `openpyxl`, `PyYAML`, `dnspython`, `geoip2`, `geopy`,
  `numpy`, `scikit-learn`, `sentence-transformers`, `nltk`, `rapidfuzz`, `tqdm`,
  `reportlab`
  (gli ultimi servono solo a classificatori e report).
  Il TLS ÃƒÂ¨ interrogato con `ssl`/`socket`, senza dipendenze aggiuntive.
- Database MaxMind GeoLite2 in `main/04 - QueryDNS/`:
  - `geolite2-asn.mmdb`
  - `GeoLite2-City.mmdb`
  - `GeoLite2-Country.mmdb`

I file `.mmdb` devono essere presenti **prima** di lanciare la fase 04: se mancano, sono
illeggibili o corrotti, `common.open_geoip()` esce con codice `1` invece di degradare in
silenzio.

Per il classificatore NLP:

```bash
python -c "import nltk; nltk.download('stopwords')"
```

> Nel repository non ÃƒÂ¨ presente un `requirements.txt`: la lista qui sopra ÃƒÂ¨ ricavata dagli
> import effettivi degli script.

---

## 3. Configurazione

### `01 - Config/config.yaml`

| Chiave | Valore | Uso |
|---|---|---|
| `database_name` | `database/Enti_IT.db` | path del DB (relativo alla radice progetto) |
| `input_dir` | `00 - Input` | cartella base degli XLSX |
| `max_run` | `1000` | limite record per run (DNS, ISDC, geocoding) |
| `files` | `mxmap`, `datacenter`, `comuni_contatti`, `comuni_lista`, `comuni_cap` | tabelle anagrafiche |
| `files_enti` | `enti_contatti` | anagrafica enti (sincronizzazione per `Codice_IPA`) |
| `isdc_required_tables` | `enti_mx`, `enti_ns`, `enti_cname` | **gate di ammissione al calcolo ISDC**, vedi [7.2](#72-coda-di-elaborazione) |

`isdc_required_tables` accetta anche una stringa singola invece di una lista. I nomi
vengono validati in `common.isdc_required_tables()` contro una lista chiusa
(`enti_mx`, `enti_ns`, `enti_cname`): arrivano dalla configurazione e finiscono in una
query SQL, quindi non possono essere arbitrari. Un elenco vuoto disattiva il controllo.

### `01 - Config/config_classificazione.yaml`

Usata da `classifica_tipo_software.py` e `classifica_codice_istat.py`:

| Chiave | Default | Uso |
|---|---|---|
| `db_path` | `database/Enti_IT.db` | DB su cui scrivere |
| `software_threshold` | `0.65` | soglia di confidenza della classificazione |
| `semantic_threshold` | `0.72` | soglia per l'uso della similaritÃƒÂ  semantica |
| `min_samples_per_class` | `3` | classi con meno campioni vengono rimosse |
| `embedding_model` | `paraphrase-multilingual-MiniLM-L12-v2` | modello di embedding |
| `max_run` | `10` | limite record per esecuzione |

> La copia `02_1 - LoadContratti/config_classificazione.yaml` ÃƒÂ¨ un duplicato obsoleto
> (`db_path: ../database/Comuni_IT.db`): non usarla, i classificatori leggono quella in
> `01 - Config/`.

---

## 4. Database

Un unico file SQLite `main/database/Enti_IT.db` ÃƒÂ¨ il punto di integrazione tra tutte le
fasi.

### Tabelle anagrafiche (da XLSX)

| Tabella | Origine | Chiave |
|---|---|---|
| `enti_contatti` | `enti_contatti.xlsx` (IndicePA) | `Codice_IPA` |
| `comuni_contatti` | `comuni_contatti.xlsx` | `codice_istat` |
| `comuni_lista` | `comuni_lista.xlsx` | `codice_istat` |
| `comuni_cap` | `comuni_cap.xlsx` | Ã¢â‚¬â€ (usata per risolvere `CAP` Ã¢â€ â€™ provincia) |
| `mxmap` | `comuni_mxmap_it_dataset.xlsx` | Ã¢â‚¬â€ |
| `datacenter` | `italy_datacenters.xlsx` | Ã¢â‚¬â€ |

Un vincolo `UNIQUE` ÃƒÂ¨ dichiarato solo dove serve davvero: `codice_IPA` su
`enti_mx`/`enti_ns`/`enti_cname`/`isdc_scores`, `ip` su `ip_country`,
`asn_number` su `asn`. Le tabelle anagrafiche non hanno PK e vengono ricaricate da
zero.

`enti_contatti` ÃƒÂ¨ l'anagrafica di riferimento: mantiene `Codice_IPA`, `Codice_ISTAT`
(nullable), `Denominazione_ente`, `Tipologia`, `CAP`, `Indirizzo`, `Mail1/2`,
`Sito_istituzionale`, `lat`, `lon`, `provincia`.

> `codice_istat` **non** ÃƒÂ¨ una chiave: molti enti non sono comuni.

### Tabelle raccolte DNS (per ente, PK `codice_IPA`)

| Tabella | Contenuto |
|---|---|
| `enti_mx` | `dominio`, `mx`, `priorita`, `mx_ip`, `asn_number`, `last_crawl` |
| `enti_ns` | `dominio`, `ns_primary`, `ns_ip`, `ns_asn`, `last_crawl` |
| `enti_cname` | `dominio`, `a_record`, `a_asn`, `cname_final`, `cname_ip`, `cname_asn`, `tls_ip`, `tls_asn`, `tls_issuer`, `tls_type`, `last_crawl` |

### Tabelle di supporto

| Tabella | Contenuto |
|---|---|
| `asn` | `asn_number` (PK), `asn_organization`, `last_crawl` |
| `ip_country` | `ip` (PK), `country_code`, `country_name`, `continent`, `registered_country`, `cluster_registered_country`, `last_crawl`, `country_source` |
| `isdc_scores` | score ISDC per ente, PK `codice_IPA` |
| `contratti` | gare pubbliche (OCDS) con `codice_istat`, `codice_IPA`, `tipo_software`, `hyperscaler` |
| `isdc_scores_legacy` | copia congelata del vecchio schema per-`codice_istat` |
| `comuni_cap` | Mappa CAP -> comune/provincia per risoluzione provincia |
| `comuni_lista` | Elenco comuni per georeferenziazione contratti |
| `Geonames` | Database GeoNames IT (caricato da `LoadGeonames.py`), usato da `AggiornaLatLonEnti.py --geonames` |
| `change_history_mod` | Storico per-campo delle modifiche (una riga per campo cambiato). Usato da `LoadTableEnti.py` per `enti_contatti` e dai crawler DNS (`get_mx.py`, `get_ns.py`, `get_cname.py`) per `enti_mx`, `enti_ns`, `enti_cname`. Supporta `tipo_operazione` `MOD`/`DEL`. |

### Viste (`05 - ISDC/Crea_View.sql`)

Lo script ÃƒÂ¨ **ri-eseguibile**: ogni vista viene prima rimossa con `DROP VIEW IF EXISTS`.

| Vista | Origine | Note |
|---|---|---|
| `POI_MX` | `enti_contatti` Ã¢â€¹Ë† `enti_mx` Ã¢â€¹Ë† `asn` Ã¢â€¹Ë† `ip_country` | `INNER JOIN` su ASN e IP: escono solo i record geolocalizzati |
| `POI_NS` | idem su `enti_ns` | `LEFT JOIN` su ASN/IP: mantiene gli enti senza nameserver |
| `POI_CNAME` | idem su `enti_cname` | include `tls_issuer`, `tls_type` |
| `POI_ISDC` | `isdc_scores` + join `enti_*` | tutti `LEFT JOIN`: nessuno score viene perso |
| `POI_CONTRATTI` | `contratti` + `comuni_lista` / `enti_contatti` | `UNION` comuni + altri enti, coordinate giÃƒÂ  risolte |
| `POI_DATACENTER` | `datacenter` | semplice proiezione |
| `STAT_SOVRANITA` | `POI_ISDC` | distribuzione per `ISDC_band` |
| `STAT_LOCKIN` | `POI_ISDC` | ASN coincidenti su MX/NS/CNAME |
| `STAT_HYPERSCALER` | `POI_ISDC` | quota enti su Amazon/Google/Microsoft |

**Contratto con il frontend:** nomi e *case* delle colonne delle viste (`Codice_IPA`,
`Codice_ISTAT`, `ISDC_totale`, `ASN_mx`, `ORGANIZATION_mx`, `tls_issuer`, Ã¢â‚¬Â¦) sono parte
del contratto di `Generate_geojson.py` e `StatJson.py`. Rinominarli rompe la pipeline in
modo silenzioso.

---

## 5. Pipeline principale

```bat
cd main
pipeline.bat
```

`pipeline.bat` esegue, nell'ordine:

```
04 get_mx.py  â†’  04 get_ns.py  â†’  04 get_cname.py  â†’  04 geo_lookup.py
05 isdc.py
06 Generate_geojson.py
07 StatJson.py
```

`Contratti_geojson.py` **non Ã¨ nella pipeline** (va lanciato a mano in `06 - BuildGeojson`).

`pipeline.bat` esegue le tre fasi DNS in **modalitÃƒÂ  ordinaria**, cioe' sugli enti nuovi:
il `--retry` ([vedi 04](#04-querydns)) non fa parte della pipeline e va lanciato a mano.

`pipeline.bat` non controlla `errorlevel`: se una fase fallisce le successive partono
lo stesso e il fallimento si vede solo nel log di quella fase.

Le fasi **00, 01, 02, 02_1, 03, 09** e lo script `05 - ISDC/Crea_View.sql`
**non sono nella pipeline** e vanno eseguiti manualmente quando cambiano i dati di
origine o la struttura delle viste.

Ordine di esecuzione completo consigliato per un aggiornamento completo:

```
02 Ã¢â€ â€™ 02_1 Ã¢â€ â€™ 03 Ã¢â€ â€™ 04 (Ãƒâ€”N) Ã¢â€ â€™ Crea_View.sql Ã¢â€ â€™ 05 Ã¢â€ â€™ 06 Ã¢â€ â€™ 07 Ã¢â€ â€™ 08
```

---

## 6. Fasi nel dettaglio

### `02 - LoadAnagrafiche`

**`LoadTable.py`** Ã¢â‚¬â€ caricamento massivo, `pandas.to_sql(if_exists='replace')`:
sovrascrive le tabelle `mxmap`, `datacenter`, `comuni_contatti`, `comuni_lista`,
`comuni_cap`. Un file mancante viene saltato con un avviso.

**`LoadTableEnti.py`** Ã¢â‚¬â€ anagrafica enti, con logica piÃƒÂ¹ delicata perchÃƒÂ© la tabella va
allineata senza perdere i dati derivati:

- normalizzazione nomi colonna, rimozione colonne deprecate (`Codice_natura`,
  `mail3-5`, `Url_*`, Ã¢â‚¬Â¦);
- `Sito_istituzionale` ridotto al dominio nudo;
- `CAP` normalizzato a 5 cifre con zeri iniziali;
- deduplica;
- `sincronizza_enti()`: `INSERT` per i nuovi enti, `UPDATE` per le chiavi giÃ  presenti.
  Se la colonna `stato` esiste, il valore scritto Ã¨ `INS` (nuovo ente),
  `MOD` (ente giÃ  presente con almeno un campo realmente cambiato) oppure `STA`
  (ente giÃ  presente e identico al file, cioÃ¨ STABLE);
- **campi preservati**: `lat`, `lon`, `provincia` non vengono mai sovrascritti; per i
  nuovi enti la provincia Ã¨ risolta dal CAP via `comuni_cap`;
- `allinea_al_file()`: marca `stato = 'DEL'` (in lotti da 500) gli enti il cui
  `Codice_IPA` non Ã¨ piÃ¹ nel file, cosÃ¬ la tabella riflette esattamente l'indice IPA
  corrente. Se la colonna `stato` non esiste, il record viene cancellato (comportamento
  retrocompatibile). `DRY_RUN = True` mostra cosa verrebbe rimosso senza toccare nulla.

**`LoadGeonames.py`** - carica il dataset GeoNames italiano
(`00 - Input/geonames/IT.txt`, 12 campi tab-separati senza intestazione) nella tabella
`Geonames` (`to_sql(if_exists='replace')`). I campi restano testo per preservare i CAP con
zeri iniziali; `latitude`, `longitude` e `accuracy` sono convertiti in numero. La tabella
serve poi al geocoding offline di `03 - AggiornaLatLon` (`--geonames`).

### `02_1 - LoadContratti`

**`clean_contratti.py`** Ã¢â‚¬â€ ETL delle gare pubbliche. Legge `contratti.csv`
(separatore `;`, `latin1`, **percorso relativo: eseguire dalla cartella dello script**),
estrae il testo dagli HTML, converte gli importi in numero, e risolve
`codice_istat` per le amministrazioni che iniziano con `COMUNE DI`. Appende alla tabella
`contratti`.

**`classifica_tipo_software.py`** Ã¢â‚¬â€ classificatore ML degli oggetti di gara in
`contratti.tipo_software`. Pipeline TF-IDF + `LinearSVC` calibrato + similarity
semantica su embedding multilingue; allenato sulle righe giÃƒÂ  classificate, applicato a
quelle vuote. Scrive solo con `--apply`.

```bash
python classifica_tipo_software.py --apply --max-runs 500
```

**`classifica_codice_istat.py`** Ã¢â‚¬â€ entity resolution ISTAT + IPA, *province-aware*.
Combina fuzzy matching (`rapidfuzz`, peso 0.58) e similaritÃƒÂ  semantica (peso 0.42),
con fallback `COMUNE DI Ã¢â‚¬Â¦` e candidate pool `k=80`. Aggiorna `codice_istat` e
`codice_IPA`; scrive solo con `--apply`.

```bash
python classifica_codice_istat.py --apply --max-runs 500
```

### `03 - AggiornaLatLon`

**`AggiornaLatLonEnti.py`** e **`AggiornaLatLonDatacenter.py`** Ã¢â‚¬â€ geocoding via
Nominatim (1 richiesta/secondo, `max_run` record per run).

Costruiscono l'indirizzo concatenando i campi disponibili + `Italia`, poi:

- coordinate trovate Ã¢â€ â€™ `UPDATE lat, lon`;
- coordinate non trovate Ã¢â€ â€™ `lat = -1, lon = -1` (sentinella, per non riprovare i record
  giÃƒÂ  cercati).

I record con `lat IS NULL AND lon IS NULL` sono gli unici candidati.

La coda di default e' pero' separata da quella delle ritentative, perche' i due stati non
sono lo stesso lavoro: i `NULL` sono il backlog da processare, i `-1` sono enti gia'
interrogati senza esito e vanno riprovati solo se qualcosa e' cambiato.

```bash
# default: enti con coordinate mai calcolate
python AggiornaLatLonEnti.py

# --update: rilegge solo i -1, cioe' quelli gia' tentati e falliti
python AggiornaLatLonEnti.py --update

# limite per una sessione di prova (default: max_run da config.yaml)
python AggiornaLatLonEnti.py --update --max-run 20
```

In modalita' `--update` un fallimento riscrive la stessa sentinel e non viene contato come
nuovo fallimento: il conteggio "non trovate" resta quindi il numero di enti che *non* si
riescono a recuperare, non un doppio conteggio di quelli gia' a `-1`.

Con `--geonames` gli stessi enti a `-1` vengono risolti **senza rete**: il `CAP` viene
cercato nella tabella `Geonames` (caricata da `02 - LoadAnagrafiche/LoadGeonames.py`) e, se
trovato, la sua `latitude`/`longitude` sostituisce la sentinella. Il dataset ha piu' righe
per lo stesso CAP, una per localita', quindi vince la prima trovata; se il CAP manca il
record resta a `-1`. L'indirizzo non viene usato, quindi non conta che sia sporco o
incompleto: basta il CAP.

```bash
# geocoding offline dei -1 dal CAP, senza contattare Nominatim
python AggiornaLatLonEnti.py --geonames
```

Tutte le modalita' stampano lo stato dei tre stati delle coordinate all'avvio (se non
c'e' niente da fare) e alla fine, cosi' un run a vuoto non e' indistinguibile da uno che ha
scritto qualcosa.

### `04 - QueryDNS`

Ogni script lavora sugli enti con record mancanti, limitato da `max_run`, e fa
`upsert` su `codice_IPA`.

**`get_mx.py`** Ã¢â‚¬â€ risolve MX del dominio di ogni ente (`8.8.8.8`, `1.1.1.1`), estrae IP
e ASN del mail exchanger, scrive `enti_mx`.

**`get_ns.py`** Ã¢â‚¬â€ risolve i nameserver, scrive `enti_ns`.

**`get_cname.py`** Ã¢â‚¬â€ risolve `a_record` e catena CNAME, poi interroga il TLS del dominio
(`tls_ip`, `tls_asn`, `tls_issuer`, `tls_type`), scrive `enti_cname`.

Tutti e tre condividono `dominio.py`, che contiene `canonicalizza_dominio()` e
`declinazioni()`: nessuno dei tre duplica la logica di normalizzazione.

#### Normalizzazione del dominio

`sito_istituzionale` Ã¨ un campo libero e non un nome di host. Prima di interrogare il
resolver ogni dominio passa da `canonicalizza_dominio()`, che toglie schema, slash
iniziali, percorso, query string, fragment, porta, punto finale e maiuscole, e accetta
anche testo introduttivo estraendo il primo host. Sono **rifiutati** i valori che non
sono un dominio: le caselle di posta (`ente@pec.it`) e i domini malformati.

Il dominio memorizzato in tabella Ã¨ **sempre il valore normalizzato**, non quello grezzo:
serve a mantenere la colonna confrontabile fra le righe storiche e quelle raccolte oggi.

#### Le declinazioni tentate, stadio per stadio

Un dominio puÃ² non rispondere sul nome esatto ma rispondere sulla sua variante. Ogni
script prova quindi piÃ¹ nomi, in ordine, fermandosi al primo successo:

| script | tentativi | motivazione |
|---|---|---|
| `get_cname.py` | dominio, `www.` | il nome nudo puÃ² dare l'A record mentre il `www.` risponde |
| `get_ns.py` | dominio, `www.`, **apex** | sotto un apex gli NS non esistono: sono quelli della zona |
| `get_mx.py` | dominio, `www.` | l'MX **non** si eredita sull'apex superiore (RFC 5321) |

Per il solo NS vale un caso in piÃ¹: se il dominio Ã¨ un sottodominio, si risale di un
livello alla ricerca della zona che lo serve (`scuola.example.it` â†’ `example.it`), e si
prendono gli NS di quella zona. Il risalire Ã¨ fermato a **due etichette**, quindi non si
sale mai fino al TLD.

Gli NS di una zona `.it` sono perÃ² condivisi da molti domini: `edu.it` e `gov.it`
rispondono con i propri nameserver centrali. Se quegli NS venissero attribuiti a una scuola
o a un ufficio, il dato sarebbe falso, quindi il fallback apex **scarta** i registry:
`a.dns.it`, `m.dns.it`, `r.dns.it`, `dns.edu.it` e gli apex `edu.it` / `gov.it`.
Il caso `aci.it` non Ã¨ un registry: `ns-a.aci.it` e `ns-b.aci.it` servono davvero le
province, e i 102 enti ACI ne hanno bisogno.

Il tentativo sull'IP segue la stessa logica: se il nameserver o l'exchanger trovato non
risolve, si prova il suo `www.` prima di dichiarare il campo non trovato.

#### Ritentativa: `--retry` e ricalcolo: `--recalculate`

I tre script supportano `--retry` per recuperare campi mancanti sui record già presenti nelle rispettive tabelle `enti_mx`/`enti_ns`/`enti_cname`. Supportano anche `--recalculate` per ricalcolare ex novo i record già presenti (rileggendo il dominio da `enti_contatti`).

```bash
cd "04 - QueryDNS"
python get_mx.py --retry            # riprova i record già incompleti
python get_mx.py --retry --max-run 500
python get_mx.py --recalculate     # ricalcola ex novo da enti_mx rileggendo dominio da enti_contatti
```

| Flag | Effetto |
| --- | --- |
| `--retry` | legge la coda da `enti_<tabella>` invece che da `enti_contatti` |
| `--recalculate` | legge la coda da `enti_<tabella>` ordinata per `last_crawl ASC`, rilegge `Sito_istituzionale` da `enti_contatti` (join solo su `codice_IPA`), ricalcola ex novo, registra storico in `change_history_mod` (`MOD`/`DEL`), cancella la riga se dominio assente/vuoto in `enti_contatti`, aggiorna solo `last_crawl` se dominio non canonicalizzabile |

#### La coda ruota: esempio

Tre `--retry` consecutivi su `enti_ns` con la rete bloccata, `max-run 30`:

| run | primi 5 record presi in carico |
|---|---|
| 1 | `093`, `0D7QKFH5`, `219TJPHO`, `2FE009RQ`, `2US6PK0U` |
| 2 | `41M5YBG2`, `4QYODNC5`, `5B9J9SUG`, `5DVYPGTK`, `7UG4CTPM` |
| 3 | `GCSW5TUX`, `GFL97UO2`, `GWQ11J62`, `aatom`, `ac_tp` |

Nessun record viene perso e nessuna riga viene cancellata: cambiano solo le date.

#### Stato attuale delle code

Misurato sul database di produzione:

| tabella | righe | completi | in coda | di cui parziali | tutti assenti |
|---|---|---|---|---|---|
| `enti_mx` | 6 550 | 5 817 | 733 | 3 | 730 |
| `enti_ns` | 6 550 | 6 010 | 540 | 1 | 539 |
| `enti_cname` | 6 560 | 5 284 | 1 276 | 5 | 1 271 |

I "tutti assenti" sono quasi interamente irrecuperabili: su 300 campioni, MX risolve per
22 al dominio base e 1 via `www`, NS per 2 e 1. Sono in prevalenza enti senza sito valido
o con dominio morto, non un difetto della raccolta. Il `--retry` ha quindi un rendimento
basso by design e va letto come un giro di **verifica periodica**, non come un riempimento
massivo.

**`geo_lookup.py`** Ã¢â‚¬â€ arricchisce `asn` e `ip_country` a partire dagli IP giÃƒÂ  raccolti
(`mx_ip`, `ns_ip`, `cname_ip`, `a_record`, `tls_ip`):

- ASN e organizzazione letti con `reader._db_reader.get(ip)`;
- paese da GeoLite2-City, con fallback su `registered_country` (da GeoLite2-Country);
- `country_source` valorizzato con `geoip` / `registered` / `unknown`;
- `classify_cluster(None)` Ã¢â€ â€™ `unknown`.

> Il GeoLite2-ASN in uso ÃƒÂ¨ di tipo `asn ipvAll`: `reader.asn()` solleverebbe
> `TypeError`, per questo si usa l'accessor raw.

File di supporto nella stessa cartella: `da_sanificare.txt` (domini da sanificare) e
`trova_duplicati.sql`.

### `05 - ISDC`

**`isdc.py`** Ã¢â‚¬â€ calcola l'Indice di SovranitÃƒÂ  Digitale per ente, leggendo
`enti_contatti`, `enti_mx`, `enti_ns`, `enti_cname`, `asn` e `ip_country`.

Il risultato viene scritto in `isdc_scores` con PK `codice_IPA`. Se la tabella esiste
con il vecchio schema per-`codice_istat`, viene migrata: `isdc_scores_legacy` conserva la
tabella originale e `isdc_scores` viene ricreata.

Un ente entra in coda solo se supera la stessa lettura che `MX_SQL`, `CNAME_SQL` e
`NS_SQL` faranno dopo, su **tutte** le tabelle indicate in `isdc_required_tables`
(`enti_mx`, `enti_ns`, `enti_cname` per default): ÃƒÂ¨ il gate di ammissione descritto in
[7.2](#72-coda-di-elaborazione). `main()` logga i conteggi di candidati, ammessi e
scartati, cosÃƒÂ¬ si vede subito quanto ÃƒÂ¨ ampio il gate.

> **Non lanciare `isdc.py` prima di `geo_lookup.py`.** `MX_SQL` e `CNAME_SQL` fanno join
> interno su `asn` e `ip_country`: senza quelle tabelle il gate non ammetterebbe nessun
> ente, oppure Ã¢â‚¬â€ se i join fossero left Ã¢â‚¬â€ ogni dimensione valerebbe `42.40`.

La **logica di calcolo completa** Ã¢â‚¬â€ coda di elaborazione, funzioni di punteggio,
pesi, normalizzazione, bonus/malus e fasce Ã¢â‚¬â€ ÃƒÂ¨ descritta nel
[capitolo 7](#7-il-calcolo-di-isdc_scores).

**`Crea_View.sql`** Ã¢â‚¬â€ da eseguire **prima** di `Generate_geojson.py` e `StatJson.py`:

```bash
sqlite3 database/Enti_IT.db < "05 - ISDC/Crea_View.sql"
```

### `06 - BuildGeojson`

**`Generate_geojson.py`** Ã¢â‚¬â€ legge le viste e scrive i GeoJSON nel frontend. Config
dichiarata in `RECORD_CONFIG`:

| Record | Vista | Output | Mode |
|---|---|---|---|
| `MX` | `POI_MX` | `poi_mx.geojson` | standard |
| `NS` | `POI_NS` | `poi_ns.geojson` | standard |
| `CNAME` | `POI_CNAME` | `poi_cname.geojson` | standard |
| `DATACENTER` | `POI_DATACENTER` | `poi_datacenter.geojson` | custom |
| `ISDC` | `POI_ISDC` | `poi_isdc.geojson` | isdc |

Ogni riga con coordinate mancanti viene scartata e il totale compare nel log; le feature
hanno `geometry.Point` in `[lon, lat]`.

`fetch_poi_data` non lascia trapelare `sqlite3.OperationalError`: se una vista non esiste
solleva `FonteNonDisponibile`, `process_record_type` la intercetta e `main` salta quel
layer, prosegue con gli altri e restituisce codice di uscita `1`. Una vista non creata
lascia quindi il GeoJSON precedente al suo posto invece di far morire la fase e lasciare
i layer successivi indietro di giorni.

I nomi di colonna nelle viste non sono uniformi (`POI_MX` espone `Codice_IPA`,
`POI_ISDC` espone `codice_IPA`), quindi `row_values()` normalizza le chiavi in minuscolo
prima di ogni lookup: senza, `codice_IPA` e `codice_istat` verrebbero emessi `null` senza
alcun errore.

**`Contratti_geojson.py`** Ã¢â‚¬â€ legge `POI_CONTRATTI`, aggrega per
`codice_istat`/`codice_IPA`/`anno`, calcola `totale_valore` e `numero_contratti`,
deduplica le liste (`oggetti`, `classi_software`, `hyperscaler`, `cig`) e scrive
`poi_contratti.geojson` includendo anche `totale_valore_it` in formato italiano.

### `07 - StatsJson`

**`StatJson.py`** â€” aggrega tutto in `stat.json`, interrogando viste `POI_*` e tabelle
`enti_*`.

Le query sono divise in due categorie, e la differenza Ã¨ deliberata:

- `fetch_one_required` / `fetch_all_required` per le fonti da cui dipende la validitÃ 
  del file: se mancano, sollevano `FonteNonDisponibile`, il JSON **non viene scritto** e
  lo script esce con codice `1`. Un `stat.json` a metÃ  Ã¨ peggio di un `stat.json`
  vecchio: il frontend lo legge e mostra numeri inventati come se fossero misurati.
- `safe_fetch_one` / `safe_fetch_all` per i valori accessori: loggano l'errore e
  restituiscono `0`, senza fermare la generazione.

Sezioni prodotte: `base_dati`, `sovranita_digitale`, `lockin`, `provider`, `resilienza`,
`cloud`, `dns_tls`, piÃ¹ `bands` per la distribuzione ISDC. **Non esistono piÃ¹** le sezioni
`contratti`, `trend_procurement` e `valore_economico_per_anno`: vedi
[10.4](#104-statjsonpy-non-produce-piÃ¹-kpi-contrattuali).

La sezione `base_dati` contiene i totali di censimento **piÃ¹ una card per ogni valore
distinto di `enti_contatti.Tipologia`**, generata dal `GROUP BY` e non da una lista
scritta a mano: se domani un nuovo tipo di ente compare un KPI nuovo senza toccare il
codice. Gli `id` sono derivati da `slug(Tipologia)` e hanno il prefisso `enti_`.

Le tracce sono su **stderr**, perchÃ© `StatJson.py` usa `logging`; `Generate_geojson.py` e
gli altri script usano invece `print` su stdout. Per redirigerle in un file serve creare
prima la cartella (non esiste in `07 - StatsJson`):

```
cd "07 - StatsJson"
mkdir logs 2>nul
python StatJson.py 2> logs\statjson.log
```

#### Controlli di coerenza

Prima di scrivere il file, `StatJson.py` esegue otto controlli e restituiscono un conteggio
dei KO, che fa uscire con codice `1` **anche quando il JSON Ã¨ stato scritto**:

| Controllo | PerchÃ© esiste |
|---|---|
| somma tipologie = enti censiti | intercetta un aggregato su colonna o tabella sbagliata |
| lock-in alto + parziale + distribuito + non determinabile = enti con ISDC | le quattro categorie devono essere una partizione |
| band ISDC sommano agli enti con ISDC | idem sulle fasce |
| percentuali delle band sommano a 100 | discrepanza tra conteggio e percentuale |
| `0 < HHI <= 1` | HHI oltre 1 = denominatore sbagliato |
| quota del primo ASN in 0â€“100 | percentuale espressa come frazione |
| nessuna card `count` a zero | **il controllo che avrebbe intercettato `comuni_mx`/`comuni_ns`/`comuni_cname`, rinominate in `OLD_*`**: tre KPI a zero che sembravano valori normali |
| `id` delle card univoci | il frontend indicizza per `id` |

Un controllo KO **non impedisce la scrittura** del file: serve a far saltare all'occhio il
valore sospetto in fase di revisione, non a bloccare la pipeline su un dato ancora da
ricostruire. Il codice di uscita `1` Ã¨ perÃ² ciÃ² che uno script di verifica deve controllare.

#### Tracce

`traccia_query()` Ã¨ chiamata dentro gli helper `fetch_*_required`, quindi ogni query Ã¨
tracciata per numero, risultato e durata senza dover instrumentare le singole chiamate:

```
[01] enti censiti                 = (23746,)  (99 ms)
[07] tipologie di ente            = 5 righe  (17 ms)
[12] slot ASN                     = (12646,)  (106 ms)
```

Segue un riepilogo di ogni card effettivamente scritta, sezione per sezione. Il
contatore finale di query serve a un controllo rapido: se le query sono 25 ma le card
sono meno, Ã¨ sparito un KPI.

### `08 - ReportPDF`

**`Generate_report.py`** â€” report PDF (`reportlab`) con grafici 2024 vs 2025. **Non
interroga il database**: legge `stat.json` dal frontend e produce
`08 - ReportPDF/report/YYYYMMDD-report-osservatorio.pdf`, con log in
`08 - ReportPDF/logs/`.

> âš  Legge ancora le chiavi dei KPI contrattuali rimosse da `StatJson.py` e
> `data["kpi"]["total_comuni"]`: va aggiornato prima di poterlo usare, vedi
> [10.4](#104-statjsonpy-non-produce-piÃ¹-kpi-contrattuali).

### `09 - UtilsClean`

**`clean_record.py`** Ã¢â‚¬â€ utility interattiva: inserendo un `codice_istat` conta i record
corrispondenti, chiede conferma e li elimina. Utile per ripulire un comune errato prima
di rilanciare la pipeline.

> Ã¢Å¡Â Ã¯Â¸Â La lista tabelle ÃƒÂ¨ **ancora quella pre-modello per-ente**
> (`comuni_mx`, `comuni_ns`, `comuni_cname`, `isdc_scores`). Le tabelle correnti sono
> `enti_mx`, `enti_ns`, `enti_cname`, `isdc_scores`: va aggiornata `tables` in
> `clean_record.py:108` prima di usarlo.

---

## 7. Il calcolo di `isdc_scores`

Questo capitolo documenta per intero la logica applicata da `05 - ISDC/isdc.py`, dalla
selezione degli enti fino alla fascia finale.

### 7.1 Struttura della tabella

```sql
CREATE TABLE isdc_scores (
    codice_IPA       TEXT PRIMARY KEY NOT NULL,
    codice_istat     INTEGER,     -- informativa, NULL per gli enti non comuni
    denominazione_ita TEXT,
    dominio           TEXT,
    ISDC_mx           REAL,
    ISDC_cname        REAL,
    ISDC_dns          REAL,
    ISDC_totale       REAL,
    ISDC_band         TEXT,
    bonus             REAL,
    malus             REAL,
    last_crawl        TEXT
)
```

La chiave ÃƒÂ¨ **`codice_IPA`**. `codice_istat` non puÃƒÂ² esserlo: in `enti_contatti` ÃƒÂ¨ `NULL`
per metÃƒÂ  degli enti e non ÃƒÂ¨ univoco, perchÃƒÂ© piÃƒÂ¹ enti condividono lo stesso codice ISTAT.
Resta come colonna informativa per i raggruppamenti statistici.

I tre punteggi parziali (`ISDC_mx`, `ISDC_cname`, `ISDC_dns`) sono salvati **oltre** al
totale: servono al frontend per mostrare il dettaglio del perchÃƒÂ© un ente ha un certo
punteggio.

### 7.2 Coda di elaborazione

```sql
SELECT c.Codice_IPA, c.Codice_ISTAT, c.Denominazione_ente, c.Sito_istituzionale
FROM enti_contatti c
LEFT JOIN isdc_scores s ON c.Codice_IPA = s.codice_IPA
WHERE s.codice_IPA IS NULL
  AND c.Sito_istituzionale IS NOT NULL
  AND TRIM(c.Sito_istituzionale) != ''
  AND EXISTS (SELECT 1 FROM enti_mx e
              JOIN asn a ON a.asn_number = e.asn_number
              JOIN ip_country i ON i.ip = e.mx_ip
              WHERE e.codice_IPA = c.Codice_IPA)
  AND EXISTS (SELECT 1 FROM enti_ns e
              LEFT JOIN asn a ON a.asn_number = e.ns_asn
              LEFT JOIN ip_country i ON i.ip = e.ns_ip
              WHERE e.codice_IPA = c.Codice_IPA)
  AND EXISTS (SELECT 1 FROM enti_cname e
              JOIN asn a ON a.asn_number = e.cname_asn
              JOIN ip_country i ON i.ip = e.cname_ip
              WHERE e.codice_IPA = c.Codice_IPA)
ORDER BY c.Codice_IPA
LIMIT <max_run>
```

I tre `EXISTS` sono il **gate di ammissione**: non basta che la riga esista, deve esistere
anche **la stessa lettura che il calcolo farÃƒÂ  dopo**. Le tre tabelle sono elencate in
`isdc_required_tables` (`config.yaml`) e validate contro una lista chiusa in
`common.isdc_required_tables()`.

I `FROM`/`JOIN` dei tre `EXISTS` **non sono riscritti a mano**: sono generati da
`isdc.py:DNS_SOURCES`, la stessa struttura da cui nascono `MX_SQL`, `CNAME_SQL` e `NS_SQL`.
Non esiste quindi il rischio che il gate e le query di scoring si disallineino.

| enti su 22 877 con sito | esclusi | residui |
|---|---|---|
| nessun filtro | Ã¢â‚¬â€ | 22 877 |
| record presente in MX, NS e CNAME | 17 877 | 5 000 |
| **+ join su `asn`/`ip_country` risolvibile (implementato)** | 18 626 | **4 251** |

PerchÃƒÂ© il gate ÃƒÂ¨ necessario. Un ente ammesso senza i tre record verrebbe valutato con
`raw = 0.5` su ogni dimensione, cioÃƒÂ¨ `apply_coverage(0.5, 0.4) = 42.40` Ã¢â‚¬â€ un numero che ha
l'aria di essere una misura ma non lo ÃƒÂ¨. PerchÃƒÂ© il gate ÃƒÂ¨ *stretto*. Un ente con la riga
in `enti_mx` ma con `mx_ip` assente da `ip_country` fa comunque zero righe in `MX_SQL` e
riceve lo stesso `42.40`: ÃƒÂ¨ successo su 224 enti su 350 prima che il gate venisse
irrobustito.

La garanzia risultante ÃƒÂ¨ verificabile e riguarda il calcolo, non la coda: **nessun ente
in `isdc_scores` puÃƒÂ² avere `ISDC_mx`, `ISDC_cname` o `ISDC_dns` a `42.40` per assenza di
dati.** Un `42.40` puÃƒÂ² comparire solo come conseguenza della combinazione dei punteggi
(`ISDC_totale`), mai come segnaposto su una dimensione.

Gli altri due filtri hanno effetti diversi:

- **`Sito_istituzionale` non vuoto** Ã¢â‚¬â€ un ente senza dominio non puÃƒÂ² avere MX, NS o
  CNAME: la pipeline DNS li scarta comunque, quindi il punteggio sarebbe privo di
  significato. Vengono esclusi anche dal conteggio "enti censiti".
- **`s.codice_IPA IS NULL`** Ã¢â‚¬â€ la coda ÃƒÂ¨ **incrementale**: ogni ente viene calcolato una
  volta sola. Rilanciare `isdc.py` non ricalcola nulla; per rivalutare un ente bisogna
  cancellarne la riga da `isdc_scores`. In particolare il gate **non** ripara gli score giÃƒÂ 
  calcolati: vedi [10](#10-stato-noto).
- **`ORDER BY Codice_IPA`** Ã¢â‚¬â€ rende i lotti riproducibili fra un giro e l'altro, dato che
  `LIMIT` senza ordinamento darebbe sempre gli stessi record.

Il limite ÃƒÂ¨ `max_run` da `config.yaml` (attualmente `1000`): la coda si svuota a lotti
successivi.

`main()` logga tre conteggi distinti, entrambi calcolati **senza** `LIMIT` perchÃƒÂ© altrimenti
la differenza confonderebbe gli enti scartati dal gate con quelli semplicemente tagliati dal
limite di run:

```
GATE tabelle richieste: enti_mx, enti_ns, enti_cname
CODA 22877 enti con sito e senza score -> 4251 ammessi dal gate, 18626 scartati per dati DNS mancanti
IN CODA 1000 enti da processare
```

Il gate e il `--retry` dei crawler ([04](#04-querydns)) risolvono due problemi diversi e
non si sostituiscono. Il gate serve a **non ammettere** enti che verrebbero valutati con
dati mancanti; il `--retry` serve a **recuperare** quei dati. Nel caso di MX i due si
incontrano: `enti_mx` partecipa al gate con `JOIN` interni su `asn` e `ip_country`, quindi un
ente con `mx_ip` ancora da recuperare non entra nel calcolo finchÃƒÂ© il retry non lo risolve.

Nota la differenza di trattamento fra le tre tabelle: `enti_ns` partecipa al gate con
`LEFT JOIN`, quindi un NS incompleto **resta visibile** al calcolo, mentre per MX e CNAME
il record sparisce. Il `--retry` su `enti_ns` ha quindi un peso maggiore sul punteggio
rispetto a quello su `enti_mx`.

### 7.3 Le tre sorgenti dati

Per ogni ente vengono lette tre tabelle, con cardinalitÃƒÂ  di una riga per record
(`mx_ip`, `ns_ip`, `cname_ip` ciascuno unico):

| Query | Tabelle | Join | Campi estratti |
|---|---|---|---|
| `MX_SQL` | `enti_mx` | `asn`, `ip_country` **inner** | `asn_organization`, `country_name`, `continent`, `host` (`mx`) |
| `CNAME_SQL` | `enti_cname` | `asn`, `ip_country` **inner** | + `tls_issuer`, `host` (`cname_final`) |
| `NS_SQL` | `enti_ns` | `asn`, `ip_country` **left** | `asn_organization`, `country_name`, `continent`, `host` (`ns_primary`) |

I join interni su MX e CNAME escludono i record senza ASN o senza geolocalizzazione: si
punteggio solo ciÃƒÂ² che ÃƒÂ¨ stato effettivamente risolto. NS usa join a sinistra perchÃƒÂ©
`ns_asn` e `ns_ip` possono essere `NULL` (nameserver non risolti) e non si vuole perdere
l'ente.

Ogni query espone l'hostname realmente valutato come `host`: ÃƒÂ¨ l'host a dire se
l'infrastruttura ÃƒÂ¨ ospitata in Italia, non il nome dell'ASN, che puÃƒÂ² essere italiano
mentre il servizio ÃƒÂ¨ interamente overseas.

> **Il join interno ÃƒÂ¨ il vero collo di bottiglia.** Un ente puÃƒÂ² avere la riga in
> `enti_mx` (quindi superare un gate che controlla solo l'esistenza) e tuttavia non
> comparire in `MX_SQL`, perchÃƒÂ© il suo `mx_ip` non ÃƒÂ¨ ancora in `ip_country` o il suo
> `asn_number` non ÃƒÂ¨ in `asn`. In quel caso `infra_score` riceve zero righe e restituisce
> `42.40`. Per questo il gate di [7.2](#72-coda-di-elaborazione) ÃƒÂ¨ costruito sugli stessi
> `FROM`/`JOIN` di queste query: richiede che i dati ci siano, non solo che la riga ci sia.

### 7.4 Le funzioni di punteggio

**`geo_score(country, continent)`** Ã¢â‚¬â€ giudizio sulla giurisdizione dell'infrastruttura.
I controlli sono in cascata: vince il primo che scatta.

| Condizione (nell'ordine del codice) | Score |
|---|---|
| `country == "italy"` | `1.00` |
| `country` Ã¢Ë†Ë† EU (27 Paesi) | `0.85` |
| `country` Ã¢Ë†Ë† `SANCTIONED` = {`china`, `russia`} | `0.25` |
| `continent == "europe"` | `0.70` |
| `continent` Ã¢Ë†Ë† America/Africa/Asia/Oceania | `0.50` |
| altrimenti (sconosciuto) | `0.30` |

> Ã¢Å¡Â Ã¯Â¸Â **L'ordine dei controlli ÃƒÂ¨ parte del calcolo.** `SANCTIONED` sta *sopra* il
> controllo sul continente perchÃƒÂ© MaxMind classifica la Russia nel continente europeo:
> con l'ordine inverso la Russia prenderebbe `0.70`, identica a Francia e Germania,
> annullando la penalitÃƒÂ . Chi modifica `geo_score` deve mantenere questa precedenza.

**`infra_score(asn_organization, host)`** Ã¢â‚¬â€ giudizio sulla natura del provider.
Parte da `0.50` e applica correzioni cumulabili, poi satura a `[0, 1]`.

| Condizione | ÃŽâ€ |
|---|---|
| organization Ã¢Ë†Ë† `HYPERSCALERS` (google, gmail, microsoft, azure, amazon, aws, oracle, alibaba, ibm) | `-0.30` |
| organization Ã¢Ë†Ë† `GLOBAL_CDNS` (cloudflare, akamai, fastly, edgesuite, cdn77) | `-0.20` |
| contiene `.it` o `italia` | `+0.25` |
| contiene `gov`, `comune`, `ministero`, `regione`, `provincia`, `enti` | `+0.35` |

Il matching ÃƒÂ¨ per **sottostringa** su `asn_organization` + `host` in minuscolo, con i due
valori concatenati. Il bonus `+0.25` scatta sull'uno o sull'altro: un MX su
`mx1.serverplan.it` con ASN `Server Plan S.r.l.` lo prende tramite l'host, mentre lo
stesso MX con ASN `Vodafone Italia` ospitato su `mx1.aws.com` non lo prende affatto.

**`tls_score(tls_issuer)`** Ã¢â‚¬â€ giudizio sull'emittente del certificato TLS.

| Condizione | Score |
|---|---|
| emittente assente | `0.50` |
| Ã¢Ë†Ë† `HYPERSCALERS` | `0.20` |
| contiene `let's encrypt` | `0.70` |
| Ã¢Ë†Ë† `{digicert, globalsign, sectigo}` | `0.85` |
| altro | `0.50` |

Le CA commerciali di grandi nome risultano preferite a Let's Encrypt: il razionale ÃƒÂ¨ che
un certificato gratuito emesso da una CA globale non dimostra controllo del
l'infrastruttura da parte dell'ente, mentre una CA con sede o policy nazionali sÃƒÂ¬.

### 7.5 Aggregazione per dimensione

Per ogni dimensione i punteggi grezzi si compongono cosÃƒÂ¬:

| Dimensione | Aggregazione | Formula |
|---|---|---|
| **MX** | `geo` = **max**, `infra` = **media** | `raw = 0.60Ã‚Â·geo + 0.40Ã‚Â·infra` |
| **CNAME** | `geo` = **max**, `infra` = **media**, `tls` = **media** | `raw = 0.50Ã‚Â·geo + 0.30Ã‚Â·infra + 0.20Ã‚Â·tls` |
| **DNS** (NS) | `geo` = **max**, `infra` = **media** | `raw = 0.60Ã‚Â·geo + 0.40Ã‚Â·infra` |

Si prende il **massimo** del geo-score perchÃƒÂ© un solo record in Italia basta a rendere
l'infrastruttura sovrana: la media punirebbe un MX il cui secondo host ÃƒÂ¨ in Europa.
L'infra-score ÃƒÂ¨ invece mediato, perchÃƒÂ© conta la **maggioranza** dei provider.

Se una query non restituisce righe, `raw` vale `0.50` Ã¢â‚¬â€ il valore neutro, nÃƒÂ© buono nÃƒÂ©
cattivo.

### 7.6 Normalizzazione sigmoidale

Il punteggio grezzo ÃƒÂ¨ un valore in `[0, 1]` e viene riportato su scala `0Ã¢â‚¬â€œ100` con una
sigmoide centrata su `0.6`:

```
sigmoid(x) = 100 / (1 + e^(-8Ã‚Â·(x - 0.6)))
```

- `x = 0.6` Ã¢â€ â€™ `50.0`
- `x = 0.9` Ã¢â€ â€™ `91.7`
- `x = 0.5` Ã¢â€ â€™ `31.0`
- `x = 0.0` Ã¢â€ â€™ `0.8`

La curva ÃƒÂ¨ volutamente ripida (`k = 8`): uno scostamento anche piccolo dalla neutralitÃƒÂ 
produce un movimento netto nel punteggio finale.

### 7.7 Fattore di copertura

Un ente con un solo MX e un MX ridondante non ÃƒÂ¨ confrontabile con uno con dieci: si
introduce un fattore di copertura sulla numerositÃƒÂ  dei record.

| Record | `coverage` |
|---|---|
| 0 | `0.40` |
| 1 | `0.70` |
| 2 | `0.90` |
| Ã¢â€°Â¥ 3 | `1.00` |

Il punteggio viene poi **smorzato verso il neutro**:

```
apply_coverage(score, cov) = score Ã‚Â· cov + 50 Ã‚Â· (1 - cov)
```

Una dimensione assente (0 record) non porta a 0 ma a un valore vicino a 50, segnalando
"non lo sappiamo" invece di "ÃƒÂ¨ a terra". Dopo il dimensionamento, `ISDC_mx`,
`ISDC_cname` e `ISDC_dns` sono tutti valori in scala `0Ã¢â‚¬â€œ100`.

### 7.8 Bonus e malus

Calcolati sull'unione delle righe di MX, CNAME e NS dell'ente
(`sovereignty_bonus()`), come **proporzione di righe** che soddisfano ciascuna condizione:

| Condizione | Effetto |
|---|---|
| quota di ASN hyperscaler Ã¢â€°Â¥ 0.80 | `malus -= 20` |
| quota Ã¢â€°Â¥ 0.50 | `malus -= 15` |
| quota Ã¢â€°Â¥ 0.25 | `malus -= 10` |
| quota di CDN globale Ã¢â€°Â¥ 0.50 | `malus -= 10` |
| quota di record in Italia Ã¢â€°Â¥ 0.50 | `bonus += 8` |
| quota di record in EU Ã¢â€°Â¥ 0.95 | `bonus += 6` |

Se non ci sono dati, bonus e malus valgono `0`. Il bonus Italia ed il bonus EU non sono
in cumulativi solo se le rispettive soglie sono entrambe superate: un ente con il 100%
di record in Italia soddisfa anche quella EU (l'Italia ÃƒÂ¨ nell'insieme EU), quindi prende
`+14`.

### 7.9 Totale e fascia

```
ISDC_totale = 0.40Ã‚Â·ISDC_mx + 0.35Ã‚Â·ISDC_cname + 0.25Ã‚Â·ISDC_dns + bonus + malus
ISDC_totale = clamp(ISDC_totale, 0, 100)
```

Il peso piÃƒÂ¹ alto (40%) ÃƒÂ¨ su MX: la posta in gioco del mail exchanger ÃƒÂ¨ la posta in gioco
della posta elettronica dell'ente. Il DNS pesa il 25% come semplice delega tecnica.

`ISDC_band` classifica il risultato:

| Fascia | Range |
|---|---|
| SovranitÃƒÂ  digitale fragile | `Ã¢â€°Â¤ 40` |
| Dipendenza infrastrutturale | `Ã¢â€°Â¤ 60` |
| Infrastruttura eterogenea | `Ã¢â€°Â¤ 78` |
| Infrastruttura sovrana | `> 78` |

Le soglie corrispondono alle card dello `stat.json`: `ISDC Ã¢â€°Â¥ 78` = "Infrastruttura
sovrana", `ISDC < 40` = "SovranitÃƒÂ  fragile".

> La colonna `hyperscaler` non sta in `isdc_scores`: ÃƒÂ¨ calcolata in SQL dentro
> `POI_ISDC`, cercando `amazon` / `microsoft` / `google` nelle tre colonne
> `ORGANIZATION_*`. Se le due definizioni (Python e SQL) divergono, i conteggi del
> frontend e i punteggi non torna: le liste vanno tenute allineate.

### 7.10 Esempio numerico

Ente con: 1 MX in Italia (ASN `Vodafone Italia`, host `mx1.vodafone.it`), 1 CNAME in
Italia (ASN `Cloudflare, Inc.`, host `cdn.example.it`, TLS `Let's Encrypt`), 2 NS
(`ns1.vodafone.it` in Italia e `ns1.ovh.net` in Francia).

**MX**

| Passo | Valore |
|---|---|
| `geo_score(italy)` | `1.00` |
| `infra_score("Vodafone Italia", "mx1.vodafone.it")` | `0.50 + 0.25` = `0.75` |
| `raw` | `0.60Ã‚Â·1.00 + 0.40Ã‚Â·0.75` = `0.90` |
| `sigmoid(0.90)` | `91.68` |
| `coverage(1) = 0.70` | `91.68Ã‚Â·0.70 + 50Ã‚Â·0.30` = **79.18** |

**CNAME**

| Passo | Valore |
|---|---|
| `geo_score(italy)` | `1.00` |
| `infra_score("Cloudflare, Inc.", "cdn.example.it")` | `0.50 Ã¢Ë†â€™ 0.20 + 0.25` = `0.55` |
| `tls_score("Let's Encrypt")` | `0.70` |
| `raw` | `0.50Ã‚Â·1.00 + 0.30Ã‚Â·0.55 + 0.20Ã‚Â·0.70` = `0.805` |
| `sigmoid(0.805)` | `83.75` |
| `coverage(1) = 0.70` | `83.75Ã‚Â·0.70 + 15` = **73.63** |

**DNS**

| Passo | Valore |
|---|---|
| `geo_score` (max fra Italia e Francia) | `1.00` |
| `infra_score` (media di `0.75` e `0.50`) | `0.625` |
| `raw` | `0.60Ã‚Â·1.00 + 0.40Ã‚Â·0.625` = `0.85` |
| `sigmoid(0.85)` | `88.08` |
| `coverage(2) = 0.90` | `88.08Ã‚Â·0.90 + 50Ã‚Â·0.10` = **84.27** |

**Bonus/malus** su 4 righe: nessun hyperscaler Ã¢â€ â€™ nessun malus; CDN al 25% (sotto la
soglia del 50%) Ã¢â€ â€™ nessun malus; Italia al 75% Ã¢â€ â€™ `+8`; EU al 100% Ã¢â€ â€™ `+6`.
Totale `bonus +14`, `malus 0`.

**Totale**

```
0.40Ã‚Â·79.18 + 0.35Ã‚Â·73.63 + 0.25Ã‚Â·84.27 + 14 + 0
= 31.67 + 25.77 + 21.07 + 14
= 92.51  Ã¢â€ â€™  "Infrastruttura sovrana"
```

**Controesempio Ã¢â‚¬â€ dati mancanti.** Un ente senza nameserver non crolla a zero:

```
raw = 0.50 Ã¢â€ â€™ sigmoid(0.50) = 30.97 Ã¢â€ â€™ coverage(0) = 0.40
ISDC_dns = 30.97Ã‚Â·0.40 + 50Ã‚Â·0.60 = 42.40
```

Il valore si ferma intorno a 42: "non sappiamo", non "da rifare da capo".

### 7.11 Impatto delle correzioni

Le due correzioni (penalitÃƒÂ  `SANCTIONED` prima del continente, `host` reale invece della
stringa vuota) sono state verificate sui 50 punteggi giÃƒÂ  presenti in produzione:

| Metrica | Valore |
|---|---|
| delta medio sul totale | `+3.11` |
| delta minimo | `0.00` |
| delta massimo | `+6.49` |
| enti con punteggio invariato | `4 / 50` |
| enti che cambiano fascia | `3 / 50` |

Lo spostamento ÃƒÂ¨ **a favore**: quasi tutti gli host degli enti italiani sono `.it`, quindi
il bonus `+0.25` scatta piÃƒÂ¹ spesso di quanto facesse prima, quando l'host non veniva
guardato. La correzione sulla Russia non ha effetti sui dati attuali (nessun ente
dell'-sample ha infrastruttura russa), ma conta per le elaborazioni successive.

Attenzione: la coda di [7.2](#72-coda-di-elaborazione) ÃƒÂ¨ incrementale, quindi **i 50
punteggi giÃƒÂ  in tabella conservano il valore vecchio**. Per applicare le correzioni:

```sql
DELETE FROM isdc_scores;   -- su una copia, prima di fare le prove
```

e poi rilanciare `isdc.py`. I 50 enti rientrano in coda e vengono ricalcolati.

### 7.12 Persistenza e idempotenza

`save()` scrive con `INSERT Ã¢â‚¬Â¦ ON CONFLICT(codice_IPA) DO UPDATE`:

- `last_crawl` compare **solo** nell'`INSERT`: un punteggio giÃ  calcolato che viene
  ricalcolato mantiene la data di primo inserimento. **Qui la semantica Ã¨ "primo
  inserimento", non "ultimo aggiornamento"**: Ã¨ un'intenzione diversa da quella dei crawler
  DNS ([9](#9-regole-operative)), dove il retry aggiorna la data a ogni tentativo. I due
  script non vanno allineati senza ripensare il gate;
- i punteggi sono arrotondati a 2 decimali prima della scrittura;
- con `results` vuoto la funzione ritorna senza toccare il database.

Il log della fase finisce in `isdc_scores.log`, creato nella cartella da cui ÃƒÂ¨ lanciato
lo script.

---

## 8. Output verso il frontend

Tutti i file finiscono in `<frontend>/main/osservatorio/data/`:

| File | Produttore | Dimensione tipica |
|---|---|---|
| `poi_mx.geojson` | `Generate_geojson.py` | ~2.6 MB |
| `poi_ns.geojson` | `Generate_geojson.py` | ~2.9 MB |
| `poi_cname.geojson` | `Generate_geojson.py` | ~3 MB |
| `poi_isdc.geojson` | `Generate_geojson.py` | ~3.6 MB |
| `poi_datacenter.geojson` | `Generate_geojson.py` | ~145 KB |
| `poi_contratti.geojson` | `Contratti_geojson.py` | ~2 MB |
| `stat.json` | `StatJson.py` | ~8 KB |

La dimensione segue il numero di record della coda, quindi cresce con l'avanzamento delle
fasi 04 e 05.

### 8.1 Campi dei GeoJSON

`codice_IPA` ÃƒÂ¨ **sempre il primo campo** di `properties` nei quattro layer per ente: ÃƒÂ¨ la
chiave con cui il frontend unisce i layer e con cui `StatJson.py` aggrega. I datacenter non
sono enti e non hanno un codice IPA, quindi non lo hanno.

| Layer | `properties` |
|---|---|
| `poi_mx` | `codice_IPA`, `codice_istat`, `denominazione`, `dominio`, `mx`, `mx_ip`, `mx_country`, `mx_continent`, `mx_organization` |
| `poi_ns` | `codice_IPA`, `codice_istat`, `denominazione`, `dominio`, `ns_primary`, `ns_ip`, `ns_country`, `ns_continent`, `ns_organization` |
| `poi_cname` | `codice_IPA`, `codice_istat`, `denominazione`, `dominio`, `tls_issuer`, `tls_type`, `cname`, `cname_ip`, `cname_country`, `cname_continent`, `cname_organization` |
| `poi_isdc` | `codice_IPA`, `codice_istat`, `denominazione_ita`, `dominio`, `isdc_mx`, `asn_mx`, `organization_mx`, `isdc_dns`, `asn_ns`, `organization_ns`, `isdc_cname`, `asn_cname`, `organization_cname`, `tls_issuer`, `isdc_totale`, `isdc_band`, `hyperscaler` |
| `poi_datacenter` | `Nome`, `Proprietario`, `Indirizzo`, `CittÃƒÂ `, `tipo` |

Nel layer ISDC le tre dimensioni (`isdc_mx`, `isdc_dns`, `isdc_cname`) sono esposte
insieme al rispettivo ASN e alla rispettiva organizzazione, in tre blocchi leggibili in
sequenza. Sono i punteggi che `isdc.py` calcola con il significato di 7.5: senza di essi
la mappa puÃƒÂ² colorare solo sul totale e non puÃƒÂ² dire *perchÃƒÂ©* un ente ÃƒÂ¨ fragile.

`denominazione` nei layer DNS e `denominazione_ita` in ISDC hanno nomi diversi per
contratto con il frontend: non vanno uniformati senza modificare entrambi i lati.

### 8.2 Coordinate: tre stati, due usi

`enti_contatti.lat/lon` hanno tre stati che non sono intercambiabili:

| Stato | Significato |
|---|---|
| `NULL` | mai calcolate: l'ente ÃƒÂ¨ in coda, non ancora interrogato |
| `-1` | calcolate e **fallite**: il geocoder ha risposto senza risultato |
| `>= 0` | calcolate con successo, mappabili |

`-1` **non ÃƒÂ¨ una coordinata**: `[-1, -1]` ÃƒÂ¨ un punto valido del golfo di Guinea. Senza un
filtro esplicito finiva disegnato come un ammasso di ~610 marker sovrapposti in ogni layer.

La conseguenza pratica ÃƒÂ¨ che i dati si usano in due modi diversi:

- **statistiche** (`StatJson.py`): tutti i record, georeferenziati o no. Un ente senza
  coordinate ha comunque un'infrastruttura DNS reale e un punteggio ISDC calcolato su dati
  reali; escluderlo perchÃƒÂ© non sappiamo dove si trova introdurrebbe un bias di selezione
 campione, e geograficamente non correggibile perchÃƒÂ© manca il CAP.
- **mappa** (`Generate_geojson.py`): solo i record pubblicabili, perchÃƒÂ© un punto senza
  posizione non ÃƒÂ¨ disegnabile.

Per questo il filtro sta **in `Generate_geojson.py` e non in `Crea_View.sql`**: le viste
`POI_*` sono il contratto dati del database e alimentano anche le statistiche. Il
dettaglio numerico per layer ÃƒÂ¨ nel log a ogni run.

Le definizioni dei tre stati stanno in `common.py` (`COORD_PUBBLICABILI_SQL`,
`COORD_IN_CODA_SQL`, `coordinate_plottable()`, `stato_coordinate()`) perchÃƒÂ© devono restare
un unico punto di riferimento: se SQL e Python definissero la soglia separatamente,
divergerebbero senza che nulla fallisse.

`stato_coordinate()` viene stampato all'avvio di `Generate_geojson.py` perchÃƒÂ© il backlog
dei `-1` non produce errori nÃƒÂ© eccezioni: senza quel controllo cresce in silenzio.

I `-1` non rientrano nella coda di default di `AggiornaLatLonEnti.py`, che seleziona solo i
`NULL`. E' una scelta: il geocoder e' deterministico, e sui 2.115 `-1` nessuno ha indirizzo
vuoto o CAP mancante, quindi l'indirizzo c'e' ed e' semplicemente non risolvibile da
Nominatim. Il tasso di fallimento e' uniforme su tutte le tipologie (13,7% pubbliche
amministrazioni, 11,5% gestori, 11,0% stazioni appaltanti), il che conferma che non e' un
problema di rete. Ritentarli costa una chiamata API per ottenerlo di nuovo.

Se pero' un indirizzo viene corretto nelle fonti, o Nominatim cambia risposta, il modo
per recuperarli e' `AggiornaLatLonEnti.py --update`, che interroga solo i `-1` senza
intaccare il backlog dei `NULL`.

`data/manifest.json` elenca i GeoJSON da precaricare:

```json
["data/poi_mx.geojson", "data/poi_ns.geojson", "data/poi_cname.geojson",
 "data/poi_isdc.geojson", "data/poi_contratti.geojson", "data/poi_datacenter.geojson"]
```

Aggiungere un nuovo GeoJSON richiede di aggiungerlo anche a `manifest.json`.

### 8.3 Il contratto di `stat.json`

Struttura di primo livello: `dataset`, `generated_at`, `kpi`, `bands`.

`kpi` contiene `total_enti` e `sections`, dove ogni sezione Ã¨
`{"title": ..., "cards": [...]}`. Ogni card Ã¨:

```json
{"id": "herfindahl", "title": "...", "subtitle": "...",
 "value": 0.1408, "value_type": "index"}
```

| `value_type` | Significato |
|---|---|
| `count` | numero assoluto di record |
| `percentage` | giÃ  in percentuale (`53.14` = 53,14%) |
| `index` | indice normalizzato 0â€“1 |
| `score` | punteggio ISDC 0â€“100 |
| `list` | stringa con voci separate da `\|` |

**I consumer indicizzano per `id`, quindi gli `id` sono un contratto**, non un'etichetta
cosmetica: rinominarne uno senza aggiornare il frontend lo lascia semplicemente non
visualizzato, senza errore. Per lo stesso motivo va mantenuto univoco.

`kpi.total_enti` (4251) Ã¨ il numero di **enti con ISDC**, cioÃ¨ quelli su cui Ã¨ possibile
misurare la sovranitÃ  digitale. Il censimento completo Ã¨ invece la card `total_enti`
dentro `base_dati` (23746). Sono due numeri diversi con nomi simili: il primo Ã¨ il
denominatore degli indici, il secondo la dimensione della popolazione.

`bands` Ã¨ una lista piatta e indipendente dalle sezioni: `band`, `count`, `pct`. Le
percentuali sommano a 100 con tolleranza 0,05.

---

## 9. Regole operative

**`last_crawl` = data dell'ultimo aggiornamento del record.**
La colonna dice quando il record e' stato scritto l'ultima volta, con successo o senza:
un tentativo fallito la aggiorna lo stesso. Non e' la data di primo inserimento e non
indica la freschezza di un singolo campo.

- compare nelle clause `INSERT` di `get_mx.py`, `get_ns.py`, `get_cname.py`, `isdc.py`,
  `common.upsert_asn()`;
- **compare anche nelle clause `DO UPDATE`** dei tre crawler, che la aggiornano a ogni
  tentativo. E' questa la chiave che rende `--retry` rotante: l'ordinamento della coda e'
  `last_crawl ASC`, quindi il record tentato piu' tempo fa viene sempre prima e un `--retry`
  ripetuto non riprova piu' gli stessi record ([04](#04-querydns));
- `geo_lookup.py` esegue solo insert in `ip_country` e non aggiorna `last_crawl` dei
  record esistenti;
- le riparazioni geografiche legacy continuano a correggere `country_*` lasciando
  `last_crawl` invariato.

**Perche' `last_crawl` va aggiornata anche quando il retry non recupera nulla.** Senza
questa scrittura un record irrecuperabile resterebbe in testa alla coda per sempre, perche'
l'ordinamento non cambierebbe: ogni giro ripartirebbe dagli stessi e la coda non si
svuoterebbe. Costa una riga scritta per ogni tentativo inutile, e in cambio la coda si
svuota davvero ed e' possibile misurare quanto e' vecchio un tentativo.

**Perche' `last_crawl` e' il criterio primario e non un tiebreak.** Ordinare prima per
numero di campi pieni metterebbe in testa i record con piu' dati, e sembrerebbe piu'
sensato, ma i record parziali sono per definizione quelli che hanno gia' un dato: se il
retry fallisce restano parziali e vengono riproposti per sempre, occupando sempre le prime
posizioni. Su `enti_cname` sono 5 parziali contro 1 271 completamente assenti: con
`max_run` ridotto i 1 271 non verrebbero mai tentati. `campi_pieni` resta come tiebreak, per
non sprecare la stessa fascia su un record recuperabile quando la data coincide. Nessun
record viene cancellato.

Nel run ordinario un record gia' presente non viene toccato: la coda arriva da
`enti_contatti` con un `NOT IN` sulle tabelle di destinazione, quindi l'`ON CONFLICT` non
si attiva e la pipeline resta idempotente e ri-eseguibile.

Solo `--retry` aggiorna record gia' presenti, e lo fa in modo conservativo: `COALESCE`
puo' riempiere un campo vuoto, ma non puo' azzerare un dato gia' raccolto. Attenzione,
pero': quando esistono **entrambi** i valori vince quello vecchio, quindi un campo gia'
valorizzato non viene mai corretto. Vedi il punto aperto in
[04 - QueryDNS](#04-querydns).

**Timezone.** I timestamp usano `Europe/Rome`, formato `%Y-%m-%d %H:%M:%S`.

**GeoIP fail-fast.** MMDB mancante, illeggibile, corrotto o GeoIP2 non installato Ã¢â€ â€™
`SystemExit(1)`. La pipeline si ferma invece di scrivere dati incompleti.

**Test.** Non si eseguiscono mai gli script contro `database/Enti_IT.db` direttamente.
Le verifiche si fanno su copie:

```python
import sqlite3
src = sqlite3.connect(r"database/Enti_IT.db")
dst = sqlite3.connect(r"database/test.db")
src.backup(dst)          # copia coerente anche a DB in uso
```

**Attenzione al path del DB in sandbox.** `common.db_path()` risolve `database_name` da
`config.yaml` a partire da `PROJECT_ROOT`, che &egrave; la cartella che contiene
`common.py`. Copiare solo gli script in una directory temporanea **non basta**: se
`common.py` resta quello di `main/`, `db_path()` continua a puntare alla produzione e i
test ci scrivono sopra. Nella sandbox vanno copiati `common.py`, `01 - Config/`,
`database/` e i database GeoLite2.

Per ispezionare senza scrivere usare `file:...?mode=ro`:

```python
con = sqlite3.connect("file:database/Enti_IT.db?mode=ro", uri=True)
```

**Non usare il `mtime` come controllo.** `Enti_IT.db` &egrave; in WAL: le scritture
accumulano in `Enti_IT.db-wal` e il file principale resta invariato fino al checkpoint.
Un `mtime` vecchio **non** significa che nessuno abbia scritto. Per verificare che una run
abbia prodotto scritture, controllare il conteggio delle righe o `last_crawl`.

---

## 10. Stato noto

### 10.1 I dati DNS e la geolocalizzazione sono completi

La geolocalizzazione ÃƒÂ¨ stata portata a termine, quindi il collo di bottiglia descritto in
[7.3](#73-le-tre-sorgenti-dati) ÃƒÂ¨ risolto:

| tabella | righe |
|---|---|
| `enti_mx` | 6 550 |
| `enti_ns` | 6 550 |
| `enti_cname` | 6 560 |
| `asn` | 306 |
| `ip_country` | **4 321** |

Le fasi DNS hanno raccolto **4 324 IP distinti**, di cui **4 321 giÃƒÂ  in `ip_country`
(99,9%)**. Ne restano tre da geolocalizzare, irrilevanti.

Questi conteggi valgono per `Enti_IT.db` in WAL: il file principale puÃƒÂ² avere un
`mtime` precedente all'ultima scrittura, perchÃƒÂ© le transazioni non checkpointate stanno
in `Enti_IT.db-wal`. Per verificare che una run abbia scritto qualcosa **non** usare il
`mtime` del `.db`, bensi il conteggio delle righe o `last_crawl`.

Nota: molti IP servono piÃƒÂ¹ enti Ã¢â‚¬â€ 780 IP distinti coprono tutti i MX, 2 359 tutti i CNAME Ã¢â‚¬â€
quindi una `ip_country` relativamente piccola puÃƒÂ² essere sufficiente. Era il caso anche
prima della bonifica, ma allora `ip_country` aveva 102 righe e la copertura era del 2,7%.

### 10.2 `isdc_scores` ÃƒÂ¨ vuota: va ripopolata

`isdc_scores` ÃƒÂ¨ stata svuotata e i tre enti che avevano ricevuto il valore neutro senza
avere alcun dato DNS (`09Q0MK8F`, `0M9HV9B8`, `0WHKRWPA`, tutti a `42.40` nella fascia
`Dipendenza infrastrutturale`) non ci sono piÃƒÂ¹. Non serve alcuna `DELETE` mirata: il gate
impedisce che vengano ricreati.

La coda ÃƒÂ¨ incrementale, quindi `isdc_scores` si ripopola rilanciando `isdc.py` nei lotti
previsti da `max_run` (`1000`), senza bisogno di alcuna cancellia.

**Risultato atteso**, misurato eseguendo l'intera coda su una copia del DB:

| | |
|---|---|
| enti con sito in anagrafica | 22 877 |
| ammessi dal gate | **4 251** (18,6 %) |
| scartati dal gate | 18 626 (81,4 %) |
| dimensioni a `42.40` per assenza di dati | **0** |

Distribuzione delle fasce risultante:

| enti | ISDC medio | fascia |
|---|---|---|
| 693 | 30,4 | SovranitÃƒÂ  digitale fragile |
| 1 040 | 51,2 | Dipendenza infrastrutturale |
| 809 | 67,6 | Infrastruttura eterogenea |
| 1 709 | 84,6 | Infrastruttura sovrana |

Dopo il ripopolamento vanno ricostruite le viste ([10.3](#103-altro)), altrimenti
`Generate_geojson.py` e `StatJson.py` continueranno a produrre output vuoti.

### 10.3 Altro

- **`POI_ISDC` in produzione ÃƒÂ¨ ancora la versione vecchia.** La vista presente in
  `Enti_IT.db` fa `join comuni_mx on comuni_mx.codice_istat = isdc_scores.codice_istat`;
  con `codice_istat` nullo sugli enti non comuni restituisce **0 righe**, e a cascata
  anche `STAT_SOVRANITA` e `STAT_LOCKIN`. La versione corretta (join su `codice_IPA`, tutti
  `LEFT JOIN`) ÃƒÂ¨ giÃƒÂ  in `05 - ISDC/Crea_View.sql`: **va eseguito lo script sul DB di
  produzione** dopo il ripopolamento di `isdc_scores`.
- `coverage(2)` e `coverage(>=3)` sono irraggiungibili: le tabelle DNS hanno PK
  `codice_IPA`, quindi esiste al massimo un record per ente per tabella. Con il gate
  attivo l'unico valore raggiungibile ÃƒÂ¨ `coverage(1) = 0.7`. I rami restano nel codice per
  compatibilitÃƒÂ  con un eventuale modello multi-riga.
- `clean_record.py` opera ancora sulle tabelle `comuni_*`: vedi nota in `09 - UtilsClean`.
- `02_1 - LoadContratti/config_classificazione.yaml` Ã¨ obsoleto: vedi sezione 3.
- I file `*.py.bak` presenti in `04 - QueryDNS` sono backup manuali della migrazione
  per-ente e possono essere rimossi.

### 10.4 `StatJson.py` non produce piÃ¹ KPI contrattuali

Rimossi da `stat.json` la sezione `contratti` e i blocchi `trend_procurement` e
`valore_economico_per_anno`. Erano derivati da `POI_CONTRATTI`, che a sua volta dipende da
`02_1 - LoadContratti`; nessuno dei due Ã¨ nella pipeline principale, quindi quei numeri
potevano restare fermi su un dataset vecchio senza che nulla lo segnalasse.

Rinominati inoltre `kpi.total_comuni` â†’ `kpi.total_enti` e le card da `comuni_*` a `enti_*`.

**I consumer che leggono le chiavi eliminate non sono ancora stati aggiornati** e quindi
oggi falliscono:

| Consumer | Chiave mancante |
|---|---|
| `08 - ReportPDF/Generate_report.py` | `data["kpi"]["total_comuni"]`, `sections["contratti"]`, `trend_procurement`, `valore_economico_per_anno` |
| frontend `dashboard.html` | `data.kpi.comuni_dataset`, `kpi.total_contratti` |
| frontend `report.html` | l'intero blocco KPI contrattuale e il grafico trend |
| frontend `index.html` | legge `dataset` solo per il titolo: innocuo |

`kpi.total_enti` ha anche un significato diverso dal nome: Ã¨ il numero di **enti con
ISDC**, non il censimento (vedi [8.3](#83-il-contratto-di-statjson)). Un consumer che
sostituisce il nome senza ricontrollare la semantica mostra un numero diverso senza
accorgersene.

Aggiornare il frontend o `Generate_report.py` richiede una decisione di merito, non un
rename meccanico: se quei KPI restano utili vanno ricalcolati da una fonte allineata alla
pipeline, altrimenti vanno tolti anche dalle pagine.


### 10.5 Restano record DNS con campi vuoti

| tabella | record con almeno un campo vuoto |
|---|---|
| `enti_mx` | 733 su 6 550 (11,2%) |
| `enti_ns` | 540 su 6 550 (8,2%) |
| `enti_cname` | 1 276 su 6 560 (19,4%) |

`--retry` esiste proprio per questo ([04](#04-querydns)), ma ha un rendimento basso: quasi
tutti questi record sono **interamente** vuoti (730 su 733 per MX, 539 su 540 per NS,
1 271 su 1 276 per CNAME), e su 300 campioni di record interamente vuoti MX risolve per 22
al dominio base e 1 via `www`, NS per 2 e 1. Quindi la gran parte **non e' un bug** da
riprovare: sono enti senza sito valido, con dominio morto, o con record che il resolver non
espone.

Da distinguere i due gruppi, perche' solo il primo e' un difetto:

- **dominio assente o malformato** â€” dato non recuperabile, l'ente non ha un sito utilizzabile;
- **dominio valido che non risolve** â€” qui il `--retry` ha senso e va girato periodicamente.

Non e' stato fatto uno screening per distinguere i due, quindi **non si sa** quanto della
tabella sia recuperabile. Prima di trattare questi numeri come debito, serve quello screening.

Il `--retry` ruota correttamente la coda (verificato: run consecutivi su blocchi disgiunti,
zero campi persi, `csi_piem` invariato), quindi il limite non e' il meccanismo ma la
reale irrecuperabilita' dei domini.

---

## 11. Fonti dati

L'elenco completo con gli URL originali ÃƒÂ¨ in [`Fonti.txt`](../Fonti.txt).
Sintesi:

| Dataset | Fonte |
|---|---|
| `enti_contatti` | IndicePA Ã¢â‚¬â€ indicepa.gov.it |
| `comuni_contatti`, `comuni_lista`, `comuni_cap` | anagrafiche comunali |
| `contratti` | OCDS Appalti Ã¢â‚¬â€ dati.anticorruzione.it |
| `datacenter` | datacentermap.com |
| GeoLite2 ASN / City / Country | MaxMind |
| CPV | TED/SIMAP Ã¢â‚¬â€ usato per la classificazione software |
