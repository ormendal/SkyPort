# Sistema Informativo Aeroportuale

Progetto per il corso di **Sistemi Informativi** · Ingegneria Industriale · UCBM A.A. 2025/2026

Sistema web multi-ruolo che copre l'intero ciclo di vita di un volo: dalla programmazione del volo da parte della compagnia, alla prenotazione e al pagamento da parte del passeggero, fino al check-in (online o al banco) e alla gestione operativa dei gate.

---

## Architettura

```
aeroporto/
├── Dockerfile              # Immagine Docker (python:3.10-slim)
├── docker-compose.yml      # Orchestrazione servizi + volume dati
├── requirements.txt        # Dipendenze Python (Flask, Werkzeug)
├── DESIGN.md               # Design system: palette, tipografia, componenti
├── PRODUCT.md              # Contesto di prodotto: ruoli, principi, anti-pattern
├── data/                   # Volume Docker — contiene aeroporto.db
├── db/
│   ├── __init__.py
│   ├── schema.sql          # DDL: definizione delle 9 tabelle SQLite
│   ├── queries.sql         # Tutte le query SQL esternalizzate (Jinja2)
│   └── query_loader.py     # Loader: parsing queries.sql + rendering Jinja2
└── web/
    ├── app.py              # Applicazione Flask: API REST + route template
    ├── static/
    │   └── style.css       # Design system CSS (OKLCH, Barlow + Figtree)
    └── templates/
        ├── base.html                   # Layout base: navbar, toast, helper JS
        ├── home.html                   # Home: ricerca voli + mappa Leaflet
        ├── login.html                  # Login e registrazione (due colonne)
        ├── dashboard_passeggero.html   # Prenotazioni + check-in + profilo
        ├── dashboard_compagnia.html    # Gestione voli (crea/modifica/elimina)
        ├── dashboard_operatore.html    # Stato gate + check-in al banco
        └── dashboard_admin.html        # Statistiche + storico voli + aeroporti
```

### Livelli applicativi

| Livello | Tecnologia | Note |
|---------|-----------|------|
| Database | SQLite 3 | Gestito da `sqlite3` stdlib; `PRAGMA foreign_keys = ON` |
| Backend | Flask 3.0.3 | REST API + Jinja2 template rendering |
| Query SQL | `db/queries.sql` + Jinja2 | Query esternalizzate; template dinamici per filtri opzionali |
| Autenticazione | Flask sessions + cookie | `werkzeug.security` per hash password |
| Frontend | HTML5 + Bootstrap 5 CDN | Vanilla JS (Fetch API), nessun framework |
| Icone | Bootstrap Icons 1.11 CDN | Standard 16/20/24px |
| Mappe | Leaflet.js 1.9.4 CDN | Solo nella home, fallback se CDN non disponibile |
| Containerizzazione | Docker + Docker Compose | Volume `./data` per persistenza SQLite |

---

## Schema del database

| Tabella | Descrizione |
|---------|-------------|
| `compagnie_aeree` | Anagrafica compagnie (id, nome) |
| `gate` | Gate fisici con stato: libero / occupato / manutenzione |
| `voli` | Voli con compagnia, gate, tratta IATA, orari, capienza e stato |
| `passeggeri` | Anagrafica passeggeri con documento univoco |
| `prenotazioni` | Collegamento passeggero–volo: PNR, prezzo, stato ciclo vita |
| `utenti` | Autenticazione e ruoli (admin / operatore / compagnia / passeggero) |
| `carte_imbarco` | Una per prenotazione; `operatore_id NULL` = check-in online |
| `aeroporti` | Coordinate geografiche IATA per la mappa interattiva |

### Relazioni principali

```
compagnie_aeree 1:N voli
gate            1:N voli
gate            1:N carte_imbarco
passeggeri      1:N prenotazioni
passeggeri      1:N utenti
voli            1:N prenotazioni
prenotazioni    1:0..1 carte_imbarco
utenti          1:N carte_imbarco  (operatore_id)
```

