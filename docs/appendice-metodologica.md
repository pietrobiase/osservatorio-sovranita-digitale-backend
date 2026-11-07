# Appendice metodologica

Questa appendice raccoglie i dettagli di calcolo che il racconto principale
tralascia di proposito. Non contiene comandi né istruzioni operative: descrive
regole, soglie e formule nella forma in cui sono applicate.

## A. Oggetti e convenzioni

### Unità di analisi

L'unità è l'**ente**, identificato dal codice IPA. Le tabelle dei canali
contengono una riga per ente; le viste di lettura aggiungono categoria,
coordinate e dati del provider. Il codice ISTAT non è una chiave: può essere
assente e non è univoco tra enti.

### Tempo

Ogni record conserva la data dell'ultimo tentativo (`last_crawl`), aggiornata
anche quando l'esito è negativo. La data non indica l'ultimo esito positivo:
indica l'ultima volta che il record è stato preso in carico.

### Valori mancanti

Nel database i valori mancanti sono `NULL`. Nei file GeoJSON le coordinate
mancanti diventano una coppia sentinella `(-1, -1)`. Nei punteggi, l'assenza di
una sorgente viene trattata con un valore neutro, ma il cancello d'ammissione
cerca di impedire che questo caso venga scambiato per una misura reale.

## B. Normalizzazione del dominio

Il valore di partenza è il sito istituzionale, un campo libero. La
normalizzazione avviene prima di ogni chiamata di rete e segue questo ordine.

1. Rimozione degli spazi iniziali e finali.
2. Rimozione di uno schema iniziale (`http://`, `https://`, `ftp://`, ecc.).
3. Rimozione degli slash iniziali di un URL senza schema (`//host/...`).
4. Se il valore contiene spazi, estrazione del primo token che somiglia a un
   nome di host.
5. Rifiuto delle caselle di posta: un indirizzo come `info@pec.esempio.it`
   descrive il provider, non l'ente.
6. Taglio di percorso, query e frammento.
7. Gestione della chiocciola: se precede un nome locale senza due punti, il
   valore viene rifiutato come casella; se il nome locale contiene due punti
   (credenziali di un URL), viene conservato l'host.
8. Rimozione della porta esplicita, esclusi i letterali IPv6 tra parentesi
   quadre.
9. Rimozione del punto finale.
10. Conversione in minuscolo.
11. Verifica della presenza di almeno due etichette.
12. Verifica delle etichette: non vuote, massimo 63 caratteri, senza trattino
    iniziale o finale.
13. Verifica di un suffisso alfabetico plausibile.

Se il risultato non supera i controlli, l'ente viene saltato per quella
campagna. La normalizzazione accetta solo caratteri ASCII e non converte i
nomi internazionalizzati.

### Declinazioni

Per ogni dominio si provano, in ordine:

1. il nome così com'è;
2. la variante con `www`, se il nome non inizia già per `www`;
3. la variante senza `www`, se il nome inizia già per `www`.

Il `www` è un fallback, non una sostituzione. Il dominio memorizzato resta
quello normalizzato; i campi osservati dicono da quale declinazione proviene
la risposta. Le declinazioni vengono applicate indipendentemente a MX, NS, A,
CNAME e TLS.

## C. Canale MX

### Selezione del mail exchanger

1. Si interroga il dominio per i record MX.
2. Si costruiscono le coppie `(host, preferenza)` e si ordinano per preferenza
   crescente.
3. Si sceglie il primo host il cui nome non contiene la parola `antispam`.
4. Se tutti gli host contengono `antispam`, si sceglie il primo della lista,
   cioè quello con preferenza più bassa.
5. Se la declinazione non produce record, si passa alla successiva.
6. Se nessuna declinazione produce record, il campo MX resta vuoto.

Non si eredita il MX dal dominio padre. Un dominio senza MX non usa
automaticamente il mail exchanger del genitore: può usare il proprio record A
come MX implicito, ma questo caso non viene osservato.

### Arricchimento

1. Si risolve l'host MX in un indirizzo IPv4.
2. Se l'host non ha indirizzo, si provano le declinazioni dell'host MX.
3. Si associa l'indirizzo a un ASN e a un paese.
4. Si conservano host, preferenza, IP e ASN.

Ogni ente ha una sola riga nella tabella MX. Il canale non conserva l'elenco
completo dei mail exchanger: conserva quello selezionato.

## D. Canale NS

### Selezione del nameserver

