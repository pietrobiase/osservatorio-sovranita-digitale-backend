#!/usr/bin/env python3

"""
Normalizzazione del dominio istituzionale e declinazioni da
tentare, condivise da get_cname.py, get_ns.py e get_mx.py.

Vive in un modulo perche' la logica e' identica nei tre
script e una copia per file divergeva: get_cname.py aveva gia'
dovuto aggiungere il rifiuto delle caselle di posta, gli
altri due no, e cosi' avrebbero continuato a scrivere 'pec.it'
come dominio dell'ente.

Non importa niente dal DB e non tocca la rete: qui c'e' solo
sintassi. Chiamare get_ns.py o get_mx.py non deve avere effetti
collaterali.
"""

import re

# =========================================================
# CANONICALIZZAZIONE
# =========================================================
#
# sito_istituzionale e' un campo libero: contiene URL completi,
# domini con percorso, valori con porta e testo introduttivo.
# Mandare tutto questo al resolver non puo' funzionare, quindi
# il valore viene ridotto al solo nome di host.
#
# Nota sullo schema http/https: non e' una declinazione che
# aiuta la risoluzione. Il resolver accetta solo un nome di
# host, e il TLS parla sempre sulla porta 443. Quello che
# invece manca spesso e' il prefisso www, perche' moltissimi
# enti pubblicano il sito solo su www.esempio.it e il dominio
# nudo non ha record. Sono due declinazioni diverse e non
# vanno confuse: si provano entrambe, in quest'ordine.

# Schema solo all'inizio: 'comune.it/path' non contiene '://'
# e non deve essere mutilato.
_SCHEMA_RE = re.compile(
    r"^[a-zA-Z][a-zA-Z0-9+.\-]*://"
)

# Primo token che sembra un nome di host: uno o piu' gruppi
# di label separati da punto, chiusi da un TLD alfabetico.
# Non richiede lo schema, cosi' funziona sia su
# 'Sito ufficiale: comune.it' sia su
# 'http://www.comune.it, altro'.
_ESTRAI_HOST_RE = re.compile(
    r"(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}"
)

_TIPPI_PORTAA = re.compile(
    r"\.(?P<tipo>[a-z]{2,})$"
)

# Qualsiasi casella di posta, non solo quelle PEC: nei dati
# compaiono anche indirizzi su gmail, libero, yahoo e
# regione.sicilia.it. Un indirizzo di posta non descrive
# l'infrastruttura web dell'ente, e il dominio che segue la
# '@' appartiene al provider.
#
# La '@' e' preceduta da un nome locale che non contiene
# due punti, cosi' 'user:pass@host' dei browser non viene
# scambiato per una casella.
_CASELLA_RE = re.compile(
    r"(?:^|[\s,;:])"
    r"[^@\s:;,]+@"
    r"[a-z0-9\-]+(?:\.[a-z0-9\-]+)+"
    r"(?:$|[\s,;/)])",
    re.IGNORECASE,
)


