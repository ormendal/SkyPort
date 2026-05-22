"""
Sistema Informativo Aeroportuale — API REST
Sistemi Informativi · Ingegneria Industriale · UCBM A.A. 2025/2026

Struttura del progetto:
  schema.sql        →  DDL del database (cartella radice)
  web/app.py        →  questo file: Flask + logica API
  data/aeroporto.db →  file SQLite (montato come volume Docker)

Avvio rapido con Docker:
  docker compose up --build
"""

import os
import json
import shutil
import sqlite3
import random
import string
import tempfile
import functools
from datetime import datetime

from flask import Flask, request, jsonify, session, render_template, redirect, url_for, send_file
from werkzeug.security import generate_password_hash, check_password_hash

# =============================================================================
# Configurazione
# =============================================================================

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'chiave-segreta-sviluppo-aeroporto')

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH     = os.path.join(BASE_DIR, 'data', 'aeroporto.db')
SCHEMA_PATH = os.path.join(BASE_DIR, 'schema.sql')


# =============================================================================
# Helper: accesso al database
# =============================================================================

def get_db():
    """Apre e restituisce una connessione SQLite con chiavi esterne abilitate."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def query_rows(sql, params=()):
    """Esegue una SELECT e restituisce tutte le righe come lista di dizionari."""
    conn = get_db()
    try:
        cur = conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def query_row(sql, params=()):
    """Esegue una SELECT e restituisce una sola riga come dizionario (o None)."""
    conn = get_db()
    try:
        cur = conn.execute(sql, params)
        r = cur.fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def db_execute(sql, params=()):
    """Esegue INSERT / UPDATE / DELETE con commit. Restituisce lastrowid."""
    conn = get_db()
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# =============================================================================
# Helper: generazione codici e posti
# =============================================================================

def _genera_pnr_unico(conn):
    """Genera un PNR alfanumerico di 6 caratteri non ancora presente nel DB."""
    while True:
        pnr = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not conn.execute(
            "SELECT id FROM prenotazioni WHERE codice_prenotazione = ?", (pnr,)
        ).fetchone():
            return pnr


def _genera_posto(conn, volo_id, posti_totali):
    """Restituisce il primo posto libero sul volo (es. '1A', '1B', ...)."""
    posti_occupati = {
        r[0] for r in conn.execute(
            """SELECT ci.numero_posto FROM carte_imbarco ci
               JOIN prenotazioni p ON ci.prenotazione_id = p.id
               WHERE p.volo_id = ? AND ci.numero_posto IS NOT NULL""",
            (volo_id,)
        ).fetchall()
    }
    for riga in range(1, posti_totali + 1):
        for lettera in 'ABCDEF':
            posto = f"{riga}{lettera}"
            if posto not in posti_occupati:
                return posto
    return None


# =============================================================================
# Helper: log di sistema
# =============================================================================

def registra_log(azione, utente_id=None, dettagli=None):
    """Inserisce un evento nel log di sistema. Non interrompe mai l'operazione principale."""
    try:
        db_execute(
            "INSERT INTO log (utente_id, azione, dettagli) VALUES (?, ?, ?)",
            (
                utente_id,
                azione,
                json.dumps(dettagli, ensure_ascii=False) if dettagli else None
            )
        )
    except Exception:
        pass


# =============================================================================
# Helper: conflitti gate
# =============================================================================

def _calcola_warning_gate(voli):
    """
    Aggiunge 'warning_gate' ai voli programmati con possibili conflitti di gate.
    Due voli sullo stesso gate a meno di 60 minuti l'uno dall'altro.
    """
    programmati = [v for v in voli if v.get('stato') == 'programmato' and v.get('gate_id')]
    for v in programmati:
        try:
            t1 = datetime.fromisoformat(v['data_ora_partenza'].replace(' ', 'T'))
        except Exception:
            v['warning_gate'] = None
            continue
        conflitti = []
        for altro in programmati:
            if altro['id'] == v['id'] or altro.get('gate_id') != v.get('gate_id'):
                continue
            try:
                t2 = datetime.fromisoformat(altro['data_ora_partenza'].replace(' ', 'T'))
                if abs((t1 - t2).total_seconds()) / 60 < 60:
                    conflitti.append(f"{altro['codice_volo']} ({t2.strftime('%H:%M')})")
            except Exception:
                continue
        v['warning_gate'] = f"Conflitto gate con: {', '.join(conflitti)}" if conflitti else None
    return voli


# =============================================================================
# Inizializzazione e migrazione del database
# =============================================================================

def _migra_colonne(conn):
    """
    Aggiunge colonne mancanti alle tabelle esistenti.
    Ogni ALTER TABLE è idempotente: gli errori 'duplicate column' vengono ignorati.
    """
    migrazioni = [
        "ALTER TABLE utenti      ADD COLUMN attivo       INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE voli        ADD COLUMN prezzo_base  REAL    NOT NULL DEFAULT 100.0",
        "ALTER TABLE voli        ADD COLUMN orario_stimato TEXT",
        "ALTER TABLE voli        ADD COLUMN ritardo_note  TEXT",
        "ALTER TABLE prenotazioni ADD COLUMN valutazione  INTEGER",
        "ALTER TABLE passeggeri  ADD COLUMN crediti      REAL    NOT NULL DEFAULT 0.0",
    ]
    for sql in migrazioni:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass  # colonna già esistente
    conn.commit()


