# Osservatorio Sovranità Digitale — Backend

Pipeline dati dell'*Osservatorio Sovranità Digitale*: raccoglie le anagrafiche degli enti pubblici italiani, interroga DNS e TLS dei domini istituzionali, arricchisce i record con dati ASN e geografici, calcola l'**Indice di Sovranità Digitale della Pubblica Amministrazione (ISDPA)** e produce i GeoJSON e le statistiche consumati dal frontend.

Il frontend è un repository separato e **non esegue mai SQL**: legge esclusivamente i file JSON/GeoJSON generati da questa pipeline.

**Documentazione online:** la documentazione metodologica e tecnica dell'Osservatorio è pubblicata su Read the Docs: [sovranita-digitale-osservatorio.readthedocs.io](https://sovranita-digitale-osservatorio.readthedocs.io/).

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
    ├── 05 - ISDC/                # calcolo ISDPA e viste correlate
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
| `ip_country` | Geolocalizzazione IP (paese, continente, paese di registrazione, cluster e fonte `country_source`). |
| `country_coordinates` | Centroidi dei paesi per codice ISO alpha-2 (`alpha2`, `alpha3`, `latitude`, `longitude`, `name`), caricati da `00 - Input/country-centroids.xlsx`. |
| `isdc_scores` | Punteggi ISDPA calcolati per ente. |
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
        └─► ISDPA (isdc.py) ─► isdc_scores
                                  │
                                  ├─► Crea_View.sql / viste DB
                                  ├─► Generate_geojson.py ─► GeoJSON + manifest
                                  └─► StatJson.py ─► stat.json
```

---

## 5. Moduli (cosa fanno e come usarli)

### 5.1 `02 - LoadAnagrafiche`

Carica/aggiorna le anagrafiche (es. `enti_contatti`) dalle fonti in `00 - Input`. `LoadTableEnti.py` registra lo storico delle modifiche (`MOD`) in `change_history_mod` per i campi tracciati.

Inoltre mantiene coerenti le cache DNS rispetto al dominio istituzionale:

- quando un record esistente viene aggiornato con una modifica (`MOD`) e `Sito_istituzionale` cambia tra valore precedente e nuovo, cancella da `enti_mx`, `enti_ns` ed `enti_cname` i record con lo stesso `Codice_IPA`; il successivo run dei crawler DNS li rigenera con il nuovo dominio;
- la stessa cancellazione avviene per i record marcati `stato = 'DEL'`, sia quando lo stato arriva dal file sorgente sia quando il record viene marcato `DEL` durante l'allineamento al file (assenza dal file);
- la cancellazione riguarda solo le tabelle DNS, non l'anagrafica `enti_contatti`: se la tabella ha la colonna `stato`, il record viene marcato `DEL`; in assenza della colonna, l'allineamento cancella il record per retrocompatibilita';
- i comportamenti sono controllati da `INVALIDA_DNS_SU_MOD_CONTATTI`, `INVALIDA_DNS_SU_DEL` e `DRY_RUN`; `ALLINEA_AL_FILE` abilita l'allineamento al file sorgente.

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
- --retry e --recalculate non possono essere usati insieme (controllo a runtime negli script).
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

### 5.4 `05 - ISDC` (indice ISDPA)
Calcola l'indice **ISDPA** (Indice di Sovranità Digitale della Pubblica Amministrazione) e popola `isdc_scores` in base ai dati disponibili (DNS/ASN/geo, secondo le regole implementate nello script e nelle viste). Dopo variazioni strutturali o ripopolamenti può essere necessario rieseguire `Crea_View.sql` per aggiornare le viste consumate da GeoJSON/statistiche.

> Nota sui nomi tecnici: l'indice è oggi denominato **ISDPA**, ma restano invariati per compatibilità i nomi storici `05 - ISDC/`, `isdc.py`, `isdc_scores`, `POI_ISDC` e `poi_isdc.geojson`.

### 5.5 `06 - BuildGeojson`
Genera i GeoJSON e il `manifest.json` usati dal frontend. Le viste `POI_*` sono il contratto dati lato DB; la pubblicabilità dei punti sulla mappa (coordinate valide/plottabili) va applicata secondo le regole condivise in `common.py` e negli script di generazione. La voce `IP_COUNTRY` produce `poi_ip_country.geojson`, il layer con una feature per paese (dettagli in §7.1).

### 5.6 `07 - StatsJson`
Genera `stat.json` (KPI, bande, metadati dataset) per il frontend/reportistica. Gli `id` delle card sono contrattuali per i consumer: rinominarli richiede aggiornamento coordinato dei consumer.

### 5.7 `08 - ReportPDF` e `09 - UtilsClean`
Script di supporto/reportistica e manutenzione. Verificare sempre prerequisiti e dipendenze prima dell'uso; alcuni script legacy possono fare riferimento a schemi/tabelle non più centrali nella pipeline principale.

---

## 6. Calcolo dei dati DNS (MX, NS, CNAME)

Questa sezione descrive come i tre crawler di `04 - QueryDNS` trasformano `Sito_istituzionale` nei record di `enti_mx`, `enti_ns` ed `enti_cname`. Non sono elencati solo i campi di output: sono documentati l'ordine delle interrogazioni, le scelte applicate quando una risposta manca o è ambigua e le euristiche di selezione.

### 6.1 Elementi comuni ai tre crawler

**Ingresso e normalizzazione.** Tutti e tre gli script partono da `Sito_istituzionale` in `enti_contatti` (in `--retry`, dal `dominio` già presente nella tabella target). Prima di qualsiasi query, `dominio.canonicalizza_dominio()` riduce il valore a un nome di host:

- rimuove spazi, schema (`http://`, `https://`, …), `//` iniziale e testo introduttivo;
- taglia percorso, query e fragment;
- scarta le caselle di posta (ad esempio `ente@pec.it`): il dominio sarebbe quello del provider e non dell'ente; accetta invece `user:pass@host` di un URL con credenziali;
- rimuove credenziali, porta esplicita e punto finale;
- converte in minuscolo e verifica la sintassi (almeno due etichette, label non vuote, massimo 63 caratteri, nessun `-` iniziale/finale, TLD alfabetico).

