-- =============================================================================
-- Schema database: Sistema Informativo Aeroportuale
-- Sistemi Informativi - Ingegneria Industriale - UCBM A.A. 2025/2026
-- =============================================================================
-- Solo DDL: le tabelle vengono create qui.
-- I dati di seed vengono inseriti da web/app.py al primo avvio.
--
-- Questo file è l'unica fonte di verità dello schema: tutte le colonne sono
-- definite direttamente nei CREATE TABLE.
-- =============================================================================

PRAGMA foreign_keys = ON;

-- -----------------------------------------------------------------------------
-- Tabella: compagnie_aeree
-- Anagrafica delle compagnie aeree che operano nell'aeroporto.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS compagnie_aeree (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT    NOT NULL
);

-- -----------------------------------------------------------------------------
-- Tabella: gate
-- Gate fisici dell'aeroporto con il loro stato corrente.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gate (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    codice TEXT    NOT NULL UNIQUE,
    stato  TEXT    NOT NULL DEFAULT 'libero'
                   CHECK (stato IN ('libero', 'occupato', 'manutenzione'))
);

-- -----------------------------------------------------------------------------
-- Tabella: voli
-- Ogni volo ha una compagnia, un gate (opzionale se non ancora assegnato),
-- origine/destinazione in codice IATA, orari e capienza.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS voli (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    codice_volo       TEXT    NOT NULL UNIQUE,
    compagnia_id      INTEGER NOT NULL REFERENCES compagnie_aeree(id)
                                       ON DELETE RESTRICT ON UPDATE RESTRICT,
    gate_id           INTEGER REFERENCES gate(id)
                              ON DELETE RESTRICT ON UPDATE RESTRICT,
    origine           TEXT    NOT NULL,
    destinazione      TEXT    NOT NULL,
    data_ora_partenza TEXT    NOT NULL,
    data_ora_arrivo   TEXT    NOT NULL,
    posti_totali      INTEGER NOT NULL CHECK (posti_totali > 0),
    stato             TEXT    NOT NULL DEFAULT 'programmato'
                              CHECK (stato IN ('programmato', 'partito', 'arrivato')),
    prezzo_base       REAL    NOT NULL DEFAULT 100.0,
    orario_stimato    TEXT,
    ritardo_note      TEXT
);

-- -----------------------------------------------------------------------------
-- Tabella: passeggeri
-- Anagrafica dei passeggeri (documento univoco per identificazione).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS passeggeri (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    nome      TEXT    NOT NULL,
    cognome   TEXT    NOT NULL,
    documento TEXT    NOT NULL UNIQUE,
    crediti   REAL    NOT NULL DEFAULT 0.0
);

-- -----------------------------------------------------------------------------
-- Tabella: prenotazioni
-- Collega ogni passeggero a un volo con il relativo PNR e stato pagamento.
-- Vincolo CHECK sullo stato: i valori ammessi rispecchiano il ciclo di vita
-- della prenotazione (prenotata → pagata → imbarcato, oppure cancellata).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS prenotazioni (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    passeggero_id       INTEGER NOT NULL REFERENCES passeggeri(id)
                                         ON DELETE RESTRICT ON UPDATE RESTRICT,
    volo_id             INTEGER NOT NULL REFERENCES voli(id)
                                         ON DELETE RESTRICT ON UPDATE RESTRICT,
    codice_prenotazione TEXT    NOT NULL UNIQUE,
    data_prenotazione   TEXT    NOT NULL DEFAULT (datetime('now')),
    prezzo              REAL    NOT NULL CHECK (prezzo >= 0),
    stato               TEXT    NOT NULL DEFAULT 'prenotata'
                                CHECK (stato IN ('prenotata', 'pagata', 'cancellata', 'imbarcato')),
    valutazione         INTEGER CHECK (valutazione BETWEEN 1 AND 5)
);

-- -----------------------------------------------------------------------------
-- Tabella: utenti
-- Gestione autenticazione e ruoli. La FK su compagnia_id è valorizzata solo
-- per ruolo='compagnia'; quella su passeggero_id solo per ruolo='passeggero'.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS utenti (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    ruolo         TEXT    NOT NULL CHECK (ruolo IN ('admin', 'operatore', 'compagnia', 'passeggero')),
    compagnia_id  INTEGER REFERENCES compagnie_aeree(id)
                          ON DELETE RESTRICT ON UPDATE RESTRICT,
    passeggero_id INTEGER REFERENCES passeggeri(id)
                          ON DELETE RESTRICT ON UPDATE RESTRICT,
    attivo        INTEGER NOT NULL DEFAULT 1
);

-- -----------------------------------------------------------------------------
-- Tabella: carte_imbarco
-- Una e una sola carta per prenotazione (UNIQUE su prenotazione_id).
-- operatore_id è NULL per check-in online, valorizzato per check-in al banco.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS carte_imbarco (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    prenotazione_id INTEGER NOT NULL UNIQUE REFERENCES prenotazioni(id)
                                            ON DELETE RESTRICT ON UPDATE RESTRICT,
    volo_id         INTEGER NOT NULL REFERENCES voli(id)
                                    ON DELETE RESTRICT ON UPDATE RESTRICT,
    numero_posto    TEXT,
    gate_imbarco_id INTEGER REFERENCES gate(id)
                            ON DELETE RESTRICT ON UPDATE RESTRICT,
    data_emissione  TEXT    NOT NULL DEFAULT (datetime('now')),
    operatore_id    INTEGER REFERENCES utenti(id)
                            ON DELETE RESTRICT ON UPDATE RESTRICT
);

-- Garantisce che lo stesso posto non venga assegnato a due prenotazioni sullo stesso volo.
-- Parziale: righe con numero_posto NULL (posto non ancora assegnato) sono escluse.
CREATE UNIQUE INDEX IF NOT EXISTS uq_posto_volo
    ON carte_imbarco (volo_id, numero_posto)
    WHERE numero_posto IS NOT NULL;

-- -----------------------------------------------------------------------------
-- Tabella: aeroporti
-- Coordinate geografiche degli aeroporti (codice IATA come chiave naturale).
-- Usata dalla mappa interattiva nella home per disegnare le rotte dei voli.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS aeroporti (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    codice TEXT    NOT NULL UNIQUE,   -- codice IATA, es. "MXP"
    nome   TEXT,                       -- nome esteso, es. "Milano Malpensa"
    lat    REAL    NOT NULL,           -- latitudine WGS-84
    lon    REAL    NOT NULL            -- longitudine WGS-84
);

-- -----------------------------------------------------------------------------
-- Tabella: log
-- Registro degli eventi di sistema. utente_id NULL per azioni anonime.
-- ON DELETE SET NULL preserva la riga anche se l'utente viene eliminato.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS log (
    id        INTEGER  PRIMARY KEY AUTOINCREMENT,
    utente_id INTEGER,
    azione    TEXT     NOT NULL,
    dettagli  TEXT,                    -- JSON con informazioni contestuali
    timestamp DATETIME NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (utente_id) REFERENCES utenti(id) ON DELETE SET NULL
);