1. Si interroga il dominio per i record NS.
2. Se la declinazione non produce NS, si passa alla successiva.
3. Se nessuna declinazione produce NS, si risale la gerarchia togliendo
   un'etichetta alla volta.
4. La risalita si ferma quando restano due etichette: non si sale al TLD.
5. Il primo livello che restituisce NS viene considerato l'apex della zona.
6. I nomi restituiti vengono ordinati alfabeticamente e si conserva il primo.

Il termine "primario" è convenzionale: non esiste una priorità NS paragonabile
a quella MX. La scelta alfabetica serve a rendere il dato riproducibile e a
evitare che un ente con più nameserver pesi più di uno con uno solo.

### Esclusione dei nameserver del registro

Un nameserver viene scartato quando:

- il suo nome appartiene all'insieme `a.dns.it`, `m.dns.it`, `r.dns.it`,
  `dns.edu.it`; oppure
- l'apex raggiunto è `edu.it` o `gov.it`.

In questi casi la risalita restituisce nessun nameserver utile. La scelta evita
di attribuire a migliaia di enti lo stesso nameserver del registro, che non
descrive la loro infrastruttura.

### Arricchimento

1. Si risolve il nameserver in un indirizzo IPv4.
2. Se non ha indirizzo, si provano le declinazioni del nome del nameserver.
3. Si associa l'indirizzo a un ASN e a un paese.
4. Si conservano nameserver, IP e ASN.

Ogni ente ha una sola riga nella tabella NS. I collegamenti con ASN e paese
sono permissivi: un ente può avere un nameserver senza provider o senza IP.
Nel calcolo dell'indice questo caso produce un punteggio di canale basso, non
un'esclusione.

## E. Canale web: A, CNAME e TLS

### Record A

Si prova il primo indirizzo IPv4 disponibile tra le declinazioni. Il record A
non viene cercato sul nome finale del CNAME: è un'osservazione indipendente sul
dominio.

### Catena CNAME

1. Si parte dal nome della declinazione.
2. Si interroga il nome per un record CNAME.
3. Se esiste, si conserva il primo valore e si prosegue sul nome puntato.
4. Si ripete per un massimo di 10 passaggi.
5. Se un nome è già stato visitato, si interrompe la catena per loop.

Se nessuna declinazione espone una catena, il nome finale coincide con il nome
di partenza della prima declinazione tentata. Questo significa che il campo
"nome finale" è sempre valorizzato, anche in assenza di CNAME: non è una prova
dell'uso di un alias.

### IP del nome finale

1. Si risolve il nome finale in un indirizzo IPv4.
2. Se il nome finale non ha indirizzo, si provano le sue declinazioni.
3. Si associa l'indirizzo a un ASN e a un paese.

### TLS

1. Si apre una connessione TCP sulla porta 443.
2. Si legge subito l'indirizzo del peer: è il server che termina TLS.
3. Si esegue l'handshake con verifica della catena e del nome.
4. Se l'handshake riesce, si legge l'organizzazione dell'emittente.
5. Se l'handshake fallisce per un errore TLS, l'IP resta e l'emittente no.
6. Se la connessione non si apre, entrambi restano vuoti.

La modalità permissiva, usata solo per recupero, disattiva la verifica della
catena e del nome. I dati raccolti in questa modalità non sono confrontabili
con quelli raccolti in modalità verificata.

### Classificazione dell'emittente

| Categoria | Parole chiave riconosciute |
|---|---|
| Autorità pubblica | Let's Encrypt, Actalis, GlobalSign, DigiCert, Sectigo |
| CDN Cloudflare | Cloudflare |
| Cloud Google | Google |
| Cloud AWS | Amazon |
| Cloud Azure | Microsoft |
| Rivenditore | GoGetSSL |
| Sconosciuta | Nessuna corrispondenza |

La classificazione è separata dal punteggio TLS. Un certificato può essere
classificato come cloud e ricevere un punteggio basso, oppure come autorità
pubblica e ricevere un punteggio intermedio o alto.

## F. Arricchimento ASN e GeoIP

### Indirizzi considerati

Vengono arricchiti gli indirizzi referenziati dai canali:

- IP del mail exchanger;
- IP del nameserver;
- IP del nome finale web;
- record A;
- IP del peer TLS.

Un indirizzo non referenziato non viene elaborato.

### ASN

Per ogni indirizzo si conservano:

- numero del sistema autonomo;
- nome dell'organizzazione.