def init_db():
    """
    Crea le tabelle (schema.sql), applica le migrazioni e carica i dati di seed.
    Viene chiamata una sola volta prima di avviare il server.
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    try:
        # 1. Crea le tabelle (idempotente grazie a IF NOT EXISTS)
        with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
            conn.executescript(f.read())

        # 2. Aggiunge le nuove colonne alle tabelle esistenti
        _migra_colonne(conn)

        # 3. Seed principale — solo se il database è vuoto
        if conn.execute("SELECT COUNT(*) FROM compagnie_aeree").fetchone()[0] == 0:
            _seed(conn)
            print("[init_db] Dati di seed caricati.")
        else:
            print("[init_db] Database già inizializzato, seed saltato.")

        # 4. Seed aeroporti — separato per supportare DB già esistenti
        if conn.execute("SELECT COUNT(*) FROM aeroporti").fetchone()[0] == 0:
            _seed_aeroporti(conn)
            print("[init_db] Aeroporti di seed caricati.")

    finally:
        conn.close()


def _seed_aeroporti(conn):
    """Inserisce le coordinate geografiche degli aeroporti italiani ed europei di esempio."""
    conn.executemany(
        "INSERT OR IGNORE INTO aeroporti (codice, nome, lat, lon) VALUES (?, ?, ?, ?)",
        [
            # --- Aeroporti italiani ---
            ("MXP", "Milano Malpensa",          45.6301,  8.7236),
            ("FCO", "Roma Fiumicino",            41.7999, 12.2462),
            ("VCE", "Venezia Marco Polo",        45.5053, 12.3519),
            ("BGY", "Bergamo Orio al Serio",     45.6734,  9.7040),
            ("LIN", "Milano Linate",             45.4454,  9.2788),
            ("NAP", "Napoli Capodichino",        40.8860, 14.2908),
            ("CTA", "Catania Fontanarossa",      37.4668, 15.0664),
            # --- Aeroporti europei ---
            ("LHR", "Londra Heathrow",           51.4775, -0.4614),
            ("CDG", "Parigi Charles de Gaulle",  49.0097,  2.5479),
            ("MAD", "Madrid Barajas",            40.4983, -3.5676),
            ("BER", "Berlino Brandenburg",       52.3667, 13.5033),
            ("BCN", "Barcellona El Prat",        41.2971,  2.0785),
        ]
    )
    conn.commit()


def _seed(conn):
    """
    Inserisce i dati di esempio nel database (ordine rispetta le FK).
    compagnie → gate → voli → passeggeri → prenotazioni → utenti → carte_imbarco → log
    """
    ph = generate_password_hash("password")

    # ── 1. Compagnie aeree (3 compagnie) ─────────────────────────────────────
    conn.executemany(
        "INSERT INTO compagnie_aeree (nome) VALUES (?)",
        [("Air Dolomiti",), ("Ryanair",), ("ITA Airways",)]
        # id: 1=Air Dolomiti, 2=Ryanair, 3=ITA Airways
    )

    # ── 2. Gate (G1-G6, stati misti) ─────────────────────────────────────────
    conn.executemany(
        "INSERT INTO gate (codice, stato) VALUES (?, ?)",
        [
            ("G1", "libero"),       # id=1
            ("G2", "occupato"),     # id=2
            ("G3", "manutenzione"), # id=3
            ("G4", "libero"),       # id=4
            ("G5", "occupato"),     # id=5
            ("G6", "manutenzione"), # id=6
        ]
    )

    # ── 3. Voli (16 voli: passato/futuro, tutte le compagnie, casi speciali) ─
    conn.executemany(
        """INSERT INTO voli
           (codice_volo, compagnia_id, gate_id, origine, destinazione,
            data_ora_partenza, data_ora_arrivo, posti_totali, stato, prezzo_base,
            orario_stimato, ritardo_note)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            # id=1 — futuro programmato, gate G1 (conflitto con volo EN3000 alle 08:30)
            ("EN1234", 1, 1, "MXP", "FCO",
             "2026-06-01 08:00", "2026-06-01 09:30", 150, "programmato", 120.0, None, None),
            # id=2 — recente, partito
            ("EN5678", 1, 2, "FCO", "VCE",
             "2026-05-20 10:00", "2026-05-20 11:00", 100, "partito",      80.0, None, None),
            # id=3 — futuro, gate NULL (test warning gate mancante)
            ("FR9012", 2, None, "BGY", "LIN",
             "2026-06-15 14:00", "2026-06-15 15:00", 189, "programmato",  45.0, None, None),
            # id=4 — passato, arrivato (storico + valutazioni)
            ("FR3456", 2, 2, "MXP", "NAP",
             "2026-05-18 07:00", "2026-05-18 08:30", 189, "arrivato",     60.0, None, None),
            # id=5 — futuro, gate NULL, 50 posti
            ("EN7890", 1, None, "FCO", "MXP",
             "2026-06-20 16:00", "2026-06-20 17:15",  50, "programmato",  95.0, None, None),
            # id=6 — futuro, 180 posti, gate G4
            ("ITA001", 3, 4, "FCO", "LHR",
             "2026-06-10 09:30", "2026-06-10 11:30", 180, "programmato", 150.0, None, None),
            # id=7 — passato, arrivato (storico + valutazioni), 120 posti
            ("ITA002", 3, 1, "FCO", "CDG",
             "2026-04-15 07:00", "2026-04-15 09:00", 120, "arrivato",    110.0, None, None),
            # id=8 — futuro, RITARDO (orario_stimato popolato), gate G5
            ("FR5000", 2, 5, "MXP", "MAD",
             "2026-06-05 14:30", "2026-06-05 17:00", 189, "programmato",  55.0,
             "2026-06-05 16:30", "Ritardo tecnico per manutenzione aeromobile"),
            # id=9 — futuro, 3 posti totali → OVERBOOKING con 3 prenotazioni attive
            ("EN2000", 1, 4, "VCE", "BER",
             "2026-06-08 11:00", "2026-06-08 13:30",   3, "programmato", 200.0, None, None),
            # id=10 — passato, arrivato (storico + valutazioni), 100 posti
            ("ITA003", 3, 1, "NAP", "FCO",
             "2026-04-20 15:00", "2026-04-20 16:10", 100, "arrivato",     90.0, None, None),
            # id=11 — futuro, gate G5, 189 posti
            ("FR6000", 2, 5, "BGY", "BCN",
             "2026-06-12 08:00", "2026-06-12 10:00", 189, "programmato",  49.0, None, None),
            # id=12 — futuro, gate G1 alle 08:30 → CONFLITTO con EN1234 (stessa gate, 30 min)
            ("EN3000", 1, 1, "MXP", "CTA",
             "2026-06-01 08:30", "2026-06-01 10:30", 120, "programmato", 130.0, None, None),
            # id=13 — recente, partito, gate G4, 180 posti
            ("ITA004", 3, 4, "LHR", "FCO",
             "2026-05-22 14:00", "2026-05-22 16:30", 180, "partito",     160.0, None, None),
            # id=14 — OGGI 2026-05-23, programmato, gate G2 (cruscotto operatore)
            ("FR7000", 2, 2, "MXP", "FCO",
             "2026-05-23 10:00", "2026-05-23 11:00", 120, "programmato",  75.0, None, None),
            # id=15 — futuro, 5 posti totali, 4 prenotazioni attive → QUASI COMPLETO (1 libero)
            ("EN4000", 1, 3, "FCO", "VCE",
             "2026-06-18 09:00", "2026-06-18 10:00",   5, "programmato",  85.0, None, None),
            # id=16 — futuro, gate NULL, 180 posti
            ("ITA005", 3, None, "FCO", "MAD",
             "2026-07-01 11:00", "2026-07-01 13:30", 180, "programmato", 145.0, None, None),
        ]
    )

    # ── 4. Passeggeri (20 passeggeri, crediti variabili) ─────────────────────
    conn.executemany(
        "INSERT INTO passeggeri (nome, cognome, documento, crediti) VALUES (?, ?, ?, ?)",
        [
            ("Mario",     "Rossi",        "IT00001",  500.0),  # id=1
            ("Laura",     "Bianchi",      "IT00002",  200.0),  # id=2  utente bloccato
            ("Giuseppe",  "Verdi",        "IT00003",  150.0),  # id=3
            ("Anna",      "Ferrari",      "IT00004",    0.0),  # id=4
            ("Luca",      "Romano",       "IT00005",    0.0),  # id=5
            ("Sofia",     "Esposito",     "IT00006",    0.0),  # id=6
            ("Marco",     "Conti",        "IT00007",    0.0),  # id=7
            ("Elena",     "Ricci",        "IT00008",    0.0),  # id=8
            ("Paolo",     "Lombardi",     "IT00009",    0.0),  # id=9
            ("Giulia",    "Mancini",      "IT00010",    0.0),  # id=10
            ("Francesco", "Bruno",        "IT00011",  300.0),  # id=11
            ("Chiara",    "De Luca",      "IT00012",   50.0),  # id=12  50<55 → crediti insuff. su FR5000
            ("Roberto",   "Galli",        "IT00013", 1000.0),  # id=13
            ("Valentina", "Marini",       "IT00014",    0.0),  # id=14
            ("Andrea",    "Moretti",      "IT00015",  180.0),  # id=15
            ("Serena",    "Costa",        "IT00016",   75.0),  # id=16
            ("Matteo",    "Ferretti",     "IT00017",    0.0),  # id=17
            ("Alessia",   "Pellegrini",   "IT00018",  250.0),  # id=18
            ("Davide",    "Caruso",       "IT00019",    0.0),  # id=19
            ("Monica",    "Santoro",      "IT00020",  400.0),  # id=20
        ]
    )

    # ── 5. Prenotazioni (43 prenotazioni, tutti gli stati) ───────────────────
    conn.executemany(
        """INSERT INTO prenotazioni
           (passeggero_id, volo_id, codice_prenotazione, data_prenotazione,
            prezzo, stato, valutazione)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            # --- Volo 1 (EN1234, futuro programmato) ---
            ( 1,  1, "AA1234", "2026-05-10 09:00", 120.0, "prenotata",  None),  # id=1
            ( 2,  1, "BB1234", "2026-05-10 09:30", 120.0, "pagata",     None),  # id=2
            ( 3,  1, "CC1234", "2026-05-10 10:00", 130.0, "imbarcato",  None),  # id=3  → carta
            (11,  1, "PQ1234", "2026-05-15 08:00", 120.0, "pagata",     None),  # id=4
            # --- Volo 2 (EN5678, partito) ---
            ( 4,  2, "DD5678", "2026-05-11 08:00",  80.0, "imbarcato",  None),  # id=5  → carta
            ( 5,  2, "EE5678", "2026-05-11 08:30",  80.0, "pagata",     None),  # id=6
            ( 6,  2, "XC5678", "2026-05-11 09:00",  80.0, "cancellata", None),  # id=7
            # --- Volo 3 (FR9012, futuro, no gate) ---
            ( 6,  3, "FF9012", "2026-05-12 11:00",  45.0, "prenotata",  None),  # id=8
            ( 7,  3, "GG9012", "2026-05-12 11:30",  45.0, "prenotata",  None),  # id=9
            ( 8,  3, "HH9012", "2026-05-12 12:00",  45.0, "cancellata", None),  # id=10
            # --- Volo 4 (FR3456, arrivato — storico + valutazioni) ---
            ( 9,  4, "II3456", "2026-05-13 07:00",  60.0, "imbarcato",     4),  # id=11 ★★★★
            (10,  4, "JJ3456", "2026-05-13 07:30",  60.0, "imbarcato",  None),  # id=12 → carta
            (11,  4, "KK3456", "2026-05-13 08:00",  60.0, "imbarcato",     5),  # id=13 ★★★★★
            # --- Volo 5 (EN7890, futuro no gate 50 posti) ---
            ( 1,  5, "LL7890", "2026-05-14 10:00",  95.0, "pagata",     None),  # id=14
            ( 2,  5, "MM7890", "2026-05-14 10:30",  95.0, "pagata",     None),  # id=15
            ( 3,  5, "NN7890", "2026-05-14 11:00",  95.0, "prenotata",  None),  # id=16
            ( 4,  5, "OO7890", "2026-05-14 11:30",  95.0, "prenotata",  None),  # id=17
            # --- Volo 6 (ITA001, futuro 180 posti) ---
            (13,  6, "PP0001", "2026-05-16 09:00", 150.0, "pagata",     None),  # id=18
            (14,  6, "QQ0001", "2026-05-16 09:30", 150.0, "prenotata",  None),  # id=19
            (18,  6, "RR0001", "2026-05-16 10:00", 150.0, "pagata",     None),  # id=20
            # --- Volo 7 (ITA002, arrivato — storico + valutazioni) ---
            (16,  7, "SS0002", "2026-04-10 08:00", 110.0, "imbarcato",     3),  # id=21 ★★★
            (15,  7, "TT0002", "2026-04-10 08:30", 110.0, "imbarcato",  None),  # id=22 → carta
            # --- Volo 8 (FR5000, futuro RITARDO — Chiara ha 50 crediti < prezzo 55) ---
            (12,  8, "UU5000", "2026-05-17 10:00",  55.0, "prenotata",  None),  # id=23
            (17,  8, "VV5000", "2026-05-17 10:30",  55.0, "prenotata",  None),  # id=24
            # --- Volo 9 (EN2000, 3 posti — OVERBOOKING: 3/3 occupati) ---
            (19,  9, "WW2000", "2026-05-18 09:00", 200.0, "prenotata",  None),  # id=25
            (20,  9, "XX2000", "2026-05-18 09:30", 200.0, "prenotata",  None),  # id=26
            (13,  9, "YY2000", "2026-05-18 10:00", 200.0, "prenotata",  None),  # id=27 → 3/3 full
            # --- Volo 10 (ITA003, arrivato — storico + valutazioni) ---
            ( 7, 10, "ZZ3000", "2026-04-15 08:00",  90.0, "imbarcato",     5),  # id=28 ★★★★★
            ( 8, 10, "AB3000", "2026-04-15 08:30",  90.0, "imbarcato",  None),  # id=29 → carta
            # --- Volo 11 (FR6000, futuro) ---
            ( 9, 11, "CD6000", "2026-05-18 11:00",  49.0, "pagata",     None),  # id=30
            (10, 11, "EF6000", "2026-05-18 11:30",  49.0, "prenotata",  None),  # id=31
            # --- Volo 12 (EN3000, futuro, gate G1 — CONFLITTO con EN1234) ---
            (11, 12, "GH3000", "2026-05-19 09:00", 130.0, "pagata",     None),  # id=32
            (12, 12, "IJ3000", "2026-05-19 09:30", 130.0, "prenotata",  None),  # id=33
            # --- Volo 13 (ITA004, partito) ---
            (16, 13, "KL4000", "2026-05-01 10:00", 160.0, "imbarcato",  None),  # id=34 → carta
            (15, 13, "MN4000", "2026-05-01 10:30", 160.0, "imbarcato",  None),  # id=35 → carta
            # --- Volo 14 (FR7000, OGGI — cruscotto operatore) ---
            (17, 14, "OP7000", "2026-05-21 09:00",  75.0, "pagata",     None),  # id=36
            (19, 14, "QR7000", "2026-05-21 09:30",  75.0, "pagata",     None),  # id=37
            # --- Volo 15 (EN4000, 5 posti — QUASI COMPLETO: 4/5 prenotati) ---
            (20, 15, "ST4000", "2026-05-20 08:00",  85.0, "prenotata",  None),  # id=38
            (14, 15, "UV4000", "2026-05-20 08:30",  85.0, "pagata",     None),  # id=39
            ( 5, 15, "WX4000", "2026-05-20 09:00",  85.0, "prenotata",  None),  # id=40
            ( 6, 15, "YZ4000", "2026-05-20 09:30",  85.0, "prenotata",  None),  # id=41 → 4/5=1 libero
            # --- Volo 16 (ITA005, futuro gate NULL) ---
            (20, 16, "AA5000", "2026-05-22 10:00", 145.0, "pagata",     None),  # id=42
            (13, 16, "BB5000", "2026-05-22 10:30", 145.0, "prenotata",  None),  # id=43
        ]
    )

    # ── 6. Utenti (1 admin, 3 compagnie, 2 operatori, 20 passeggeri) ─────────
    # id: 1=admin, 2=cmp_airdolomiti, 3=cmp_ryanair, 4=cmp_ita,
    #     5=operatore1, 6=operatore2, 7-26=passeggeri 1-20
    conn.executemany(
        """INSERT INTO utenti
           (username, password_hash, ruolo, compagnia_id, passeggero_id, attivo)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [
            # Admin
            ("admin",               ph, "admin",      None, None, 1),  # id=1
            # Compagnie
            ("compagnia1",          ph, "compagnia",     1, None, 1),  # id=2  Air Dolomiti
            ("compagnia2",          ph, "compagnia",     2, None, 1),  # id=3  Ryanair
            ("compagnia3",          ph, "compagnia",     3, None, 1),  # id=4  ITA Airways
            # Operatori
            ("operatore1",          ph, "operatore",  None, None, 1),  # id=5
            ("operatore2",          ph, "operatore",  None, None, 1),  # id=6
            # Passeggeri (credenziali facili per i primi 4: mario.rossi/password ecc.)
            ("mario.rossi",         ph, "passeggero", None,  1,   1),  # id=7
            ("laura.bianchi",       ph, "passeggero", None,  2,   0),  # id=8  BLOCCATO
            ("giuseppe.verdi",      ph, "passeggero", None,  3,   1),  # id=9
            ("anna.ferrari",        ph, "passeggero", None,  4,   1),  # id=10
            ("luca.romano",         ph, "passeggero", None,  5,   1),  # id=11
            ("sofia.esposito",      ph, "passeggero", None,  6,   1),  # id=12
            ("marco.conti",         ph, "passeggero", None,  7,   1),  # id=13
            ("elena.ricci",         ph, "passeggero", None,  8,   1),  # id=14
            ("paolo.lombardi",      ph, "passeggero", None,  9,   1),  # id=15
            ("giulia.mancini",      ph, "passeggero", None, 10,   1),  # id=16
            ("francesco.bruno",     ph, "passeggero", None, 11,   1),  # id=17
            ("chiara.deluca",       ph, "passeggero", None, 12,   1),  # id=18
            ("roberto.galli",       ph, "passeggero", None, 13,   1),  # id=19
            ("valentina.marini",    ph, "passeggero", None, 14,   1),  # id=20
            ("andrea.moretti",      ph, "passeggero", None, 15,   1),  # id=21
            ("serena.costa",        ph, "passeggero", None, 16,   1),  # id=22
            ("matteo.ferretti",     ph, "passeggero", None, 17,   1),  # id=23
            ("alessia.pellegrini",  ph, "passeggero", None, 18,   1),  # id=24
            ("davide.caruso",       ph, "passeggero", None, 19,   1),  # id=25
            ("monica.santoro",      ph, "passeggero", None, 20,   1),  # id=26
        ]
    )

    # ── 7. Carte d'imbarco (11 carte: 5 online, 6 al banco) ──────────────────
    # operatore_id 5=operatore1, 6=operatore2; NULL=check-in online
    conn.executemany(
        """INSERT INTO carte_imbarco
           (prenotazione_id, numero_posto, gate_imbarco_id, data_emissione, operatore_id)
           VALUES (?, ?, ?, ?, ?)""",
        [
            # Volo 1 (EN1234, gate G1=id 1)
            ( 3, "10A",  1, "2026-05-31 18:00", None),  # online
            # Volo 2 (EN5678, gate G2=id 2)
            ( 5,  "5B",  2, "2026-05-20 07:00",    5),  # banco — operatore1
            # Volo 4 (FR3456, gate G2=id 2)
            (11,  "1C",  2, "2026-05-17 20:00",    5),  # banco — operatore1
            (12,  "2A",  2, "2026-05-17 20:30", None),  # online
            (13,  "3B",  2, "2026-05-17 21:00",    5),  # banco — operatore1
            # Volo 7 (ITA002, gate G1=id 1)
            (21, "14C",  1, "2026-04-14 20:00", None),  # online
            (22, "15A",  1, "2026-04-14 20:30",    6),  # banco — operatore2
            # Volo 10 (ITA003, gate G1=id 1)
            (28,  "7D",  1, "2026-04-19 19:00", None),  # online
            (29,  "8F",  1, "2026-04-19 19:30",    6),  # banco — operatore2
            # Volo 13 (ITA004, gate G4=id 4)
            (34,  "3C",  4, "2026-05-01 22:00", None),  # online
            (35,  "4A",  4, "2026-05-01 22:30",    5),  # banco — operatore1
        ]
    )

    # ── 8. Log di sistema (21 eventi rappresentativi) ────────────────────────
    conn.executemany(
        """INSERT INTO log (utente_id, azione, dettagli, timestamp)
           VALUES (?, ?, ?, ?)""",
        [
            # Login riusciti
            (1, "login_success", None,
             "2026-05-10 08:00:00"),
            (2, "login_success", None,
             "2026-05-10 09:00:00"),
            (7, "login_success", None,
             "2026-05-10 09:01:00"),
            # Creazione voli da compagnie
            (2, "creazione_volo", '{"volo_id": 1, "codice_volo": "EN1234"}',
             "2026-05-01 10:00:00"),
            (3, "creazione_volo", '{"volo_id": 3, "codice_volo": "FR9012"}',
             "2026-05-02 11:00:00"),
            (4, "creazione_volo", '{"volo_id": 6, "codice_volo": "ITA001"}',
             "2026-05-05 09:00:00"),
            # Prenotazioni passeggeri
            (7,  "prenotazione", '{"prenotazione_id": 1, "volo_id": 1}',
             "2026-05-10 09:05:00"),
            (8,  "prenotazione", '{"prenotazione_id": 2, "volo_id": 1}',
             "2026-05-10 09:32:00"),
            # Pagamenti
            (8,  "pagamento", '{"prenotazione_id": 2, "importo": 120.0}',
             "2026-05-10 09:35:00"),
            (11, "pagamento", '{"prenotazione_id": 6, "importo": 80.0}',
             "2026-05-11 08:35:00"),
            # Check-in online e al banco
            (9,  "checkin_online", '{"prenotazione_id": 3, "numero_posto": "10A"}',
             "2026-05-31 18:00:00"),
            (5,  "checkin_banco",  '{"prenotazione_id": 5, "numero_posto": "5B"}',
             "2026-05-20 07:00:00"),
            # Cancellazione con penale
            (12, "cancellazione_prenotazione", '{"prenotazione_id": 7, "penale": 8.0}',
             "2026-05-11 09:10:00"),
            # Login falliti (tentativi non autorizzati)
            (None, "login_failed", '{"tentativo_username": "admin123"}',
             "2026-05-12 10:30:00"),
            (None, "login_failed", '{"tentativo_username": "mario"}',
             "2026-05-13 14:20:00"),
            # Blocco utente da admin
            (1, "blocco_utente", '{"utente_id_target": 8}',
             "2026-05-15 11:00:00"),
            # Cambio stato gate da operatori
            (5, "cambio_stato_gate",
             '{"gate_id": 3, "stato_precedente": "libero", "nuovo_stato": "manutenzione"}',
             "2026-05-16 09:00:00"),
            (6, "cambio_stato_gate",
             '{"gate_id": 2, "stato_precedente": "libero", "nuovo_stato": "occupato"}',
             "2026-05-17 08:30:00"),
            # Valutazione volo completato
            (15, "valutazione", '{"prenotazione_id": 11, "valutazione": 4}',
             "2026-05-19 10:00:00"),
            # Modifica volo con aggiunta ritardo
            (3, "modifica_volo",
             '{"volo_id": 8, "codice_volo": "FR5000", "nuovo_stato": "programmato"}',
             "2026-05-18 11:00:00"),
            # Backup database
            (1, "backup", None,
             "2026-05-20 15:00:00"),
        ]
    )

    conn.commit()


