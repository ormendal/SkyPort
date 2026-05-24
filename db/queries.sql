-- =============================================================================
-- SkyPort — Query SQL esternalizzate
-- Formato: ogni sezione inizia con "-- :nome_query"
-- Parametri nominali (:nome) per SQLite; blocchi {% if %} per query dinamiche
-- =============================================================================

-- =============================================================================
-- Aeroporti
-- =============================================================================

-- :lista_aeroporti
SELECT id, codice, nome, lat, lon FROM aeroporti ORDER BY codice

-- =============================================================================
-- Voli (pubblici)
-- =============================================================================

-- :voli_attivi
SELECT v.id, v.codice_volo, c.nome AS compagnia,
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
ORDER BY v.data_ora_partenza

-- :cerca_voli
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
{% if origine %}AND v.origine = :origine{% endif %}
{% if destinazione %}AND v.destinazione = :destinazione{% endif %}
{% if data %}AND DATE(v.data_ora_partenza) = :data{% endif %}
AND v.data_ora_partenza > datetime('now', 'localtime')
ORDER BY v.data_ora_partenza

-- :volo_by_id
SELECT * FROM voli WHERE id = :id

-- :posti_occupati_carta
SELECT ci.numero_posto
FROM   carte_imbarco ci
JOIN   prenotazioni p ON ci.prenotazione_id = p.id
WHERE  p.volo_id = :volo_id AND ci.numero_posto IS NOT NULL

-- =============================================================================
-- Autenticazione e utenti
-- =============================================================================

-- :utente_by_username
SELECT * FROM utenti WHERE username = :username

-- :passeggero_by_doc
SELECT id FROM passeggeri WHERE documento = :documento

-- :utente_by_username_check
SELECT id FROM utenti WHERE username = :username

-- :insert_passeggero
INSERT INTO passeggeri (nome, cognome, documento) VALUES (:nome, :cognome, :documento)

-- :insert_utente_passeggero
INSERT INTO utenti (username, password_hash, ruolo, passeggero_id)
VALUES (:username, :password_hash, 'passeggero', :passeggero_id)

-- =============================================================================
-- Prenotazioni (passeggero)
-- =============================================================================

-- :posti_occupati_count
SELECT COUNT(*) FROM prenotazioni
WHERE volo_id = :volo_id AND stato IN ('prenotata', 'pagata')

-- :pren_esistente
SELECT id FROM prenotazioni
WHERE passeggero_id = :passeggero_id AND volo_id = :volo_id AND stato != 'cancellata'

-- :pren_pnr_check
SELECT id FROM prenotazioni WHERE codice_prenotazione = :pnr

-- :insert_prenotazione
INSERT INTO prenotazioni (passeggero_id, volo_id, codice_prenotazione, prezzo, stato)
VALUES (:passeggero_id, :volo_id, :pnr, :prezzo, 'prenotata')

-- :mie_prenotazioni
SELECT p.id, p.codice_prenotazione, p.data_prenotazione, p.prezzo,
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
WHERE  p.passeggero_id = :passeggero_id
ORDER BY v.data_ora_partenza

-- :pren_by_id_passeggero
SELECT * FROM prenotazioni WHERE id = :id AND passeggero_id = :passeggero_id

-- :crediti_passeggero
SELECT crediti FROM passeggeri WHERE id = :id

-- :update_pren_pagata
UPDATE prenotazioni SET stato = 'pagata' WHERE id = :id

-- :update_crediti_scala
UPDATE passeggeri SET crediti = crediti - :importo WHERE id = :id

-- :volo_info_ricevuta
SELECT v.codice_volo, v.origine, v.destinazione, v.data_ora_partenza, c.nome AS compagnia
FROM   voli v
JOIN   compagnie_aeree c ON v.compagnia_id = c.id
WHERE  v.id = :volo_id

-- :carta_by_pren
SELECT id FROM carte_imbarco WHERE prenotazione_id = :pren_id

-- :insert_carta_imbarco_online
INSERT INTO carte_imbarco (prenotazione_id, numero_posto, gate_imbarco_id, operatore_id)
VALUES (:pren_id, :numero_posto, :gate_id, NULL)

-- :update_pren_imbarcato
UPDATE prenotazioni SET stato = 'imbarcato' WHERE id = :id

-- :update_pren_cancellata
UPDATE prenotazioni SET stato = 'cancellata' WHERE id = :id

-- =============================================================================
-- Storico, valutazioni, crediti, profilo (passeggero)
-- =============================================================================

-- :passeggero_storico
SELECT p.id AS prenotazione_id, p.codice_prenotazione, p.prezzo, p.valutazione,
       v.codice_volo, c.nome AS compagnia, v.origine, v.destinazione,
       v.data_ora_partenza, v.data_ora_arrivo,
       ci.numero_posto
