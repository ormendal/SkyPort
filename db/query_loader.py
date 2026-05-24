"""
Caricatore di query SQL esternalizzate per SkyPort.
Le query sono definite in db/queries.sql con la sintassi:

    -- :nome_query
    SELECT ...
    FROM   ...

Le query dinamiche usano Jinja2 per i blocchi condizionali:
    {% if campo %}AND tabella.campo = :campo{% endif %}

Utilizzo in app.py:
    from db.query_loader import Q

    # Query statica
    rows = query_rows(Q.get('lista_aeroporti'))

    # Query dinamica con parametri contestuali
    sql = Q.render('cerca_voli', origine='MXP', destinazione='', data='')
    rows = query_rows(sql, {'origine': 'MXP', 'destinazione': '', 'data': ''})
"""

import os
from jinja2 import Environment

_QUERIES_FILE = os.path.join(os.path.dirname(__file__), 'queries.sql')
_queries = {}
_env = Environment()


def _carica():
    """Legge queries.sql e popola il dizionario interno nome → testo SQL."""
    with open(_QUERIES_FILE, encoding='utf-8') as f:
        content = f.read()

    current_name = None
    current_lines = []

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith('-- :'):
            if current_name is not None:
                _queries[current_name] = '\n'.join(current_lines).strip()
            current_name = stripped[4:].strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_name is not None:
        _queries[current_name] = '\n'.join(current_lines).strip()


class Q:
    """Interfaccia per accedere alle query SQL esternalizzate in queries.sql."""

    @staticmethod
    def get(name):
        """Restituisce il testo SQL grezzo di una query statica."""
        try:
            return _queries[name]
        except KeyError:
            raise KeyError(f"Query '{name}' non trovata in queries.sql") from None

    @staticmethod
    def render(name, **kwargs):
        """Renderizza una query dinamica Jinja2 con i valori dei filtri."""
        template = _env.from_string(Q.get(name))
        return template.render(**kwargs)


_carica()