# =============================================================================
# Decoratori per l'autenticazione
# =============================================================================

def login_required(f):
    """Restituisce 401 se l'utente non è autenticato."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if 'utente_id' not in session:
            return jsonify({"errore": "Autenticazione richiesta"}), 401
        return f(*args, **kwargs)
    return wrapper


def ruolo_richiesto(*ruoli):
    """Restituisce 401 se non autenticato, 403 se il ruolo non è ammesso."""
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            if 'utente_id' not in session:
                return jsonify({"errore": "Autenticazione richiesta"}), 401
            if session.get('ruolo') not in ruoli:
                return jsonify({"errore": f"Accesso riservato a: {', '.join(ruoli)}"}), 403
            return f(*args, **kwargs)
        return wrapper
    return decorator


# =============================================================================
# Route: health check e pagine template
# =============================================================================

@app.route('/')
def index():
    return render_template('home.html')


@app.route('/api/health')
def health():
    return jsonify({"status": "ok", "messaggio": "API Aeroporto attiva"})


@app.route('/login')
def pagina_login():
    if 'utente_id' in session:
        return redirect(url_for(f"dashboard_{session.get('ruolo', '')}"))
    return render_template('login.html')


@app.route('/dashboard/passeggero')
def dashboard_passeggero():
    if 'utente_id' not in session or session.get('ruolo') != 'passeggero':
        return redirect(url_for('pagina_login'))
    return render_template('dashboard_passeggero.html')


@app.route('/dashboard/compagnia')
def dashboard_compagnia():
    if 'utente_id' not in session or session.get('ruolo') != 'compagnia':
        return redirect(url_for('pagina_login'))
    return render_template('dashboard_compagnia.html')


@app.route('/dashboard/operatore')
def dashboard_operatore():
    if 'utente_id' not in session or session.get('ruolo') != 'operatore':
        return redirect(url_for('pagina_login'))
    return render_template('dashboard_operatore.html')


@app.route('/dashboard/admin')
def dashboard_admin():
    if 'utente_id' not in session or session.get('ruolo') != 'admin':
        return redirect(url_for('pagina_login'))
    return render_template('dashboard_admin.html')


# =============================================================================
# Route: autenticazione
# =============================================================================

@app.route('/api/login', methods=['POST'])
def login():
    """
    POST /api/login
    Body JSON: { "username": "...", "password": "..." }
    Controlla anche che l'account non sia bloccato (attivo = 0).
    """
    dati = request.get_json(silent=True) or {}
    username = dati.get('username', '').strip()
    password = dati.get('password', '')

    if not username or not password:
        return jsonify({"errore": "username e password obbligatori"}), 400

    utente = query_row("SELECT * FROM utenti WHERE username = ?", (username,))

    if not utente or not check_password_hash(utente['password_hash'], password):
        registra_log('login_failed', None, {'tentativo_username': username})
        return jsonify({"errore": "Credenziali non valide"}), 401

    # Controlla se l'account è bloccato
    if not utente.get('attivo', 1):
        registra_log('login_failed', utente['id'], {'motivo': 'account_bloccato'})
        return jsonify({"errore": "Account bloccato. Contattare l'amministratore."}), 403

    session['utente_id']     = utente['id']
    session['username']      = utente['username']
    session['ruolo']         = utente['ruolo']
    session['compagnia_id']  = utente['compagnia_id']
    session['passeggero_id'] = utente['passeggero_id']

    registra_log('login_success', utente['id'])

    return jsonify({
        "messaggio": f"Benvenuto, {utente['username']}!",
        "ruolo":     utente['ruolo'],
        "utente_id": utente['id'],
        "redirect":  f"/dashboard/{utente['ruolo']}",
    })


@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"messaggio": "Logout effettuato"})


@app.route('/api/registrazione', methods=['POST'])
def registrazione():
    """
    POST /api/registrazione
    Body JSON: { nome, cognome, documento, username, password }
    """
    dati = request.get_json(silent=True) or {}
    for campo in ['nome', 'cognome', 'documento', 'username', 'password']:
        if not dati.get(campo):
            return jsonify({"errore": f"Campo obbligatorio mancante: {campo}"}), 400

    if len(dati['password']) < 8:
        return jsonify({"errore": "La password deve essere di almeno 8 caratteri"}), 400

    if query_row("SELECT id FROM passeggeri WHERE documento = ?", (dati['documento'],)):
        return jsonify({"errore": "Documento già registrato"}), 409
    if query_row("SELECT id FROM utenti WHERE username = ?", (dati['username'],)):
        return jsonify({"errore": "Username già in uso"}), 409

    conn = get_db()
    try:
        conn.execute("BEGIN")
        cur_pass = conn.execute(
            "INSERT INTO passeggeri (nome, cognome, documento) VALUES (?, ?, ?)",
            (dati['nome'].strip(), dati['cognome'].strip(), dati['documento'].strip())
        )
        passeggero_id = cur_pass.lastrowid

        cur_utente = conn.execute(
            """INSERT INTO utenti (username, password_hash, ruolo, passeggero_id)
               VALUES (?, ?, 'passeggero', ?)""",
            (dati['username'].strip(), generate_password_hash(dati['password']), passeggero_id)
        )
        utente_id = cur_utente.lastrowid
        conn.commit()

        registra_log('registrazione', utente_id, {'username': dati['username']})

        return jsonify({"messaggio": "Registrazione completata", "passeggero_id": passeggero_id}), 201

    except sqlite3.IntegrityError as e:
        conn.rollback()
        return jsonify({"errore": f"Conflitto dati: {e}"}), 409
    except Exception:
        conn.rollback()
        return jsonify({"errore": "Errore interno durante la registrazione"}), 500
    finally:
        conn.close()


# =============================================================================
# Route: aeroporti e voli (pubbliche)
# =============================================================================

@app.route('/api/aeroporti')
def lista_aeroporti():
    return jsonify(query_rows("SELECT id, codice, nome, lat, lon FROM aeroporti ORDER BY codice"))


@app.route('/api/voli/attivi')
def voli_attivi():
    """GET /api/voli/attivi — voli programmato/partito con coordinate per la mappa."""
    voli = query_rows(
        """SELECT v.id, v.codice_volo, c.nome AS compagnia,
                  v.origine, v.destinazione, v.data_ora_partenza, v.data_ora_arrivo,
                  v.posti_totali, v.stato, v.prezzo_base,
                  v.posti_totali - COALESCE((
                      SELECT COUNT(*) FROM prenotazioni p
                      WHERE p.volo_id = v.id AND p.stato IN ('prenotata', 'pagata')
                  ), 0) AS posti_liberi,
                  ao.lat AS orig_lat, ao.lon AS orig_lon, ao.nome AS orig_nome,
                  ad.lat AS dest_lat, ad.lon AS dest_lon, ad.nome AS dest_nome
           FROM   voli v
           JOIN   compagnie_aeree c ON v.compagnia_id = c.id
           LEFT JOIN aeroporti ao   ON v.origine      = ao.codice
           LEFT JOIN aeroporti ad   ON v.destinazione = ad.codice
           WHERE  v.stato IN ('programmato', 'partito')
           ORDER BY v.data_ora_partenza"""
    )
    return jsonify(voli)


@app.route('/api/voli/search')
def cerca_voli():
    """GET /api/voli/search?origine=&destinazione=&data= — ricerca voli pubblica."""
    origine      = request.args.get('origine', '').strip().upper()
    destinazione = request.args.get('destinazione', '').strip().upper()
    data         = request.args.get('data', '').strip()

    sql = """
        SELECT v.id, v.codice_volo, c.nome AS compagnia, g.codice AS gate,
               v.origine, v.destinazione, v.data_ora_partenza, v.data_ora_arrivo,
               v.posti_totali, v.stato, v.prezzo_base,
               v.posti_totali - COALESCE((
                   SELECT COUNT(*) FROM prenotazioni p
                   WHERE p.volo_id = v.id AND p.stato IN ('prenotata', 'pagata')
               ), 0) AS posti_liberi,
               ao.lat AS orig_lat, ao.lon AS orig_lon, ao.nome AS orig_nome,
               ad.lat AS dest_lat, ad.lon AS dest_lon, ad.nome AS dest_nome
        FROM   voli v
        JOIN   compagnie_aeree c ON v.compagnia_id = c.id
        LEFT JOIN gate g         ON v.gate_id = g.id
        LEFT JOIN aeroporti ao   ON v.origine      = ao.codice
        LEFT JOIN aeroporti ad   ON v.destinazione = ad.codice
        WHERE  1=1
    """
    params = []
    if origine:
        sql += " AND v.origine = ?"
        params.append(origine)
    if destinazione:
        sql += " AND v.destinazione = ?"
        params.append(destinazione)
    if data:
        sql += " AND DATE(v.data_ora_partenza) = ?"
        params.append(data)
    sql += " ORDER BY v.data_ora_partenza"
    return jsonify(query_rows(sql, params))


@app.route('/api/voli/<int:volo_id>/posti')
@login_required
def volo_posti(volo_id):
    """
    GET /api/voli/<id>/posti
    Mappa dei posti liberi e occupati per il componente seat map.
    """
    volo = query_row("SELECT id, posti_totali FROM voli WHERE id = ?", (volo_id,))
    if not volo:
        return jsonify({"errore": "Volo non trovato"}), 404

    posti_totali = volo['posti_totali']
    righe        = (posti_totali + 5) // 6  # arrotondamento per eccesso su 6 colonne
    lettere      = ['A', 'B', 'C', 'D', 'E', 'F']

    # Genera tutti i posti teorici e taglia al numero reale
    tutti = [f"{r}{l}" for r in range(1, righe + 1) for l in lettere]
    tutti = tutti[:posti_totali]

    # Posti già assegnati nelle carte d'imbarco
    occupati_rows = query_rows(
        """SELECT ci.numero_posto FROM carte_imbarco ci
           JOIN prenotazioni p ON ci.prenotazione_id = p.id
           WHERE p.volo_id = ? AND ci.numero_posto IS NOT NULL""",
        (volo_id,)
    )
    posti_occupati = [r['numero_posto'] for r in occupati_rows if r['numero_posto']]
    posti_liberi   = [p for p in tutti if p not in posti_occupati]

    return jsonify({
        "posti_totali":      posti_totali,
        "righe":             righe,
        "lettere_per_riga":  lettere,
        "posti_occupati":    posti_occupati,
        "posti_liberi":      posti_liberi,
        "posti_liberi_count": len(posti_liberi),
    })


# =============================================================================
# Route: area PASSEGGERO — prenotazioni
# =============================================================================

@app.route('/api/prenota', methods=['POST'])
@ruolo_richiesto('passeggero')
def prenota():
    """
    POST /api/prenota
    Body JSON: { "volo_id": 1 }
    Il prezzo viene preso da prezzo_base del volo.
    """
    dati    = request.get_json(silent=True) or {}
    volo_id = dati.get('volo_id')
    if not volo_id:
        return jsonify({"errore": "volo_id obbligatorio"}), 400

    passeggero_id = session['passeggero_id']

    conn = get_db()
    try:
        conn.execute("BEGIN")

        volo = conn.execute("SELECT * FROM voli WHERE id = ?", (volo_id,)).fetchone()
        if not volo:
            conn.rollback()
            return jsonify({"errore": "Volo non trovato"}), 404
        if volo['stato'] != 'programmato':
            conn.rollback()
            return jsonify({"errore": f"Il volo è in stato '{volo['stato']}': non accetta prenotazioni"}), 400

        posti_occupati = conn.execute(
            "SELECT COUNT(*) FROM prenotazioni WHERE volo_id = ? AND stato IN ('prenotata', 'pagata')",
            (volo_id,)
        ).fetchone()[0]
        if posti_occupati >= volo['posti_totali']:
            conn.rollback()
            return jsonify({"errore": "Volo completo"}), 400

        esistente = conn.execute(
            "SELECT id FROM prenotazioni WHERE passeggero_id = ? AND volo_id = ? AND stato != 'cancellata'",
            (passeggero_id, volo_id)
        ).fetchone()
        if esistente:
            conn.rollback()
            return jsonify({"errore": "Hai già una prenotazione attiva su questo volo"}), 409

        # Usa il prezzo base del volo, non un valore passato dal client
        prezzo = float(volo['prezzo_base']) if volo['prezzo_base'] else 100.0
        pnr    = _genera_pnr_unico(conn)
        cur    = conn.execute(
            "INSERT INTO prenotazioni (passeggero_id, volo_id, codice_prenotazione, prezzo, stato) VALUES (?, ?, ?, ?, 'prenotata')",
            (passeggero_id, volo_id, pnr, prezzo)
        )
        prenotazione_id = cur.lastrowid
        conn.commit()

        registra_log('prenotazione', session['utente_id'],
                     {'prenotazione_id': prenotazione_id, 'volo_id': volo_id})

        return jsonify({
            "messaggio":           "Prenotazione effettuata con successo",
            "prenotazione_id":     prenotazione_id,
            "codice_prenotazione": pnr,
            "prezzo":              prezzo,
        }), 201

    except Exception as e:
        conn.rollback()
        return jsonify({"errore": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/mie_prenotazioni')
@ruolo_richiesto('passeggero')
def mie_prenotazioni():
    """GET /api/mie_prenotazioni — prenotazioni del passeggero loggato con carta d'imbarco."""
    passeggero_id = session['passeggero_id']
    prenotazioni = query_rows(
        """SELECT p.id, p.codice_prenotazione, p.data_prenotazione, p.prezzo,
                  p.stato, p.valutazione,
                  v.id AS volo_id, v.codice_volo, v.origine, v.destinazione,
                  v.data_ora_partenza, v.data_ora_arrivo, v.stato AS stato_volo,
                  v.orario_stimato, c.nome AS compagnia,
                  ci.numero_posto, ci.gate_imbarco_id,
                  ci.data_emissione AS data_carta_imbarco
           FROM   prenotazioni p
           JOIN   voli v            ON p.volo_id = v.id
           JOIN   compagnie_aeree c ON v.compagnia_id = c.id
           LEFT JOIN carte_imbarco ci ON ci.prenotazione_id = p.id
           WHERE  p.passeggero_id = ?
           ORDER BY v.data_ora_partenza""",
        (passeggero_id,)
    )
    return jsonify(prenotazioni)


