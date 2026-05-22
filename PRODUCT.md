# Product

## Register

product

## Users

Quattro ruoli distinti, ciascuno con contesto operativo diverso:

- **Passeggero**: usa il sistema da casa o in aeroporto per cercare voli, prenotare, pagare e fare check-in online. Livello tecnico variabile; si aspetta semplicità e chiarezza.
- **Operatore aeroportuale**: al banco del check-in, sotto pressione temporale. Ha bisogno di trovare una prenotazione in pochi secondi e emettere la carta d'imbarco senza frizioni.
- **Compagnia aerea**: gestisce il proprio catalogo di voli. Vuole una dashboard chiara con stato e disponibilità, e strumenti rapidi per creare o modificare voli.
- **Admin**: supervisione aggregata. Legge statistiche, non agisce su singole entità. Ha bisogno di una panoramica leggibile, non di dettagli operativi.

## Product Purpose

Sistema informativo aeroportuale multi-ruolo che copre l'intero ciclo di vita di un volo: dalla programmazione (compagnia) alla prenotazione (passeggero), dal pagamento al check-in (online o al banco), fino alla gestione operativa dei gate. Il successo si misura in zero errori operativi, zero ambiguità di stato, zero ritardi causati dall'interfaccia.

## Brand Personality

Moderno · Fluido · Professionale

Tono calmo e autorevole, come un sistema che ha già gestito migliaia di voli. Non aggressivo, non giocoso. Chi lo usa deve sentirsi competente e supportato, non istruito o infantilizzato.

## Anti-references

- Gradienti viola-blu (SaaS generico): il progetto non è una startup, è infrastruttura.
- Glassmorphism decorativo: nessun blur-as-style. Ogni superficie deve essere leggibile.
- Card dentro card: nidificazione visiva che confonde la gerarchia.
- Font Inter/Roboto: scelte di default, invisibili, prive di carattere.
- Hero con numeri giganti: cliché delle dashboard SaaS. I numeri devono essere leggibili, non monumentali.
- Neon / dark terminal: il riferimento è aviation premium (Lufthansa, Emirates), non un tool di sviluppo.
- Animazioni di layout: width, height, padding non si animano mai.

## Design Principles

1. **Chiarezza prima di tutto**: ogni schermata prioritizza il compito principale del ruolo. Un operatore non deve cercare il form di check-in; un passeggero non deve capire cosa fa un gate.
2. **L'informazione comanda**: dati, stato e azioni precedono sempre l'estetica. Il design supporta il contenuto, non compete con esso.
3. **Fiducia attraverso coerenza**: azioni, feedback e navigazione seguono schemi prevedibili in tutti i ruoli. Nessuna sorpresa.
4. **Precisione da aviazione**: zero ambiguità. Gli stati di prenotazione e gate sono sempre visibili e non interpretabili. I messaggi di errore spiegano, non accusano.
5. **Moderno senza sperimentare**: contemporaneo a sufficienza da sembrare attuale, stabile a sufficienza da sembrare sicuro. Nessun pattern sperimentale in un contesto operativo.

## Accessibility & Inclusion

WCAG 2.1 AA: contrasto minimo 4.5:1 per testo normale, 3:1 per testo large. Focus visible su tutti gli elementi interattivi. Testo ridimensionabile senza perdita di funzionalità. Etichette form sempre associate agli input. Messaggi di stato comunicati anche via attributi ARIA, non solo colore.