FROM   prenotazioni p
JOIN   voli v            ON p.volo_id = v.id
JOIN   compagnie_aeree c ON v.compagnia_id = c.id
LEFT JOIN carte_imbarco ci ON ci.prenotazione_id = p.id
WHERE  p.passeggero_id = :passeggero_id AND p.stato = 'imbarcato' AND v.stato = 'arrivato'
ORDER BY v.data_ora_partenza DESC

-- :pren_valuta
SELECT p.*, v.stato AS stato_volo FROM prenotazioni p
JOIN voli v ON p.volo_id = v.id
WHERE p.id = :id AND p.passeggero_id = :passeggero_id

-- :update_valutazione
UPDATE prenotazioni SET valutazione = :valutazione WHERE id = :id

-- :profilo_passeggero
SELECT nome, cognome, documento, crediti FROM passeggeri WHERE id = :id

-- :utente_username
SELECT username FROM utenti WHERE id = :id

-- :passeggero_full
SELECT * FROM passeggeri WHERE id = :id

-- :utente_full
SELECT * FROM utenti WHERE id = :id

-- :doc_altro_passeggero
SELECT id FROM passeggeri WHERE documento = :documento AND id != :id

-- :update_passeggero_anagrafica
UPDATE passeggeri SET nome = :nome, cognome = :cognome, documento = :documento WHERE id = :id

-- :username_altro_utente
SELECT id FROM utenti WHERE username = :username AND id != :id

-- :update_username
UPDATE utenti SET username = :username WHERE id = :id

-- :update_password
UPDATE utenti SET password_hash = :password_hash WHERE id = :id

-- :update_crediti_aggiungi
UPDATE passeggeri SET crediti = crediti + :importo WHERE id = :id

-- =============================================================================
-- Compagnia
-- =============================================================================

-- :compagnia_lista_voli
SELECT v.id, v.codice_volo, v.origine, v.destinazione,
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
WHERE  v.compagnia_id = :compagnia_id
ORDER BY v.data_ora_partenza

-- :volo_compagnia
SELECT * FROM voli WHERE id = :id AND compagnia_id = :compagnia_id

-- :insert_volo
INSERT INTO voli
    (codice_volo, compagnia_id, gate_id, origine, destinazione,
     data_ora_partenza, data_ora_arrivo, posti_totali, stato, prezzo_base)
VALUES (:codice_volo, :compagnia_id, :gate_id, :origine, :destinazione,
        :data_ora_partenza, :data_ora_arrivo, :posti_totali, 'programmato', :prezzo_base)

-- :pren_attive_volo
SELECT COUNT(*) AS n FROM prenotazioni
WHERE volo_id = :volo_id AND stato IN ('prenotata', 'pagata')

-- :delete_volo
DELETE FROM voli WHERE id = :id

-- :update_volo
UPDATE voli
SET gate_id           = :gate_id,
    data_ora_partenza = :data_ora_partenza,
    data_ora_arrivo   = :data_ora_arrivo,
    posti_totali      = :posti_totali,
    stato             = :stato,
    prezzo_base       = :prezzo_base,
    orario_stimato    = :orario_stimato,
    ritardo_note      = :ritardo_note
WHERE id = :id

-- :compagnia_passeggeri_volo
SELECT p.id AS prenotazione_id, pass.id AS passeggero_id,
       pass.nome, pass.cognome, pass.documento,
       p.stato AS stato_prenotazione,
       p.codice_prenotazione,
       ci.numero_posto
FROM   prenotazioni p
JOIN   passeggeri pass ON p.passeggero_id = pass.id
LEFT JOIN carte_imbarco ci ON ci.prenotazione_id = p.id
WHERE  p.volo_id = :volo_id
ORDER BY pass.cognome, pass.nome

-- =============================================================================
-- Operatore
-- =============================================================================

-- :gate_list
SELECT g.id, g.codice, g.stato,
       GROUP_CONCAT(v.codice_volo, ', ') AS voli_assegnati
FROM   gate g
LEFT JOIN voli v ON v.gate_id = g.id AND v.stato != 'arrivato'
GROUP BY g.id
ORDER BY g.codice

-- :gate_by_id
SELECT * FROM gate WHERE id = :id

-- :update_gate
UPDATE gate SET stato = :stato WHERE id = :id

-- :operatore_voli_oggi
SELECT v.id, v.codice_volo, c.nome AS compagnia_nome,
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
WHERE  DATE(v.data_ora_partenza) = :data
ORDER BY v.data_ora_partenza

-- :checkin_by_pnr
SELECT p.id, p.codice_prenotazione, p.volo_id,
       v.codice_volo, v.origine, v.destinazione, v.data_ora_partenza,
       v.posti_totali, v.gate_id,
       pass.nome AS passeggero_nome, pass.cognome AS passeggero_cognome,
       pass.documento