@app.route('/api/paga/<int:prenotazione_id>', methods=['POST'])
@ruolo_richiesto('passeggero')
def paga(prenotazione_id):
    """
    POST /api/paga/<id>
    Scala i crediti del passeggero. Restituisce 400 se crediti insufficienti.
    """
    passeggero_id = session['passeggero_id']

    pren = query_row(
        "SELECT * FROM prenotazioni WHERE id = ? AND passeggero_id = ?",
        (prenotazione_id, passeggero_id)
    )
    if not pren:
        return jsonify({"errore": "Prenotazione non trovata"}), 404
    if pren['stato'] != 'prenotata':
        return jsonify({"errore": f"La prenotazione è in stato '{pren['stato']}' e non può essere pagata"}), 400

    passeggero = query_row("SELECT crediti FROM passeggeri WHERE id = ?", (passeggero_id,))
    crediti    = float(passeggero['crediti']) if passeggero else 0.0
    prezzo     = float(pren['prezzo'])

    if crediti < prezzo:
        return jsonify({
            "errore":               "Crediti insufficienti. Ricarica il tuo portafoglio.",
            "crediti_disponibili":  crediti,
            "prezzo":               prezzo,
        }), 400

    conn = get_db()
    try:
        conn.execute("BEGIN")
        conn.execute("UPDATE prenotazioni SET stato = 'pagata' WHERE id = ?", (prenotazione_id,))
        conn.execute("UPDATE passeggeri SET crediti = crediti - ? WHERE id = ?", (prezzo, passeggero_id))
        conn.commit()
    except Exception as e:
        conn.rollback()
        return jsonify({"errore": str(e)}), 500
    finally:
        conn.close()

    registra_log('pagamento', session['utente_id'],
                 {'prenotazione_id': prenotazione_id, 'importo': prezzo})

    nuovi = query_row("SELECT crediti FROM passeggeri WHERE id = ?", (passeggero_id,))

    # Recupera info volo per la ricevuta
    volo_info = query_row(
        """SELECT v.codice_volo, v.origine, v.destinazione, v.data_ora_partenza, c.nome AS compagnia
           FROM voli v JOIN compagnie_aeree c ON v.compagnia_id = c.id
           WHERE v.id = ?""",
        (pren['volo_id'],)
    )
    # ID transazione basato su prenotazione_id + timestamp ridotto
    ts_short = int(datetime.now().timestamp()) % 1000000
    transazione_id = f"TXN{prenotazione_id:06d}{ts_short:06d}"

    return jsonify({
        "messaggio":         "Pagamento completato",
        "nuovo_stato":       "pagata",
        "crediti_rimanenti": float(nuovi['crediti']),
        "ricevuta": {
            "transazione_id":      transazione_id,
            "codice_prenotazione": pren['codice_prenotazione'],
            "codice_volo":         volo_info['codice_volo']      if volo_info else '—',
            "origine":             volo_info['origine']          if volo_info else '—',
            "destinazione":        volo_info['destinazione']     if volo_info else '—',
            "data_ora_partenza":   volo_info['data_ora_partenza'] if volo_info else '—',
            "compagnia":           volo_info['compagnia']        if volo_info else '—',
            "prezzo":              prezzo,
            "data_pagamento":      datetime.now().strftime('%Y-%m-%d %H:%M'),
        },
    })