Se il valore non è canonicalizzabile, il record viene saltato: in run ordinario e `--retry` non viene scritto nulla; in `--recalculate` viene aggiornato solo `last_crawl`, quindi la riga resta in tabella con i vecchi dati DNS e senza storico `MOD`.

**Declinazioni.** Per ogni host si prova prima il nome così com'è e poi la variante `www.` (oppure la variante senza `www.` se il nome inizia già con `www.`). L'ordine è significativo: il valore del database resta la prima scelta e `www` è un fallback, non una sostituzione. Ogni stadio della risoluzione applica le declinazioni in modo indipendente e si ferma al primo tentativo che produce un risultato; per questo campi diversi dello stesso ente possono provenire da nomi diversi.

**Resolver.** Le query DNS usano `dnspython` con resolver `8.8.8.8` e `1.1.1.1`, timeout e lifetime di 10 secondi. `get_mx.py` e `get_ns.py` risolvono gli hostname in IPv4 con `socket.gethostbyname`; `get_cname.py` usa una query `A` via `dnspython` e prende il primo indirizzo restituito.

**Errori e coda.** `NoAnswer` (nome esistente senza quel tipo di record) e `NXDOMAIN` non sono errori fatali: il campo corrispondente resta `NULL` e la riga viene comunque scritta, con `last_crawl` aggiornato. È questo che fa ruotare la coda e distingue "già tentato" da "da tentare". Le modalità `--retry` e `--recalculate` sono descritte in §5.3: il retry riprende solo i record con almeno un campo di coda mancante (`NULL` o vuoto) e usa `COALESCE`; il recalculate rielegge il dominio e sovrascrive. In entrambi i casi lo storico `MOD`/`DEL` è registrato in `change_history_mod`.

**ASN.** Dopo aver ottenuto un IP, l'arricchimento ASN usa il database MaxMind GeoLite2-ASN (`autonomous_system_number` e `autonomous_system_organization`). L'ASN viene scritto anche nella tabella `asn` (solo se valorizzato e diverso da 0), ma non è un criterio di risoluzione: non modifica la scelta di MX, NS o CNAME.

### 6.2 MX (`get_mx.py`)

