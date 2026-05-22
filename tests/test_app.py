"""
Test automatici per l'API del Sistema Informativo Aeroportuale.
Ogni test usa un database SQLite separato (tmp_path di pytest) per isolamento completo.

Esecuzione locale (mostra output dettagliato e resoconto finale):
    cd aeroporto
    pytest tests/ -v -s

Esecuzione in Docker:
    docker-compose run --rm web pytest tests/ -v -s
"""

import sys
import os
import pytest

# Aggiunge la cartella web al path Python così da poter importare app.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'web'))
import app as flask_app  # noqa: E402

# Percorso assoluto allo schema SQL (relativo a questo file)
_SCHEMA_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'schema.sql')
)


# =============================================================================
# Fixture
# =============================================================================

@pytest.fixture
def app(tmp_path, monkeypatch):
    """
    Configura l'applicazione Flask per i test:
    - usa un database SQLite temporaneo e isolato (uno per test)
    - inizializza schema + dati di seed tramite init_db()
    """
    db_file = str(tmp_path / 'test.db')
    monkeypatch.setattr(flask_app, 'DB_PATH', db_file)
    monkeypatch.setattr(flask_app, 'SCHEMA_PATH', _SCHEMA_PATH)
    flask_app.init_db()
    flask_app.app.config.update(TESTING=True, SECRET_KEY='chiave-test-aeroporto')
    return flask_app.app


@pytest.fixture
def client(app):
    """Restituisce il client HTTP di test Flask con cookie/sessione persistente."""
    return app.test_client()


# =============================================================================
# Helper
# =============================================================================

def _login(client, username='admin', password='password'):
    """Esegue il login via API e restituisce la risposta Flask."""
    return client.post('/api/login', json={'username': username, 'password': password})


# =============================================================================
# Test 1 — Login con credenziali corrette
# =============================================================================

def test_login_success(client):
    """POST /api/login con credenziali valide deve restituire 200 e il ruolo corretto."""
    print("\n▶ Avvio test_login_success")
    r = _login(client, 'admin', 'password')
    assert r.status_code == 200
    dati = r.get_json()
    assert dati['ruolo'] == 'admin'
    assert 'utente_id' in dati
    print("✔ test_login_success completato con successo")


# =============================================================================
# Test 2 — Login con password errata
# =============================================================================

def test_login_failure(client):
    """POST /api/login con password sbagliata deve restituire 401."""
    print("\n▶ Avvio test_login_failure")
    r = _login(client, 'admin', 'password_sbagliata')
    assert r.status_code == 401
    print("✔ test_login_failure completato con successo")


# =============================================================================
# Test 3 — Registrazione con username duplicato
# =============================================================================

def test_registrazione_duplicato(client):
    """
    Registrare due volte lo stesso username deve restituire 201 al primo tentativo
    e 409 al secondo.
    """
    print("\n▶ Avvio test_registrazione_duplicato")
    payload = {
        'nome':     'Test',
        'cognome':  'Duplicato',
        'documento': 'DOCTEST01',
        'username': 'utente_duplicato',
        'password': 'segreto1',  # ≥ 8 caratteri (vincolo minimo)
    }
    r1 = client.post('/api/registrazione', json=payload)
    assert r1.status_code == 201
    print("  Prima registrazione: 201 OK")

    r2 = client.post('/api/registrazione', json=payload)
    assert r2.status_code == 409
    print("  Seconda registrazione: 409 Conflict (atteso)")
    print("✔ test_registrazione_duplicato completato con successo")


# =============================================================================
# Test 4 — Ricerca voli
# =============================================================================

def test_ricerca_voli(client):
    """GET /api/voli/search deve restituire 200 con una lista non vuota di voli."""
    print("\n▶ Avvio test_ricerca_voli")
    r = client.get('/api/voli/search')
    assert r.status_code == 200
    voli = r.get_json()
    assert isinstance(voli, list)
    assert len(voli) > 0
    print(f"  Trovati {len(voli)} voli")
    print("✔ test_ricerca_voli completato con successo")