@app.route('/api/checkin_online/<int:prenotazione_id>', methods=['POST'])
@ruolo_richiesto('passeggero')
def checkin_online(prenotazione_id):
    """
    POST /api/checkin_online/<id>
    Body JSON opzionale: { "numero_posto": "14C" }
    Se numero_posto non fornito, assegna automaticamente il primo posto libero.
    """
    passeggero_id         = session['passeggero_id']
    dati                  = request.get_json(silent=True) or {}
    numero_posto_richiesto = (dati.get('numero_posto') or '').strip() or None

    pren = query_row(
        "SELECT * FROM prenotazioni WHERE id = ? AND passeggero_id = ?",
        (prenotazione_id, passeggero_id)
    )
    if not pren:
        return jsonify({"errore": "Prenotazione non trovata"}), 404
    if pren['stato'] != 'pagata':
        return jsonify({"errore": "Il check-in online richiede una prenotazione in stato 'pagata'"}), 400

    if query_row("SELECT id FROM carte_imbarco WHERE prenotazione_id = ?", (prenotazione_id,)):
        return jsonify({"errore": "Carta d'imbarco già emessa per questa prenotazione"}), 409

    volo = query_row("SELECT * FROM voli WHERE id = ?", (pren['volo_id'],))

    conn = get_db()
    try:
        conn.execute("BEGIN")

        if numero_posto_richiesto:
            # Verifica che il posto richiesto sia libero
            occupati = {r[0] for r in conn.execute(
                """SELECT ci.numero_posto FROM carte_imbarco ci
                   JOIN prenotazioni p ON ci.prenotazione_id = p.id
                   WHERE p.volo_id = ? AND ci.numero_posto IS NOT NULL""",
                (volo['id'],)
            ).fetchall()}
            if numero_posto_richiesto in occupati:
                conn.rollback()
                return jsonify({"errore": f"Il posto {numero_posto_richiesto} è già occupato"}), 409
            posto = numero_posto_richiesto
        else:
            posto = _genera_posto(conn, volo['id'], volo['posti_totali'])

        cur = conn.execute(
            "INSERT INTO carte_imbarco (prenotazione_id, numero_posto, gate_imbarco_id, operatore_id) VALUES (?, ?, ?, NULL)",
            (prenotazione_id, posto, volo['gate_id'])
        )
        carta_id = cur.lastrowid
        conn.execute("UPDATE prenotazioni SET stato = 'imbarcato' WHERE id = ?", (prenotazione_id,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        return jsonify({"errore": str(e)}), 500
    finally:
        conn.close()

    registra_log('checkin_online', session['utente_id'],
                 {'prenotazione_id': prenotazione_id, 'numero_posto': posto})

    return jsonify({
        "messaggio":        "Check-in online completato",
        "carta_imbarco_id": carta_id,
        "numero_posto":     posto,
        "gate_imbarco_id":  volo['gate_id'],
    })


@app.route('/api/cancella/<int:prenotazione_id>', methods=['POST'])
@ruolo_richiesto('passeggero')
def cancella_prenotazione(prenotazione_id):
    """
    POST /api/cancella/<id>
    Cancella una prenotazione in stato 'prenotata'. Applica una penale del 10%.
    """
    passeggero_id = session['passeggero_id']

    pren = query_row(
        "SELECT * FROM prenotazioni WHERE id = ? AND passeggero_id = ?",
        (prenotazione_id, passeggero_id)
    )
    if not pren:
        return jsonify({"errore": "Prenotazione non trovata"}), 404
    if pren['stato'] != 'prenotata':
        return jsonify({
            "errore": f"Non è possibile cancellare una prenotazione in stato '{pren['stato']}'. "
                      "Solo le prenotazioni in stato 'prenotata' possono essere cancellate."
        }), 400

    # Penale del 10% del prezzo (i crediti possono diventare negativi)
    penale = round(float(pren['prezzo']) * 0.10, 2)

    conn = get_db()
    try:
        conn.execute("BEGIN")
        conn.execute("UPDATE prenotazioni SET stato = 'cancellata' WHERE id = ?", (prenotazione_id,))
        conn.execute("UPDATE passeggeri SET crediti = crediti - ? WHERE id = ?", (penale, passeggero_id))
        conn.commit()
    except Exception as e:
        conn.rollback()
        return jsonify({"errore": str(e)}), 500
    finally:
        conn.close()

    registra_log('cancellazione_prenotazione', session['utente_id'],
                 {'prenotazione_id': prenotazione_id, 'penale': penale})

    return jsonify({"status": "ok", "messaggio": "Prenotazione cancellata", "penale_applicata": penale})


# =============================================================================
# Route: area PASSEGGERO — storico, valutazioni, crediti, profilo
# =============================================================================

@app.route('/api/passeggero/storico')
@ruolo_richiesto('passeggero')
def passeggero_storico():
    """GET /api/passeggero/storico — viaggi completati (imbarcato + volo arrivato)."""
    passeggero_id = session['passeggero_id']
    viaggi = query_rows(
        """SELECT p.id AS prenotazione_id, p.codice_prenotazione, p.prezzo, p.valutazione,
                  v.codice_volo, c.nome AS compagnia, v.origine, v.destinazione,
                  v.data_ora_partenza, v.data_ora_arrivo,
                  ci.numero_posto
           FROM   prenotazioni p
           JOIN   voli v            ON p.volo_id = v.id
           JOIN   compagnie_aeree c ON v.compagnia_id = c.id
           LEFT JOIN carte_imbarco ci ON ci.prenotazione_id = p.id
           WHERE  p.passeggero_id = ? AND p.stato = 'imbarcato' AND v.stato = 'arrivato'
           ORDER BY v.data_ora_partenza DESC""",
        (passeggero_id,)
    )
    return jsonify(viaggi)


@app.route('/api/passeggero/valuta/<int:prenotazione_id>', methods=['POST'])
@ruolo_richiesto('passeggero')
def passeggero_valuta(prenotazione_id):
    """POST /api/passeggero/valuta/<id> — Body: { "valutazione": 1-5 }"""
    dati       = request.get_json(silent=True) or {}
    valutazione = dati.get('valutazione')

    if not isinstance(valutazione, int) or not (1 <= valutazione <= 5):
        return jsonify({"errore": "Valutazione deve essere un intero da 1 a 5"}), 400

    passeggero_id = session['passeggero_id']
    pren = query_row(
        """SELECT p.*, v.stato AS stato_volo FROM prenotazioni p
           JOIN voli v ON p.volo_id = v.id
           WHERE p.id = ? AND p.passeggero_id = ?""",
        (prenotazione_id, passeggero_id)
    )
    if not pren:
        return jsonify({"errore": "Prenotazione non trovata"}), 404
    if pren['stato'] != 'imbarcato' or pren['stato_volo'] != 'arrivato':
        return jsonify({"errore": "Puoi valutare solo voli completati (imbarcato + volo arrivato)"}), 400
    if pren['valutazione'] is not None:
        return jsonify({"errore": "Hai già valutato questo volo"}), 400

    db_execute("UPDATE prenotazioni SET valutazione = ? WHERE id = ?", (valutazione, prenotazione_id))
    registra_log('valutazione', session['utente_id'],
                 {'prenotazione_id': prenotazione_id, 'valutazione': valutazione})

    return jsonify({"messaggio": "Valutazione inviata, grazie!", "valutazione": valutazione})


@app.route('/api/passeggero/crediti')
@ruolo_richiesto('passeggero')
def passeggero_crediti():
    """GET /api/passeggero/crediti — saldo del portafoglio virtuale."""
    p = query_row("SELECT crediti FROM passeggeri WHERE id = ?", (session['passeggero_id'],))
    return jsonify({"crediti": float(p['crediti']) if p else 0.0})


@app.route('/api/passeggero/ricarica', methods=['POST'])
@ruolo_richiesto('passeggero')
def passeggero_ricarica():
    """POST /api/passeggero/ricarica — Body: { "importo": 100.0 }. Simulazione ricarica."""
    dati = request.get_json(silent=True) or {}
    try:
        importo = float(dati.get('importo', 0))
        if importo <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"errore": "Importo deve essere un numero positivo"}), 400

    db_execute(
        "UPDATE passeggeri SET crediti = crediti + ? WHERE id = ?",
        (importo, session['passeggero_id'])
    )
    p = query_row("SELECT crediti FROM passeggeri WHERE id = ?", (session['passeggero_id'],))
    registra_log('ricarica_crediti', session['utente_id'], {'importo': importo})

    return jsonify({"status": "ok", "crediti": float(p['crediti'])})


@app.route('/api/passeggero/profilo', methods=['GET'])
@ruolo_richiesto('passeggero')
def leggi_profilo():
    """GET /api/passeggero/profilo — dati anagrafici e credenziali (no password)."""
    passeggero = query_row(
        "SELECT nome, cognome, documento, crediti FROM passeggeri WHERE id = ?",
        (session['passeggero_id'],)
    )
    utente = query_row("SELECT username FROM utenti WHERE id = ?", (session['utente_id'],))
    if not passeggero or not utente:
        return jsonify({"errore": "Profilo non trovato"}), 404

    return jsonify({
        "nome":      passeggero['nome'],
        "cognome":   passeggero['cognome'],
        "documento": passeggero['documento'],
        "username":  utente['username'],
        "crediti":   float(passeggero['crediti']),
    })


@app.route('/api/passeggero/profilo', methods=['PUT'])
@ruolo_richiesto('passeggero')
def modifica_profilo():
    """
    PUT /api/passeggero/profilo
    Body JSON: { nome?, cognome?, documento?, username?,
                 password_attuale?, nuova_password?, conferma_password? }
    """
    passeggero_id = session['passeggero_id']
    utente_id     = session['utente_id']
    dati          = request.get_json(silent=True) or {}

    passeggero = query_row("SELECT * FROM passeggeri WHERE id = ?", (passeggero_id,))
    utente     = query_row("SELECT * FROM utenti WHERE id = ?", (utente_id,))
    if not passeggero or not utente:
        return jsonify({"errore": "Profilo non trovato"}), 404

    # ── Dati anagrafici ──────────────────────────────────────────────────────
    nome      = (dati.get('nome')      or passeggero['nome']).strip()
    cognome   = (dati.get('cognome')   or passeggero['cognome']).strip()
    documento = (dati.get('documento') or passeggero['documento']).strip()

    if not nome or not cognome or not documento:
        return jsonify({"errore": "Nome, cognome e documento non possono essere vuoti"}), 400

    if documento != passeggero['documento']:
        if query_row("SELECT id FROM passeggeri WHERE documento = ? AND id != ?",
                     (documento, passeggero_id)):
            return jsonify({"errore": "Documento già in uso da un altro passeggero"}), 409

    db_execute(
        "UPDATE passeggeri SET nome = ?, cognome = ?, documento = ? WHERE id = ?",
        (nome, cognome, documento, passeggero_id)
    )

    # ── Username ─────────────────────────────────────────────────────────────
    nuovo_username = (dati.get('username') or '').strip()
    if nuovo_username and nuovo_username != utente['username']:
        if query_row("SELECT id FROM utenti WHERE username = ? AND id != ?",
                     (nuovo_username, utente_id)):
            return jsonify({"errore": "Username già in uso da un altro utente"}), 409
        db_execute("UPDATE utenti SET username = ? WHERE id = ?", (nuovo_username, utente_id))
        session['username'] = nuovo_username

    # ── Password ─────────────────────────────────────────────────────────────
    nuova_password    = (dati.get('nuova_password')    or '').strip()
    conferma_password = (dati.get('conferma_password') or '').strip()
    password_attuale  = (dati.get('password_attuale')  or '').strip()

    if nuova_password:
        if not password_attuale:
            return jsonify({"errore": "Inserisci la password attuale per cambiarla"}), 400
        if not check_password_hash(utente['password_hash'], password_attuale):
            return jsonify({"errore": "Password attuale non corretta"}), 401
        if nuova_password != conferma_password:
            return jsonify({"errore": "La nuova password e la conferma non coincidono"}), 400
        if len(nuova_password) < 8:
            return jsonify({"errore": "La password deve essere di almeno 8 caratteri"}), 400
        db_execute("UPDATE utenti SET password_hash = ? WHERE id = ?",
                   (generate_password_hash(nuova_password), utente_id))

    registra_log('modifica_profilo', utente_id)

    return jsonify({
        "messaggio": "Profilo aggiornato",
        "nome":      nome,
        "cognome":   cognome,
        "documento": documento,
        "username":  session['username'],
    })


# =============================================================================
# Route: area COMPAGNIA
# =============================================================================

@app.route('/api/compagnia/voli', methods=['GET'])
@ruolo_richiesto('compagnia')
def compagnia_lista_voli():
    """GET /api/compagnia/voli — voli della compagnia con posti liberi e warning gate."""
    compagnia_id = session['compagnia_id']
    voli = query_rows(
        """SELECT v.id, v.codice_volo, v.origine, v.destinazione,
                  v.data_ora_partenza, v.data_ora_arrivo,
                  v.posti_totali, v.stato, v.prezzo_base,
                  v.orario_stimato, v.ritardo_note,
                  v.gate_id, g.codice AS gate,
                  v.posti_totali - COALESCE((
                      SELECT COUNT(*) FROM prenotazioni p
                      WHERE p.volo_id = v.id AND p.stato IN ('prenotata', 'pagata')
                  ), 0) AS posti_liberi
           FROM   voli v
           LEFT JOIN gate g ON v.gate_id = g.id
           WHERE  v.compagnia_id = ?
           ORDER BY v.data_ora_partenza""",
        (compagnia_id,)
    )
    voli = _calcola_warning_gate(voli)
    return jsonify(voli)


