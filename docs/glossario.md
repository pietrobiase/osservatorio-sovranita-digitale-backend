# Glossario

## Enti e perimetro

| Termine | Significato |
|---|---|
| **Ente** | Unità di analisi dell'Osservatorio. Corrisponde a una voce dell'anagrafica e non coincide necessariamente con un comune. |
| **Codice IPA** | Identificativo dell'ente nell'Indice dei domicili digitali delle pubbliche amministrazioni. È la chiave usata dalla pipeline. |
| **Codice ISTAT** | Codice del comune. Non è la chiave dell'ente: più enti possono stare nello stesso comune e molti enti non hanno un codice ISTAT utilizzabile. |
| **Tipologia** | Prima classificazione dell'ente, usata per le card di distribuzione. |
| **Categoria IPA** | Classificazione più fine dell'ente, usata nelle tabelle di ranking. |
| **Perimetro** | Insieme degli enti considerati in una data analisi. Può essere più ampio o più ristretto del numero di enti valutati. |
| **Ente censito** | Ente presente nell'anagrafica. |
| **Ente valutato** | Ente con un indice di sovranità calcolato. |
| **Gate di ammissione** | Insieme di condizioni che un ente deve soddisfare per entrare nel calcolo dell'indice. |
| **Coda incrementale** | Modalità di elaborazione per cui un ente già valutato non viene ricalcolato automaticamente. |
| **Lotto** | Porzione di record elaborata in una singola esecuzione. |
| **Ricalcolo** | Nuova osservazione di un record già presente, che sostituisce i valori precedenti. |
| **Ritentativo** | Nuovo tentativo su un record incompleto, senza ricominciare da zero. |

## Domini e DNS

| Termine | Significato |
|---|---|
| **Dominio** | Nome che identifica un sito o un servizio su Internet, per esempio `comune.esempio.it`. |
| **Host** | Nome di un singolo dispositivo o servizio. Un dominio può avere più host. |
| **TLD** | Dominio di primo livello, come `.it`, `.eu`, `.com`. |
| **Apex** | Livello in cui una zona DNS è delegata. È il punto in cui esistono i record NS della zona. |
| **Sottodominio** | Nome che sta sotto un apex. Di norma non ha record NS propri. |
| **Normalizzazione** | Riduzione del campo libero del sito istituzionale a un nome di host interrogabile. |
| **Declinazione** | Variante di un nome provata dalla pipeline. Le principali sono il nome nudo e la variante con `www`. |
| **DNS** | Sistema che traduce nomi in indirizzi e pubblica le informazioni di instradamento. |
| **Resolver** | Server che risolve le interrogazioni DNS per conto del client. |
| **Record A** | Record che associa un nome a un indirizzo IPv4. |
| **Record MX** | Record che indica il server a cui consegnare la posta di un dominio, con una preferenza. |
| **Record NS** | Record che indica i nameserver autorevoli per una zona. |
| **Record CNAME** | Alias: indica che un nome deve essere risolto altrove. |
| **Registry** | Soggetto che amministra un TLD o una categoria di domini. Nel caso italiano, il registro del `.it` e le categorie `.edu.it` e `.gov.it`. |
| **Mail exchanger** | Server indicato da un record MX. |
| **Preferenza MX** | Numero che ordina i server di posta: più basso significa maggiore priorità. |
| **Dominio nudo** | Il dominio senza prefisso `www`. |
| **Catena CNAME** | Sequenza di alias che porta dal nome di partenza al nome finale. |

## Infrastruttura e rete

| Termine | Significato |
|---|---|
| **ASN** | *Autonomous System Number*: identificativo di una rete amministrata da un unico soggetto. |
| **Sistema autonomo** | La rete associata a un ASN, con proprie politiche di routing. |
| **Organizzazione ASN** | Nome del soggetto che gestisce un sistema autonomo. È il nome mostrato nelle schede e nelle classifiche. |
| **Provider** | Soggetto che fornisce un servizio di rete, posta, DNS o web. Nel dato è identificato dall'ASN. |
| **GeoIP** | Banca dati che associa indirizzi IP a paesi e continenti. |
| **Anycast** | Tecnica per cui lo stesso indirizzo è annunciato da più località. Tipica delle CDN. |
| **Paese osservato** | Paese associato all'indirizzo dalla banca dati geografica. |
| **Paese di registrazione** | Paese in cui è registrato il blocco di indirizzi. Usato come fallback quando il paese osservato manca. |
| **Cluster geografico** | Raggruppamento statistico in IT, UE, USA, Extra UE o sconosciuto, calcolato sul paese di registrazione. |
| **CDN** | *Content Delivery Network*: rete distribuita che serve contenuti vicino agli utenti. |
| **Hyperscaler** | Grande piattaforma cloud con infrastruttura globale. |
| **Cloud provider** | Fornitore di servizi di calcolo e ospitalità in rete. |
| **Lock-in** | Concentrazione dei servizi su un unico fornitore o su pochi fornitori. |
| **HHI** | Indice di concentrazione normalizzato tra 0 e 1. Valori alti indicano una concentrazione maggiore. |
| **Resilienza** | Qui: grado di distribuzione dei servizi tra provider diversi. Non è una misura di affidabilità o sicurezza. |