Il nome è la stringa usata nelle schede e nelle classifiche. Non è un
identificativo stabile: può cambiare, può essere assente e può non coincidere
con il marchio commerciale.

### GeoIP

Per ogni indirizzo si conservano:

- paese osservato;
- continente;
- paese di registrazione;
- fonte del paese;
- cluster statistico.

La fonte può essere:

| Fonte | Significato |
|---|---|
| Diretta | Il paese è stato letto dalla banca dati geografica |
| Registrazione | Il paese osservato mancava; è stato usato il paese di registrazione |
| Sconosciuta | Nessuna delle due informazioni è disponibile |

Il cluster è calcolato sul **paese di registrazione**:

| Paese di registrazione | Cluster |
|---|---|
| Italia | IT |
| Stati Uniti | USA |
| Altro paese UE | UE |
| Paese fuori UE | Extra UE |
| Non disponibile | unknown |

La scelta del paese di registrazione rende le quote confrontabili anche per gli
indirizzi anycast, ma non coincide con la posizione fisica del server.

### Incrementalità

Un indirizzo già presente non viene rielaborato, a meno che la sua riga non sia
incompleta. Questo vale anche per l'ASN e per il GeoIP: la fotografia può
contenere dati di date diverse.

## G. Indice ISDC

### G.1 Cancello e coda

Un ente entra nel calcolo se soddisfa tutte le condizioni:

1. il sito istituzionale è valorizzato e non vuoto;
2. non esiste già una riga nel registro dei punteggi;
3. le sorgenti richieste restituiscono almeno una riga.

La terza condizione usa la stessa struttura di collegamento del calcolo:

- per MX e CNAME il collegamento con ASN e paese è interno: la riga esiste
  solo se provider e paese sono risolti;
- per NS il collegamento è permissivo: è sufficiente che l'ente sia presente
  nella tabella NS, anche con provider o IP mancanti.

Se l'elenco delle sorgenti richieste è vuoto, il cancello è disabilitato e gli
enti senza dati possono ricevere il valore neutro.

La coda è ordinata per codice IPA e limitata a un numero massimo di record per
esecuzione. Un ente già valutato non viene ricalcolato: per rivalutarlo va
rimossa la sua riga.

### G.2 Sorgenti per ente

Per ogni ente si leggono tre righe, una per canale:

- **MX**: organizzazione ASN, paese, continente, host del mail exchanger;
- **CNAME**: organizzazione ASN, paese, continente, emittente TLS, nome finale;
- **NS**: organizzazione ASN, paese, continente, nameserver.

Per MX e CNAME i collegamenti richiedono ASN e paese. Per NS sono permissivi.
Questo spiega perché il numero di righe di canale può differire.

### G.3 Punteggio geografico

Il punteggio geografico `geo` è compreso tra 0 e 1.

| Condizione | Valore |
|---|---|
| Paese = Italia | 1.00 |
| Paese in Unione Europea | 0.85 |
| Paese = Cina o Russia | 0.25 |
| Continente = Europa | 0.70 |
| Continente = America del Nord, America del Sud, Africa, Asia, Oceania | 0.50 |
| Nessuna informazione | 0.30 |

L'ordine dei controlli è parte del calcolo. Cina e Russia vengono valutate
prima del continente, perché la banca dati colloca la Russia in Europa. Senza
questo ordine, la Russia sarebbe indistinguibile da un paese europeo non
sanzionato.

L'insieme UE usato per il punteggio geografico **non include l'Italia**,
perché l'Italia è gestita dal primo controllo. Include Austria, Belgio,
Bulgaria, Croazia, Cipro, Cechia, Danimarca, Estonia, Finlandia, Francia,
Germania, Grecia, Ungheria, Irlanda, Lettonia, Lituania, Lussemburgo, Malta,
Paesi Bassi, Polonia, Portogallo, Romania, Slovacchia, Slovenia, Spagna e
Svezia.

### G.4 Punteggio infrastrutturale

Il punteggio infrastrutturale `infra` parte da 0.5 e applica correzioni
sull'unione del nome dell'organizzazione ASN e dell'host osservato.

| Condizione | Correzione |
|---|---|
| L'unione contiene una parola chiave hyperscaler | -0.30 |
| L'unione contiene una parola chiave CDN globale | -0.20 |
| L'unione contiene `.it` o `italia` | +0.25 |
| L'unione contiene `gov`, `comune`, `ministero`, `regione`, `provincia` o `enti` | +0.35 |

