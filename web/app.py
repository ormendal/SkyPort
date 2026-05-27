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
import sys
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
SCHEMA_PATH = os.path.join(BASE_DIR, 'db', 'schema.sql')
SEED_PATH   = os.path.join(BASE_DIR, 'db', 'seed.sql')

# Aggiunge la radice del progetto al path per importare db.query_loader
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
from db.query_loader import Q


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
        if not conn.execute(Q.get('pren_pnr_check'), {'pnr': pnr}).fetchone():
            return pnr


def _genera_posto(conn, volo_id, posti_totali):
    """Restituisce il primo posto libero sul volo (es. '1A', '1B', ...)."""
    posti_occupati = {
        r[0] for r in conn.execute(
            Q.get('posti_occupati_carta'), {'volo_id': volo_id}
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
            Q.get('log_insert'),
            {
                'uid':      utente_id,
                'azione':   azione,
                'dettagli': json.dumps(dettagli, ensure_ascii=False) if dettagli else None,
            }
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
# Inizializzazione del database
# =============================================================================

def init_db():
    """
    Crea le tabelle (schema.sql) e carica i dati di seed.
    Viene chiamata una sola volta prima di avviare il server.

    Il seed è diviso in due fasi:
      * _seed_statico  → dati statici da db/seed.sql (aeroporti, compagnie,
                         gate, passeggeri, voli, prenotazioni, carte d'imbarco)
      * _seed_dinamico → utenti con password hashate (salt random non
                         pre-calcolabile in SQL puro)
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    try:
        # 1. Crea le tabelle (idempotente grazie a IF NOT EXISTS)
        with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
            conn.executescript(f.read())

        # 2. Seed principale — solo se il database è vuoto.
        #    L'ordine è importante: _seed_statico crea i passeggeri che _seed_dinamico
        #    referenzia (utente mario.rossi → passeggero demo).
        if conn.execute("SELECT COUNT(*) FROM compagnie_aeree").fetchone()[0] == 0:
            _seed_statico(conn)
            _seed_dinamico(conn)
            print("[init_db] Dati di seed caricati (statico + dinamico).")
        else:
            print("[init_db] Database già inizializzato, seed saltato.")

        # 3. Fallback aeroporti — per DB ripristinati da backup vecchi che potrebbero
        #    non avere ancora la tabella aeroporti popolata. seed.sql è idempotente
        #    (tutto INSERT OR IGNORE), quindi rieseguirlo è sicuro.
        if conn.execute("SELECT COUNT(*) FROM aeroporti").fetchone()[0] == 0:
            _seed_statico(conn)
            print("[init_db] Aeroporti di seed caricati (fallback).")

    finally:
        conn.close()


def _seed_statico(conn):
    """
    Carica i dati statici dal file db/seed.sql via executescript().

    Il file contiene tutte le INSERT OR IGNORE per: aeroporti, compagnie_aeree,
    gate, passeggeri, voli, prenotazioni, carte_imbarco. Per modificare il
    popolamento iniziale del database, editare db/seed.sql, NON questa funzione.
    """
    with open(SEED_PATH, 'r', encoding='utf-8') as f:
        conn.executescript(f.read())
    conn.commit()


def _seed_dinamico(conn):
    """
    Inserisce gli utenti con password hashate via werkzeug.security.

    Gli utenti sono in Python (e non in db/seed.sql) perché generate_password_hash
    usa un salt random ad ogni invocazione: non è pre-calcolabile in SQL puro.
    Deve essere chiamata DOPO _seed_statico() perché alcuni utenti referenziano
    passeggeri creati in seed.sql.
    """
    ph      = generate_password_hash("password")
    ph_demo = generate_password_hash("demo1234")

    row = conn.execute(
        "SELECT id FROM passeggeri WHERE documento = 'AY1234567'"
    ).fetchone()
    demo_pid = row[0] if row else None

    row = conn.execute(
        "SELECT id FROM passeggeri WHERE documento = 'IT00013'"
    ).fetchone()
    galli_pid = row[0] if row else None

    conn.executemany(
        """INSERT OR IGNORE INTO utenti
           (id, username, password_hash, ruolo, compagnia_id, passeggero_id, attivo)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            (1, 'admin',         ph,      'admin',     None,      None, 1),
            (2, 'operatore1',    ph,      'operatore', None,      None, 1),
            (3, 'compagnia1',    ph,      'compagnia',    1,      None, 1),  # Air Dolomiti
            (4, 'compagnia2',    ph,      'compagnia',    2,      None, 1),  # ITA Airways
            (5, 'mario.rossi',   ph_demo, 'passeggero',None,  demo_pid, 1),  # DEMO (password 'demo1234')
            (6, 'roberto.galli', ph,      'passeggero',None, galli_pid, 1),
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

    utente = query_row(Q.get('utente_by_username'), {'username': username})

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

    if query_row(Q.get('passeggero_by_doc'), {'documento': dati['documento']}):
        return jsonify({"errore": "Documento già registrato"}), 409
    if query_row(Q.get('utente_by_username_check'), {'username': dati['username']}):
        return jsonify({"errore": "Username già in uso"}), 409

    conn = get_db()
    try:
        conn.execute("BEGIN")
        cur_pass = conn.execute(
            Q.get('insert_passeggero'),
            {'nome': dati['nome'].strip(), 'cognome': dati['cognome'].strip(), 'documento': dati['documento'].strip()}
        )
        passeggero_id = cur_pass.lastrowid

        cur_utente = conn.execute(
            Q.get('insert_utente_passeggero'),
            {'username': dati['username'].strip(), 'password_hash': generate_password_hash(dati['password']), 'passeggero_id': passeggero_id}
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
    return jsonify(query_rows(Q.get('lista_aeroporti')))


@app.route('/api/voli/attivi')
def voli_attivi():
    """GET /api/voli/attivi — voli programmato/partito con coordinate per la mappa."""
    voli = query_rows(Q.get('voli_attivi'))
    return jsonify(voli)


@app.route('/api/voli/search')
def cerca_voli():
    """GET /api/voli/search?origine=&destinazione=&data= — ricerca voli pubblica."""
    origine      = request.args.get('origine', '').strip().upper()
    destinazione = request.args.get('destinazione', '').strip().upper()
    data         = request.args.get('data', '').strip()

    sql = Q.render('cerca_voli', origine=origine, destinazione=destinazione, data=data)
    return jsonify(query_rows(sql, {'origine': origine, 'destinazione': destinazione, 'data': data}))


@app.route('/api/voli/<int:volo_id>/posti')
@login_required
def volo_posti(volo_id):
    """
    GET /api/voli/<id>/posti
    Mappa dei posti liberi e occupati per il componente seat map.
    """
    volo = query_row(Q.get('volo_by_id'), {'id': volo_id})
    if not volo:
        return jsonify({"errore": "Volo non trovato"}), 404

    posti_totali = volo['posti_totali']
    righe        = (posti_totali + 5) // 6  # arrotondamento per eccesso su 6 colonne
    lettere      = ['A', 'B', 'C', 'D', 'E', 'F']

    # Genera tutti i posti teorici e taglia al numero reale
    tutti = [f"{r}{l}" for r in range(1, righe + 1) for l in lettere]
    tutti = tutti[:posti_totali]

    # Posti già assegnati nelle carte d'imbarco
    occupati_rows = query_rows(Q.get('posti_occupati_carta'), {'volo_id': volo_id})
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

        volo = conn.execute(Q.get('volo_by_id'), {'id': volo_id}).fetchone()
        if not volo:
            conn.rollback()
            return jsonify({"errore": "Volo non trovato"}), 404
        if volo['stato'] != 'programmato':
            conn.rollback()
            return jsonify({"errore": f"Il volo è in stato '{volo['stato']}': non accetta prenotazioni"}), 400

        posti_occupati = conn.execute(
            Q.get('posti_occupati_count'), {'volo_id': volo_id}
        ).fetchone()[0]
        if posti_occupati >= volo['posti_totali']:
            conn.rollback()
            return jsonify({"errore": "Volo completo"}), 400

        esistente = conn.execute(
            Q.get('pren_esistente'), {'passeggero_id': passeggero_id, 'volo_id': volo_id}
        ).fetchone()
        if esistente:
            conn.rollback()
            return jsonify({"errore": "Hai già una prenotazione attiva su questo volo"}), 409

        # Usa il prezzo base del volo, non un valore passato dal client
        prezzo = float(volo['prezzo_base']) if volo['prezzo_base'] is not None else 100.0
        pnr    = _genera_pnr_unico(conn)
        cur    = conn.execute(
            Q.get('insert_prenotazione'),
            {'passeggero_id': passeggero_id, 'volo_id': volo_id, 'pnr': pnr, 'prezzo': prezzo}
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
    prenotazioni = query_rows(Q.get('mie_prenotazioni'), {'passeggero_id': passeggero_id})
    return jsonify(prenotazioni)


@app.route('/api/paga/<int:prenotazione_id>', methods=['POST'])
@ruolo_richiesto('passeggero')
def paga(prenotazione_id):
    """
    POST /api/paga/<id>
    Scala i crediti del passeggero. Restituisce 400 se crediti insufficienti.
    """
    passeggero_id = session['passeggero_id']

    # Lettura iniziale per rispondere 404/400 prima di aprire la transazione.
    pren = query_row(
        Q.get('pren_by_id_passeggero'), {'id': prenotazione_id, 'passeggero_id': passeggero_id}
    )
    if not pren:
        return jsonify({"errore": "Prenotazione non trovata"}), 404
    if pren['stato'] != 'prenotata':
        return jsonify({"errore": f"La prenotazione è in stato '{pren['stato']}' e non può essere pagata"}), 400

    prezzo = float(pren['prezzo'])

    conn = get_db()
    try:
        conn.execute("BEGIN")

        # Rileggi i crediti dentro la transazione per eliminare la TOCTOU race.
        pas     = conn.execute(Q.get('crediti_passeggero'), {'id': passeggero_id}).fetchone()
        crediti = float(pas['crediti']) if pas else 0.0

        if crediti < prezzo:
            conn.rollback()
            return jsonify({
                "errore":               "Crediti insufficienti. Ricarica il tuo portafoglio.",
                "crediti_disponibili":  crediti,
                "prezzo":               prezzo,
            }), 400

        # WHERE stato = 'prenotata' garantisce che rowcount == 0 se un thread concorrente
        # ha già modificato la prenotazione tra la lettura iniziale e questo UPDATE.
        cur = conn.execute(Q.get('update_pren_pagata'), {'id': prenotazione_id})
        if cur.rowcount != 1:
            conn.rollback()
            return jsonify({"errore": "Prenotazione non più disponibile per il pagamento"}), 409

        # WHERE crediti >= :importo è la guardia atomica finale: rowcount == 0 se nel
        # frattempo un altro thread ha già scalato i crediti portandoli sotto soglia.
        cur = conn.execute(Q.get('update_crediti_paga'), {'importo': prezzo, 'id': passeggero_id})
        if cur.rowcount != 1:
            conn.rollback()
            return jsonify({
                "errore":               "Crediti insufficienti. Ricarica il tuo portafoglio.",
                "crediti_disponibili":  crediti,
                "prezzo":               prezzo,
            }), 400

        nuovi_crediti = crediti - prezzo
        conn.commit()
    except Exception as e:
        conn.rollback()
        return jsonify({"errore": str(e)}), 500
    finally:
        conn.close()

    registra_log('pagamento', session['utente_id'],
                 {'prenotazione_id': prenotazione_id, 'importo': prezzo})

    # Recupera info volo per la ricevuta
    volo_info = query_row(Q.get('volo_info_ricevuta'), {'volo_id': pren['volo_id']})
    # ID transazione basato su prenotazione_id + timestamp ridotto
    ts_short = int(datetime.now().timestamp()) % 1000000
    transazione_id = f"TXN{prenotazione_id:06d}{ts_short:06d}"

    return jsonify({
        "messaggio":         "Pagamento completato",
        "nuovo_stato":       "pagata",
        "crediti_rimanenti": nuovi_crediti,
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
        Q.get('pren_by_id_passeggero'), {'id': prenotazione_id, 'passeggero_id': passeggero_id}
    )
    if not pren:
        return jsonify({"errore": "Prenotazione non trovata"}), 404
    if pren['stato'] != 'pagata':
        return jsonify({"errore": "Il check-in online richiede una prenotazione in stato 'pagata'"}), 400

    if query_row(Q.get('carta_by_pren'), {'pren_id': prenotazione_id}):
        return jsonify({"errore": "Carta d'imbarco già emessa per questa prenotazione"}), 409

    volo = query_row(Q.get('volo_by_id'), {'id': pren['volo_id']})

    conn = get_db()
    try:
        conn.execute("BEGIN")

        if numero_posto_richiesto:
            # Verifica che il posto richiesto sia libero
            occupati = {r[0] for r in conn.execute(
                Q.get('posti_occupati_carta'), {'volo_id': volo['id']}
            ).fetchall()}
            if numero_posto_richiesto in occupati:
                conn.rollback()
                return jsonify({"errore": f"Il posto {numero_posto_richiesto} è già occupato"}), 409
            posto = numero_posto_richiesto
        else:
            posto = _genera_posto(conn, volo['id'], volo['posti_totali'])

        cur = conn.execute(
            Q.get('insert_carta_imbarco_online'),
            {'pren_id': prenotazione_id, 'volo_id': pren['volo_id'], 'numero_posto': posto, 'gate_id': volo['gate_id']}
        )
        carta_id = cur.lastrowid
        conn.execute(Q.get('update_pren_imbarcato'), {'id': prenotazione_id})
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
        Q.get('pren_by_id_passeggero'), {'id': prenotazione_id, 'passeggero_id': passeggero_id}
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
        # WHERE stato = 'prenotata' impedisce che due richieste concorrenti applichino
        # entrambe la penale: la seconda troverà rowcount == 0 e farà ROLLBACK.
        cur = conn.execute(Q.get('update_pren_cancellata'), {'id': prenotazione_id})
        if cur.rowcount != 1:
            conn.rollback()
            return jsonify({"errore": "prenotazione non più cancellabile"}), 409
        conn.execute(Q.get('update_crediti_scala'), {'importo': penale, 'id': passeggero_id})
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
    viaggi = query_rows(Q.get('passeggero_storico'), {'passeggero_id': passeggero_id})
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
        Q.get('pren_valuta'), {'id': prenotazione_id, 'passeggero_id': passeggero_id}
    )
    if not pren:
        return jsonify({"errore": "Prenotazione non trovata"}), 404
    if pren['stato'] != 'imbarcato' or pren['stato_volo'] != 'arrivato':
        return jsonify({"errore": "Puoi valutare solo voli completati (imbarcato + volo arrivato)"}), 400
    if pren['valutazione'] is not None:
        return jsonify({"errore": "Hai già valutato questo volo"}), 400

    db_execute(Q.get('update_valutazione'), {'valutazione': valutazione, 'id': prenotazione_id})
    registra_log('valutazione', session['utente_id'],
                 {'prenotazione_id': prenotazione_id, 'valutazione': valutazione})

    return jsonify({"messaggio": "Valutazione inviata, grazie!", "valutazione": valutazione})


@app.route('/api/passeggero/crediti')
@ruolo_richiesto('passeggero')
def passeggero_crediti():
    """GET /api/passeggero/crediti — saldo del portafoglio virtuale."""
    p = query_row(Q.get('crediti_passeggero'), {'id': session['passeggero_id']})
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

    db_execute(Q.get('update_crediti_aggiungi'), {'importo': importo, 'id': session['passeggero_id']})
    p = query_row(Q.get('crediti_passeggero'), {'id': session['passeggero_id']})
    registra_log('ricarica_crediti', session['utente_id'], {'importo': importo})

    return jsonify({"status": "ok", "crediti": float(p['crediti'])})


@app.route('/api/passeggero/profilo', methods=['GET'])
@ruolo_richiesto('passeggero')
def leggi_profilo():
    """GET /api/passeggero/profilo — dati anagrafici e credenziali (no password)."""
    passeggero = query_row(Q.get('profilo_passeggero'), {'id': session['passeggero_id']})
    utente = query_row(Q.get('utente_username'), {'id': session['utente_id']})
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

    passeggero = query_row(Q.get('passeggero_full'), {'id': passeggero_id})
    utente     = query_row(Q.get('utente_full'), {'id': utente_id})
    if not passeggero or not utente:
        return jsonify({"errore": "Profilo non trovato"}), 404

    # ── Dati anagrafici ──────────────────────────────────────────────────────
    nome      = (dati.get('nome')      or passeggero['nome']).strip()
    cognome   = (dati.get('cognome')   or passeggero['cognome']).strip()
    documento = (dati.get('documento') or passeggero['documento']).strip()

    if not nome or not cognome or not documento:
        return jsonify({"errore": "Nome, cognome e documento non possono essere vuoti"}), 400

    if documento != passeggero['documento']:
        if query_row(Q.get('doc_altro_passeggero'), {'documento': documento, 'id': passeggero_id}):
            return jsonify({"errore": "Documento già in uso da un altro passeggero"}), 409

    db_execute(
        Q.get('update_passeggero_anagrafica'),
        {'nome': nome, 'cognome': cognome, 'documento': documento, 'id': passeggero_id}
    )

    # ── Username ─────────────────────────────────────────────────────────────
    nuovo_username = (dati.get('username') or '').strip()
    if nuovo_username and nuovo_username != utente['username']:
        if query_row(Q.get('username_altro_utente'), {'username': nuovo_username, 'id': utente_id}):
            return jsonify({"errore": "Username già in uso da un altro utente"}), 409
        db_execute(Q.get('update_username'), {'username': nuovo_username, 'id': utente_id})
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
        db_execute(Q.get('update_password'), {'password_hash': generate_password_hash(nuova_password), 'id': utente_id})

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
    """
    GET /api/compagnia/voli — voli della compagnia divisi in operativi/storici.

    Risposta:
      {
        "operativi": [...],   # stato IN ('programmato','partito'), ordine data_ora_partenza ASC
        "storici":   [...]    # stato = 'arrivato',                 ordine data_ora_partenza DESC
      }
    """
    compagnia_id = session['compagnia_id']
    voli = query_rows(Q.get('compagnia_lista_voli'), {'compagnia_id': compagnia_id})

    operativi = [v for v in voli if v['stato'] in ('programmato', 'partito')]
    storici   = [v for v in voli if v['stato'] == 'arrivato']
    storici.sort(key=lambda v: v['data_ora_partenza'], reverse=True)

    # I warning gate hanno senso solo sui voli operativi (storici non si possono più modificare)
    operativi = _calcola_warning_gate(operativi)

    return jsonify({"operativi": operativi, "storici": storici})


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

    # Validazione temporale: la data di partenza non può essere nel passato
    try:
        _normalizza = lambda s: s.strip().replace('T', ' ')[:16]
        dt_partenza = datetime.strptime(_normalizza(dati['data_ora_partenza']), '%Y-%m-%d %H:%M')
        dt_arrivo   = datetime.strptime(_normalizza(dati['data_ora_arrivo']),   '%Y-%m-%d %H:%M')
    except (ValueError, AttributeError):
        return jsonify({"errore": "Formato data/ora non valido (atteso: YYYY-MM-DD HH:MM)"}), 400

    if dt_partenza <= datetime.now():
        return jsonify({"errore": "Non è possibile creare un volo con data di partenza nel passato"}), 400
    if dt_arrivo <= dt_partenza:
        return jsonify({"errore": "La data e ora di arrivo deve essere successiva alla data e ora di partenza"}), 400

    compagnia_id = session['compagnia_id']
    try:
        volo_id = db_execute(
            Q.get('insert_volo'),
            {
                'codice_volo':      dati['codice_volo'].strip().upper(),
                'compagnia_id':     compagnia_id,
                'gate_id':          dati.get('gate_id'),
                'origine':          dati['origine'].strip().upper(),
                'destinazione':     dati['destinazione'].strip().upper(),
                'data_ora_partenza': dati['data_ora_partenza'].strip(),
                'data_ora_arrivo':  dati['data_ora_arrivo'].strip(),
                'posti_totali':     posti,
                'prezzo_base':      prezzo_base,
            }
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
    volo = query_row(Q.get('volo_compagnia'), {'id': id, 'compagnia_id': compagnia_id})
    if not volo:
        return jsonify({"errore": "Volo non trovato o non appartenente alla tua compagnia"}), 404
    if volo['stato'] != 'programmato':
        return jsonify({"errore": f"Il volo è in stato '{volo['stato']}': solo i voli programmato sono eliminabili"}), 400

    attive = query_row(Q.get('pren_attive_volo'), {'volo_id': id})
    if attive['n'] > 0:
        return jsonify({"errore": f"Il volo ha {attive['n']} prenotazione/i attiva/e. Impossibile eliminarlo."}), 409

    db_execute(Q.get('delete_volo'), {'id': id})
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
    volo = query_row(Q.get('volo_compagnia'), {'id': id, 'compagnia_id': compagnia_id})
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
        nuovo_prezzo = float(dati.get('prezzo_base', volo['prezzo_base'] if volo['prezzo_base'] is not None else 100.0))
        if nuovo_prezzo < 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"errore": "prezzo_base deve essere un numero non negativo"}), 400

    # Validazione temporale: controlla le date solo se vengono modificate
    nuova_partenza = dati.get('data_ora_partenza', volo['data_ora_partenza'])
    nuova_arrivo   = dati.get('data_ora_arrivo',   volo['data_ora_arrivo'])
    try:
        _norm = lambda s: str(s).strip().replace('T', ' ')[:16]
        dt_partenza = datetime.strptime(_norm(nuova_partenza), '%Y-%m-%d %H:%M')
        dt_arrivo   = datetime.strptime(_norm(nuova_arrivo),   '%Y-%m-%d %H:%M')
    except (ValueError, AttributeError):
        return jsonify({"errore": "Formato data/ora non valido (atteso: YYYY-MM-DD HH:MM)"}), 400

    # Impedisce di spostare la partenza nel passato (solo se la data viene cambiata)
    if 'data_ora_partenza' in dati and dt_partenza <= datetime.now():
        return jsonify({"errore": "Non è possibile modificare un volo con data di partenza nel passato"}), 400
    # L'arrivo deve sempre essere successivo alla partenza
    if dt_arrivo <= dt_partenza:
        return jsonify({"errore": "La data e ora di arrivo deve essere successiva alla data e ora di partenza"}), 400

    # orario_stimato e ritardo_note solo per voli programmato
    orario_stimato = dati.get('orario_stimato', volo.get('orario_stimato'))
    ritardo_note   = dati.get('ritardo_note',   volo.get('ritardo_note'))

    # Quando il volo parte o arriva, azzera il ritardo
    if nuovo_stato in ('partito', 'arrivato'):
        orario_stimato = None
        ritardo_note   = None

    db_execute(
        Q.get('update_volo'),
        {
            'gate_id':           dati.get('gate_id', volo['gate_id']),
            'data_ora_partenza': dati.get('data_ora_partenza', volo['data_ora_partenza']),
            'data_ora_arrivo':   dati.get('data_ora_arrivo',   volo['data_ora_arrivo']),
            'posti_totali':      nuovi_posti,
            'stato':             nuovo_stato,
            'prezzo_base':       nuovo_prezzo,
            'orario_stimato':    orario_stimato,
            'ritardo_note':      ritardo_note,
            'id':                id,
        }
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
    if not query_row(Q.get('volo_compagnia'), {'id': id, 'compagnia_id': compagnia_id}):
        return jsonify({"errore": "Volo non trovato o non appartenente alla tua compagnia"}), 404

    passeggeri = query_rows(Q.get('compagnia_passeggeri_volo'), {'volo_id': id})
    return jsonify(passeggeri)


# =============================================================================
# Route: area OPERATORE
# =============================================================================

@app.route('/api/operatore/gate')
@ruolo_richiesto('operatore')
def operatore_gate():
    """GET /api/operatore/gate — stato di tutti i gate con voli assegnati."""
    gate = query_rows(Q.get('gate_list'))
    return jsonify(gate)


@app.route('/api/operatore/gate/<int:id>', methods=['PUT'])
@ruolo_richiesto('operatore')
def operatore_modifica_gate(id):
    """PUT /api/operatore/gate/<id> — Body: { "stato": "libero"|"occupato"|"manutenzione" }"""
    dati        = request.get_json(silent=True) or {}
    nuovo_stato = dati.get('stato', '').strip()

    if nuovo_stato not in ('libero', 'occupato', 'manutenzione'):
        return jsonify({"errore": "stato non valido. Valori ammessi: libero, occupato, manutenzione"}), 400

    gate = query_row(Q.get('gate_by_id'), {'id': id})
    if not gate:
        return jsonify({"errore": "Gate non trovato"}), 404

    db_execute(Q.get('update_gate'), {'stato': nuovo_stato, 'id': id})
    registra_log('cambio_stato_gate', session['utente_id'],
                 {'gate_id': id, 'stato_precedente': gate['stato'], 'nuovo_stato': nuovo_stato})
    return jsonify({"messaggio": f"Gate aggiornato a '{nuovo_stato}'"})


@app.route('/api/operatore/voli')
@ruolo_richiesto('operatore')
def operatore_voli_oggi():
    """GET /api/operatore/voli?data=YYYY-MM-DD — cruscotto voli per data (default: oggi)."""
    data = request.args.get('data', datetime.now().strftime('%Y-%m-%d')).strip()

    voli = query_rows(Q.get('operatore_voli_oggi'), {'data': data})
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

    # ── Ricerca per PNR ──────────────────────────────────────────────────────
    if codice_prenotazione:
        pren = query_row(
            Q.get('checkin_by_pnr'), {'pnr': codice_prenotazione.upper()}
        )
        if not pren:
            return jsonify({"errore": "Prenotazione non trovata o non in stato 'pagata'"}), 404
        return jsonify({"prenotazioni_disponibili": [pren]})

    # ── Ricerca per nome + cognome ───────────────────────────────────────────
    if nome and cognome:
        risultati = query_rows(
            Q.get('checkin_by_nome_cognome'), {'nome': nome, 'cognome': cognome}
        )
        if not risultati:
            return jsonify({"errore": "Nessuna prenotazione pagata trovata per questo passeggero"}), 404
        return jsonify({"prenotazioni_disponibili": risultati})

    # ── Ricerca per documento ─────────────────────────────────────────────────
    if not documento:
        return jsonify({"errore": "Fornire documento, codice_prenotazione oppure nome e cognome"}), 400

    passeggero = query_row(Q.get('passeggero_by_doc_full'), {'documento': documento})
    if not passeggero:
        return jsonify({"errore": "Nessun passeggero trovato con questo documento"}), 404

    prenotazioni_idonee = query_rows(
        Q.get('checkin_by_documento'), {'passeggero_id': passeggero['id']}
    )
    if not prenotazioni_idonee:
        return jsonify({"errore": "Nessuna prenotazione 'pagata' senza carta d'imbarco trovata"}), 404

    # Se c'è un'unica prenotazione idonea, esegui il check-in automaticamente (legacy)
    if len(prenotazioni_idonee) == 1:
        pren         = prenotazioni_idonee[0]
        operatore_id = session['utente_id']

        conn = get_db()
        try:
            conn.execute("BEGIN")
            numero_posto = _genera_posto(conn, pren['volo_id'], pren['posti_totali'])
            cur = conn.execute(
                Q.get('insert_carta_imbarco_banco'),
                {'pren_id': pren['id'], 'volo_id': pren['volo_id'],
                 'numero_posto': numero_posto, 'gate_id': pren['gate_id'], 'operatore_id': operatore_id}
            )
            carta_id = cur.lastrowid
            conn.execute(Q.get('update_pren_imbarcato'), {'id': pren['id']})
            conn.commit()
        except Exception as e:
            conn.rollback()
            return jsonify({"errore": str(e)}), 500
        finally:
            conn.close()

        registra_log('checkin_banco', operatore_id,
                     {'prenotazione_id': pren['id'], 'numero_posto': numero_posto})

        return jsonify({
            "messaggio":        "Check-in completato",
            "carta_imbarco_id": carta_id,
            "numero_posto":     numero_posto,
            "gate_imbarco_id":  pren['gate_id'],
            "passeggero":       f"{passeggero['nome']} {passeggero['cognome']}",
        }), 201

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

    pren = query_row(Q.get('pren_checkin_exec'), {'id': prenotazione_id})
    if not pren:
        return jsonify({"errore": "Prenotazione non trovata o non in stato 'pagata'"}), 404

    if query_row(Q.get('carta_by_pren'), {'pren_id': prenotazione_id}):
        return jsonify({"errore": "Carta d'imbarco già emessa"}), 409

    operatore_id = session['utente_id']
    gate_id      = gate_imbarco_id if gate_imbarco_id else pren['volo_gate_id']

    conn = get_db()
    try:
        conn.execute("BEGIN")
        if not numero_posto:
            numero_posto = _genera_posto(conn, pren['volo_id'], pren['posti_totali'])
        else:
            # Verifica che il posto esplicito non sia già occupato (stesso controllo di checkin_online).
            # Il controllo è dentro la stessa transazione per evitare la race tra check e INSERT.
            occupati = {r[0] for r in conn.execute(
                Q.get('posti_occupati_carta'), {'volo_id': pren['volo_id']}
            ).fetchall()}
            if numero_posto in occupati:
                conn.rollback()
                return jsonify({"errore": "posto già occupato"}), 409
        cur = conn.execute(
            Q.get('insert_carta_imbarco_banco'),
            {'pren_id': prenotazione_id, 'volo_id': pren['volo_id'],
             'numero_posto': numero_posto, 'gate_id': gate_id, 'operatore_id': operatore_id}
        )
        carta_id = cur.lastrowid
        conn.execute(Q.get('update_pren_imbarcato'), {'id': prenotazione_id})
        conn.commit()
    except Exception as e:
        conn.rollback()
        return jsonify({"errore": str(e)}), 500
    finally:
        conn.close()

    registra_log('checkin_banco', operatore_id,
                 {'prenotazione_id': prenotazione_id, 'numero_posto': numero_posto})

    # Recupera nome passeggero per il messaggio di conferma
    pass_row = query_row(Q.get('nominativo_passeggero'), {'pren_id': prenotazione_id})

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
            "totale":    query_row(Q.get('admin_stats_voli_totale'))['n'],
            "per_stato": query_rows(Q.get('admin_stats_voli_per_stato')),
        },
        "prenotazioni": {
            "totale":    query_row(Q.get('admin_stats_pren_totale'))['n'],
            "per_stato": query_rows(Q.get('admin_stats_pren_per_stato')),
        },
        "passeggeri":   query_row(Q.get('admin_stats_passeggeri'))['n'],
        "compagnie":    query_row(Q.get('admin_stats_compagnie'))['n'],
        "gate": {
            "totale":    query_row(Q.get('admin_stats_gate_totale'))['n'],
            "per_stato": query_rows(Q.get('admin_stats_gate_per_stato')),
        },
        "carte_imbarco": query_row(Q.get('admin_stats_carte'))['n'],
    }
    return jsonify(stats)


@app.route('/api/admin/voli')
@ruolo_richiesto('admin')
def admin_storico_voli():
    """GET /api/admin/voli?stato=&compagnia_id=&data= — storico voli con filtri."""
    stato        = request.args.get('stato', '').strip()
    compagnia_id = request.args.get('compagnia_id', '').strip()
    data         = request.args.get('data', '').strip()

    cid = int(compagnia_id) if compagnia_id else None
    sql = Q.render('admin_storico_voli', stato=stato, compagnia_id=cid, data=data)
    return jsonify(query_rows(sql, {'stato': stato, 'compagnia_id': cid, 'data': data}))


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
            Q.get('insert_aeroporto'),
            {'codice': codice, 'nome': nome, 'lat': lat, 'lon': lon}
        )
        return jsonify({"messaggio": "Aeroporto inserito", "aeroporto_id": aid}), 201
    except sqlite3.IntegrityError:
        return jsonify({"errore": "Codice IATA già presente nel database"}), 409


@app.route('/api/admin/utenti')
@ruolo_richiesto('admin')
def admin_lista_utenti():
    """GET /api/admin/utenti — tutti gli utenti con dati associati."""
    utenti = query_rows(Q.get('admin_lista_utenti'))
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

    if not query_row(Q.get('utente_by_id'), {'id': id}):
        return jsonify({"errore": "Utente non trovato"}), 404

    attivo = int(bool(dati['attivo']))
    db_execute(Q.get('update_utente_attivo'), {'attivo': attivo, 'id': id})

    azione = 'sblocco_utente' if attivo else 'blocco_utente'
    registra_log(azione, session['utente_id'], {'utente_id_target': id})

    return jsonify({"messaggio": f"Utente {'attivato' if attivo else 'bloccato'}"})


@app.route('/api/admin/utenti/<int:id>', methods=['DELETE'])
@ruolo_richiesto('admin')
def admin_elimina_utente(id):
    """DELETE /api/admin/utenti/<id> — con controlli su voli/prenotazioni attive."""
    if id == session['utente_id']:
        return jsonify({"errore": "Non puoi eliminare il tuo stesso account"}), 400

    utente = query_row(Q.get('utente_full_admin'), {'id': id})
    if not utente:
        return jsonify({"errore": "Utente non trovato"}), 404

    if utente['ruolo'] == 'compagnia' and utente['compagnia_id']:
        voli_attivi = query_row(
            Q.get('voli_compagnia_programmati'), {'compagnia_id': utente['compagnia_id']}
        )
        if voli_attivi['n'] > 0:
            return jsonify({
                "errore": f"Impossibile eliminare: la compagnia ha {voli_attivi['n']} volo/i programmato/i. "
                          "Elimina o cambia lo stato dei voli prima di procedere."
            }), 400

    if utente['ruolo'] == 'passeggero' and utente['passeggero_id']:
        pren_attive = query_row(
            Q.get('pren_attive_passeggero'), {'passeggero_id': utente['passeggero_id']}
        )
        if pren_attive['n'] > 0:
            return jsonify({
                "errore": f"Impossibile eliminare: il passeggero ha {pren_attive['n']} prenotazione/i attiva/e."
            }), 400

    db_execute(Q.get('delete_utente'), {'id': id})
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

    uid = None
    if utente_id:
        try:
            uid = int(utente_id)
        except ValueError:
            pass

    sql = Q.render('admin_log', azione=azione, utente_id=uid, data_da=data_da, data_a=data_a)
    return jsonify(query_rows(sql, {'azione': azione, 'utente_id': uid, 'data_da': data_da, 'data_a': data_a, 'limite': limite}))


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
        eventi = query_rows(Q.get('notif_eventi_recenti'), {'passeggero_id': pid})
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
        ricariche = query_rows(Q.get('notif_ricariche'), {'utente_id': session['utente_id']})
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
        imminenti = query_rows(Q.get('notif_imminenti'), {'passeggero_id': pid})
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
        ritardi = query_rows(Q.get('notif_ritardi'), {'passeggero_id': pid})
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
        nuove = query_rows(Q.get('notif_compagnia_prenotazioni'), {'compagnia_id': cid})
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
        pendenti = query_rows(Q.get('notif_operatore_pendenti'), {'oggi': oggi})
        for pend in pendenti:
            risultato.append({
                'id':        f"checkin_pend_{pend['codice_volo']}_{oggi}",
                'icona':     'bi-person-check',
                'testo':     f"{pend['n']} passeggero/i senza check-in su {pend['codice_volo']} oggi",
                'timestamp': ora_dt.strftime('%Y-%m-%d %H:%M:%S'),
                'tipo':      'checkin',
            })

    elif ruolo == 'admin':
        nuovi_reg = query_row(Q.get('notif_admin_nuovi_utenti'))
        if nuovi_reg and nuovi_reg['n'] > 0:
            risultato.append({
                'id':        f"nuovi_utenti_{ora_dt.date()}",
                'icona':     'bi-person-plus',
                'testo':     f"{nuovi_reg['n']} nuova/e registrazione/i nell'ultima settimana",
                'timestamp': ora_dt.strftime('%Y-%m-%d %H:%M:%S'),
                'tipo':      'admin',
            })
        login_fail = query_row(Q.get('notif_admin_login_fail'))
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
