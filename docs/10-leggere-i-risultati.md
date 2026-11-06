# Leggere i risultati

## Prima di tutto: tre numeri diversi

Chi apre l'Osservatorio incontra subito alcuni numeri. È utile non
confonderli.

| Grandezza | Che cosa conta | Perché è diversa dalle altre |
|---|---|---|
| Enti censiti | Tutte le righe dell'anagrafica | Comprende enti senza sito, senza DNS o non valutati |
| Enti valutati | Enti con un indice calcolato | Richiede un sito e dati DNS sufficienti |
| Record di canale | Osservazioni disponibili per MX, NS o CNAME | Un ente può avere un canale e non un altro |

Un ente censito può non essere valutato. Un ente valutato può avere un canale
senza provider identificato. Un record di canale può esistere anche quando
l'informazione è incompleta. Se si usa il numero sbagliato come denominatore,
qualsiasi percentuale diventa fuorviante.

## La mappa

La mappa mostra gli enti nella loro sede. Ogni punto è un'entità, non un
server. Il colore o il simbolo possono rappresentare la banda di sovranità o il
canale selezionato; il popup raccoglie i dettagli.

Alcuni enti non compaiono sulla mappa perché non hanno coordinate. Non sono
esclusi dalle statistiche: semplicemente non hanno una posizione disegnabile.
Se il numero di punti sembra inferiore al numero di enti valutati, questa è
spesso la spiegazione.

La mappa risponde a domande come:

- dove si concentrano gli enti con una certa banda?
- quali aree mostrano una maggiore presenza di infrastrutture estere?
- come cambia il quadro passando da un canale all'altro?

Non risponde a:

- dove si trovano i server dell'ente;
- dove sono conservati i dati;
- quale provider ha la sede legale in un certo luogo.

## La scheda di un ente

La scheda riunisce i tre canali e l'indice. Conviene leggerla in un ordine
preciso.

1. **Il dominio osservato.** È il punto di partenza. Se è stato normalizzato,
   potrebbe differire dal valore grezzo dell'anagrafica.
2. **La posta.** Server MX, provider, paese. Un valore vuoto significa "non
   osservato", non "inesistente".
3. **La delega DNS.** Nameserver, provider, paese. Un nameserver del registro
   può essere assente per scelta metodologica.
4. **Il web.** Nome finale, IP, provider, certificato. Il nome finale può
   coincidere con il dominio anche in assenza di CNAME.
5. **L'indice.** Punteggi per canale, totale, banda. Va letto insieme ai
   canali, non al posto loro.
6. **La data.** Ogni osservazione ha un momento. La scheda è una fotografia,
   non una proprietà permanente.

### Un esempio di lettura

Immaginiamo una scheda con questi tratti:

- posta presso un provider italiano;
- nameserver presso un grande operatore internazionale;
- sito dietro una CDN globale, con certificato emesso dalla CDN;
- indice nella fascia intermedia.

La lettura corretta è: l'ente ha una parte della propria infrastruttura in
Italia, ma la risoluzione del nome e la distribuzione del sito dipendono da
soggetti globali. Non è un ente "sicuro" né "insicuro": è un ente con una
dipendenza distribuita. L'indice intermedio riflette questa mescolanza, non una
valutazione morale.

Un altro esempio: posta, DNS e web tutti presso lo stesso grande fornitore.
L'indice può essere basso e il lock-in alto. La storia qui è la
concentrazione: un unico punto di dipendenza per funzioni diverse. Non
significa che il servizio sia scadente; significa che l'autonomia
infrastrutturale è limitata.

## Le bande

Le bande sono utili per una lettura rapida, ma non sono compartimenti stagni.
Il confine tra una banda e l'altra è convenzionale. Un ente a 61 e un ente a
59 possono essere molto simili, anche se compaiono in bande diverse.

La banda va sempre accompagnata da:

- i punteggi dei singoli canali;
- la presenza o assenza di lock-in;
- la data dell'osservazione.

Una banda alta con un canale molto debole racconta una storia diversa da una
banda alta con tre canali equilibrati. Il totale sintetizza, ma non sostituisce
il dettaglio.

## Lock-in e resilienza

Le statistiche usano due parole vicine ma non identiche.

Il **lock-in** descrive la concentrazione dei provider: stesso ASN sui tre
canali, due canali uguali, tre canali diversi, oppure dati insufficienti.

La **resilienza** descrive la stessa struttura da un altro punto di vista:
DNS centralizzato quando i tre canali coincidono, DNS distribuito quando sono
tutti diversi.

