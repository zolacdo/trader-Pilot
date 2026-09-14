# TradePilot — Guide de dépannage

Symptômes → causes probables → solutions concrètes.
Pour l'installation complète, voir [BRIDGE_WINDOWS_SETUP.md](BRIDGE_WINDOWS_SETUP.md).

**Premier réflexe, toujours :**

```powershell
cd "C:\Users\<votre-nom>\Desktop\trader apk"
.\scripts\check_environment.ps1
Get-Content bridge\data\logs\bridge-stderr.log -Tail 40
```

---

## Tableau récapitulatif

| # | Symptôme | Causes probables | Solutions |
|---|---|---|---|
| 1 | **Bridge injoignable depuis le téléphone** | Bridge arrêté ; tunnel ngrok fermé ; mauvaise URL dans l'app ; téléphone hors du Wi-Fi sans ngrok ; PC en veille | Vérifier `/api/v1/health` en local, puis l'URL publique ; redémarrer le Bridge ; corriger l'URL dans l'app ; désactiver la veille du PC |
| 2 | **MT5 non connecté** | Terminal fermé ; compte déconnecté ; mauvais chemin `terminal64.exe` ; Python 32 bits ; MT5 lancé sous un autre compte Windows | Lancer et connecter MT5 Desktop, cocher *Conserver le mot de passe*, renseigner `MT5_TERMINAL_PATH`, réinstaller en 64 bits |
| 3 | **« AutoTrading désactivé dans le terminal »** | Bouton *AutoTrading* éteint ; trading algorithmique interdit dans les options ; compte en lecture seule ; marché fermé | Activer *AutoTrading* (Ctrl+E), cocher *Autoriser le trading algorithmique*, vérifier les droits du compte chez le broker |
| 4 | **Telegram déconnecté** | Session expirée ou révoquée ; `api_id`/`api_hash` erronés ; fichier de session corrompu ; connexion depuis un nouveau lieu | Re-appairer Telegram depuis l'app ; vérifier `TELEGRAM_*` dans `.env` ; supprimer `bridge\data\sessions\*` et refaire la connexion |
| 5 | **OpenRouter 429 (trop de requêtes)** | Quota gratuit atteint ; trop de signaux analysés d'affilée ; pas de cache | Attendre la fenêtre de quota ; réduire le nombre de canaux suivis ; laisser le Bridge appliquer son backoff ; ajouter une clé personnelle |
| 6 | **Aucun modèle gratuit disponible** | Modèle préféré retiré du catalogue ; tous les modèles `:free` saturés ; `OPENROUTER_FREE_ONLY=true` bloque le repli payant | Vider `OPENROUTER_PREFERRED_TEXT_MODEL` pour laisser la sélection automatique ; réessayer plus tard ; en connaissance de cause, passer `OPENROUTER_FREE_ONLY=false` |
| 7 | **Tunnel ngrok expiré / URL changée** | Agent arrêté ; domaine non réservé (URL aléatoire) ; `ERR_NGROK_108` (déjà une session) ; token invalide | Réserver un domaine et le mettre dans `NGROK_DOMAIN` ; `Stop-Process -Name ngrok -Force` puis redémarrer ; refaire `setup_ngrok.ps1` |
| 8 | **Base verrouillée (`database is locked`)** | Deux Bridges lancés en parallèle ; fichier SQLite ouvert par un autre outil ; arrêt brutal ; antivirus qui scanne `data\` | Arrêter tous les Bridges, ne garder qu'une instance ; fermer les visionneuses SQLite ; exclure `bridge\data\` de l'antivirus |
| 9 | **Session Telegram invalide** | `MASTER_KEY` modifiée ou perdue ; session révoquée depuis un autre appareil ; fichier `.session` corrompu | Restaurer la sauvegarde de `bridge\.env` ; sinon supprimer la session et se reconnecter (code SMS) |
| 10 | **L'APK ne se connecte pas** | Mauvaise URL ; code d'appairage expiré ; certificat/HTTPS ; Bridge sur un autre réseau ; version d'app obsolète | Tester l'URL dans le navigateur du téléphone ; regénérer le code d'appairage ; toujours utiliser `https://` avec ngrok ; réinstaller l'APK |

---

## 1. Bridge injoignable depuis le téléphone

**Diagnostic, dans l'ordre :**

```powershell
# a) Le processus tourne-t-il ?
.\scripts\install_autostart.ps1 -Status
Get-Process -Id (Get-Content bridge\data\bridge.pid) -ErrorAction SilentlyContinue

# b) L'API répond-elle en local ?
Invoke-RestMethod http://127.0.0.1:8787/api/v1/health

# c) Le tunnel est-il ouvert ?
(Invoke-RestMethod http://127.0.0.1:4040/api/tunnels).tunnels.public_url

# d) L'URL publique répond-elle depuis le PC ?
Invoke-RestMethod https://<votre-domaine>.ngrok-free.app/api/v1/health
```