@app.route('/api/compagnia/voli', methods=['POST'])
@ruolo_richiesto('compagnia')
def compagnia_crea_volo():
    """
    POST /api/compagnia/voli
    Body JSON: { codice_volo, origine, destinazione,
                 data_ora_partenza, data_ora_arrivo, posti_totali,
                 gate_id?, prezzo_base? }
    """
    dati = request.get_json(silent=True) or {}
    for campo in ['codice_volo', 'origine', 'destinazione', 'data_ora_partenza',
                  'data_ora_arrivo', 'posti_totali']:
        if dati.get(campo) is None:
            return jsonify({"errore": f"Campo obbligatorio mancante: {campo}"}), 400

    try:
        posti = int(dati['posti_totali'])
        if posti <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"errore": "posti_totali deve essere un intero positivo"}), 400

    try:
        prezzo_base = float(dati.get('prezzo_base') or 100.0)
        if prezzo_base < 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"errore": "prezzo_base deve essere un numero non negativo"}), 400

    compagnia_id = session['compagnia_id']
    try:
        volo_id = db_execute(
            """INSERT INTO voli
               (codice_volo, compagnia_id, gate_id, origine, destinazione,
                data_ora_partenza, data_ora_arrivo, posti_totali, stato, prezzo_base)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'programmato', ?)""",
            (
                dati['codice_volo'].strip().upper(),
                compagnia_id,
                dati.get('gate_id'),
                dati['origine'].strip().upper(),
                dati['destinazione'].strip().upper(),
                dati['data_ora_partenza'].strip(),
                dati['data_ora_arrivo'].strip(),
                posti,
                prezzo_base,
            )
        )
        registra_log('creazione_volo', session['utente_id'],
                     {'volo_id': volo_id, 'codice_volo': dati['codice_volo'].strip().upper()})
        return jsonify({"messaggio": "Volo creato", "volo_id": volo_id}), 201

    except sqlite3.IntegrityError:
        return jsonify({"errore": "Codice volo già esistente"}), 409


@app.route('/api/compagnia/voli/<int:id>', methods=['DELETE'])
@ruolo_richiesto('compagnia')
def compagnia_elimina_volo(id):
    """DELETE /api/compagnia/voli/<id> — solo voli programmato senza prenotazioni attive."""
    compagnia_id = session['compagnia_id']
    volo = query_row("SELECT * FROM voli WHERE id = ? AND compagnia_id = ?", (id, compagnia_id))
    if not volo:
        return jsonify({"errore": "Volo non trovato o non appartenente alla tua compagnia"}), 404
    if volo['stato'] != 'programmato':
        return jsonify({"errore": f"Il volo è in stato '{volo['stato']}': solo i voli programmato sono eliminabili"}), 400

    attive = query_row(
        "SELECT COUNT(*) AS n FROM prenotazioni WHERE volo_id = ? AND stato IN ('prenotata', 'pagata')",
        (id,)
    )
    if attive['n'] > 0:
        return jsonify({"errore": f"Il volo ha {attive['n']} prenotazione/i attiva/e. Impossibile eliminarlo."}), 409

    db_execute("DELETE FROM voli WHERE id = ?", (id,))
    registra_log('eliminazione_volo', session['utente_id'],
                 {'volo_id': id, 'codice_volo': volo['codice_volo']})
    return jsonify({"messaggio": f"Volo {volo['codice_volo']} eliminato"})


@app.route('/api/compagnia/voli/<int:id>', methods=['PUT'])
@ruolo_richiesto('compagnia')
def compagnia_modifica_volo(id):
    """
    PUT /api/compagnia/voli/<id>
    Body JSON: { gate_id?, data_ora_partenza?, data_ora_arrivo?, posti_totali?,
                 stato?, prezzo_base?, orario_stimato?, ritardo_note? }
    """
    compagnia_id = session['compagnia_id']
    volo = query_row("SELECT * FROM voli WHERE id = ? AND compagnia_id = ?", (id, compagnia_id))
    if not volo:
        return jsonify({"errore": "Volo non trovato o non appartenente alla tua compagnia"}), 404

    dati = request.get_json(silent=True) or {}

    nuovo_stato = dati.get('stato', volo['stato'])
    if nuovo_stato not in ('programmato', 'partito', 'arrivato'):
        return jsonify({"errore": "Stato non valido. Valori ammessi: programmato, partito, arrivato"}), 400

    try:
        nuovi_posti = int(dati.get('posti_totali', volo['posti_totali']))
        if nuovi_posti <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"errore": "posti_totali deve essere un intero positivo"}), 400

    try:
        nuovo_prezzo = float(dati.get('prezzo_base', volo['prezzo_base'] or 100.0))
        if nuovo_prezzo < 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"errore": "prezzo_base deve essere un numero non negativo"}), 400

    # orario_stimato e ritardo_note solo per voli programmato
    orario_stimato = dati.get('orario_stimato', volo.get('orario_stimato'))
    ritardo_note   = dati.get('ritardo_note',   volo.get('ritardo_note'))

    # Quando il volo parte o arriva, azzera il ritardo
    if nuovo_stato in ('partito', 'arrivato'):
        orario_stimato = None
        ritardo_note   = None

    db_execute(
        """UPDATE voli
           SET gate_id           = ?,
               data_ora_partenza = ?,
               data_ora_arrivo   = ?,
               posti_totali      = ?,
               stato             = ?,
               prezzo_base       = ?,
               orario_stimato    = ?,
               ritardo_note      = ?
           WHERE id = ?""",
        (
            dati.get('gate_id', volo['gate_id']),
            dati.get('data_ora_partenza', volo['data_ora_partenza']),
            dati.get('data_ora_arrivo',   volo['data_ora_arrivo']),
            nuovi_posti,
            nuovo_stato,
            nuovo_prezzo,
            orario_stimato,
            ritardo_note,
            id,
        )
    )
    registra_log('modifica_volo', session['utente_id'],
                 {'volo_id': id, 'codice_volo': volo['codice_volo'], 'nuovo_stato': nuovo_stato})
    return jsonify({"messaggio": "Volo aggiornato"})


@app.route('/api/compagnia/voli/<int:id>/passeggeri')
@ruolo_richiesto('compagnia')
def compagnia_passeggeri_volo(id):
    """GET /api/compagnia/voli/<id>/passeggeri — passeggeri prenotati sul volo."""
    compagnia_id = session['compagnia_id']

    # Verifica appartenenza del volo alla compagnia loggata
    if not query_row("SELECT id FROM voli WHERE id = ? AND compagnia_id = ?", (id, compagnia_id)):
        return jsonify({"errore": "Volo non trovato o non appartenente alla tua compagnia"}), 404

    passeggeri = query_rows(
        """SELECT p.id AS prenotazione_id, pass.id AS passeggero_id,
                  pass.nome, pass.cognome, pass.documento,
                  p.stato AS stato_prenotazione,
                  p.codice_prenotazione,
                  ci.numero_posto
           FROM   prenotazioni p
           JOIN   passeggeri pass ON p.passeggero_id = pass.id
           LEFT JOIN carte_imbarco ci ON ci.prenotazione_id = p.id
           WHERE  p.volo_id = ?
           ORDER BY pass.cognome, pass.nome""",
        (id,)
    )
    return jsonify(passeggeri)


# =============================================================================
# Route: area OPERATORE
# =============================================================================

@app.route('/api/operatore/gate')
@ruolo_richiesto('operatore')
def operatore_gate():
    """GET /api/operatore/gate — stato di tutti i gate con voli assegnati."""
    gate = query_rows(
        """SELECT g.id, g.codice, g.stato,
                  GROUP_CONCAT(v.codice_volo, ', ') AS voli_assegnati
           FROM   gate g
           LEFT JOIN voli v ON v.gate_id = g.id AND v.stato != 'arrivato'
           GROUP BY g.id
           ORDER BY g.codice"""
    )
    return jsonify(gate)


@app.route('/api/operatore/gate/<int:id>', methods=['PUT'])
@ruolo_richiesto('operatore')
def operatore_modifica_gate(id):
    """PUT /api/operatore/gate/<id> — Body: { "stato": "libero"|"occupato"|"manutenzione" }"""
    dati        = request.get_json(silent=True) or {}
    nuovo_stato = dati.get('stato', '').strip()

    if nuovo_stato not in ('libero', 'occupato', 'manutenzione'):
        return jsonify({"errore": "stato non valido. Valori ammessi: libero, occupato, manutenzione"}), 400

    gate = query_row("SELECT * FROM gate WHERE id = ?", (id,))
    if not gate:
        return jsonify({"errore": "Gate non trovato"}), 404

    db_execute("UPDATE gate SET stato = ? WHERE id = ?", (nuovo_stato, id))
    registra_log('cambio_stato_gate', session['utente_id'],
                 {'gate_id': id, 'stato_precedente': gate['stato'], 'nuovo_stato': nuovo_stato})
    return jsonify({"messaggio": f"Gate aggiornato a '{nuovo_stato}'"})


@app.route('/api/operatore/voli')
@ruolo_richiesto('operatore')
def operatore_voli_oggi():
    """GET /api/operatore/voli?data=YYYY-MM-DD — cruscotto voli per data (default: oggi)."""
    data = request.args.get('data', datetime.now().strftime('%Y-%m-%d')).strip()

    voli = query_rows(
        """SELECT v.id, v.codice_volo, c.nome AS compagnia_nome,
                  v.origine, v.destinazione, v.data_ora_partenza, v.data_ora_arrivo,
                  v.orario_stimato, v.stato AS stato_volo,
                  g.codice AS gate_codice, g.stato AS gate_stato,
                  v.posti_totali,
                  COALESCE((
                      SELECT COUNT(*) FROM prenotazioni p
                      WHERE p.volo_id = v.id AND p.stato IN ('pagata', 'imbarcato')
                  ), 0) AS posti_occupati
           FROM   voli v
           JOIN   compagnie_aeree c ON v.compagnia_id = c.id
           LEFT JOIN gate g         ON v.gate_id = g.id
           WHERE  DATE(v.data_ora_partenza) = ?
           ORDER BY v.data_ora_partenza""",
        (data,)
    )
    for v in voli:
        if v['posti_totali'] > 0:
            v['percentuale_occupazione'] = round(v['posti_occupati'] / v['posti_totali'] * 100, 1)
        else:
            v['percentuale_occupazione'] = 0
    return jsonify(voli)