# =============================================================================
# Test 5 — Overbooking: il terzo passeggero su un volo da 2 posti deve essere rifiutato
# =============================================================================

def test_overbooking(client):
    """
    Un volo con posti_totali=2 e 2 prenotazioni già attive deve rifiutare la terza
    con HTTP 400 e messaggio 'Volo completo'.
    """
    print("\n▶ Avvio test_overbooking")
    # Inserisce direttamente nel DB un volo con soli 2 posti
    conn = flask_app.get_db()
    cur = conn.execute(
        """INSERT INTO voli
               (codice_volo, compagnia_id, origine, destinazione,
                data_ora_partenza, data_ora_arrivo, posti_totali, stato, prezzo_base)
           VALUES ('OB9999', 1, 'MXP', 'FCO',
                   '2027-06-01 10:00', '2027-06-01 11:00', 2, 'programmato', 50.0)"""
    )
    volo_id = cur.lastrowid
    print(f"  Creato volo OB9999 con id={volo_id} e 2 posti")
    # Occupa entrambi i posti con prenotazioni di passeggeri senza account utente
    conn.execute(
        "INSERT INTO prenotazioni (passeggero_id, volo_id, codice_prenotazione, prezzo, stato)"
        " VALUES (4, ?, 'OB0001', 50.0, 'prenotata')",
        (volo_id,)
    )
    conn.execute(
        "INSERT INTO prenotazioni (passeggero_id, volo_id, codice_prenotazione, prezzo, stato)"
        " VALUES (5, ?, 'OB0002', 50.0, 'prenotata')",
        (volo_id,)
    )
    conn.commit()
    conn.close()
    print("  Inserite 2 prenotazioni (pieno)")

    # Tenta una terza prenotazione come passeggero1 (che non ha prenotazioni su questo volo)
    _login(client, 'passeggero1', 'password')
    r = client.post('/api/prenota', json={'volo_id': volo_id})
    assert r.status_code == 400
    assert 'Volo completo' in r.get_json()['errore']
    print("  Terza prenotazione respinta con 400 'Volo completo'")
    print("✔ test_overbooking completato con successo")


# =============================================================================
# Test 6 — Prenotazione senza sessione attiva
# =============================================================================

def test_prenotazione_senza_login(client):
    """POST /api/prenota senza sessione autenticata deve restituire 401."""
    print("\n▶ Avvio test_prenotazione_senza_login")
    r = client.post('/api/prenota', json={'volo_id': 1})
    assert r.status_code == 401
    print("  Richiesta senza login restituisce 401")
    print("✔ test_prenotazione_senza_login completato con successo")


# =============================================================================
# Test 7 — Pagamento con crediti insufficienti + ricarica + pagamento riuscito
# =============================================================================