## Web e certificati

| Termine | Significato |
|---|---|
| **TLS** | Protocollo che cifra e autentica le connessioni web. |
| **Certificato TLS** | Documento digitale che associa una chiave a un nome e a un emittente. |
| **Emittente** | Organizzazione che ha firmato il certificato. |
| **Autorità di certificazione** | Soggetto che emette certificati. Può essere pubblica, una CDN, un cloud o un rivenditore. |
| **Handshake** | Fase di negoziazione della connessione cifrata, in cui il certificato viene presentato e verificato. |
| **Peer TLS** | Server che termina la connessione cifrata sulla porta 443. |
| **Origine** | Server che conserva i contenuti di un sito, dietro eventuali CDN e bilanciatori. |
| **Punto di terminazione** | Nodo che chiude la connessione TLS. Può essere un server dell'ente o un nodo della CDN. |

## Indice e statistiche

| Termine | Significato |
|---|---|
| **ISDPA** | *Indice di Sovranità Digitale della Pubblica Amministrazione*: sintesi dei tre canali in un punteggio da 0 a 100. |
| **ISDC** | Denominazione storica dell'indice, oggi ISDPA. Resta nei nomi tecnici (`05 - ISDC/`, `isdc.py`, `isdc_scores`, `POI_ISDC`, `poi_isdc.geojson`) per compatibilità. |
| **Paese dell'IP** | Paese associato a un indirizzo IP da GeoIP. Nel layer per paese è il paese osservato, non necessariamente la posizione fisica del server. |
| **Centroide** | Punto centrale di un paese usato per posizionare la feature nel layer `poi_ip_country.geojson`; non è la posizione del server. |
| **Punteggio di canale** | Punteggio parziale relativo a posta, DNS o web. |
| **Peso** | Importanza relativa di una dimensione o di un canale nella composizione del punteggio. |
| **Punteggio grezzo** | Valore tra 0 e 1 ottenuto combinando le dimensioni di un canale, prima della trasformazione e della copertura. |
| **Compressione** | Trasformazione a curva a S che porta il punteggio grezzo sulla scala 0-100. |
| **Copertura** | Correttivo che avvicina al centro della scala i punteggi basati su poche osservazioni. |
| **Valore neutro** | Valore intermedio prodotto in assenza di osservazioni. Non è una misura reale. |
| **Bonus** | Correzione positiva applicata al totale in base alla distribuzione dei canali. |
| **Malus** | Correzione negativa applicata al totale in base alla presenza di hyperscaler o CDN. |
| **Banda** | Fascia descrittiva in cui viene collocato il punteggio finale. |
| **Sovranità digitale** | In questo progetto: misura della collocazione e della concentrazione delle infrastrutture digitali osservabili. Non è un giudizio giuridico, politico o di sicurezza. |
| **KPI** | Indicatore sintetico mostrato in una card o in una classifica. |
| **Card** | Elemento del frontend che mostra un singolo indicatore con titolo, valore e sottotitolo. |
| **Denominatore** | Insieme rispetto al quale viene calcolata una percentuale. Cambia da canale a canale. |

## Dati e pubblicazione

| Termine | Significato |
|---|---|
| **GeoJSON** | Formato testuale per dati geografici, composto da feature con geometria e proprietà. |
| **Feature** | Singolo elemento di un GeoJSON: una geometria con i suoi attributi. |
| **FeatureCollection** | Insieme di feature, cioè il contenuto di un file GeoJSON. |
| **Sentinella** | Valore convenzionale che indica un dato non disponibile. Per le coordinate è `-1, -1`. |
| **stat.json** | File aggregato con le statistiche e le card del frontend. |
| **change_history** | Registro delle variazioni dei record, con valori precedenti, nuovi, data e tipo di operazione. |
| **last_crawl** | Data e ora dell'ultimo tentativo di aggiornamento di un record. |
| **Fotografia** | Metafora usata per ricordare che i dati descrivono un momento, non una condizione permanente. |
| **Pubblicazione** | Passaggio dai dati del database ai file statici letti dal frontend. |
| **Vista di lettura** | Rappresentazione intermedia che unisce ente, canale, provider e geografia per alimentare mappe e statistiche. |
