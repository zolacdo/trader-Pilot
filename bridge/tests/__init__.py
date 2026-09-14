"""Suite de tests du Bridge TradePilot.

Ce module est importe par pytest AVANT ``conftest.py`` et avant tout module de
test : c'est donc l'endroit ou l'environnement est fige, une fois pour toutes,
avant que ``app.config.settings`` ne construise son objet ``Settings`` mis en
cache.

Trois garanties sont posees ici :

* ``TESTING=true`` force la base SQLite en memoire (aucune ecriture dans
  ``bridge/data``) ;
* ``MASTER_KEY`` est fournie explicitement, sinon la couche de chiffrement
  ecrirait un fichier ``master.key`` sur le disque du projet ;
* ``DATA_DIR`` pointe vers un repertoire temporaire et les integrations
  externes (ngrok, OpenRouter, Telegram) restent non configurees : aucun test
  ne peut atteindre le reseau.
"""

from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path

# Cle Fernet deterministe : 32 octets encodes en base64 url-safe.
_TEST_MASTER_KEY = base64.urlsafe_b64encode(b"tradepilot-tests-master-key-0001").decode()

_TEST_DATA_DIR = Path(tempfile.gettempdir()) / "tradepilot-tests-data"

os.environ["TESTING"] = "true"
os.environ["MASTER_KEY"] = _TEST_MASTER_KEY
os.environ["DATA_DIR"] = str(_TEST_DATA_DIR)
os.environ["NGROK_ENABLED"] = "false"
os.environ["NGROK_AUTHTOKEN"] = ""
os.environ["NGROK_DOMAIN"] = ""
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["TELEGRAM_API_ID"] = ""
os.environ["TELEGRAM_API_HASH"] = ""
os.environ["TELEGRAM_PHONE"] = ""
os.environ["MT5_LOGIN"] = ""
os.environ["MT5_PASSWORD"] = ""
os.environ["MT5_SERVER"] = ""
os.environ["PAIRING_CODE"] = ""
os.environ["CORS_ORIGINS"] = ""

__all__ = ["_TEST_DATA_DIR", "_TEST_MASTER_KEY"]