def test_pagamento_crediti_insufficienti(client):
    """
    Sequenza completa:
    1. Nuovo passeggero registrato (crediti = 0 per default)
    2. Prenotazione su volo 1 (EN1234, prezzo_base = 120)
    3. Tentativo di pagamento → 400 (crediti insufficienti)
    4. Ricarica 200 crediti → 200
    5. Pagamento → 200 (stato diventa 'pagata')
    """
    print("\n▶ Avvio test_pagamento_crediti_insufficienti")
    # 1. Registrazione di un nuovo passeggero con 0 crediti
    r = client.post('/api/registrazione', json={
        'nome':     'Prova',
        'cognome':  'Crediti',
        'documento': 'PROVA001',
        'username': 'prova_crediti',
        'password': 'pass1234',  # ≥ 8 caratteri (vincolo minimo)
    })
    assert r.status_code == 201
    print("  Registrazione nuovo utente: 201")

    # 2. Login
    _login(client, 'prova_crediti', 'pass1234')
    print("  Login effettuato")

    # 3. Prenotazione volo 1 (EN1234, programmato, prezzo_base=120)
    r = client.post('/api/prenota', json={'volo_id': 1})
    assert r.status_code == 201
    pren_id = r.get_json()['prenotazione_id']
    print(f"  Prenotazione creata con id={pren_id}")

    # 4. Pagamento con crediti a zero → 400
    r = client.post(f'/api/paga/{pren_id}')
    assert r.status_code == 400
    assert 'insufficienti' in r.get_json()['errore'].lower()
    print("  Pagamento rifiutato: crediti insufficienti (atteso)")

    # 5. Ricarica portafoglio con 200 crediti → 200
    r = client.post('/api/passeggero/ricarica', json={'importo': 200.0})
    assert r.status_code == 200
    print("  Ricarica di 200 crediti effettuata")

    # 6. Pagamento ora sufficiente → 200
    r = client.post(f'/api/paga/{pren_id}')
    assert r.status_code == 200
    assert r.get_json()['nuovo_stato'] == 'pagata'
    print("  Pagamento riuscito, stato='pagata'")
    print("✔ test_pagamento_crediti_insufficienti completato con successo")


# =============================================================================
# Test 8 — Check-in online
# =============================================================================

def test_checkin_online(client):
    """
    Il check-in online su una prenotazione 'pagata' deve:
      - restituire 200
      - impostare operatore_id = NULL nella carta d'imbarco (non è check-in al banco)
    Il check-in su una prenotazione 'prenotata' deve restituire 400.
    """
    print("\n▶ Avvio test_checkin_online")
    _login(client, 'passeggero1', 'password')

    # Prenotazione 11 (KK7890): passeggero1, volo 5 (EN7890), stato='pagata', senza CI
    r = client.post('/api/checkin_online/11')
    assert r.status_code == 200
    assert 'carta_imbarco_id' in r.get_json()
    print("  Check-in online su prenotazione 11 riuscito")

    # Verifica che operatore_id sia NULL (il check-in online non ha operatore)
    conn = flask_app.get_db()
    riga = conn.execute(
        "SELECT operatore_id FROM carte_imbarco WHERE prenotazione_id = 11"
    ).fetchone()
    conn.close()
    assert riga is not None
    assert riga['operatore_id'] is None
    print("  Verificato: operatore_id = NULL")

    # Prenotazione 1 (AA1234): passeggero1, volo 1, stato='prenotata' → non ammesso
    r = client.post('/api/checkin_online/1')
    assert r.status_code == 400
    print("  Check-in online su prenotazione non pagata: 400 (atteso)")
    print("✔ test_checkin_online completato con successo")


# =============================================================================
# Test 9 — Check-in al banco da parte dell'operatore
# =============================================================================

def test_operatore_checkin(client):
    """
    L'operatore che esegue il check-in al banco deve:
      - restituire 201
      - valorizzare operatore_id nella carta d'imbarco con il proprio utente_id
    """
    print("\n▶ Avvio test_operatore_checkin")
    _login(client, 'operatore1', 'password')

    # Passeggero1 (documento IT00001) ha la prenotazione 11 (KK7890) pagata e senza CI
    r = client.post('/api/operatore/checkin', json={'documento': 'IT00001'})
    assert r.status_code == 201
    print("  Check-in al banco per documento IT00001: 201")

    # Verifica che operatore_id sia valorizzato (utente_id=3 per operatore1 nel seed)
    conn = flask_app.get_db()
    riga = conn.execute(
        "SELECT operatore_id FROM carte_imbarco WHERE prenotazione_id = 11"
    ).fetchone()
    conn.close()
    assert riga is not None
    assert riga['operatore_id'] is not None
    print(f"  Verificato: operatore_id = {riga['operatore_id']} (valore atteso: 3)")
    print("✔ test_operatore_checkin completato con successo")