FROM   prenotazioni p
JOIN   voli v          ON p.volo_id = v.id
JOIN   passeggeri pass ON p.passeggero_id = pass.id
LEFT JOIN carte_imbarco ci ON ci.prenotazione_id = p.id
WHERE  p.codice_prenotazione = :pnr AND p.stato = 'pagata' AND ci.id IS NULL

-- :checkin_by_nome_cognome
SELECT p.id, p.codice_prenotazione, p.volo_id,
       v.codice_volo, v.origine, v.destinazione, v.data_ora_partenza,
       v.posti_totali, v.gate_id,
       pass.nome AS passeggero_nome, pass.cognome AS passeggero_cognome,
       pass.documento
FROM   prenotazioni p
JOIN   voli v          ON p.volo_id = v.id
JOIN   passeggeri pass ON p.passeggero_id = pass.id
LEFT JOIN carte_imbarco ci ON ci.prenotazione_id = p.id
WHERE  LOWER(pass.nome) = LOWER(:nome) AND LOWER(pass.cognome) = LOWER(:cognome)
  AND  p.stato = 'pagata' AND ci.id IS NULL
ORDER BY v.data_ora_partenza

-- :passeggero_by_doc_full
SELECT * FROM passeggeri WHERE documento = :documento

-- :checkin_by_documento
SELECT p.id, p.codice_prenotazione, p.volo_id,
       v.codice_volo, v.origine, v.destinazione, v.data_ora_partenza,
       v.posti_totali, v.gate_id,
       pass.nome AS passeggero_nome, pass.cognome AS passeggero_cognome,
       pass.documento
FROM   prenotazioni p
JOIN   voli v          ON p.volo_id = v.id
JOIN   passeggeri pass ON p.passeggero_id = pass.id
LEFT JOIN carte_imbarco ci ON ci.prenotazione_id = p.id
WHERE  p.passeggero_id = :passeggero_id AND p.stato = 'pagata' AND ci.id IS NULL
ORDER BY v.data_ora_partenza

-- :insert_carta_imbarco_banco
INSERT INTO carte_imbarco (prenotazione_id, numero_posto, gate_imbarco_id, operatore_id)
VALUES (:pren_id, :numero_posto, :gate_id, :operatore_id)

-- :pren_checkin_exec
SELECT p.*, v.posti_totali, v.gate_id AS volo_gate_id
FROM   prenotazioni p
JOIN   voli v ON p.volo_id = v.id
WHERE  p.id = :id AND p.stato = 'pagata'

-- :nominativo_passeggero
SELECT pas.nome || ' ' || pas.cognome AS nominativo
FROM   prenotazioni pr
JOIN   passeggeri pas ON pr.passeggero_id = pas.id
WHERE  pr.id = :pren_id

-- =============================================================================
-- Admin
-- =============================================================================

-- :admin_stats_voli_totale
SELECT COUNT(*) AS n FROM voli

-- :admin_stats_voli_per_stato
SELECT stato, COUNT(*) AS numero FROM voli GROUP BY stato ORDER BY stato

-- :admin_stats_pren_totale
SELECT COUNT(*) AS n FROM prenotazioni

-- :admin_stats_pren_per_stato
SELECT stato, COUNT(*) AS numero FROM prenotazioni GROUP BY stato ORDER BY stato

-- :admin_stats_passeggeri
SELECT COUNT(*) AS n FROM passeggeri

-- :admin_stats_compagnie
SELECT COUNT(*) AS n FROM compagnie_aeree

-- :admin_stats_gate_totale
SELECT COUNT(*) AS n FROM gate

-- :admin_stats_gate_per_stato
SELECT stato, COUNT(*) AS numero FROM gate GROUP BY stato ORDER BY stato

-- :admin_stats_carte
SELECT COUNT(*) AS n FROM carte_imbarco

-- :admin_storico_voli
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
{% if stato %}AND v.stato = :stato{% endif %}
{% if compagnia_id %}AND v.compagnia_id = :compagnia_id{% endif %}
{% if data %}AND DATE(v.data_ora_partenza) = :data{% endif %}
ORDER BY v.data_ora_partenza DESC

-- :admin_lista_utenti
SELECT u.id, u.username, u.ruolo, u.attivo,
       u.compagnia_id, c.nome AS compagnia_nome,
       u.passeggero_id, p.nome AS passeggero_nome, p.cognome AS passeggero_cognome
FROM   utenti u
LEFT JOIN compagnie_aeree c ON u.compagnia_id = c.id
LEFT JOIN passeggeri p      ON u.passeggero_id = p.id
ORDER BY u.id

-- :utente_by_id
SELECT id FROM utenti WHERE id = :id