def canonicalizza_dominio(raw):
    """
    Riduce sito_istituzionale al solo nome di host.

    Rimuove, nell'ordine:
      - spazi iniziali e finali
      - uno schema iniziale (http://, https://, ftp://...)
      - slash iniziali di un URL senza schema ('//host/path')
      - testo introduttivo, se il valore ne contiene
      - percorso, query e fragment
      - credenziali prima della '@'
      - porta esplicita
      - punto finale del nome root

    Restituisce None se non rimane un nome plausibile: senza
    almeno due etichette non c'e' niente da risolvere, e una
    stringa come 'example' o '/' produrrebbe solo rumore nei
    log e una riga di risultato tutta NULL.

    Il case viene abbassato perche' il DNS e' case-insensitive
    e i confronti fra declinazioni devono essere esatti.
    """

    if raw is None:
        return None

    testo = str(raw).strip()

    if not testo:
        return None

    testo = _SCHEMA_RE.sub("", testo, count=1)

    # URL senza schema ('//host/path'): togliere gli slash
    # iniziali, altrimenti il taglio sul percorso
    # lascerebbe una stringa vuota.
    testo = testo.lstrip("/")

    # testo libero: 'Sito ufficiale: https://comune.it' o
    # 'http://a.it, http://b.it'. Un nome di host non puo'
    # contenere spazi, quindi in presenza di spazi si estrae
    # il primo token che somiglia a un dominio. Senza questo
    # passaggio quei valori passerebbero i controlli di
    # sintassi (punti e TLD) e finirebbero inviati al resolver
    # come se fossero host.
    if re.search(r"\s", testo):

        # Una casella di posta dentro testo libero
        # ('Sito ufficiale: info@pec.it') viene respinta prima
        # di ogni estrazione: il dominio del provider di
        # posta non descrive l'infrastruttura dell'ente.
        if _CASELLA_RE.search(testo):

            return None

        candidato = _ESTRAI_HOST_RE.search(testo)

        if not candidato:

            return None

        testo = candidato.group(0)

    # Percorso, query, fragment
    for sep in ("/", "?", "#"):
        if sep in testo:
            testo = testo.split(sep, 1)[0]

    # Una casella di posta non e' un sito istituzionale.
    # sito_istituzionale ne contiene parecchie: tagliare
    # sotto la '@' produrrebbe 'pec.it' come dominio
    # dell'ente, cioe' il nome del provider di posta
    # certificata. Sarebbe un dominio reale, ma
    # descriverebbe il provider e non l'ente, e finirebbe
    # nelle statistiche di concentrazione come se fosse
    # infrastruttura dell'amministrazione.
    #
    # Il caso 'user:pass@host' dei browser resta invece
    # accettato: li' la '@' e' seguita da due punti ed e'
    # parte di un URL con credenziali.
    #
    # Il controllo viene dopo il taglio del percorso perche'
    # in un URL con credenziali il percorso viene dopo la
    # '@': tagliarlo prima lascerebbe solo 'user:pass@host',
    # che sarebbe scartato come casella.
    if "@" in testo:

        locale, _, dominio = testo.rpartition("@")

        if ":" not in locale:

            # 'utente@pec.it' e simili: nessun dominio utile.
            return None

        testo = dominio

    testo = testo.strip()

    if not testo:
        return None

    # Porta esplicita. Si esclude il caso IPv6 literal
    # ('[::1]:443'), che non e' un dominio ma lo zero-punto
    # contiene due ':'.
    if ":" in testo and not testo.startswith("["):
        testo = testo.split(":", 1)[0]

    # Punto finale: 'comune.it.' e 'comune.it' sono lo stesso
    # nome, ma per il resolver sono due stringhe diverse.
    testo = testo.rstrip(".")

    if not testo:
        return None

    testo = testo.lower()

    # Servono almeno due etichette: un TLD o un nome singolo
    # non e' un dominio utilizzabile. 'localhost' resta
    # escluso, e va bene.
    if "." not in testo:
        return None

    # Una label non puo' iniziare o finire con '-', e non puo'
    # superare 63 caratteri. Un nome che violerebbe la sintassi
    # non e' un dominio: e' rumore nel campo.
    for label in testo.split("."):

        if not label:
            return None

        if len(label) > 63:
            return None

        if label.startswith("-") or label.endswith("-"):
            return None

    if not _TIPPI_PORTAA.search(testo):
        return None

    return testo


def declinazioni(host):
    """
    Elenco dei nomi da provare per un host, in ordine di
    preferenza.

    L'ordine conta: il dominio come scritto nel DB viene
    sempre tentato per primo, cosi' il comportamento resta
    identico a prima quando quel nome funziona. 'www.' e' un
    tentativo successivo, non una sostituzione.

    Non si tentano altri prefissi (admin, posta, intranet...):
    sarebbero enumerazioni alla cieca, e il nome che espone il
    sito istituzionale e' in genere quello nudo o con www.

    Il prefisso www viene rimosso quando c'e' gia', per non
    produrre 'www.www.comune.it'.
    """

    if not host:
        return []

    out = [host]

    if host.startswith("www."):

        senza = host[4:]

        if "." in senza:
            out.append(senza)

    else:

        out.append(f"www.{host}")

    return out