**Interprétation :**

| Résultat | Conclusion | Action |
|---|---|---|
| (b) échoue | le Bridge ne tourne pas | `.\scripts\start_bridge_background.ps1` puis lire `bridge-stderr.log` |
| (b) OK, (c) vide | le tunnel n'est pas ouvert | vérifier `NGROK_ENABLED=true` et le token, voir §7 |
| (c) OK, (d) échoue | domaine incohérent | `NGROK_DOMAIN` doit être identique au domaine réservé |
| (d) OK, téléphone KO | problème côté app ou réseau mobile | voir §10 |

**Cause fréquente : le PC se met en veille.** Le Bridge s'arrête avec lui.

```powershell
# Console ADMINISTRATEUR : désactiver la veille sur secteur
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
```

---

## 2. MT5 non connecté

**Vérifications :**

```powershell
Get-Process terminal64                       # le terminal tourne-t-il ?
.\scripts\check_environment.ps1              # section « MetaTrader 5 »
bridge\.venv\Scripts\python.exe -c "import MetaTrader5 as m; print(m.initialize(), m.last_error())"
```

`m.initialize()` doit renvoyer `True`. Codes d'erreur courants :

| Code | Signification | Solution |
|---|---|---|
| `(-10005, 'IPC timeout')` | le terminal ne répond pas | fermer complètement MT5 et le relancer, puis redémarrer le Bridge |
| `(-10003, 'IPC initialize failed')` | terminal introuvable ou non lancé | lancer MT5, renseigner `MT5_TERMINAL_PATH` |
| `(-10004, 'IPC no connection')` | terminal non connecté au serveur du broker | se reconnecter dans MT5 (identifiant, mot de passe, serveur) |

**Pièges classiques :**

- Python **32 bits** avec un MT5 **64 bits** : incompatible, réinstaller Python 64 bits ;
- MT5 lancé en administrateur alors que le Bridge ne l'est pas (ou l'inverse) :
  les deux doivent tourner dans **la même session, au même niveau de privilège** ;
- plusieurs installations MT5 (plusieurs brokers) : renseignez explicitement
  `MT5_TERMINAL_PATH` pour lever l'ambiguïté ;
- le Bridge démarré par la tâche planifiée avant MT5 : le délai de 60 s aide,
  mais mettez aussi MT5 dans `shell:startup`.

---

## 3. « AutoTrading désactivé dans le terminal »

Le Bridge reçoit l'erreur MT5 `10027 / TRADE_RETCODE_CLIENT_DISABLES_AT`.

**Dans MetaTrader 5 :**

1. barre d'outils : le bouton **AutoTrading** doit être **vert** (raccourci `Ctrl+E`) ;
2. *Outils → Options → Expert Advisors* : cocher **Autoriser le trading
   algorithmique** ;
3. après un redémarrage de MT5, le bouton revient parfois à l'état désactivé :
   revérifiez-le à chaque lancement — c'est la cause n°1 des ordres refusés au
   démarrage automatique.

**Autres refus d'ordre à ne pas confondre :**

| Code MT5 | Signification | Solution |
|---|---|---|
| `10018` | marché fermé | attendre l'ouverture de la session |
| `10019` | fonds insuffisants | réduire le lot ou alimenter le compte démo |
| `10016` | stops invalides (SL/TP trop proches) | respecter le `stops_level` du symbole |
| `10014` | volume invalide | arrondir au pas de lot du symbole |
| `10006` | ordre rejeté par le serveur | vérifier le symbole (suffixe Exness type `XAUUSDm`) |

---

## 4. Telegram déconnecté

**Symptômes :** plus aucun signal ne remonte, le diagnostic de l'app indique
Telegram hors ligne, les journaux montrent `AuthKeyUnregisteredError` ou
`SessionRevokedError`.

**Causes et solutions :**

1. **Session révoquée** depuis un autre appareil
   (Telegram → *Paramètres → Appareils → Terminer la session*) :
   il faut refaire l'appairage depuis l'application TradePilot (code SMS).
2. **`api_id` / `api_hash` incorrects** : revérifiez sur <https://my.telegram.org>.
   Ils doivent être ceux **de votre compte**, pas ceux d'un bot.
3. **Fichier de session corrompu** (coupure de courant, disque plein) :

```powershell
.\scripts\stop_bridge.ps1
Get-ChildItem bridge\data\sessions
# Sauvegarder avant de supprimer :
Move-Item bridge\data\sessions bridge\data\sessions.bak
.\scripts\start_bridge_background.ps1   # puis refaire la connexion depuis l'app
```