-- :utente_full_admin
SELECT u.*, c.nome AS compagnia_nome FROM utenti u
LEFT JOIN compagnie_aeree c ON u.compagnia_id = c.id
WHERE u.id = :id

-- :voli_compagnia_programmati
SELECT COUNT(*) AS n FROM voli WHERE compagnia_id = :compagnia_id AND stato = 'programmato'

-- :pren_attive_passeggero
SELECT COUNT(*) AS n FROM prenotazioni
WHERE passeggero_id = :passeggero_id AND stato IN ('prenotata', 'pagata')

-- :update_utente_attivo
UPDATE utenti SET attivo = :attivo WHERE id = :id

-- :delete_utente
DELETE FROM utenti WHERE id = :id

-- :insert_aeroporto
INSERT INTO aeroporti (codice, nome, lat, lon) VALUES (:codice, :nome, :lat, :lon)

-- :admin_log
SELECT l.id, l.utente_id, u.username,
       l.azione, l.dettagli, l.timestamp
FROM   log l
LEFT JOIN utenti u ON l.utente_id = u.id
WHERE  1=1
{% if azione %}AND l.azione = :azione{% endif %}
{% if utente_id %}AND l.utente_id = :utente_id{% endif %}
{% if data_da %}AND DATE(l.timestamp) >= :data_da{% endif %}
{% if data_a %}AND DATE(l.timestamp) <= :data_a{% endif %}
ORDER BY l.timestamp DESC LIMIT :limite

-- =============================================================================
-- Log di sistema
-- =============================================================================

-- :log_insert
INSERT INTO log (utente_id, azione, dettagli) VALUES (:uid, :azione, :dettagli)

-- =============================================================================
-- Notifiche — passeggero
-- =============================================================================

-- :notif_eventi_recenti
SELECT p.id, p.codice_prenotazione, p.data_prenotazione,
       p.prezzo, p.stato, v.codice_volo
FROM   prenotazioni p
JOIN   voli v ON p.volo_id = v.id
WHERE  p.passeggero_id = :passeggero_id
  AND  p.data_prenotazione >= datetime('now', '-7 days')
ORDER BY p.data_prenotazione DESC

-- :notif_ricariche
SELECT l.dettagli, l.timestamp FROM log l
WHERE  l.utente_id = :utente_id AND l.azione = 'ricarica_crediti'
  AND  l.timestamp >= datetime('now', '-7 days')
ORDER BY l.timestamp DESC

-- :notif_imminenti
SELECT p.codice_prenotazione, v.codice_volo, v.destinazione,
       v.data_ora_partenza, v.orario_stimato
FROM   prenotazioni p
JOIN   voli v ON p.volo_id = v.id
WHERE  p.passeggero_id = :passeggero_id AND p.stato IN ('pagata', 'imbarcato')
  AND  v.stato = 'programmato'
  AND  datetime(COALESCE(v.orario_stimato, v.data_ora_partenza))
       BETWEEN datetime('now') AND datetime('now', '+24 hours')
ORDER BY v.data_ora_partenza

-- :notif_ritardi
SELECT p.codice_prenotazione, v.codice_volo, v.orario_stimato
FROM   prenotazioni p
JOIN   voli v ON p.volo_id = v.id
WHERE  p.passeggero_id = :passeggero_id AND p.stato IN ('prenotata', 'pagata', 'imbarcato')
  AND  v.stato = 'programmato' AND v.orario_stimato IS NOT NULL

-- =============================================================================
-- Notifiche — compagnia
-- =============================================================================

-- :notif_compagnia_prenotazioni
SELECT v.codice_volo, COUNT(*) AS n
FROM   prenotazioni p
JOIN   voli v ON p.volo_id = v.id
WHERE  v.compagnia_id = :compagnia_id
  AND  p.data_prenotazione >= datetime('now', '-7 days')
  AND  p.stato != 'cancellata'
GROUP BY v.codice_volo
ORDER BY n DESC

-- =============================================================================
-- Notifiche — operatore
-- =============================================================================

-- :notif_operatore_pendenti
SELECT v.codice_volo, COUNT(*) AS n
FROM   prenotazioni p
JOIN   voli v ON p.volo_id = v.id
LEFT JOIN carte_imbarco ci ON ci.prenotazione_id = p.id
WHERE  DATE(v.data_ora_partenza) = :oggi AND p.stato = 'pagata' AND ci.id IS NULL
GROUP BY v.codice_volo

-- =============================================================================
-- Notifiche — admin
-- =============================================================================

-- :notif_admin_nuovi_utenti
SELECT COUNT(*) AS n FROM log
WHERE azione = 'registrazione' AND timestamp >= datetime('now', '-7 days')

-- :notif_admin_login_fail
SELECT COUNT(*) AS n FROM log
WHERE azione = 'login_failed' AND timestamp >= datetime('now', '-1 day')
