# Osservatorio Sovranità Digitale — Backend

Pipeline dati dell'*Osservatorio Sovranità Digitale*: raccoglie le anagrafiche degli enti pubblici italiani, interroga DNS e TLS dei domini istituzionali, arricchisce i record con dati ASN e geografici, calcola l'**Indice di Sovranità Digitale (ISDC)** e produce i GeoJSON e le statistiche consumati dal frontend.

Il frontend è un repository separato e **non esegue mai SQL**: legge esclusivamente i file JSON/GeoJSON generati da questa pipeline.

---

## 1. Architettura

```text
osservatorio-sovranita-digitale-backend/
├── Fonti.txt                     # elenco e URL delle fonti dati
└── main/                         # radice operativa del progetto
    ├── common.py                 # percorsi, configurazione, GeoIP, helper ASN
    ├── change_history.py         # storico per-campo (change_history_mod)
    ├── Crea_View.sql             # viste SQL (POI_*, STAT_*)
    ├── pipeline.bat              # esecuzione rapida della pipeline principale
    ├── 00 - Input/               # file di input (CSV/JSON/XLSX, dataset terzi)
    ├── 01 - Config/              # config.yaml
    ├── 02 - LoadAnagrafiche/     # caricamento anagrafiche e storico modifiche
    ├── 03 - AggiornaLatLon/      # geocoding/aggiornamento coordinate
    ├── 04 - QueryDNS/            # crawler DNS/TLS/ASN (MX, NS, CNAME)
    ├── 05 - ISDC/                # calcolo ISDC e viste correlate
    ├── 06 - BuildGeojson/        # generazione GeoJSON per il frontend
    ├── 07 - StatsJson/           # generazione stat.json
    ├── 08 - ReportPDF/           # reportistica (se utilizzata)
    ├── 09 - UtilsClean/          # script di utilità/manutenzione
    └── database/                 # SQLite e database GeoLite2
```

`PROJECT_ROOT` è la cartella che contiene `common.py` (`main/`). Tutti i percorsi relativi (config, DB, input/output) vengono risolti da lì.

---

## 2. Dipendenze e configurazione

- **Python**: 3.11+ consigliato.
- **Dipendenze tipiche**: `pyyaml`, `dnspython`, `geoip2`, `requests`/`httpx` (a seconda degli script), librerie standard SQLite.
- **Configurazione**: `main/01 - Config/config.yaml`.
  - `database_name`: nome del file SQLite in `main/database/` (es. `Enti_IT.db`).
  - `max_run`: limite di record processati per run dagli script che supportano la coda.

I percorsi e l'accesso alla configurazione sono centralizzati in `common.py`.

---

## 3. Database e tabelle principali

Database SQLite: `main/database/<database_name>` (tipicamente `Enti_IT.db`).

### Tabelle dati principali

| Tabella | Contenuto |
|---|---|
| `enti_contatti` | Anagrafica enti (codice IPA, tipologia/categoria, sito istituzionale, coordinate, ecc.). |
| `enti_mx` | Risultati DNS MX per ente (host MX, IP, ASN, priorità, metadati dominio/crawl). |
| `enti_ns` | Risultati DNS NS per ente (nameserver primario utile, IP, ASN, metadati dominio/crawl). |
| `enti_cname` | Risultati CNAME/A/TLS per ente (catena/finale, IP, ASN, issuer/tipo TLS, metadati). |
| `asn` | Anagrafica ASN osservati. |
| `ip_country` | Geolocalizzazione IP (country/continent/cluster, ecc.). |
| `isdc_scores` | Punteggi ISDC calcolati per ente. |
| `change_history_mod` | Storico per-campo delle modifiche. |

### Storico modifiche (`change_history_mod`)

`change_history_mod` registra una riga per ogni campo effettivamente modificato (o cancellato, nel caso `DEL`).

- **Produttori attuali**:
  - `02 - LoadAnagrafiche/LoadTableEnti.py` su `enti_contatti` (operazioni `MOD`).
  - `04 - QueryDNS/get_mx.py`, `get_ns.py`, `get_cname.py` su `enti_mx`, `enti_ns`, `enti_cname` per le modalità `--retry` e `--recalculate` (`MOD`/`DEL`).
