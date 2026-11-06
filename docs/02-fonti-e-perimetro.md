# Fonti e perimetro

## Da dove partono i dati

L'Osservatorio non inventa e non stima la presenza digitale degli enti: la
osserva. La materia prima è un insieme di fonti pubbliche, ciascuna con un
ruolo preciso.

| Fonte | Che cosa fornisce | Come viene usata |
|---|---|---|
| IndicePA — anagrafica degli enti | Nome, codice IPA, categoria, sito istituzionale, contatti | Costruisce il perimetro degli enti e il punto di partenza delle interrogazioni DNS |
| Anagrafiche comunali e CAP | Comune, provincia, codice catastale, CAP | Colloca l'ente sul territorio e risolve le coordinate |
| GeoNames / servizi di geocoding | Coordinate geografiche | Assegna latitudine e longitudine quando non sono già disponibili |
| Italy Datacenters | Elenco dei datacenter presenti in Italia | Alimenta il livello informativo dedicato ai datacenter |
| MaxMind GeoLite2 ASN | Sistema autonomo associato a un indirizzo IP | Identifica il provider di rete di MX, NS, CNAME e TLS |
| MaxMind GeoLite2 Country | Paese e continente di un indirizzo IP | Colloca geograficamente l'infrastruttura osservata |

A queste si aggiungono dati di contesto che possono essere presenti nel
database, ma non alimentano necessariamente le mappe e l'indice. La
documentazione descrive il perimetro della pipeline principale: quando un
dataset è storico, sperimentale o accessorio, non viene presentato come parte
del calcolo corrente.

## Il perimetro: enti, non comuni

L'unità di analisi è l'**ente**, identificato dal codice IPA. Non è il comune:
più enti possono avere sede nello stesso comune, e un comune può essere
rappresentato da più strutture. Contare i comuni, quindi, sottostimerebbe il
perimetro reale.

Questo ha una conseguenza importante per chi legge le statistiche: il numero
totale di enti censiti, il numero di enti valutati e il numero di record DNS
analizzati sono tre grandezze diverse.

- **Enti censiti**: tutte le righe dell'anagrafica.
- **Enti valutati**: gli enti per cui esiste un indice di sovranità calcolato.
- **Record analizzati**: le osservazioni DNS disponibili per ciascun canale.

Un ente può essere censito ma non valutato, perché non ha un sito
istituzionale, perché il sito non è interpretabile come dominio, oppure perché
i dati DNS non sono sufficienti per costruire tutte le dimensioni dell'indice.

## Il cancello d'ingresso

Non tutti gli enti entrano nel calcolo dell'indice. Per essere valutato, un
ente deve soddisfare alcune condizioni:

1. avere un sito istituzionale valorizzato;
2. avere dati DNS utilizzabili per tutti i canali richiesti;
3. non avere già un punteggio calcolato.

La terza condizione merita una spiegazione. Il calcolo è **incrementale**: una
volta che un ente ha il suo punteggio, non viene ricalcolato automaticamente a
ogni esecuzione. Questo evita di rifare ogni volta lo stesso lavoro su tutto il
perimetro, ma significa anche che un punteggio può diventare meno attuale se le
condizioni cambiano. Il tema è ripreso nel capitolo sui limiti e sul ciclo di
vita del dato.

La seconda condizione, invece, serve a evitare un errore sottile: un ente privo
di dati non deve ricevere un punteggio neutro che sembri una misura reale. Se
mancasse un canale, il sistema produrrebbe un valore intermedio — circa 42,4 —
che è indistinguibile da una misura effettiva. Per questo il cancello richiede
che i dati esistano davvero, non solo che le righe siano presenti.

## Una fotografia, non un film

Ogni osservazione è datata. Il campo `last_crawl` registra l'ultimo tentativo di
aggiornamento di un record, indipendentemente dal fatto che l'esito sia stato
positivo o negativo. È un dettaglio tecnico, ma ha un significato importante per
il lettore: i dati che vede sono lo stato dell'osservazione in un certo momento,
non una proprietà permanente dell'ente.

Un dominio può cambiare provider, un certificato può scadere, un nameserver può
essere dismesso. La mappa e le statistiche raccontano la fotografia scattata
nell'ultima campagna di raccolta, non una verità senza tempo.

## Quanto dura una campagna

La pipeline lavora per lotti. Ogni esecuzione elabora un numero massimo di
record, configurabile, e lascia gli altri in coda per le esecuzioni successive.
Le code sono ordinate in modo da far ruotare i record: chi è stato aggiornato
meno di recente torna prima degli altri.

Questo modello ha due vantaggi:

- **sostenibilità**: non si forza la rete con migliaia di interrogazioni
  simultanee;
- **continuità**: il sistema può restare in funzione mentre aggiorna
  progressivamente il quadro.

Il prezzo da pagare è che il dataset non è mai tutto aggiornato nello stesso
istante. Le statistiche riflettono l'insieme delle osservazioni disponibili, con
date diverse. È un aspetto da tenere presente quando si confrontano enti o si
analizzano tendenze.
