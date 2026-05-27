-- =============================================================================
-- SkyPort — Seed iniziale del database (dati statici)
-- =============================================================================
-- Popola il database con i dati di esempio statici:
--   aeroporti, compagnie_aeree, gate, passeggeri, voli, prenotazioni, carte_imbarco.
--
-- Gli UTENTI (con password hashate) sono creati separatamente in
-- web/app.py::_seed_dinamico() perché richiedono generate_password_hash() di
-- werkzeug.security con salt random non pre-calcolabile in SQL.
--
-- Data di riferimento della demo: giovedì 28 maggio 2026.
-- Tutte le date dei voli sono STATICHE relative a questa data.
--
-- Esecuzione: caricato da _seed_statico() via conn.executescript().
-- Tutti gli INSERT sono OR IGNORE per garantire idempotenza.
-- =============================================================================

PRAGMA foreign_keys = ON;

-- -----------------------------------------------------------------------------
-- Aeroporti (codici IATA + coordinate WGS-84 per la mappa Leaflet)
-- -----------------------------------------------------------------------------
INSERT OR IGNORE INTO aeroporti (codice, nome, lat, lon) VALUES
    ('MXP', 'Milano Malpensa',           45.6301,  8.7236),
    ('FCO', 'Roma Fiumicino',            41.7999, 12.2462),
    ('LIN', 'Milano Linate',             45.4454,  9.2788),
    ('NAP', 'Napoli Capodichino',        40.8860, 14.2908),
    ('BLQ', 'Bologna Marconi',           44.5354, 11.2887),
    ('VCE', 'Venezia Marco Polo',        45.5053, 12.3519),
    ('BGY', 'Bergamo Orio al Serio',     45.6734,  9.7040),
    ('CTA', 'Catania Fontanarossa',      37.4668, 15.0664),
    ('LHR', 'Londra Heathrow',           51.4775, -0.4614),
    ('CDG', 'Parigi Charles de Gaulle',  49.0097,  2.5479),
    ('MAD', 'Madrid Barajas',            40.4983, -3.5676),
    ('AMS', 'Amsterdam Schiphol',        52.3086,  4.7639),
    ('FRA', 'Francoforte am Main',       50.0379,  8.5622),
    ('BCN', 'Barcellona El Prat',        41.2971,  2.0785),
    ('BER', 'Berlino Brandenburg',       52.3667, 13.5033),
    ('MUC', 'Monaco Franz Josef Strauss',48.3538, 11.7861),
    ('ZRH', 'Zurigo Kloten',             47.4582,  8.5555),
    ('VIE', 'Vienna Schwechat',          48.1103, 16.5697),
    ('CPH', 'Copenaghen Kastrup',        55.6180, 12.6508),
    ('IST', 'Istanbul',                  41.2753, 28.7519),
    ('JFK', 'New York Kennedy',          40.6413,-73.7781),
    ('DXB', 'Dubai International',       25.2532, 55.3657);

-- -----------------------------------------------------------------------------
-- Compagnie aeree (2 per la demo)
-- -----------------------------------------------------------------------------
INSERT OR IGNORE INTO compagnie_aeree (id, nome) VALUES
    (1, 'Air Dolomiti'),
    (2, 'ITA Airways');

-- -----------------------------------------------------------------------------
-- Gate (4 gate per la demo)
-- -----------------------------------------------------------------------------
INSERT OR IGNORE INTO gate (id, codice, stato) VALUES
    (1, 'G1', 'libero'),
    (2, 'G2', 'libero'),
    (3, 'G3', 'libero'),
    (4, 'G4', 'libero');

-- -----------------------------------------------------------------------------
-- Passeggeri (2 per la demo)
--
-- id=1 (Mario Rossi) è il PASSEGGERO DEMO: nessuna prenotazione preesistente,
--   verrà usato durante la demo per prenotare EN1234 dal vivo.
-- id=2 (Roberto Galli) ha prenotazioni in vari stati per popolare la demo.
-- -----------------------------------------------------------------------------
INSERT OR IGNORE INTO passeggeri (id, nome, cognome, documento, crediti) VALUES
    (1, 'Mario',   'Rossi', 'AY1234567',  500.0),
    (2, 'Roberto', 'Galli', 'IT00013',   1000.0);