- **`tipo_operazione`**: `MOD` per aggiornamenti; `DEL` per cancellazioni (una riga per campo valorizzato nello snapshot precedente, con `valore_new` nullo).
- **Logica diff**: confronto tra snapshot prima/dopo (stessa transazione), solo campi cambiati; inserimento storico prima del `commit` finale.
- **Campi tracciati (crawler DNS)**: tutti i campi della tabella target tranne `codice_IPA` e `last_crawl` (includono `codice_istat`, `dominio` e i campi DNS/TLS/ASN pertinenti).

> Nota: `change_history.inserisci` inserisce le righe ma non esegue il commit; gli script chiamanti gestiscono la transazione.

---

## 4. Pipeline operativa

### 4.1 Esecuzione rapida (`pipeline.bat`)

`main/pipeline.bat` esegue la sequenza principale:

1. `04 - QueryDNS/get_mx.py`
2. `04 - QueryDNS/get_ns.py`
3. `04 - QueryDNS/get_cname.py`
4. `04 - QueryDNS/geo_lookup.py`
5. `05 - ISDC/isdc.py`
6. `06 - BuildGeojson/Generate_geojson.py`
7. `07 - StatsJson/StatJson.py`

I passaggi di caricamento anagrafiche, geocoding correttivo e le modalità DNS `--retry`/`--recalculate` **non** sono inclusi in `pipeline.bat` e vanno eseguiti manualmente quando necessario.

### 4.2 Flusso logico

```text
Anagrafiche (enti_contatti)
        │
        ├─► QueryDNS (get_mx / get_ns / get_cname) ─► enti_mx / enti_ns / enti_cname + asn
        │                         │
        │                         └─► geo_lookup ─► ip_country
        │
        └─► ISDC (isdc.py) ─► isdc_scores
                                  │
                                  ├─► Crea_View.sql / viste DB
                                  ├─► Generate_geojson.py ─► GeoJSON + manifest
                                  └─► StatJson.py ─► stat.json
```

---

## 5. Moduli (cosa fanno e come usarli)

### 5.1 `02 - LoadAnagrafiche`
Carica/aggiorna le anagrafiche (es. `enti_contatti`) dalle fonti in `00 - Input`. `LoadTableEnti.py` registra lo storico delle modifiche (`MOD`) in `change_history_mod` per i campi tracciati.

### 5.2 `03 - AggiornaLatLon`
Gestisce geocoding/aggiornamento coordinate degli enti. Usare con attenzione ai limiti delle API e alle regole operative sui test (vedi §8).

### 5.3 `04 - QueryDNS`
Raccoglie informazioni DNS/TLS/ASN partendo dal dominio istituzionale (`Sito_istituzionale`).

Script principali:
- `get_mx.py` — record MX, IP MX, ASN (e priorità).
- `get_ns.py` — nameserver (logica apex/registry preservata per evitare attribuzioni errate al registry).
- `get_cname.py` — catena CNAME/A, IP, ASN, TLS (issuer/tipo; logica `tls_permissive` preservata nel flusso ordinario/retry).
- `geo_lookup.py` — geolocalizzazione IP in `ip_country` (inserimenti per IP mancanti; non aggiorna `last_crawl` dei record esistenti).

#### Modalità di esecuzione DNS (`--retry` / `--recalculate`)

Tutti e tre gli script `get_mx.py`, `get_ns.py`, `get_cname.py` supportano:

```bash
cd "04 - QueryDNS"
python get_mx.py
python get_mx.py --retry
python get_mx.py --retry --max-run 500
python get_mx.py --recalculate
python get_mx.py --recalculate --max-run 500
```

| Flag | Effetto |
|---|---|
| `--retry` | Legge la coda dalla tabella target (`enti_mx`/`enti_ns`/`enti_cname`) per riprovare record incompleti. Aggiornamento conservativo (`COALESCE`: un nuovo valore non vuoto può riempire, ma non sovrascrive con vuoto). Registra `MOD` in `change_history_mod` per i campi effettivamente cambiati. |
| `--recalculate` | Ricalcolo **ex novo** dei record già presenti nella tabella target, ordinati per `last_crawl ASC, codice_IPA` (coda rotante), con limite `max_run`. Rilegge il dominio da `enti_contatti` tramite **join solo su `codice_IPA`** (`Codice_ISTAT` solo informativo, mai in `WHERE`). Registra `MOD`/`DEL` in `change_history_mod`. |
| `--max-run N` | Sovrascrive `max_run` da `config.yaml` per la singola esecuzione. |