4. **Trop de tentatives** : Telegram impose un délai (`FloodWaitError`, parfois
   plusieurs heures). Le message indique le nombre de secondes à attendre —
   attendez, ne relancez pas en boucle, cela rallonge le délai.

---

## 5. OpenRouter 429 (trop de requêtes)

**Symptôme :** `429 Too Many Requests` dans les journaux, l'analyse des signaux
s'interrompt ou se met en file d'attente.

**Ce qui est normal :** l'offre gratuite d'OpenRouter est limitée en requêtes
par minute **et** par jour. Le Bridge applique un backoff exponentiel et
réessaie ; un 429 isolé n'est pas une panne.

**Si c'est permanent :**

- réduisez le nombre de canaux Telegram suivis (chaque message analysé coûte une
  requête) ;
- désactivez l'analyse IA des images/graphiques si elle n'est pas indispensable ;
- vérifiez que le cache d'analyse fonctionne : un même message ne doit jamais
  être envoyé deux fois au modèle ;
- créez votre propre clé sur <https://openrouter.ai/keys> et renseignez-la dans
  `OPENROUTER_API_KEY` (une clé partagée sature immédiatement) ;
- consultez votre consommation sur <https://openrouter.ai/activity>.

**À ne pas faire :** relancer le Bridge en boucle pour « débloquer » — cela
consomme le quota restant.

---

## 6. Aucun modèle gratuit disponible

**Symptôme :** message du type « aucun modèle gratuit disponible » ou
`404 model not found` sur le modèle préféré.

**Causes :**

1. le modèle indiqué dans `OPENROUTER_PREFERRED_TEXT_MODEL` a été retiré du
   catalogue (le catalogue gratuit change souvent) ;
2. tous les modèles `:free` sont temporairement saturés ;
3. `OPENROUTER_FREE_ONLY=true` interdit — volontairement — le repli sur un
   modèle payant.

**Solutions :**

```powershell
# 1. Laisser le Bridge choisir automatiquement un modèle gratuit disponible
#    -> vider la ligne dans bridge\.env :
#    OPENROUTER_PREFERRED_TEXT_MODEL=
notepad bridge\.env

# 2. Voir les modèles gratuits actuellement proposés
(Invoke-RestMethod https://openrouter.ai/api/v1/models).data |
    Where-Object { $_.id -like "*:free" } |
    Select-Object -ExpandProperty id
```

Choisissez un identifiant de cette liste et remettez-le dans
`OPENROUTER_PREFERRED_TEXT_MODEL`, puis redémarrez le Bridge.

`OPENROUTER_FREE_ONLY=false` autorise les modèles payants : **cela peut être
facturé**. Ne le faites qu'en connaissance de cause, avec un crédit plafonné.

---

## 7. Tunnel ngrok expiré ou URL qui change

| Symptôme | Cause | Solution |
|---|---|---|
| L'URL change à chaque démarrage | aucun domaine réservé : ngrok attribue une adresse aléatoire | réserver un domaine gratuit et le mettre dans `NGROK_DOMAIN` |
| `ERR_NGROK_108` | une session d'agent est déjà active (offre gratuite = 1 session) | `Stop-Process -Name ngrok -Force`, puis redémarrer le Bridge |
| `ERR_NGROK_105` / `4018` | token absent, invalide ou non enregistré | `.\scripts\setup_ngrok.ps1 -AuthToken <token>` |
| `ERR_NGROK_313` / `8012` | le domaine demandé n'est pas réservé sur votre compte | vérifier l'orthographe exacte sur <https://dashboard.ngrok.com/domains> |
| Tunnel ouvert mais 502 | le Bridge n'écoute pas sur le port annoncé | aligner `BRIDGE_PORT` et `addr:` dans `bridge\data\ngrok.yml` |

**Remise en état complète :**

```powershell
.\scripts\stop_bridge.ps1
Stop-Process -Name ngrok -Force -ErrorAction SilentlyContinue
.\scripts\setup_ngrok.ps1 -AuthToken "<votre-token>" -Domain "<votre-domaine>" -Test
.\scripts\start_bridge_background.ps1
```

Si une session fantôme persiste côté ngrok, arrêtez-la depuis
<https://dashboard.ngrok.com/agents>.

---

## 8. Base verrouillée (`database is locked`)

**Symptôme :** `sqlite3.OperationalError: database is locked` dans
`bridge-stderr.log`, écritures qui échouent, interface figée.

**Cause n°1 : deux Bridges tournent en même temps.**

```powershell
Get-Process python, pythonw -ErrorAction SilentlyContinue |
    Select-Object Id, ProcessName, StartTime

# Tout arrêter proprement, puis relancer une seule instance
.\scripts\stop_bridge.ps1
Stop-Process -Name pythonw -Force -ErrorAction SilentlyContinue
.\scripts\start_bridge_background.ps1
```