-- -----------------------------------------------------------------------------
-- Voli (12 voli) — date statiche relative a giovedì 28 maggio 2026
--   * id=1       → VOLO DEMO PRIMARIO   (28/05/2026 ore 14:00, G1, 120€, 150 posti)
--   * id=2       → VOLO DEMO BACKUP     (28/05/2026 ore 18:30, G2, 120€, 180 posti)
--   * id=3-7     → altri programmati    (29/05 – 25/06/2026)
--   * id=8-9     → già partiti          (mattina 28/05/2026, prima della demo)
--   * id=10-12   → arrivati storici     (18/04 – 27/05/2026)
--
-- Distribuzione: Air Dolomiti (EN*) 6 voli, ITA Airways (AZ*) 6 voli.
--               Ogni gate ospita esattamente 3 voli.
-- -----------------------------------------------------------------------------
INSERT OR IGNORE INTO voli
    (id, codice_volo, compagnia_id, gate_id, origine, destinazione,
     data_ora_partenza, data_ora_arrivo, posti_totali, stato, prezzo_base,
     orario_stimato, ritardo_note) VALUES
    -- ── PROGRAMMATI (futuro rispetto a giovedì 28/05/2026 mattina) ─────────
    -- VOLO DEMO PRIMARIO: mario.rossi lo prenoterà dal vivo durante la demo
    ( 1, 'EN1234', 1, 1, 'MXP', 'FCO', '2026-05-28 14:00', '2026-05-28 15:30', 150, 'programmato', 120.0, NULL, NULL),
    -- VOLO DEMO BACKUP: roberto.galli ha GAL002 (pagata) qui per il check-in al banco
    ( 2, 'AZ2000', 2, 2, 'FCO', 'CDG', '2026-05-28 18:30', '2026-05-28 20:30', 180, 'programmato', 120.0, NULL, NULL),
    ( 3, 'EN9012', 1, 3, 'BGY', 'BCN', '2026-05-29 09:30', '2026-05-29 11:30', 189, 'programmato',  65.0, NULL, NULL),
    ( 4, 'EN5001', 1, 4, 'MXP', 'MUC', '2026-05-30 07:00', '2026-05-30 08:45', 180, 'programmato', 145.0, NULL, NULL),
    ( 5, 'AZ3001', 2, 1, 'AMS', 'FCO', '2026-06-02 09:00', '2026-06-02 11:30', 170, 'programmato', 195.0, NULL, NULL),
    ( 6, 'AZ7777', 2, 2, 'FCO', 'JFK', '2026-06-05 11:00', '2026-06-05 20:00', 280, 'programmato', 480.0, NULL, NULL),
    ( 7, 'AZ9000', 2, 3, 'CDG', 'IST', '2026-06-25 16:00', '2026-06-25 20:30', 200, 'programmato', 220.0, NULL, NULL),
    -- ── PARTITI (mattina del 28/05/2026, prima dell'orario presentazione) ──
    ( 8, 'EN1001', 1, 4, 'MXP', 'FRA', '2026-05-28 06:00', '2026-05-28 07:30', 150, 'partito',    130.0, NULL, NULL),
    ( 9, 'AZ2001', 2, 1, 'FCO', 'CDG', '2026-05-28 07:30', '2026-05-28 09:30', 180, 'partito',    195.0, NULL, NULL),
    -- ── ARRIVATI (storico per le statistiche admin e lo storico passeggero) ──
    (10, 'EN5000', 1, 2, 'MXP', 'MUC', '2026-04-18 07:00', '2026-04-18 08:45', 180, 'arrivato',   145.0, NULL, NULL),
    (11, 'AZ0005', 2, 3, 'FCO', 'LHR', '2026-04-25 08:00', '2026-04-25 10:30', 180, 'arrivato',   160.0, NULL, NULL),
    (12, 'EN8000', 1, 4, 'MXP', 'FCO', '2026-05-27 14:00', '2026-05-27 15:30', 189, 'arrivato',    75.0, NULL, NULL);

-- -----------------------------------------------------------------------------
-- Prenotazioni (6 prenotazioni) — tutte di Roberto Galli (passeggero_id=2)
--
-- Mario Rossi (id=1) non ha prenotazioni: prenoterà EN1234 dal vivo in demo.
--
-- GAL001 (id=1): volo 3,  prenotata  → può cancellarla in demo
-- GAL002 (id=2): volo 2,  pagata     → DEMO BACKUP: operatore1 farà check-in al banco
-- GAL003 (id=3): volo 5,  pagata     → può fare check-in online
-- GAL004 (id=4): volo 4,  cancellata → esempio cancellata
-- HH0001 (id=5): volo 10, imbarcato  → storico (★★★★★)
-- HH0002 (id=6): volo 11, imbarcato  → storico (★★★★)
-- -----------------------------------------------------------------------------
INSERT OR IGNORE INTO prenotazioni
    (id, passeggero_id, volo_id, codice_prenotazione, data_prenotazione,
     prezzo, stato, valutazione) VALUES
    ( 1, 2,  3, 'GAL001', '2026-05-18 12:00',  65.0, 'prenotata',  NULL),
    ( 2, 2,  2, 'GAL002', '2026-05-17 09:00', 120.0, 'pagata',     NULL),
    ( 3, 2,  5, 'GAL003', '2026-05-20 10:00', 195.0, 'pagata',     NULL),
    ( 4, 2,  4, 'GAL004', '2026-05-19 14:00', 145.0, 'cancellata', NULL),
    ( 5, 2, 10, 'HH0001', '2026-04-15 08:00', 145.0, 'imbarcato',     5),
    ( 6, 2, 11, 'HH0002', '2026-04-22 09:00', 160.0, 'imbarcato',     4);

-- -----------------------------------------------------------------------------
-- Carte d'imbarco (2 per le prenotazioni 'imbarcato')
--
-- operatore_id = NULL per tutte: gli operatori sono creati in _seed_dinamico
-- dopo questo file, quindi non è possibile referenziarli qui senza FK violation.
-- -----------------------------------------------------------------------------
INSERT OR IGNORE INTO carte_imbarco
    (id, prenotazione_id, volo_id, numero_posto, gate_imbarco_id, data_emissione, operatore_id) VALUES
    (1, 5, 10, '12A', 2, '2026-04-18 05:00', NULL),
    (2, 6, 11, '10B', 3, '2026-04-25 06:00', NULL);
