# Limiti e qualità del dato

## La qualità comincia dai limiti

Un osservatorio che non dichiara i propri limiti produce dati che sembrano più
solidi di quanto siano. Questo capitolo raccoglie i principali punti di
attenzione: che cosa la pipeline non può vedere, che cosa inferisce, dove
un'euristica può sbagliare e come vengono controllati gli errori.

Non è un elenco di difetti. È la mappa dei confini entro cui i risultati sono
utilizzabili.

## Che cosa l'osservazione non può vedere

### Il DNS è una fotografia parziale

La pipeline interroga il DNS pubblico con resolver ricorsivi. Vede ciò che il
dominio pubblica in quel momento, non tutto ciò che esiste.

- **Un dominio senza MX non è un dominio senza posta.** Può usare il record A
  come mail exchanger implicito, oppure il record può non essere stato
  osservabile.
- **Un sottodominio può non avere NS propri.** La risalita all'apex recupera la
  zona, ma il risultato descrive la zona, non necessariamente una scelta
  dell'ente.
- **I nameserver del registro vengono scartati.** Per i domini sotto `.edu.it`
  e `.gov.it` il canale NS può restare senza un nameserver utile. È una scelta
  metodologica, non un errore.
- **Il nome finale del web non dimostra un CNAME.** Se non c'è catena, coincide
  con il dominio di partenza.
- **TLS viene osservato solo sulla porta 443.** Un servizio su una porta
  diversa non viene visto.
- **Viene considerato solo IPv4.** La risoluzione usa il record A e non
  gestisce IPv6. Un sito raggiungibile solo su IPv6 non viene osservato.
- **Non vengono letti i contenuti.** Non si sa cosa il sito pubblica, quali
  tecnologie usa o se è aggiornato.

### La rete non è un contratto

L'Osservatorio osserva indirizzi e nomi, non rapporti contrattuali. Non può
sapere chi ha firmato un servizio, chi possiede i dati, quale giurisdizione si
applica o quali clausole di residenza esistono. L'ASN e il paese sono indizi
tecnici, non prove giuridiche.

### Il tempo non è uniforme

La raccolta è incrementale. Ogni record ha una data di ultimo tentativo, ma
l'insieme dei record non è stato osservato nello stesso istante. Le statistiche
mescolano osservazioni di date diverse.

Il punteggio ISDPA, in particolare, non viene ricalcolato automaticamente. Un
ente valutato mesi prima conserva il suo punteggio anche se il dominio è
cambiato. Per aggiornarlo bisogna rimuoverlo dalla tabella dei punteggi e
rimetterlo in coda. Questo è il limite più importante per chi legge serie
storiche o confronta enti valutati in momenti diversi.

## Che cosa l'inferenza può sbagliare

### Il riconoscimento del provider

La natura del provider viene dedotta da parole chiave nel nome
dell'organizzazione e nell'host. È un'euristica, con tre tipi di errore
possibili:

- **falso negativo**: un provider globale non elencato viene trattato come
  neutro;
- **falso positivo**: un nome che contiene una parola chiave per caso viene
  penalizzato o premiato senza motivo;
- **ambiguità**: lo stesso gruppo può comparire con nomi diversi o con più
  sistemi autonomi.

Le liste di hyperscaler e CDN sono finite e per definizione incomplete. Il
panorama cambia più in fretta di qualsiasi elenco.

### Le due definizioni di hyperscaler

Esiste una differenza interna che vale la pena conoscere. Il calcolo
dell'indice usa un insieme ampio di parole chiave: Google, Microsoft, Amazon,
Oracle, Alibaba, IBM e i rispettivi servizi cloud. L'indicatore "hyperscaler"
mostrato nelle statistiche cloud e nella scheda dell'ente, invece, si basa su
un insieme più ristretto: Amazon, Microsoft e Google.

Questo significa che un ente può ricevere una penalità nell'indice per un
provider come Oracle o Alibaba e non essere conteggiato nella card "dipendenza
hyperscaler". I due numeri non sono confrontabili direttamente.

### La geografia degli indirizzi

La banca dati geografica non è una mappa politica. Può sbagliare o essere
ambigua:

- **anycast**: lo stesso indirizzo è annunciato da più luoghi; il paese
  osservato è quello associato dall'archivio, non quello del server che ha
  risposto;
- **fallback alla registrazione**: per alcuni intervalli il paese osservato
  manca e viene usato il paese di registrazione del blocco;