Obiettivo: individuare il mail exchanger usato dal dominio e il suo IP/ASN.

Algoritmo applicato:

1. canonicalizza il dominio e calcola le declinazioni;
2. per ogni declinazione esegue una query `MX`; raccoglie le coppie `(exchange, preference)`, rimuove il punto finale e ordina per preferenza crescente;
3. scorre i record in ordine di preferenza e sceglie il primo il cui host non contiene `antispam`; se tutti lo contengono, sceglie comunque il primo (preferenza più bassa). Il filtro è un'euristica: evita di attribuire all'ente un'appliance antispam come MX principale, ma non scarta il record se è l'unico disponibile;
4. la prima declinazione con almeno un MX vince. L'MX **non** viene cercato sull'apex superiore: RFC 5321 prevede che un dominio senza MX usi il proprio record A come MX implicito, non quello del padre. Copiare l'MX del genitore produrrebbe un dato falso;
5. se c'è un MX, risolve `mx_ip` con `socket.gethostbyname`; se l'host non ha un record A, prova le declinazioni dell'host MX (`www.` / senza `www.`) e usa il primo IP trovato;
6. se `mx_ip` esiste, interroga GeoLite2 e ricava `asn_number`.

Casi negativi: nessun MX su nessuna declinazione significa `mx`, `priorita`, `mx_ip` e `asn_number` a `NULL`. La riga viene comunque inserita/aggiornata (run ordinario e recalculate), così l'ente non resta eternamente in coda; in `--retry` i `NULL` sono proprio la condizione di ritentativo.

Output `enti_mx`: `dominio` (host canonicalizzato), `mx`, `priorita`, `mx_ip`, `asn_number`, `codice_istat`, `last_crawl`.

### 6.3 NS (`get_ns.py`)

Obiettivo: individuare un nameserver rappresentativo della zona, evitando di attribuire all'ente l'infrastruttura del registro.

Algoritmo applicato:

1. canonicalizza il dominio e calcola le declinazioni;
2. per ogni declinazione esegue una query `NS`; raccoglie i target, rimuove il punto finale e li ordina alfabeticamente; `ns_primary` è il primo nome dell'elenco. L'ordinamento alfabetico rende la scelta deterministica: i record NS non hanno una priorità come gli MX, quindi non esiste un "primario" oggettivo;
3. la prima declinazione con NS vince;
4. se nessuna declinazione ha NS (caso normale per un sottodominio, perché gli NS sono definiti solo all'apex della zona), risale la gerarchia togliendo un'etichetta a sinistra, senza mai superare il TLD (massimo due etichette). Si ferma al primo livello che restituisce NS;
5. filtro registry: se il nameserver è uno di `a.dns.it`, `m.dns.it`, `r.dns.it`, `dns.edu.it`, oppure l'apex usato è `edu.it`/`gov.it`, il risultato viene scartato e la risalita si interrompe. Questi nomi amministrano intere categorie del Registro `.it` (scuole sotto `edu.it`, enti sotto `gov.it`) e sono identici per migliaia di enti: registrarli come NS dell'ente misurerebbe il registro, non l'amministrazione;
6. risolve `ns_ip` con `gethostbyname`; se il nameserver non ha un record A, prova le declinazioni del nome NS e prende il primo IP. Con l'IP valorizzato esegue il lookup ASN (`ns_asn`).

Casi negativi: nessun NS proprio e nessun apex utile (o apex del registry) significa `ns_primary`, `ns_ip` e `ns_asn` a `NULL`; la riga viene comunque scritta e `last_crawl` aggiornato. Il dato ricavato per risalita descrive la zona che serve il dominio e può quindi coincidere con il provider del dominio padre, non necessariamente con l'ente: il log indica l'apex usato.

Output `enti_ns`: `dominio`, `ns_primary`, `ns_ip`, `ns_asn`, `codice_istat`, `last_crawl`.

### 6.4 CNAME (`get_cname.py`)

Obiettivo: ricostruire la catena di alias, l'IP finale, il certificato TLS e la relativa classificazione. Lo script esegue tre stadi indipendenti (A, CNAME, TLS), ciascuno con le proprie declinazioni e il proprio "primo risultato utile".

**A record.** `risolvi_a` prova le declinazioni del dominio e prende il primo A restituito (il primo indirizzo dell'elenco). Da `a_record` ricava `a_asn`.

**Catena CNAME.** `trace_cname` parte dal dominio e segue gli alias:

- massimo 10 salti;
- mantiene un insieme dei nomi visitati e interrompe se rivede lo stesso nome (loop);
- a ogni salto interroga il record CNAME e prende il primo target; se non esiste, si ferma;
- restituisce l'ultimo nome raggiunto (`cname_final`) e la catena dei target attraversati.

`risolvi_cname` prova le declinazioni e preferisce la prima che espone una catena non vuota; se nessuna ne ha una, conserva il risultato della prima declinazione tentata, dove `cname_final` coincide con il nome di partenza e la catena è vuota. `cname_ip` viene risolto sul `cname_final` (non sulle declinazioni del dominio originale, per non accoppiare host e ASN non corrispondenti); se il nome finale non ha un A, si provano le sue declinazioni (`www.` / senza `www.`). Da `cname_ip` si ricava `cname_asn`.

**TLS.** `risolvi_tls` prova le declinazioni e per ognuna apre una connessione TCP sulla porta 443 con timeout di 8 secondi:

- `tls_ip` è l'IP del peer TCP, disponibile subito dopo la connessione; resta valorizzato anche se l'handshake TLS fallisce (certificato scaduto, self-signed, nome errato);
- `tls_issuer` è `organizationName` dell'emittente del certificato e richiede un handshake riuscito; se l'handshake fallisce resta `NULL`;
- il primo nome che fornisce un IP vince, anche senza issuer.

Con `--tls-permissive` la verifica di catena e hostname è disattivata (`check_hostname=False`, `CERT_NONE`): serve a raccogliere l'emittente anche da certificati non verificabili, ma cambia il significato del dato e non è il default.

`tls_type` è una classificazione lessicale dell'issuer:

- `public_ca` per Let's Encrypt, Actalis, GlobalSign, DigiCert, Sectigo;
- `cdn_cloudflare`, `cloud_google`, `cloud_aws` (Amazon), `cloud_azure` (Microsoft);
- `ca_reseller` per GoGetSSL;
- `unknown` se l'issuer è assente o non riconosciuto.

Anche `tls_ip` viene arricchito con l'ASN (`tls_asn`).

**Casi negativi e retry.** Se una fase non produce risultati, i campi corrispondenti restano `NULL`, ma la riga viene scritta e `last_crawl` aggiornato. In `--retry` un valore già presente non viene sovrascritto da un valore vuoto; `tls_type='unknown'` è trattato come valore non informativo e non sostituisce una classificazione reale; `cname_final` viene congelato quando il retry non ha trovato una catena, per non perdere un CNAME già risolto.

Output `enti_cname`: `dominio`, `a_record`, `a_asn`, `cname_final`, `cname_ip`, `cname_asn`, `tls_ip`, `tls_asn`, `tls_issuer`, `tls_type`, `codice_istat`, `last_crawl`.

### 6.5 Sintesi delle scelte

| Record | Query | Criterio di scelta | Fallback |
|---|---|---|---|
| MX | `MX` | prima preferenza senza `antispam`, altrimenti preferenza più bassa | declinazioni del dominio; IP con `www`/senza `www`; **nessuna** eredità dall'apex |
| NS | `NS` | primo target in ordine alfabetico | declinazioni del dominio; risalita all'apex con esclusione dei nameserver del registry |
| CNAME | `A`, `CNAME`, TLS | primo risultato per stadio; catena fino a 10 salti con rilevazione loop | declinazioni per ogni stadio; `www`/senza `www` su `cname_ip`; IP TLS conservato anche se l'handshake fallisce |

---

## 7. Viste SQL e output

- `Crea_View.sql` definisce le viste usate per esportazioni e statistiche (es. `POI_MX`, `POI_NS`, `POI_CNAME`, `POI_ISDC`, `POI_IP_COUNTRY`, `STAT_PAESI`, viste statistiche correlate).
- `06 - BuildGeojson` produce GeoJSON + manifest per il frontend.
- `07 - StatsJson` produce `stat.json`.

Se cambia la logica di `isdc_scores` o delle viste, rieseguire `Crea_View.sql` sul DB target prima di rigenerare GeoJSON/statistiche.

### 7.1 Il layer `poi_ip_country.geojson`

Il layer geografico degli IP aggiunge una feature **per paese**, non per IP o per ente. Il punto è il centroide del paese; i contatori descrivono i record dei cinque canali e gli enti distinti associati al paese.

**Viste coinvolte.**

| Vista | Contenuto |
|---|---|
| `POI_IP_COUNTRY_RECORDS` | Una riga per record di canale (MX, NS, CNAME, A, TLS) con il paese dell'IP. |
| `POI_IP_COUNTRY` | Aggregato per paese: contatori `mx`, `ns`, `cname`, `a`, `tls`, `enti_totali` e coordinate da `country_coordinates`. |
| `STAT_PAESI` | Classifica dei paesi per enti distinti con percentuale sul perimetro `geoip`. |

**Filtro e perimetro.** Le viste partono dalle tabelle `enti_mx`, `enti_ns` ed `enti_cname` (non dalle viste `POI_*`) e fanno join su `ip_country`. Sono incluse solo le righe con:

- un indirizzo IP valorizzato nel canale;
- un paese valorizzato in `ip_country`;
- `ip_country.country_source = 'geoip'`.

Restano quindi esclusi i record senza paese e gli IP il cui paese è stato ricavato dal paese di registrazione (`country_source = 'registered'`). I record senza IP non entrano nel conteggio.

**Modello di conteggio.** I contatori `mx`, `ns`, `cname`, `a` e `tls` contano **record di canale**, non IP distinti: lo stesso IP può contribuire a più canali. `enti_totali` è invece il numero di enti distinti del paese sui cinque canali. Un ente può comparire in più paesi, quindi la somma degli `enti_totali` non è il totale degli enti.

**Coordinate.** L'aggancio con `country_coordinates` avviene su `country_code = alpha2`. Il layer usa coordinate mondiali in gradi decimali (intervallo `-90..90` per la latitudine e `-180..180` per la longitudine) e **non** il vincolo "lat/lon non negative" valido per la sola Italia. I paesi senza coordinate valide vengono esclusi dal file e riportati nel log.

**File e proprietà.** Il file è `poi_ip_country.geojson`, con nome tutto minuscolo. Le proprietà di ogni feature sono:

| Proprietà | Significato |
|---|---|
| `country_code` | Codice ISO alpha-2 |
| `country_name` | Nome del paese come restituito da GeoIP |
| `continent` | Continente |
| `mx`, `ns`, `cname`, `a`, `tls` | Record per canale associati al paese |
| `enti_totali` | Enti distinti del paese |

**Metadati.** Il `FeatureCollection` contiene un blocco `metadata` con `generated_at` (ISO 8601, `Europe/Rome`), `source`, `perimeter`, `counting` e `caveats`. I metadati dichiarano il filtro, la non additività delle quote e il fatto che il centroide non è la posizione del server.

**Sezione `stat.json`.** `StatJson.py` aggiunge dopo `cname` la sezione `paesi`, titolo **Distribuzione geografica (IP)**, con:

- `paesi_coinvolti`: numero di paesi con almeno un IP geolocalizzato;
- `enti_perimetro_geoip`: numero di enti distinti del perimetro con almeno un IP geolocalizzato;
- `paesi_top10`: TOP 10 per enti distinti, nel formato lista `Paese (conteggio)`.

Il denominatore delle quote è il numero di enti distinti del perimetro `geoip`: **21.962**. La somma degli enti per paese è **35.378** associazioni paese-ente e non è additiva, perché un ente può comparire in più paesi. Il totale a monte, comprensivo degli IP con `country_source = 'registered'`, è **22.054**: i 92 enti di differenza non hanno IP `geoip` e quindi non compaiono nel layer. Il sottotitolo della card dichiara esplicitamente il perimetro e la non additività.

---

## 8. Regole operative e precauzioni

### 8.1 `last_crawl`
- `last_crawl` rappresenta la **data dell'ultimo aggiornamento/tentativo** del record (successo o fallimento), non la data di primo inserimento.
- Nei crawler DNS viene aggiornata anche in caso di esito negativo/incompleto (e in `--recalculate` anche nei casi di skip/delete handling, dove applicabile), così la coda `last_crawl ASC` ruota davvero.
- Run ordinario e modalità speciali hanno semantiche diverse: il comportamento incrementale/conservativo dipende dallo script e dai flag usati.

### 8.2 Timezone
- Timestamp applicativi: `Europe/Rome`, formato `%Y-%m-%d %H:%M:%S` (salvo diversa specifica nello script).

### 8.3 GeoIP
- Dipendenze e database GeoLite2/MMDB devono essere presenti e leggibili. Errori GeoIP critici devono essere trattati come fail-fast dove previsto, per evitare dati parziali/incoerenti.

### 8.4 Test (obbligatorio su copie)
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

### 8.5 Attenzione a `common.py` e ai path (sandbox/test)
`common.db_path()` risolve il DB da `config.yaml` partendo da `PROJECT_ROOT` (cartella di `common.py`). Copiare solo alcuni script in una directory temporanea **non è sufficiente** se `common.py` resta quello originale: i test potrebbero scrivere sul DB di produzione. In sandbox copiare almeno:
- `common.py`
- `change_history.py` (se serve)
- `01 - Config/`
- `database/` (o i file necessari)
- eventuali DB GeoLite2 richiesti

### 8.6 WAL e verifica delle scritture
`Enti_IT.db` usa WAL: il file `.db` può mantenere un `mtime` vecchio anche dopo scritture (i dati possono stare in `.db-wal` fino al checkpoint). **Non usare `mtime`** per verificare una run.
Controllare invece:
- conteggi righe
- valori di `last_crawl`
- presenza/assenza di record attesi
- righe in `change_history_mod`

### 8.7 Ambiente Windows/PowerShell
- Evitare concatenazioni shell non necessarie; preferire comandi separati.
- Se si usano comandi Unix-like (`grep`, `head`, `tail`) su Windows, verificare che siano disponibili; in alternativa usare PowerShell (`Select-String`, `Select-Object`) o Python.

---

## 9. Stato noto / note operative (da verificare periodicamente)

Questa sezione raccoglie note utili ma **dipendenti dallo stato del DB e dei consumer**. Prima di decisioni operative, verificare sul database/ambiente corrente.

- La copertura DNS/GeoIP, la dimensione di `isdc_scores` e le fasce ISDPA cambiano nel tempo: usare query sul DB per i numeri aggiornati.
- `isdc_scores` può richiedere ripopolamento incrementale (in base a `max_run`) e successiva ricostruzione delle viste.
- I consumer di `stat.json` (frontend/report) dipendono dal contratto delle chiavi: modifiche agli `id` o alla semantica dei KPI vanno coordinate.
- La qualità del monitoraggio può essere migliorata raccogliendo più segnali (es. lista completa MX/NS, SPF/DMARC TXT, classificazione provider CNAME/CDN, eventuale analisi HTTP). Queste sono evoluzioni progettuali da implementare in modo incrementale, mantenendo compatibilità con lo schema/storico esistente.

---

## 10. Fonti dati

L'elenco completo con URL originali è in [`../Fonti.txt`](../Fonti.txt) (se presente nel repository). In sintesi, le fonti tipiche includono:

| Dataset / ambito | Fonte |
|---|---|
| Anagrafe enti / contatti | IndicePA |
| Anagrafiche comunali / codici | fonti ISTAT/anagrafiche comunali |
| Contratti (se usati) | OCDS / ANAC (dati.anticorruzione.it) |
| Datacenter (se usati) | datacentermap.com |
| GeoIP ASN/City/Country | MaxMind GeoLite2 |
| Centroidi dei paesi | `00 - Input/country-centroids/` (CSV/XLSX locale) |
| CPV (classificazioni) | TED/SIMAP |

---

## 11. Riferimenti rapidi (comandi)

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

# ISDPA
cd ..\05 - ISDC
python isdc.py

# Output per frontend
cd ..\06 - BuildGeojson
python Generate_geojson.py
cd ..\07 - StatsJson
python StatJson.py
```

> Eseguire sempre i test su copie del database e verificare i path/config prima di lanciare run su dati reali.