**Vincoli e semantica:**
- `--retry` e `--recalculate` sono **mutualmente esclusivi**.
- Entrambe le modalità rispettano `max_run` e non effettuano backfill di entità assenti dalle tabelle target.
- `common.upsert_asn` e `change_history.inserisci` non eseguono commit; gli script gestiscono la transazione (storico inserito prima del `commit`).

**Comportamento specifico di `--recalculate`:**
- **Dominio invariato o cambiato** (canonicalizzabile): usa il dominio corrente da `enti_contatti` e sovrascrive i campi DNS/TLS con i risultati ricalcolati ex novo (senza `COALESCE` e senza logiche conservative di freeze/sentinella tipiche del retry, es. gestione speciale di `tls_type='unknown'` / `cname_final` nel retry di `get_cname.py`).
- **Dominio non canonicalizzabile** (es. email, IP, `.`): **SKIP** del record; aggiorna solo `last_crawl` (nessuno storico, nessuna modifica ai campi DNS).
- **`Sito_istituzionale` assente/vuoto in `enti_contatti` (o join non trovato)**: **DELETE** della riga dalla tabella target; registra storico `DEL` (per campi valorizzati nello snapshot). La riga non viene “resuscitata” dalla modalità ordinaria.
- **Fallimento risoluzione in recalc**: scrive il risultato effettivo (comportamento distruttivo rispetto ai dati precedenti; campi irrisolti diventano `NULL`, es. `priorita` non forzata a `0`).

**Comportamento specifico di `--retry`:**
- Utile per recuperare campi mancanti senza cancellare dati già presenti.
- Se esistono sia valore vecchio che nuovo, vince il vecchio (per effetto di `COALESCE`): il retry non è uno strumento di correzione “aggressiva” dei valori già valorizzati.

### 5.4 `05 - ISDC`
Calcola l'indice ISDC e popola `isdc_scores` in base ai dati disponibili (DNS/ASN/geo, secondo le regole implementate nello script e nelle viste). Dopo variazioni strutturali o ripopolamenti può essere necessario rieseguire `Crea_View.sql` per aggiornare le viste consumate da GeoJSON/statistiche.

### 5.5 `06 - BuildGeojson`
Genera i GeoJSON e il `manifest.json` usati dal frontend. Le viste `POI_*` sono il contratto dati lato DB; la pubblicabilità dei punti sulla mappa (coordinate valide/plottabili) va applicata secondo le regole condivise in `common.py` e negli script di generazione.

### 5.6 `07 - StatsJson`
Genera `stat.json` (KPI, bande, metadati dataset) per il frontend/reportistica. Gli `id` delle card sono contrattuali per i consumer: rinominarli richiede aggiornamento coordinato dei consumer.

### 5.7 `08 - ReportPDF` e `09 - UtilsClean`
Script di supporto/reportistica e manutenzione. Verificare sempre prerequisiti e dipendenze prima dell'uso; alcuni script legacy possono fare riferimento a schemi/tabelle non più centrali nella pipeline principale.

---

## 6. Viste SQL e output

- `Crea_View.sql` definisce le viste usate per esportazioni e statistiche (es. `POI_MX`, `POI_NS`, `POI_CNAME`, `POI_ISDC`, viste statistiche correlate).
- `06 - BuildGeojson` produce GeoJSON + manifest per il frontend.
- `07 - StatsJson` produce `stat.json`.

Se cambia la logica di `isdc_scores` o delle viste, rieseguire `Crea_View.sql` sul DB target prima di rigenerare GeoJSON/statistiche.

---

## 7. Regole operative e precauzioni

### 7.1 `last_crawl`
- `last_crawl` rappresenta la **data dell'ultimo aggiornamento/tentativo** del record (successo o fallimento), non la data di primo inserimento.
- Nei crawler DNS viene aggiornata anche in caso di esito negativo/incompleto (e in `--recalculate` anche nei casi di skip/delete handling, dove applicabile), così la coda `last_crawl ASC` ruota davvero.
- Run ordinario e modalità speciali hanno semantiche diverse: il comportamento incrementale/conservativo dipende dallo script e dai flag usati.

### 7.2 Timezone
- Timestamp applicativi: `Europe/Rome`, formato `%Y-%m-%d %H:%M:%S` (salvo diversa specifica nello script).