Il risultato viene riportato nell'intervallo 0-1.

Insiemi usati:

| Insieme | Parole chiave |
|---|---|
| Hyperscaler | Google, Gmail, Microsoft, Azure, Amazon, AWS, Oracle, Alibaba, IBM |
| CDN globali | Cloudflare, Akamai, Fastly, EdgeSuite, CDN77 |
| Contesto pubblico | gov, comune, ministero, regione, provincia, enti |

Le correzioni possono sommarsi. Un host italiano con una parola pubblica può
raggiungere il massimo; un hyperscaler può scendere sotto 0.5. Il
riconoscimento è testuale e sensibile a falsi positivi e falsi negativi.

### G.5 Punteggio TLS

Il punteggio TLS `tls` è compreso tra 0 e 1.

| Condizione | Valore |
|---|---|
| Emittente assente | 0.50 |
| Emittente con parola chiave hyperscaler | 0.20 |
| Emittente Let's Encrypt | 0.70 |
| Emittente DigiCert, GlobalSign o Sectigo | 0.85 |
| Altro emittente | 0.50 |

La prima condizione che si verifica determina il valore. Un emittente che
contiene una parola chiave hyperscaler riceve 0.20 anche se è un'autorità di
certificazione.

### G.6 Combinazione del canale

Per ogni canale si combinano le dimensioni disponibili.

**Posta**

```
raw_MX = 0.60 * geo + 0.40 * infra
```

Dove `geo` è il massimo tra le righe e `infra` è la media. Con una riga per
ente, massimo e media coincidono.

**Web**

```
raw_CNAME = 0.50 * geo + 0.30 * infra + 0.20 * tls
```

Dove `geo` è il massimo, `infra` è la media e `tls` è la media dei punteggi
degli emittenti.

**Delega DNS**

```
raw_NS = 0.60 * geo + 0.40 * infra
```

Se un canale non ha righe, il valore grezzo è 0.50.

### G.7 Compressione

Il valore grezzo viene trasformato con una sigmoide:

```
sigmoid(x) = 100 / (1 + exp(-8 * (x - 0.60)))
```

La curva è centrata su 0.60: un valore grezzo di 0.60 produce 50. La pendenza
8 rende la curva ripida vicino al centro e piatta agli estremi. I valori
possibili vanno da poco sopra 0 a poco sotto 100.

### G.8 Copertura

La copertura dipende dal numero di righe disponibili per il canale:

| Numero di righe | Copertura |
|---|---|
| 0 | 0.40 |
| 1 | 0.70 |
| 2 | 0.90 |
| 3 o più | 1.00 |

Il punteggio finale del canale è:

```
canale = sigmoid(raw) * copertura + 50 * (1 - copertura)
```

Con copertura 0.70, il valore osservato pesa il 70% e il centro della scala
pesa il 30%. Nel modello attuale ogni canale ha una riga per ente, quindi la
copertura effettiva è quasi sempre 0.70. Il correttivo non distingue quindi
molto tra enti, ma sposta comunque i punteggi verso 50.

### G.9 Composizione finale

Il totale è la media pesata dei tre canali:

```
totale = 0.40 * MX + 0.35 * CNAME + 0.25 * NS + bonus + malus
```

Il risultato viene riportato nell'intervallo 0-100.

### G.10 Bonus e malus

Le quote sono calcolate sulle righe dei tre canali non vuoti, quindi su un
massimo di tre righe per ente.

**Malus hyperscaler**

| Quota di righe con ASN hyperscaler | Malus |
|---|---|
| Almeno 0.80 | -20 |
| Almeno 0.50 | -15 |
| Almeno 0.25 | -10 |

**Malus CDN**

| Quota di righe con ASN CDN | Malus |
|---|---|
| Almeno 0.50 | -10 |

I due malus si sommano.

**Bonus Italia**

| Quota di righe con paese Italia | Bonus |
|---|---|
| Almeno 0.50 | +8 |

**Bonus Europa**