- **cluster statistico**: le quote "in Italia" e "fuori UE" usano il paese di
  registrazione, non il paese osservato;
- **proxy, VPN e servizi di protezione**: possono alterare la relazione tra
  indirizzo e posizione.

Il paese dell'IP non è la residenza dei dati. Un server in Italia può servire
dati conservati altrove, e un server all'estero può conservare dati in Italia.

### La classificazione dei certificati

L'emittente viene classificato in categorie sulla base del nome
dell'organizzazione. Un'autorità non elencata finisce tra gli sconosciuti, anche
se è perfettamente legittima. Un certificato emesso da una CDN può essere
classificato come CDN anche quando il servizio è solo in parte integrato nella
piattaforma.

### La normalizzazione del dominio

Il campo del sito istituzionale è libero. La normalizzazione compie scelte
ragionevoli ma non infallibili:

- estrae il primo nome di host plausibile dal testo libero;
- rifiuta le caselle di posta, perché il dominio che segue la chiocciola
  appartiene al provider;
- accetta solo caratteri ASCII e non converte i nomi internazionalizzati;
- prova solo il nome nudo e `www`, non altri prefissi;
- scarta i valori che non hanno almeno due etichette o un suffisso alfabetico
  plausibile.

Un sito valido ma scritto in un formato insolito può essere scartato. Un sito
non più valido ma sintatticamente corretto può essere interrogato e produrre
campi vuoti.

## I limiti del punteggio

### I pesi sono una scelta

La ripartizione 40% posta, 35% web, 25% DNS non è una legge fisica. È una
gerarchia editoriale. Cambiarla cambierebbe i punteggi e le bande. Lo stesso
vale per i pesi interni ai canali e per i valori della pagella geografica.

### La compressione schiaccia le differenze

La curva a S centrale riduce le differenze estreme. Due enti con valori grezzi
molto diversi possono avere punteggi più vicini di quanto ci si aspetti. La
scala 0-100 non va letta come una scala lineare di dipendenza.

### La copertura è quasi sempre la stessa

La copertura dovrebbe riflettere quante osservazioni sono disponibili per un
canale. Nel modello attuale ogni ente ha una riga per canale, quindi la
copertura effettiva è quella di una singola osservazione. Il correttivo sposta
i punteggi verso il centro in modo simile per tutti gli enti. Non è un errore,
ma riduce la capacità della copertura di distinguere situazioni diverse.

### Il valore neutro

In assenza di osservazioni, il sistema produrrebbe un valore intermedio di
circa 42,4. Sembra un punteggio reale, ma non lo è. Il cancello d'ammissione
serve a evitare questo caso. Per la delega DNS il cancello è più permissivo:
un ente presente nella tabella NS ma senza nameserver utile non viene escluso,
e il canale riceve un punteggio basso. È una differenza di comportamento tra i
canali che va tenuta presente.

### Le bande hanno confini convenzionali

Il passaggio da una banda alla successiva è netto, ma la realtà non lo è. Un
ente a 61 e uno a 59 possono essere quasi identici. Inoltre la statistica
"infrastruttura sovrana" conta gli enti con punteggio almeno 78, mentre la
banda usa la soglia strettamente maggiore di 78: al confine esatto i due
conteggi possono divergere di un'unità.

### Bonus e malus sono grossolani

Le soglie sono pensate su tre canali. Una soglia del 50% significa due canali
su tre; una soglia dell'80% significa tutti e tre. Non c'è gradualità fine.
Inoltre il bonus europeo si attiva solo quando tutti i canali sono in paesi UE
diversi dall'Italia, perché l'Italia è conteggiata a parte. In pratica il bonus
più frequente è quello italiano.

## I limiti delle statistiche

### Denominatori diversi

Le percentuali di canale hanno denominatori diversi:

- posta e web richiedono provider e paese risolti;
- DNS include anche enti con provider non identificato;
- l'indice è calcolato solo sugli enti valutati.

Una percentuale "in Italia" non è la stessa cosa della percentuale sul totale
degli enti censiti. Confrontare quote con denominatori diversi produce
conclusioni sbagliate.

### Enti, non comuni

L'unità di analisi è l'ente. Più enti possono stare nello stesso comune, e
molti enti non hanno un codice ISTAT utilizzabile. Aggregare per comune
sottostimerebbe il perimetro e renderebbe invisibili gli enti senza codice.
Per questo le statistiche di concentrazione contano gli enti.

### Lock-in e dati mancanti