@app.route('/api/operatore/checkin', methods=['POST'])
@ruolo_richiesto('operatore')
def operatore_checkin():
    """
    POST /api/operatore/checkin
    Ricerca per: documento | codice_prenotazione | nome+cognome
    - documento: comportamento originale (legacy)
    - codice_prenotazione o nome+cognome: restituisce risultati per la selezione
    """
    dati                = request.get_json(silent=True) or {}
    documento           = dati.get('documento', '').strip()
    codice_prenotazione = dati.get('codice_prenotazione', '').strip()
    nome                = dati.get('nome', '').strip()
    cognome             = dati.get('cognome', '').strip()
    prenotazione_id     = dati.get('prenotazione_id')

    # ── Ricerca per PNR ──────────────────────────────────────────────────────
    if codice_prenotazione:
        pren = query_row(
            """SELECT p.id, p.codice_prenotazione, p.volo_id,
                      v.codice_volo, v.origine, v.destinazione, v.data_ora_partenza,
                      v.posti_totali, v.gate_id,
                      pass.nome AS passeggero_nome, pass.cognome AS passeggero_cognome,
                      pass.documento
               FROM   prenotazioni p
               JOIN   voli v       ON p.volo_id = v.id
               JOIN   passeggeri pass ON p.passeggero_id = pass.id
               LEFT JOIN carte_imbarco ci ON ci.prenotazione_id = p.id
               WHERE  p.codice_prenotazione = ? AND p.stato = 'pagata' AND ci.id IS NULL""",
            (codice_prenotazione.upper(),)
        )
        if not pren:
            return jsonify({"errore": "Prenotazione non trovata o non in stato 'pagata'"}), 404
        return jsonify({"prenotazioni_disponibili": [pren]})

    # ── Ricerca per nome + cognome ───────────────────────────────────────────
    if nome and cognome:
        risultati = query_rows(
            """SELECT p.id, p.codice_prenotazione, p.volo_id,
                      v.codice_volo, v.origine, v.destinazione, v.data_ora_partenza,
                      v.posti_totali, v.gate_id,
                      pass.nome AS passeggero_nome, pass.cognome AS passeggero_cognome,
                      pass.documento
               FROM   prenotazioni p
               JOIN   voli v       ON p.volo_id = v.id
               JOIN   passeggeri pass ON p.passeggero_id = pass.id
               LEFT JOIN carte_imbarco ci ON ci.prenotazione_id = p.id
               WHERE  LOWER(pass.nome) = LOWER(?) AND LOWER(pass.cognome) = LOWER(?)
                 AND  p.stato = 'pagata' AND ci.id IS NULL
               ORDER BY v.data_ora_partenza""",
            (nome, cognome)
        )
        if not risultati:
            return jsonify({"errore": "Nessuna prenotazione pagata trovata per questo passeggero"}), 404
        return jsonify({"prenotazioni_disponibili": risultati})

    # ── Ricerca per documento ─────────────────────────────────────────────────
    if not documento:
        return jsonify({"errore": "Fornire documento, codice_prenotazione oppure nome e cognome"}), 400

    passeggero = query_row("SELECT * FROM passeggeri WHERE documento = ?", (documento,))
    if not passeggero:
        return jsonify({"errore": "Nessun passeggero trovato con questo documento"}), 404

    prenotazioni_idonee = query_rows(
        """SELECT p.id, p.codice_prenotazione, p.volo_id,
                  v.codice_volo, v.origine, v.destinazione, v.data_ora_partenza,
                  v.posti_totali, v.gate_id,
                  pass.nome AS passeggero_nome, pass.cognome AS passeggero_cognome,
                  pass.documento
           FROM   prenotazioni p
           JOIN   voli v          ON p.volo_id = v.id
           JOIN   passeggeri pass ON p.passeggero_id = pass.id
           LEFT JOIN carte_imbarco ci ON ci.prenotazione_id = p.id
           WHERE  p.passeggero_id = ? AND p.stato = 'pagata' AND ci.id IS NULL
           ORDER BY v.data_ora_partenza""",
        (passeggero['id'],)
    )
    if not prenotazioni_idonee:
        return jsonify({"errore": "Nessuna prenotazione 'pagata' senza carta d'imbarco trovata"}), 404

    return jsonify({"prenotazioni_disponibili": prenotazioni_idonee})