Sono due letture dello stesso fenomeno. Un lock-in alto è anche una forma di
centralizzazione. Una distribuzione completa è anche una forma di
frammentazione. Nessuna delle due è automaticamente positiva: la
centralizzazione può semplificare la gestione, la frammentazione può aumentare
la complessità. L'Osservatorio descrive la configurazione, non la valuta.

## La concentrazione ASN

L'indice HHI misura quanto il panorama è concentrato. Un valore basso indica
che molti provider coprono quote simili; un valore alto indica che pochi
provider dominano.

È calcolato sugli **slot ente-canale**, non sugli enti. Un ente con tre
provider diversi contribuisce a tre slot; un ente con lo stesso provider su
tutti i canali contribuisce tre volte allo stesso provider. Questo rende
l'indice sensibile sia alla distribuzione tra enti sia alla concentrazione
interna di ciascun ente.

L'HHI non dice quale provider sia "buono" o "cattivo". Dice quanto è
diversificato il panorama. Un HHI alto può riflettere un mercato efficiente o
una dipendenza sistemica: la differenza richiede un'analisi ulteriore.

## Le percentuali geografiche

Le quote "in Italia" e "fuori UE" sono calcolate sul **cluster di
registrazione** dell'indirizzo IP, non sulla posizione fisica del server. Per
gli indirizzi anycast, tipici delle CDN, questa distinzione è importante.

Inoltre, ogni percentuale ha il proprio denominatore: gli enti con un provider
risolto per quel canale. Non è la stessa cosa della percentuale sul totale
degli enti censiti. Quando si confrontano due percentuali, bisogna verificare
che abbiano lo stesso denominatore.

## I dati mancanti

Un campo vuoto può significare cose diverse:

- il record non è stato osservato;
- il record esiste ma non è stato possibile risolverlo;
- il record è stato scartato per una scelta metodologica;
- l'ente non ha quel servizio.

L'Osservatorio non distingue sempre questi casi nel frontend. Per questo è
importante non trattare il vuoto come zero. Un ente senza MX non ha
necessariamente zero posta; un ente senza NS non ha necessariamente zero
delega. Il vuoto è assenza di osservazione, non assenza di realtà.

## Le domande a cui i dati rispondono

| Domanda | Risposta possibile |
|---|---|
| Quanti enti hanno la posta presso un provider italiano? | Sì, sul sottoinsieme con MX risolto |
| Quanti enti dipendono da un unico provider? | Sì, tramite il lock-in |
| Quanto è concentrato il panorama dei provider? | Sì, tramite l'HHI |
| Dove sono gli enti con una certa banda? | Sì, sulla mappa, per gli enti geolocalizzati |
| Dove sono fisicamente i server? | No, solo il paese dell'IP osservato |
| Dove sono conservati i dati? | No |
| L'ente è sicuro? | No |
| L'ente offre servizi di qualità? | No |
| L'ente rispetta il GDPR? | No |

## Le domande a cui i dati non rispondono

Alcune domande sono frequenti ma fuori perimetro:

- **"Questo ente è sovrano?"** L'indice misura una configurazione
  infrastrutturale, non la sovranità giuridica o politica.
- **"Questo provider è affidabile?"** L'Osservatorio non misura affidabilità,
  continuità o sicurezza.
- **"Questo ente ha un sito obsoleto?"** Non guarda i contenuti, solo
  l'infrastruttura.
- **"Questo ente tratta dati personali all'estero?"** Non osserva i flussi
  dati né i contratti.
- **"Perché questo ente ha un punteggio basso?"** Può dipendere da scelte
  infrastrutturali, da un provider globale, da un certificato, da un canale
  mancante o da una combinazione. La scheda aiuta a capire, ma non formula un
  giudizio.

## Confrontare gli enti

Il confronto è possibile, ma va fatto con cautela:

- gli enti possono essere stati osservati in date diverse;
- i canali possono avere coperture diverse;
- un ente senza coordinate resta nelle statistiche ma non sulla mappa;
- un ente non valutato non ha un indice da confrontare;
- i punteggi sono sintesi, non misure assolute.

Un confronto utile è quello tra **configurazioni**: un ente con lock-in alto e
uno con distribuzione completa; un ente con posta italiana e web su CDN; un
ente con DNS delegato al registro e uno con nameserver propri. Il confronto
tra numeri assoluti è meno informativo del confronto tra storie
infrastrutturali.

## In sintesi

Leggere i risultati significa tenere insieme tre livelli:

1. **il dato osservato**: cosa ha risposto la rete;
2. **il dato derivato**: come è stato classificato e pesato;
3. **la lettura**: cosa possiamo e non possiamo dedurne.

L'Osservatorio è progettato per rendere trasparente il passaggio dal primo al
secondo livello. Il terzo resta responsabilità del lettore, ed è per questo che
questa documentazione esiste.