Le categorie di lock-in sono quattro, inclusa "non determinabile". Gli enti
con un provider mancante non vengono classificati come distribuiti né come
concentrati: finiscono nell'incertezza. La somma delle quattro categorie copre
tutti gli enti valutati, ma la quota di "non determinabile" va letta come
limite del dato, non come una configurazione.

### HHI sugli slot

L'indice di concentrazione è calcolato sugli slot ente-canale, non sugli enti.
Un ente con tre provider diversi pesa tre volte, uno con un solo provider pesa
tre volte sullo stesso. È una scelta corretta per misurare la concentrazione
degli slot, ma non va interpretata come concentrazione tra enti.

### Le classifiche dei provider

Le classifiche usano il nome dell'organizzazione. Nomi diversi possono
appartenere allo stesso gruppo, e lo stesso nome può coprire più società. La
classifica è utile per orientarsi, non è un registro societario.

## I presidi di qualità

Nonostante i limiti, la pipeline contiene diversi controlli.

### Il cancello d'ammissione

Impedisce che un ente senza dati riceva un punteggio neutro scambiabile per
una misura. Per posta e web richiede che provider e paese siano risolti; per
DNS è più permissivo perché il dato può essere legittimamente incompleto.

### La data di ultimo tentativo

Ogni record conserva la data dell'ultimo tentativo, anche quando l'esito è
negativo. Questo permette di far ruotare la coda e di distinguere un dato
vecchio da un dato mai tentato.

### Il registro dei cambiamenti

Quando un valore cambia, il vecchio e il nuovo vengono conservati con data e
tipo di operazione. È lo strumento che rende possibile ricostruire l'evoluzione
di un ente e verificare se un punteggio è basato su dati superati.

### I controlli di coerenza

Prima di pubblicare le statistiche, il sistema verifica che le somme coincidano
con i totali, che le bande sommino al 100%, che l'indice di concentrazione sia
normalizzato e che le quote siano plausibili. Se un controllo fallisce, la
generazione lo segnala e non pubblica un file incoerente.

### La sentinella delle coordinate

Un ente senza coordinate resta nel file con una coordinata riconoscibile e non
viene disegnato sulla mappa. Non viene spostato in un punto arbitrario né
eliminato dalle statistiche.

### La trasparenza dei campi

La scheda distingue i canali e mostra i valori osservati. Non nasconde
l'assenza di un dato dietro un valore neutro. Questa è una forma di qualità
tanto quanto la correttezza aritmetica.

## La dimensione etica

L'Osservatorio lavora solo su dati pubblici e su interrogazioni DNS
ragionevoli. Non accede ai contenuti dei siti, non cerca vulnerabilità, non
raccoglie dati personali, non enumera prefissi alla cieca. Il rispetto della
rete e dei suoi limiti è parte del metodo.

Questo ha un costo: alcune informazioni non vengono raccolte perché
richiederebbero tecniche invasive. È un costo accettabile per un osservatorio
che vuole essere trasparente e ripetibile.

## Come usare i dati senza superare i limiti

Un elenco pratico:

1. **Controlla il denominatore** prima di leggere una percentuale.
2. **Distingui l'assenza di osservazione dall'assenza del servizio.**
3. **Non confondere il paese dell'IP con la residenza dei dati.**
4. **Non leggere l'indice come una misura di sicurezza o qualità.**
5. **Considera la data di osservazione** e l'incrementalità del calcolo.
6. **Usa le bande come orientamento**, non come giudizio.
7. **Guarda i canali**, non solo il totale.
8. **Tratta le euristiche come tali**: utili per orientarsi, non definitive.
9. **Non confrontare enti valutati in momenti diversi** senza dichiararlo.
10. **Cita il metodo insieme al numero**, perché il numero da solo è
    incompleto.

## Che cosa servirebbe per andare oltre

Alcuni limiti sono strutturali, altri potrebbero essere ridotti con dati
aggiuntivi:

- una rilevazione periodica che ricalcoli i punteggi dopo i cambiamenti DNS;
- un'osservazione IPv6 e di porte diverse dalla 443;
- una verifica dell'origin dietro le CDN;
- dati contrattuali o di residenza dei dati;
- una tassonomia dei provider più stabile dei nomi delle organizzazioni;
- una copertura geografica più fine e una gestione esplicita degli anycast.

Sono estensioni possibili, non promesse. La documentazione descrive ciò che
l'Osservatorio fa oggi, con i suoi confini.