@app.route('/api/operatore/checkin/exec', methods=['POST'])
@ruolo_richiesto('operatore')
def operatore_checkin_exec():
    """
    POST /api/operatore/checkin/exec
    Body JSON: { prenotazione_id, numero_posto, gate_id? }
    Esegue il check-in con il posto scelto dalla seat map.
    """
    dati             = request.get_json(silent=True) or {}
    prenotazione_id  = dati.get('prenotazione_id')
    numero_posto     = (dati.get('numero_posto') or '').strip() or None
    gate_imbarco_id  = dati.get('gate_id')

    if not prenotazione_id:
        return jsonify({"errore": "prenotazione_id obbligatorio"}), 400

    pren = query_row(
        """SELECT p.*, v.posti_totali, v.gate_id AS volo_gate_id
           FROM prenotazioni p JOIN voli v ON p.volo_id = v.id
           WHERE p.id = ? AND p.stato = 'pagata'""",
        (prenotazione_id,)
    )
    if not pren:
        return jsonify({"errore": "Prenotazione non trovata o non in stato 'pagata'"}), 404

    if query_row("SELECT id FROM carte_imbarco WHERE prenotazione_id = ?", (prenotazione_id,)):
        return jsonify({"errore": "Carta d'imbarco già emessa"}), 409

    operatore_id = session['utente_id']
    gate_id      = gate_imbarco_id if gate_imbarco_id else pren['volo_gate_id']

    conn = get_db()
    try:
        conn.execute("BEGIN")
        if not numero_posto:
            numero_posto = _genera_posto(conn, pren['volo_id'], pren['posti_totali'])
        cur = conn.execute(
            "INSERT INTO carte_imbarco (prenotazione_id, numero_posto, gate_imbarco_id, operatore_id) VALUES (?, ?, ?, ?)",
            (prenotazione_id, numero_posto, gate_id, operatore_id)
        )
        carta_id = cur.lastrowid
        conn.execute("UPDATE prenotazioni SET stato = 'imbarcato' WHERE id = ?", (prenotazione_id,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        return jsonify({"errore": str(e)}), 500
    finally:
        conn.close()

    registra_log('checkin_banco', operatore_id,
                 {'prenotazione_id': prenotazione_id, 'numero_posto': numero_posto})

    # Recupera nome passeggero per il messaggio di conferma
    pass_row = query_row(
        """SELECT pas.nome || ' ' || pas.cognome AS nominativo
           FROM prenotazioni pr JOIN passeggeri pas ON pr.passeggero_id = pas.id
           WHERE pr.id = ?""",
        (prenotazione_id,)
    )

    return jsonify({
        "messaggio":        "Check-in completato",
        "carta_imbarco_id": carta_id,
        "numero_posto":     numero_posto,
        "gate_imbarco_id":  gate_id,
        "passeggero":       pass_row['nominativo'] if pass_row else '',
    }), 201


# =============================================================================
# Route: area ADMIN
# =============================================================================

@app.route('/api/admin/stats')
@ruolo_richiesto('admin')
def admin_stats():
    """GET /api/admin/stats — statistiche aggregate del sistema."""
    stats = {
        "voli": {
            "totale":    query_row("SELECT COUNT(*) AS n FROM voli")['n'],
            "per_stato": query_rows("SELECT stato, COUNT(*) AS numero FROM voli GROUP BY stato ORDER BY stato"),
        },
        "prenotazioni": {
            "totale":    query_row("SELECT COUNT(*) AS n FROM prenotazioni")['n'],
            "per_stato": query_rows("SELECT stato, COUNT(*) AS numero FROM prenotazioni GROUP BY stato ORDER BY stato"),
        },
        "passeggeri":   query_row("SELECT COUNT(*) AS n FROM passeggeri")['n'],
        "compagnie":    query_row("SELECT COUNT(*) AS n FROM compagnie_aeree")['n'],
        "gate": {
            "totale":    query_row("SELECT COUNT(*) AS n FROM gate")['n'],
            "per_stato": query_rows("SELECT stato, COUNT(*) AS numero FROM gate GROUP BY stato ORDER BY stato"),
        },
        "carte_imbarco": query_row("SELECT COUNT(*) AS n FROM carte_imbarco")['n'],
    }
    return jsonify(stats)


@app.route('/api/admin/voli')
@ruolo_richiesto('admin')
def admin_storico_voli():
    """GET /api/admin/voli?stato=&compagnia_id=&data= — storico voli con filtri."""
    stato        = request.args.get('stato', '').strip()
    compagnia_id = request.args.get('compagnia_id', '').strip()
    data         = request.args.get('data', '').strip()

    sql = """
        SELECT v.id, v.codice_volo, c.nome AS compagnia, c.id AS compagnia_id,
               g.codice AS gate, v.origine, v.destinazione,
               v.data_ora_partenza, v.data_ora_arrivo, v.posti_totali, v.stato,
               COALESCE((
                   SELECT COUNT(*) FROM prenotazioni p
                   WHERE p.volo_id = v.id AND p.stato IN ('prenotata', 'pagata', 'imbarcato')
               ), 0) AS posti_occupati
        FROM   voli v
        JOIN   compagnie_aeree c ON v.compagnia_id = c.id
        LEFT JOIN gate g         ON v.gate_id = g.id
        WHERE  1=1
    """
    params = []
    if stato:
        sql += " AND v.stato = ?"
        params.append(stato)
    if compagnia_id:
        sql += " AND v.compagnia_id = ?"
        params.append(int(compagnia_id))
    if data:
        sql += " AND DATE(v.data_ora_partenza) = ?"
        params.append(data)
    sql += " ORDER BY v.data_ora_partenza DESC"
    return jsonify(query_rows(sql, params))


@app.route('/api/admin/aeroporti', methods=['POST'])
@ruolo_richiesto('admin')
def admin_crea_aeroporto():
    """POST /api/admin/aeroporti — Body: { codice, nome?, lat, lon }"""
    dati = request.get_json(silent=True) or {}
    for campo in ['codice', 'lat', 'lon']:
        if dati.get(campo) is None:
            return jsonify({"errore": f"Campo obbligatorio mancante: {campo}"}), 400

    codice = dati['codice'].strip().upper()
    if len(codice) != 3 or not codice.isalpha():
        return jsonify({"errore": "Il codice IATA deve essere esattamente 3 lettere"}), 400

    try:
        lat = float(dati['lat'])
        lon = float(dati['lon'])
    except (ValueError, TypeError):
        return jsonify({"errore": "lat e lon devono essere valori numerici"}), 400

    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return jsonify({"errore": "Coordinate non valide (lat: -90…90, lon: -180…180)"}), 400

    nome = (dati.get('nome') or '').strip()
    try:
        aid = db_execute(
            "INSERT INTO aeroporti (codice, nome, lat, lon) VALUES (?, ?, ?, ?)",
            (codice, nome, lat, lon)
        )
        return jsonify({"messaggio": "Aeroporto inserito", "aeroporto_id": aid}), 201
    except sqlite3.IntegrityError:
        return jsonify({"errore": "Codice IATA già presente nel database"}), 409


@app.route('/api/admin/utenti')
@ruolo_richiesto('admin')
def admin_lista_utenti():
    """GET /api/admin/utenti — tutti gli utenti con dati associati."""
    utenti = query_rows(
        """SELECT u.id, u.username, u.ruolo, u.attivo,
                  u.compagnia_id, c.nome AS compagnia_nome,
                  u.passeggero_id, p.nome AS passeggero_nome, p.cognome AS passeggero_cognome
           FROM   utenti u
           LEFT JOIN compagnie_aeree c ON u.compagnia_id = c.id
           LEFT JOIN passeggeri p      ON u.passeggero_id = p.id
           ORDER BY u.id"""
    )
    return jsonify(utenti)


@app.route('/api/admin/utenti/<int:id>', methods=['PUT'])
@ruolo_richiesto('admin')
def admin_modifica_utente(id):
    """PUT /api/admin/utenti/<id> — Body: { "attivo": 1|0 }"""
    if id == session['utente_id']:
        return jsonify({"errore": "Non puoi modificare il tuo stesso account"}), 400

    dati = request.get_json(silent=True) or {}
    if 'attivo' not in dati:
        return jsonify({"errore": "Campo 'attivo' obbligatorio"}), 400

    if not query_row("SELECT id FROM utenti WHERE id = ?", (id,)):
        return jsonify({"errore": "Utente non trovato"}), 404

    attivo = int(bool(dati['attivo']))
    db_execute("UPDATE utenti SET attivo = ? WHERE id = ?", (attivo, id))

    azione = 'sblocco_utente' if attivo else 'blocco_utente'
    registra_log(azione, session['utente_id'], {'utente_id_target': id})

    return jsonify({"messaggio": f"Utente {'attivato' if attivo else 'bloccato'}"})


@app.route('/api/admin/utenti/<int:id>', methods=['DELETE'])
@ruolo_richiesto('admin')
def admin_elimina_utente(id):
    """DELETE /api/admin/utenti/<id> — con controlli su voli/prenotazioni attive."""
    if id == session['utente_id']:
        return jsonify({"errore": "Non puoi eliminare il tuo stesso account"}), 400

    utente = query_row(
        """SELECT u.*, c.nome AS compagnia_nome FROM utenti u
           LEFT JOIN compagnie_aeree c ON u.compagnia_id = c.id WHERE u.id = ?""",
        (id,)
    )
    if not utente:
        return jsonify({"errore": "Utente non trovato"}), 404

    if utente['ruolo'] == 'compagnia' and utente['compagnia_id']:
        voli_attivi = query_row(
            "SELECT COUNT(*) AS n FROM voli WHERE compagnia_id = ? AND stato = 'programmato'",
            (utente['compagnia_id'],)
        )
        if voli_attivi['n'] > 0:
            return jsonify({
                "errore": f"Impossibile eliminare: la compagnia ha {voli_attivi['n']} volo/i programmato/i. "
                          "Elimina o cambia lo stato dei voli prima di procedere."
            }), 400

    if utente['ruolo'] == 'passeggero' and utente['passeggero_id']:
        pren_attive = query_row(
            "SELECT COUNT(*) AS n FROM prenotazioni WHERE passeggero_id = ? AND stato IN ('prenotata', 'pagata')",
            (utente['passeggero_id'],)
        )
        if pren_attive['n'] > 0:
            return jsonify({
                "errore": f"Impossibile eliminare: il passeggero ha {pren_attive['n']} prenotazione/i attiva/e."
            }), 400

    db_execute("DELETE FROM utenti WHERE id = ?", (id,))
    registra_log('eliminazione_utente', session['utente_id'],
                 {'utente_id_target': id, 'username': utente['username']})

    return jsonify({"messaggio": f"Utente '{utente['username']}' eliminato"})


@app.route('/api/admin/backup')
@ruolo_richiesto('admin')
def admin_backup():
    """GET /api/admin/backup — scarica il file del database come attachment."""
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    registra_log('backup', session['utente_id'])
    return send_file(
        DB_PATH,
        as_attachment=True,
        download_name=f'aeroporto_backup_{ts}.db',
        mimetype='application/octet-stream'
    )


@app.route('/api/admin/restore', methods=['POST'])
@ruolo_richiesto('admin')
def admin_restore():
    """POST /api/admin/restore — ripristina il database da un file .db caricato."""
    if 'file' not in request.files:
        return jsonify({"errore": "Nessun file caricato (campo 'file' mancante)"}), 400

    f = request.files['file']
    if not f.filename.lower().endswith('.db'):
        return jsonify({"errore": "Il file deve avere estensione .db"}), 400

    tmp_path = None
    bak_path = DB_PATH + '.bak'

    try:
        fd, tmp_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        f.save(tmp_path)

        # Verifica che sia un SQLite valido prima di sovrascrivere
        test_conn = sqlite3.connect(tmp_path)
        test_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        test_conn.close()

        # Backup del database corrente come rete di sicurezza
        shutil.copy2(DB_PATH, bak_path)

        # Sostituisce il database
        shutil.copy2(tmp_path, DB_PATH)
        registra_log('restore', session.get('utente_id'))

        return jsonify({"status": "ok", "messaggio": "Database ripristinato con successo"})

    except sqlite3.DatabaseError:
        return jsonify({"errore": "Il file caricato non è un database SQLite valido"}), 400
    except Exception as e:
        # Tentativo di ripristino dal backup
        if os.path.exists(bak_path):
            try:
                shutil.copy2(bak_path, DB_PATH)
            except Exception:
                pass
        return jsonify({"errore": f"Errore durante il ripristino: {str(e)}"}), 500
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
        if os.path.exists(bak_path):
            try:
                os.unlink(bak_path)
            except Exception:
                pass


@app.route('/api/admin/log')
@ruolo_richiesto('admin')
def admin_log():
    """GET /api/admin/log?azione=&utente_id=&data_da=&data_a=&limite=100"""
    azione    = request.args.get('azione', '').strip()
    utente_id = request.args.get('utente_id', '').strip()
    data_da   = request.args.get('data_da', '').strip()
    data_a    = request.args.get('data_a', '').strip()
    try:
        limite = int(request.args.get('limite', 100))
        limite = max(1, min(limite, 1000))
    except ValueError:
        limite = 100

    sql = """
        SELECT l.id, l.utente_id, u.username,
               l.azione, l.dettagli, l.timestamp
        FROM   log l
        LEFT JOIN utenti u ON l.utente_id = u.id
        WHERE  1=1
    """
    params = []
    if azione:
        sql += " AND l.azione = ?"
        params.append(azione)
    if utente_id:
        try:
            sql += " AND l.utente_id = ?"
            params.append(int(utente_id))
        except ValueError:
            pass
    if data_da:
        sql += " AND DATE(l.timestamp) >= ?"
        params.append(data_da)
    if data_a:
        sql += " AND DATE(l.timestamp) <= ?"
        params.append(data_a)
    sql += " ORDER BY l.timestamp DESC LIMIT ?"
    params.append(limite)

    return jsonify(query_rows(sql, params))


# =============================================================================
# Route: notifiche in-app (trasversale)
# =============================================================================

@app.route('/api/notifiche')
@login_required
def notifiche():
    """
    GET /api/notifiche
    Genera notifiche dinamiche per l'utente loggato.
    Nessun dato viene persiste: lo stato "letto" è gestito lato client (localStorage).
    """
    ruolo    = session.get('ruolo')
    ora_dt   = datetime.now()
    risultato = []

    if ruolo == 'passeggero':
        pid = session['passeggero_id']

        # Prenotazioni/pagamenti/check-in recenti (ultimi 7 giorni)
        eventi = query_rows(
            """SELECT p.id, p.codice_prenotazione, p.data_prenotazione,
                      p.prezzo, p.stato, v.codice_volo
               FROM prenotazioni p JOIN voli v ON p.volo_id = v.id
               WHERE p.passeggero_id = ? AND p.data_prenotazione >= datetime('now', '-7 days')
               ORDER BY p.data_prenotazione DESC""",
            (pid,)
        )
        for e in eventi:
            icone = {
                'prenotata':  'bi-ticket',
                'pagata':     'bi-credit-card-fill',
                'imbarcato':  'bi-qr-code-scan',
                'cancellata': 'bi-x-circle',
            }
            testi = {
                'prenotata':  f"Prenotazione {e['codice_prenotazione']} confermata per {e['codice_volo']}",
                'pagata':     f"Pagamento di €{e['prezzo']:.0f} confermato per {e['codice_volo']}",
                'imbarcato':  f"Check-in completato: volo {e['codice_volo']}",
                'cancellata': f"Prenotazione {e['codice_prenotazione']} cancellata",
            }
            risultato.append({
                'id':        f"pren_{e['codice_prenotazione']}_{e['stato']}",
                'icona':     icone.get(e['stato'], 'bi-info-circle'),
                'testo':     testi.get(e['stato'], f"Prenotazione {e['codice_prenotazione']} aggiornata"),
                'timestamp': e['data_prenotazione'],
                'tipo':      e['stato'],
            })

        # Ricariche recenti (dal log)
        ricariche = query_rows(
            """SELECT l.dettagli, l.timestamp FROM log l
               WHERE l.utente_id = ? AND l.azione = 'ricarica_crediti'
                 AND l.timestamp >= datetime('now', '-7 days')
               ORDER BY l.timestamp DESC""",
            (session['utente_id'],)
        )
        for r in ricariche:
            try:
                importo = json.loads(r['dettagli'] or '{}').get('importo', '?')
            except Exception:
                importo = '?'
            risultato.append({
                'id':        f"ricarica_{r['timestamp']}",
                'icona':     'bi-wallet2',
                'testo':     f"Crediti ricaricati: €{importo}",
                'timestamp': r['timestamp'],
                'tipo':      'ricarica',
            })

        # Partenze imminenti (prossime 24h)
        imminenti = query_rows(
            """SELECT p.codice_prenotazione, v.codice_volo, v.destinazione,
                      v.data_ora_partenza, v.orario_stimato
               FROM prenotazioni p JOIN voli v ON p.volo_id = v.id
               WHERE p.passeggero_id = ? AND p.stato IN ('pagata', 'imbarcato')
                 AND v.stato = 'programmato'
                 AND datetime(COALESCE(v.orario_stimato, v.data_ora_partenza))
                     BETWEEN datetime('now') AND datetime('now', '+24 hours')
               ORDER BY v.data_ora_partenza""",
            (pid,)
        )
        for i in imminenti:
            orario = i['orario_stimato'] or i['data_ora_partenza']
            try:
                ora_str = datetime.fromisoformat(orario.replace(' ', 'T')).strftime('%H:%M')
            except Exception:
                ora_str = orario[-5:]
            risultato.append({
                'id':        f"partenza_{i['codice_prenotazione']}",
                'icona':     'bi-airplane-fill',
                'testo':     f"Il volo {i['codice_volo']} per {i['destinazione']} parte alle {ora_str}",
                'timestamp': ora_dt.strftime('%Y-%m-%d %H:%M:%S'),
                'tipo':      'partenza',
            })

        # Ritardi attivi
        ritardi = query_rows(
            """SELECT p.codice_prenotazione, v.codice_volo, v.orario_stimato
               FROM prenotazioni p JOIN voli v ON p.volo_id = v.id
               WHERE p.passeggero_id = ? AND p.stato IN ('prenotata', 'pagata', 'imbarcato')
                 AND v.stato = 'programmato' AND v.orario_stimato IS NOT NULL""",
            (pid,)
        )
        for r in ritardi:
            risultato.append({
                'id':        f"ritardo_{r['codice_prenotazione']}",
                'icona':     'bi-clock-history',
                'testo':     f"Volo {r['codice_volo']} in ritardo: nuovo orario {r['orario_stimato']}",
                'timestamp': ora_dt.strftime('%Y-%m-%d %H:%M:%S'),
                'tipo':      'ritardo',
            })

    elif ruolo == 'compagnia':
        cid = session['compagnia_id']
        nuove = query_rows(
            """SELECT v.codice_volo, COUNT(*) AS n
               FROM prenotazioni p JOIN voli v ON p.volo_id = v.id
               WHERE v.compagnia_id = ? AND p.data_prenotazione >= datetime('now', '-7 days')
                 AND p.stato != 'cancellata'
               GROUP BY v.codice_volo ORDER BY n DESC""",
            (cid,)
        )
        for n in nuove:
            risultato.append({
                'id':        f"pren_compagnia_{n['codice_volo']}",
                'icona':     'bi-people-fill',
                'testo':     f"{n['n']} nuova/e prenotazione/i su {n['codice_volo']} nell'ultima settimana",
                'timestamp': ora_dt.strftime('%Y-%m-%d %H:%M:%S'),
                'tipo':      'prenotazione',
            })

    elif ruolo == 'operatore':
        oggi = ora_dt.strftime('%Y-%m-%d')
        pendenti = query_rows(
            """SELECT v.codice_volo, COUNT(*) AS n
               FROM prenotazioni p
               JOIN voli v ON p.volo_id = v.id
               LEFT JOIN carte_imbarco ci ON ci.prenotazione_id = p.id
               WHERE DATE(v.data_ora_partenza) = ? AND p.stato = 'pagata' AND ci.id IS NULL
               GROUP BY v.codice_volo""",
            (oggi,)
        )
        for pend in pendenti:
            risultato.append({
                'id':        f"checkin_pend_{pend['codice_volo']}_{oggi}",
                'icona':     'bi-person-check',
                'testo':     f"{pend['n']} passeggero/i senza check-in su {pend['codice_volo']} oggi",
                'timestamp': ora_dt.strftime('%Y-%m-%d %H:%M:%S'),
                'tipo':      'checkin',
            })

    elif ruolo == 'admin':
        nuovi_reg = query_row(
            "SELECT COUNT(*) AS n FROM log WHERE azione = 'registrazione' AND timestamp >= datetime('now', '-7 days')"
        )
        if nuovi_reg and nuovi_reg['n'] > 0:
            risultato.append({
                'id':        f"nuovi_utenti_{ora_dt.date()}",
                'icona':     'bi-person-plus',
                'testo':     f"{nuovi_reg['n']} nuova/e registrazione/i nell'ultima settimana",
                'timestamp': ora_dt.strftime('%Y-%m-%d %H:%M:%S'),
                'tipo':      'admin',
            })
        login_fail = query_row(
            "SELECT COUNT(*) AS n FROM log WHERE azione = 'login_failed' AND timestamp >= datetime('now', '-1 day')"
        )
        if login_fail and login_fail['n'] > 0:
            risultato.append({
                'id':        f"login_falliti_{ora_dt.date()}",
                'icona':     'bi-shield-exclamation',
                'testo':     f"{login_fail['n']} tentativo/i di login fallito/i nelle ultime 24h",
                'timestamp': ora_dt.strftime('%Y-%m-%d %H:%M:%S'),
                'tipo':      'sicurezza',
            })

    return jsonify(risultato)


# =============================================================================
# Avvio dell'applicazione
# =============================================================================

if __name__ == '__main__':
    init_db()
    # host='0.0.0.0' rende il server raggiungibile dall'esterno del container Docker
    app.run(host='0.0.0.0', port=5000, debug=False)