Cela arrive typiquement quand un démarrage manuel s'ajoute au démarrage
automatique de la tâche planifiée. `start_bridge_background.ps1` est idempotent
(il refuse de lancer un second Bridge), mais `start_bridge.ps1` ne l'est pas :
n'utilisez pas les deux en même temps.

**Autres causes :**

- un explorateur SQLite (DB Browser, DBeaver) garde le fichier ouvert → le fermer ;
- l'antivirus scanne `bridge\data\tradepilot.sqlite3` en continu → ajouter une
  exclusion sur `bridge\data\` ;
- arrêt brutal ayant laissé des fichiers `-wal` / `-shm` :

```powershell
.\scripts\stop_bridge.ps1
Get-ChildItem bridge\data\tradepilot.sqlite3*     # inspecter
Copy-Item bridge\data\tradepilot.sqlite3 bridge\data\tradepilot.backup.sqlite3
bridge\.venv\Scripts\python.exe -c "import sqlite3;print(sqlite3.connect(r'bridge\data\tradepilot.sqlite3').execute('PRAGMA integrity_check').fetchone())"
```

`ok` signifie que la base est saine ; les fichiers `-wal`/`-shm` seront
réabsorbés au prochain démarrage.

---

## 9. Session Telegram invalide

**Symptôme :** au démarrage, le Bridge signale une session illisible ou
« déchiffrement impossible », alors que Telegram fonctionnait avant.

**Cause principale : la `MASTER_KEY` a changé.** Les secrets (session Telegram,
clés API) sont chiffrés avec cette clé Fernet. Si `bridge\.env` a été recréé
(par exemple après un `-Force` mal maîtrisé ou une réinstallation), une nouvelle
clé a été générée et l'ancienne session est définitivement illisible.

```powershell
# La clé est-elle présente ? (la valeur n'est jamais affichée)
.\scripts\check_environment.ps1     # section « Configuration bridge\.env »
```

**Solutions :**

1. **Restaurer la sauvegarde de `bridge\.env`** (celle demandée à l'installation)
   → la session redevient lisible ;
2. sinon, repartir proprement :

```powershell
.\scripts\stop_bridge.ps1
Move-Item bridge\data\sessions bridge\data\sessions.old
.\scripts\start_bridge_background.ps1
# puis refaire la connexion Telegram depuis l'application (code SMS)
```

**Prévention :** sauvegardez `bridge\.env` hors du PC et ne le regénérez jamais
« pour voir ».

---

## 10. L'APK ne se connecte pas au Bridge

**Vérifications côté téléphone :**

1. ouvrez le navigateur du téléphone (en 4G, pas en Wi-Fi, pour tester le
   tunnel) et allez sur
   `https://<votre-domaine>.ngrok-free.app/api/v1/health` ;
   - réponse JSON → le réseau est bon, le problème est dans l'app ;
   - page d'erreur ngrok → voir §7 ;
   - rien du tout → le Bridge est arrêté, voir §1.
2. dans l'app, vérifiez l'URL saisie :
   - **avec** `https://`,
   - **sans** `/` final,
   - **sans** `/api/v1` à la fin.
3. **Code d'appairage expiré** : les codes ont une durée de vie courte.
   Regénérez-en un depuis le Bridge (ou redémarrez-le : le nouveau code
   apparaît dans `bridge\data\logs\bridge-stdout.log`) et ressaisissez-le.

```powershell
Select-String -Path bridge\data\logs\bridge-stdout.log -Pattern "pairing" | Select-Object -Last 5
```

4. **Token de l'appareil révoqué** (réinstallation de l'APK, réinitialisation du
   téléphone) : supprimez l'appareil dans les paramètres du Bridge puis refaites
   l'appairage.
5. **Accès Wi-Fi local sans ngrok** : le téléphone et le PC doivent être sur le
   **même réseau**, `BRIDGE_HOST=0.0.0.0` doit être configuré, une règle de
   pare-feu doit autoriser le port, et l'app doit viser l'IP locale du PC :

```powershell
Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.PrefixOrigin -ne "WellKnown" } |
    Select-Object IPAddress, InterfaceAlias
```

6. **Version de l'APK obsolète** après une mise à jour du Bridge : reconstruisez
   et réinstallez l'application.

---

## Collecter les informations avant de demander de l'aide

```powershell
.\scripts\check_environment.ps1 > $env:TEMP\tradepilot-diag.txt
Get-Content bridge\data\logs\bridge-stderr.log -Tail 100 >> $env:TEMP\tradepilot-diag.txt
notepad $env:TEMP\tradepilot-diag.txt
```

**Avant de partager ce fichier, relisez-le** : il ne doit contenir aucune clé ni
aucun token. Les scripts TradePilot n'affichent jamais la valeur d'un secret
(seulement `renseigné` ou `vide`), mais un message d'erreur applicatif pourrait
en révéler un.