### 7.3 GeoIP
- Dipendenze e database GeoLite2/MMDB devono essere presenti e leggibili. Errori GeoIP critici devono essere trattati come fail-fast dove previsto, per evitare dati parziali/incoerenti.

### 7.4 Test (obbligatorio su copie)
**Non eseguire test distruttivi o sperimentali su `main/database/Enti_IT.db`.** Usare sempre una copia del DB.

Esempio (copia coerente, anche con DB in uso/WAL):

```python
import sqlite3

src = sqlite3.connect(r"database/Enti_IT.db")
dst = sqlite3.connect(r"database/test.db")
src.backup(dst)
src.close()
dst.close()
```

Per ispezione read-only:

```python
import sqlite3
con = sqlite3.connect("file:database/Enti_IT.db?mode=ro", uri=True)
```

### 7.5 Attenzione a `common.py` e ai path (sandbox/test)
`common.db_path()` risolve il DB da `config.yaml` partendo da `PROJECT_ROOT` (cartella di `common.py`). Copiare solo alcuni script in una directory temporanea **non è sufficiente** se `common.py` resta quello originale: i test potrebbero scrivere sul DB di produzione. In sandbox copiare almeno:
- `common.py`
- `change_history.py` (se serve)
- `01 - Config/`
- `database/` (o i file necessari)
- eventuali DB GeoLite2 richiesti

### 7.6 WAL e verifica delle scritture
`Enti_IT.db` usa WAL: il file `.db` può mantenere un `mtime` vecchio anche dopo scritture (i dati possono stare in `.db-wal` fino al checkpoint). **Non usare `mtime`** per verificare una run.
Controllare invece:
- conteggi righe
- valori di `last_crawl`
- presenza/assenza di record attesi
- righe in `change_history_mod`

### 7.7 Ambiente Windows/PowerShell
- Evitare concatenazioni shell non necessarie; preferire comandi separati.
- Se si usano comandi Unix-like (`grep`, `head`, `tail`) su Windows, verificare che siano disponibili; in alternativa usare PowerShell (`Select-String`, `Select-Object`) o Python.

---

## 8. Stato noto / note operative (da verificare periodicamente)

Questa sezione raccoglie note utili ma **dipendenti dallo stato del DB e dei consumer**. Prima di decisioni operative, verificare sul database/ambiente corrente.

- La copertura DNS/GeoIP, la dimensione di `isdc_scores` e le fasce ISDC cambiano nel tempo: usare query sul DB per i numeri aggiornati.
- `isdc_scores` può richiedere ripopolamento incrementale (in base a `max_run`) e successiva ricostruzione delle viste.
- I consumer di `stat.json` (frontend/report) dipendono dal contratto delle chiavi: modifiche agli `id` o alla semantica dei KPI vanno coordinate.
- La qualità del monitoraggio può essere migliorata raccogliendo più segnali (es. lista completa MX/NS, SPF/DMARC TXT, classificazione provider CNAME/CDN, eventuale analisi HTTP). Queste sono evoluzioni progettuali da implementare in modo incrementale, mantenendo compatibilità con lo schema/storico esistente.

---

## 9. Fonti dati

L'elenco completo con URL originali è in [`../Fonti.txt`](../Fonti.txt) (se presente nel repository). In sintesi, le fonti tipiche includono:

| Dataset / ambito | Fonte |
|---|---|
| Anagrafe enti / contatti | IndicePA |
| Anagrafiche comunali / codici | fonti ISTAT/anagrafiche comunali |
| Contratti (se usati) | OCDS / ANAC (dati.anticorruzione.it) |
| Datacenter (se usati) | datacentermap.com |
| GeoIP ASN/City/Country | MaxMind GeoLite2 |
| CPV (classificazioni) | TED/SIMAP |

---

## 10. Riferimenti rapidi (comandi)

```bash
# Pipeline principale (da main/)
pipeline.bat

# DNS manuale
cd "04 - QueryDNS"
python get_mx.py
python get_ns.py
python get_cname.py
python geo_lookup.py

# Retry / Recalculate (DNS)
python get_mx.py --retry --max-run 500
python get_mx.py --recalculate --max-run 500

# ISDC
cd ..\05 - ISDC
python isdc.py

# Output per frontend
cd ..\06 - BuildGeojson
python Generate_geojson.py
cd ..\07 - StatsJson
python StatJson.py
```

> Eseguire sempre i test su copie del database e verificare i path/config prima di lanciare run su dati reali.