### Ciclo di vita di una prenotazione

```
prenotata → pagata → imbarcato
     ↓
 cancellata
```

---

## Come eseguire

### Con Docker (metodo consigliato)

```bash
cd aeroporto
docker compose up --build
```

Il server è disponibile su **http://localhost:5000**

### Test automatici

```bash
# In Docker (metodo consigliato — stesso ambiente di produzione)
docker-compose run --rm web pytest tests/

# In locale
cd aeroporto
pip install flask==3.0.3 werkzeug==3.0.3 pytest==8.3.5
pytest tests/
```

I test usano un database SQLite temporaneo e isolato per ogni caso di test (`tmp_path` di pytest), senza toccare il database di produzione.

Il database SQLite viene creato automaticamente in `data/aeroporto.db` al primo avvio con dati di esempio precaricati (3 compagnie, 6 gate, 16 voli, 20 passeggeri, 43 prenotazioni, 11 carte d'imbarco, 12 aeroporti).

### In locale (senza Docker)

```bash
cd aeroporto
pip install flask==3.0.3 werkzeug==3.0.3
python web/app.py
```

**Python richiesto:** 3.10 o superiore

---

## Credenziali di default

| Username | Password | Ruolo | Note |
|----------|----------|-------|------|
| `admin` | `password` | admin | Statistiche, storico voli, aeroporti |
| `compagnia1` | `password` | compagnia | Air Dolomiti |
| `compagnia2` | `password` | compagnia | Ryanair |
| `compagnia3` | `password` | compagnia | ITA Airways |
| `operatore1` | `password` | operatore | Check-in al banco |
| `operatore2` | `password` | operatore | Check-in al banco |
| `mario.rossi` | `password` | passeggero | Mario Rossi — crediti €500 |
| `laura.bianchi` | `password` | passeggero | **Account bloccato** (test admin) — crediti €200 |
| `giuseppe.verdi` | `password` | passeggero | Giuseppe Verdi — crediti €150 |
| `anna.ferrari` | `password` | passeggero | Anna Ferrari — crediti €0 |
| `luca.romano` | `password` | passeggero | Luca Romano — crediti €0 |
| `sofia.esposito` | `password` | passeggero | Sofia Esposito — crediti €0 |
| `marco.conti` | `password` | passeggero | Marco Conti — crediti €0 |
| `elena.ricci` | `password` | passeggero | Elena Ricci — crediti €0 |
| `paolo.lombardi` | `password` | passeggero | Paolo Lombardi — crediti €0 |
| `giulia.mancini` | `password` | passeggero | Giulia Mancini — crediti €0 |
| `francesco.bruno` | `password` | passeggero | Francesco Bruno — crediti €300 |
| `chiara.deluca` | `password` | passeggero | Chiara De Luca — crediti €50 |
| `roberto.galli` | `password` | passeggero | Roberto Galli — crediti €1000 |
| `valentina.marini` | `password` | passeggero | Valentina Marini — crediti €0 |
| `andrea.moretti` | `password` | passeggero | Andrea Moretti — crediti €180 |
| `serena.costa` | `password` | passeggero | Serena Costa — crediti €75 |
| `matteo.ferretti` | `password` | passeggero | Matteo Ferretti — crediti €0 |
| `alessia.pellegrini` | `password` | passeggero | Alessia Pellegrini — crediti €250 |
| `davide.caruso` | `password` | passeggero | Davide Caruso — crediti €0 |
| `monica.santoro` | `password` | passeggero | Monica Santoro — crediti €400 |

---

## Ruoli e funzionalità

### Passeggero
- Cerca voli per origine, destinazione e data (home pubblica con mappa interattiva)
- Prenota voli con posti disponibili
- Paga la prenotazione (simulato)
- Effettua il check-in online (assegna posto e gate automaticamente)
- Visualizza la carta d'imbarco
- Modifica nome, cognome e documento del profilo

### Compagnia aerea
- Visualizza tutti i propri voli con stato e disponibilità
- Crea nuovi voli (origine/destinazione IATA, orari, capienza, gate)
- Modifica voli esistenti (gate, orari, posti, stato)
- Elimina voli (solo se in stato "programmato" e senza prenotazioni attive)

### Operatore aeroportuale
- Monitora lo stato di tutti i gate in tempo reale
- Cambia stato gate (libero / occupato / manutenzione)
- Esegue check-in al banco ricercando il passeggero per documento
- Gestisce la disambiguazione se il passeggero ha più prenotazioni idonee

### Admin
- Dashboard con statistiche aggregate (voli, prenotazioni, passeggeri, gate, carte d'imbarco)
- Storico completo di tutti i voli con filtri per stato, compagnia e data
- Tabella ordinabile per codice e data di partenza
- Gestione anagrafica aeroporti (inserimento con coordinate IATA per la mappa)

---

## Endpoint API

### Pubblici (nessun login)

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| GET | `/` | Home page (template HTML) |
| GET | `/api/health` | Health check JSON |
| GET | `/api/voli/search?origine=&destinazione=&data=` | Ricerca voli con coordinate aeroporti |
| GET | `/api/voli/attivi` | Voli attivi (programmato/partito) con coordinate per mappa |
| GET | `/api/aeroporti` | Elenco aeroporti con coordinate geografiche |

### Autenticazione

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| GET | `/login` | Pagina login/registrazione |
| POST | `/api/login` | Login — body: `{username, password}` |
| POST | `/api/logout` | Logout |
| POST | `/api/registrazione` | Registrazione passeggero |

### Passeggero (ruolo: passeggero)

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| GET | `/dashboard/passeggero` | Dashboard passeggero |
| POST | `/api/prenota` | Prenota un volo — body: `{volo_id, prezzo}` |
| GET | `/api/mie_prenotazioni` | Elenco prenotazioni con carte d'imbarco |
| POST | `/api/paga/<id>` | Pagamento simulato |
| POST | `/api/checkin_online/<id>` | Check-in online: assegna posto e gate |
| PUT | `/api/passeggero/profilo` | Aggiorna nome, cognome, documento |

### Compagnia (ruolo: compagnia)

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| GET | `/dashboard/compagnia` | Dashboard compagnia |
| GET | `/api/compagnia/voli` | Elenco voli con disponibilità |
| POST | `/api/compagnia/voli` | Crea nuovo volo |
| PUT | `/api/compagnia/voli/<id>` | Modifica volo (gate, orari, posti, stato) |
| DELETE | `/api/compagnia/voli/<id>` | Elimina volo (solo programmato senza prenotazioni attive) |

### Operatore (ruolo: operatore)

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| GET | `/dashboard/operatore` | Dashboard operatore |
| GET | `/api/operatore/gate` | Stato gate con voli assegnati |
| PUT | `/api/operatore/gate/<id>` | Cambia stato gate |
| POST | `/api/operatore/checkin` | Check-in al banco per documento passeggero |

### Admin (ruolo: admin)

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| GET | `/dashboard/admin` | Dashboard admin |
| GET | `/api/admin/stats` | Statistiche aggregate del sistema |
| GET | `/api/admin/voli?stato=&compagnia_id=&data=` | Storico voli con filtri |
| POST | `/api/admin/aeroporti` | Inserisce nuovo aeroporto con coordinate |

---

## Esempi di test con curl

```bash
# Health check
curl http://localhost:5000/api/health

# Ricerca voli MXP → FCO
curl "http://localhost:5000/api/voli/search?origine=MXP&destinazione=FCO"

# Voli attivi per la mappa
curl http://localhost:5000/api/voli/attivi

# Elenco aeroporti
curl http://localhost:5000/api/aeroporti

# Login come passeggero
curl -c cookie.txt -X POST http://localhost:5000/api/login \
     -H "Content-Type: application/json" \
     -d '{"username":"mario.rossi","password":"password"}'

# Prenotazioni del passeggero
curl -b cookie.txt http://localhost:5000/api/mie_prenotazioni

# Modifica profilo
curl -b cookie.txt -X PUT http://localhost:5000/api/passeggero/profilo \
     -H "Content-Type: application/json" \
     -d '{"nome":"Mario","cognome":"Rossi","documento":"IT00001"}'

# Login come admin e statistiche
curl -c cookie.txt -X POST http://localhost:5000/api/login \
     -H "Content-Type: application/json" \
     -d '{"username":"admin","password":"password"}'
curl -b cookie.txt http://localhost:5000/api/admin/stats
curl -b cookie.txt "http://localhost:5000/api/admin/voli?stato=programmato"

# Login come compagnia ed eliminazione volo
curl -c cookie.txt -X POST http://localhost:5000/api/login \
     -H "Content-Type: application/json" \
     -d '{"username":"compagnia1","password":"password"}'
curl -b cookie.txt -X DELETE http://localhost:5000/api/compagnia/voli/3

# Inserimento aeroporto (admin)
curl -c cookie.txt -X POST http://localhost:5000/api/admin/aeroporti \
     -H "Content-Type: application/json" \
     -d '{"codice":"LGW","nome":"Londra Gatwick","lat":51.1537,"lon":-0.1821}'
```

---

## Dipendenze

| Libreria | Versione | Uso |
|----------|----------|-----|
| Flask | 3.0.3 | Framework web, routing, sessioni, Jinja2 |
| Werkzeug | 3.0.3 | Hash password (`generate_password_hash`) |
| sqlite3 | stdlib | Database SQLite (incluso in Python) |
| Bootstrap | 5.3.3 CDN | Layout e componenti UI |
| Bootstrap Icons | 1.11.3 CDN | Icone vettoriali |
| Leaflet.js | 1.9.4 CDN | Mappa interattiva rotte voli |
| Google Fonts | CDN | Barlow Semi Condensed + Figtree |

**Python richiesto:** 3.10 o superiore

---

## Note tecniche

### Sicurezza
- Le password sono hashate con `werkzeug.security.generate_password_hash` (PBKDF2-SHA256).
- La `SECRET_KEY` per le sessioni Flask va cambiata in produzione tramite variabile d'ambiente:
  ```bash
  SECRET_KEY=chiave-super-segreta docker compose up
  ```
- Le chiavi esterne SQLite sono abilitate con `PRAGMA foreign_keys = ON` su ogni connessione.

### Database e migrazioni
- Il file `db/schema.sql` usa `CREATE TABLE IF NOT EXISTS` su tutte le tabelle: è idempotente e non distrugge i dati ad ogni riavvio.
- Il seed degli aeroporti (`_seed_aeroporti`) viene eseguito separatamente dal seed principale, garantendo la compatibilità con database già inizializzati prima dell'introduzione della tabella `aeroporti`.

### Query esternalizzate
Le query SQL operative sono definite in `db/queries.sql` con marcatori `-- :nome_query`.
Il modulo `db/query_loader.py` le carica all'avvio, le cachea in un dizionario e usa
Jinja2 per compilare le query dinamiche (quelle con filtri opzionali come `{% if campo %}`).
In `web/app.py` ogni query si richiama con `Q.get('nome')` per le statiche
e `Q.render('nome', **kwargs)` per le dinamiche.

### Mappa interattiva
- Usa le tile CartoDB Positron (sfondo neutro, adatto alla palette navy/gold).
- Se Leaflet non è disponibile (CDN down, assenza di rete), viene mostrato un messaggio di fallback senza bloccare il resto della pagina.
- I marker mostrano il codice IATA con stile navy/gold. Le polyline delle rotte sono tratteggiate in blu (`--c-blue`).

### Controllo overbooking
- L'endpoint `POST /api/prenota` usa una transazione `BEGIN`/`COMMIT` con controllo atomico: conta le prenotazioni in stato `prenotata` o `pagata` prima di inserire la nuova riga, prevenendo race condition.