| Quota di righe con paese UE (esclusa l'Italia) | Bonus |
|---|---|
| Almeno 0.95 | +6 |

Poiché l'Italia non è inclusa nell'insieme UE del bonus, i due bonus non si
sommano quasi mai: se almeno metà delle righe è italiana, la quota UE diversa
dall'Italia non può raggiungere 0.95.

Con tre righe, una soglia di 0.50 significa due righe su tre; una soglia di
0.25 significa una riga su tre. Le soglie sono quindi grossolane.

### G.11 Bande

| Intervallo | Banda |
|---|---|
| ≤ 40 | Sovranità digitale fragile |
| > 40 e ≤ 60 | Dipendenza infrastrutturale |
| > 60 e ≤ 78 | Infrastruttura eterogenea |
| > 78 | Infrastruttura sovrana |

La statistica "infrastruttura sovrana" conta gli enti con punteggio almeno 78,
mentre la banda usa la soglia strettamente maggiore di 78. Al confine esatto i
due conteggi possono differire.

### G.12 Valore neutro

Un canale senza righe produce:

```
raw = 0.50
sigmoid(0.50) ≈ 31.0
canale = 31.0 * 0.40 + 50 * 0.60 = 42.4
```

Questo è il valore neutro che il cancello d'ammissione vuole evitare. Un ente
valutato con 42,4 sembra avere una misura reale, ma in realtà non ha dati.

## H. Pubblicazione

### H.1 GeoJSON

Vengono prodotti cinque livelli:

| Livello | File | Contenuto |
|---|---|---|
| Posta | `poi_mx.geojson` | Enti con MX |
| Delega DNS | `poi_ns.geojson` | Enti con NS |
| Web | `poi_cname.geojson` | Enti con risoluzione web |
| ISDC | `poi_isdc.geojson` | Enti con indice |
| Datacenter | `poi_datacenter.geojson` | Datacenter censiti |

Ogni feature contiene:

- una geometria puntuale con longitudine e latitudine;
- gli identificativi dell'ente;
- il nome e il dominio;
- la categoria;
- i campi specifici del livello.

Per il livello ISDC i campi specifici includono:

- punteggio posta, DNS e web;
- ASN e organizzazione per ciascun canale;
- emittente TLS;
- punteggio totale e banda;
- indicatore hyperscaler.

Se le coordinate mancano, la geometria usa la coppia sentinella `(-1, -1)`.
Il record resta nel file. Il frontend può riconoscere la sentinella e non
disegnare il punto.

### H.2 Statistiche

Il file statistico contiene:

- un blocco di dati di base;
- una sezione per tipologia;
- una sezione per categoria;
- una sezione per ciascun canale;
- una sezione per l'indice;
- una sezione per il lock-in;
- una sezione per la concentrazione ASN;
- una sezione per la resilienza;
- una sezione per cloud e hyperscaler;
- una sezione per TLS;
- un elenco delle bande.

Ogni indicatore ha un identificativo, un titolo, un sottotitolo, un valore e un
tipo. I tipi sono: conteggio, percentuale, punteggio, lista, indice.

### H.3 Denominatori

| Indicatore | Denominatore |
|---|---|
| Quota MX in Italia / fuori UE | Enti nella vista MX, cioè con provider e paese risolti |
| Quota NS in Italia / fuori UE | Enti nella vista NS, anche con provider non identificato |
| Quota CNAME in Italia / fuori UE | Enti nella vista CNAME, cioè con provider e paese risolti |
| Statistiche ISDC | Enti con punteggio |
| Lock-in | Enti con punteggio |
| Concentrazione ASN | Slot ente-canale con ASN non nullo |
| Bande | Enti con punteggio |

Le quote "fuori UE" sommano i cluster USA ed Extra UE. Non includono il cluster
UE. Le percentuali di canale non sommano quindi a 100: resta una quota in UE,
una in Italia e una non mappata.

### H.4 Lock-in

Le categorie sono definite per confronto degli ASN dei tre canali:

| Categoria | Condizione |
|---|---|
| Lock-in alto | ASN posta = ASN DNS = ASN web |
| Lock-in parziale | Almeno due ASN uguali, ma non tutti e tre |
| Distribuzione completa | Tutti e tre gli ASN diversi |
| Non determinabile | Almeno un ASN mancante |

Le categorie sono pensate per coprire tutti gli enti valutati. Un ente con un
ASN mancante non viene classificato come distribuito, perché l'assenza non
prova la diversità.

### H.5 Concentrazione HHI

L'indice HHI è calcolato sugli slot ente-canale:

```
HHI = Σ (frequenza_ASN / numero_slot)^2
```

Dove `frequenza_ASN` è il numero di slot che usano un certo ASN e
`numero_slot` è il totale degli slot con ASN noto. L'indice è compreso tra 0 e
1. Un valore alto indica che pochi ASN coprono molti slot.

### H.6 Controlli di coerenza

Prima della scrittura del file statistico vengono verificati:

- somma delle tipologie = enti censiti;
- somma delle categorie = enti censiti;
- somma delle categorie di lock-in = enti valutati;
- somma delle bande = enti valutati;
- somma delle percentuali delle bande = 100;
- HHI compreso tra 0 e 1;
- quote del primo ASN comprese tra 0 e 100;
- quota hyperscaler non superiore al totale degli enti con MX.

Se un controllo fallisce, la generazione termina con esito negativo.

### H.7 Registro dei cambiamenti

Il registro delle variazioni contiene:

- tabella e chiave del record;
- campo modificato;
- valore precedente e nuovo;
- data e tipo di operazione;
- script che ha prodotto la variazione.

Il registro viene esportato in un file JSON accanto alle statistiche. Non è
filtrato: contiene l'intera storia disponibile.

## I. Ordine di esecuzione e ciclo di vita

L'ordine logico della pipeline è:

1. aggiornamento dell'anagrafica;
2. osservazione della posta;
3. osservazione della delega DNS;
4. osservazione del web e del TLS;
5. arricchimento GeoIP degli indirizzi;
6. calcolo dell'indice;
7. generazione dei GeoJSON;
8. generazione delle statistiche e del registro dei cambiamenti.

L'ordine conta: l'indice legge i risultati dei canali e l'arricchimento; i
GeoJSON leggono l'indice e le viste; le statistiche leggono tutto.

### Invalidazione

Se il sito istituzionale di un ente cambia, i record DNS precedenti vengono
rimossi. Se l'ente viene marcato come cancellato, i record DNS correlati
vengono rimossi. L'anagrafica resta, ma i canali vengono rigenerati con il
nuovo dominio.

Questa scelta evita di mostrare per mesi il provider del vecchio sito come se
fosse quello attuale.

### Modalità di lavoro

Le code prevedono tre modalità:

- **normale**: prende gli enti non ancora presenti nella tabella del canale;
- **ritentativo**: riprende i record incompleti, senza cancellare i valori già
  presenti;
- **ricalcolo**: rilegge il dominio dall'anagrafica e rigenera il record.

Nel ritentativo, un valore nuovo assente non sovrascrive un valore vecchio
presente. È una protezione contro i guasti temporanei della rete.

## J. Riepilogo dei parametri

| Parametro | Valore |
|---|---|
| Peso posta nel totale | 0.40 |
| Peso web nel totale | 0.35 |
| Peso DNS nel totale | 0.25 |
| Peso geografia nella posta | 0.60 |
| Peso provider nella posta | 0.40 |
| Peso geografia nel web | 0.50 |
| Peso provider nel web | 0.30 |
| Peso TLS nel web | 0.20 |
| Peso geografia nel DNS | 0.60 |
| Peso provider nel DNS | 0.40 |
| Centro della sigmoide | 0.60 |
| Pendenza della sigmoide | 8 |
| Copertura con 0 righe | 0.40 |
| Copertura con 1 riga | 0.70 |
| Copertura con 2 righe | 0.90 |
| Copertura con 3 o più righe | 1.00 |
| Soglia banda fragile | ≤ 40 |
| Soglia banda dipendenza | ≤ 60 |
| Soglia banda eterogenea | ≤ 78 |
| Soglia banda sovrana | > 78 |
| Valore neutro | ≈ 42.4 |

## K. Note di comparabilità

1. I punteggi sono confrontabili tra enti solo se il metodo è lo stesso. Un
   cambio di pesi, di liste o di soglie rende i punteggi non comparabili.
2. Le percentuali di canale hanno denominatori diversi. Non vanno sommate né
   confrontate senza verificare il denominatore.
3. Il paese dell'IP non è la residenza dei dati. Le quote geografiche
   descrivono la collocazione della rete osservata, non quella dei dati.
4. Il cluster statistico usa il paese di registrazione; il paese osservato può
   essere diverso, soprattutto per gli anycast.
5. L'indice è incrementale. Un punteggio può essere più vecchio dei dati DNS
   che lo circondano.
6. Le euristiche di riconoscimento dei provider sono testuali. Nomi nuovi o
   inattesi possono non essere classificati.
7. Le bande sono descrittive. Non sono certificazioni e non sostituiscono una
   valutazione di sicurezza, conformità o qualità.
8. Il valore neutro non è un punteggio. Un ente che lo riceve non è stato
   misurato.
