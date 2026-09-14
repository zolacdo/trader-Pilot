# Installation du Bridge TradePilot sur Windows

Ce guide décrit, pas à pas, l'installation du **Bridge** (le programme Python qui
tourne sur votre PC Windows) : dépendances, configuration, démarrage manuel,
démarrage automatique au boot et accès distant depuis le téléphone via ngrok.

> Le Bridge est le cerveau de TradePilot : il lit Telegram, analyse les signaux,
> applique les règles de risque et envoie les ordres à MetaTrader 5.
> L'application Android ne fait qu'afficher et commander ce que le Bridge expose.

---

## 1. Prérequis

| Élément | Version / détail | Où l'obtenir |
|---|---|---|
| Windows | Windows 10 ou 11, 64 bits | — |
| Python | **3.11 minimum** (64 bits) | <https://www.python.org/downloads/windows/> — cocher **Add python.exe to PATH** |
| MetaTrader 5 Desktop | version de votre broker (ex. Exness) | site de votre broker |
| Compte ngrok (optionnel) | offre gratuite suffisante | <https://ngrok.com> |
| Identifiants Telegram | `api_id` + `api_hash` | <https://my.telegram.org> → *API development tools* |
| Clé OpenRouter | clé gratuite | <https://openrouter.ai/keys> |

Points importants :

- **MetaTrader 5 doit être installé et lancé** sur le même PC que le Bridge.
  Le paquet Python `MetaTrader5` dialogue avec le terminal graphique : sans
  terminal ouvert et connecté, aucun ordre ne peut être passé.
- Le PC doit rester **allumé et connecté à Internet** pour que le trading
  automatique fonctionne.
- Travaillez d'abord sur un **compte démo**. C'est la règle par défaut du projet.

---

## 2. Installation pas à pas

### 2.1 Récupérer le projet

Ouvrez PowerShell et placez-vous dans le dossier du projet :

```powershell
cd "C:\Users\<votre-nom>\Desktop\trader apk"
```

### 2.2 Lancer l'installation

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_bridge.ps1
```

Le script est **idempotent** : vous pouvez le relancer autant de fois que vous
voulez, il ne casse rien et n'écrase jamais votre configuration existante.

Il enchaîne huit étapes :

1. vérification de Python 3.11+ ;
2. création de l'environnement virtuel `bridge\.venv` ;
3. mise à jour de `pip` et installation de `bridge\requirements.txt` ;
4. création de `bridge\.env` à partir de `.env.example` (s'il n'existe pas) ;
5. génération d'une `MASTER_KEY` Fernet si elle est vide ;
6. création des dossiers `bridge\data`, `data\logs`, `data\sessions`, `data\bin` ;
7. téléchargement optionnel de ngrok ;
8. exécution du diagnostic `scripts\check_environment.ps1`.

Variantes utiles :

```powershell
# Installer en téléchargeant ngrok sans question
.\scripts\install_bridge.ps1 -WithNgrok

# Installer et configurer ngrok en une seule commande
.\scripts\install_bridge.ps1 -WithNgrok -NgrokDomain "tradepilot-xyz.ngrok-free.app" -NgrokAuthToken "2ab..."

# Repartir de zéro : venv recréé, dépendances réinstallées
.\scripts\install_bridge.ps1 -Force
```

> `-Force` ne touche **jamais** à votre `MASTER_KEY` : elle chiffre vos données,
> la perdre obligerait à tout reconfigurer.

### 2.3 Message d'avertissement sur la clé

À la première installation, le script affiche un encadré jaune :

```
AVERTISSEMENT IMPORTANT
Cette clé chiffre TOUS vos secrets (session Telegram, clés API).
Sauvegardez le fichier bridge\.env dans un endroit sûr.
```

**Faites cette sauvegarde immédiatement** (clé USB, gestionnaire de mots de
passe). Le fichier `bridge\.env` n'est jamais versionné dans Git.

---

## 3. Le fichier `bridge\.env`

Créé automatiquement à partir de `.env.example`. Ouvrez-le avec le Bloc-notes :

```powershell
notepad bridge\.env
```

Les valeurs à renseigner vous-même :

| Variable | Rôle | Obligatoire |
|---|---|---|
| `BRIDGE_HOST` | interface d'écoute (`127.0.0.1` par défaut) | non |
| `BRIDGE_PORT` | port HTTP local (`8787` par défaut) | non |
| `LOG_LEVEL` | `DEBUG` / `INFO` / `WARNING` / `ERROR` | non |
| `DATA_DIR` | dossier des données (`./data`) | non |
| `MASTER_KEY` | clé de chiffrement Fernet, générée par l'installeur | **oui** |
| `PAIRING_CODE` | code d'appairage du téléphone (vide = aléatoire) | non |
| `NGROK_ENABLED` | `true` pour ouvrir le tunnel au démarrage | pour l'accès distant |
| `NGROK_AUTHTOKEN` | token de votre compte ngrok | pour l'accès distant |
| `NGROK_DOMAIN` | domaine réservé, ex. `tradepilot-xyz.ngrok-free.app` | pour l'accès distant |
| `NGROK_REGION` | `eu`, `us`, `ap`, `au`, `sa`, `jp`, `in` | non |
| `NGROK_BINARY` | chemin de `ngrok.exe` (vide = recherche automatique) | non |
| `MT5_TERMINAL_PATH` | chemin de `terminal64.exe` (vide = auto-détection) | non |
| `TELEGRAM_API_ID` | identifiant obtenu sur my.telegram.org | **oui** |
| `TELEGRAM_API_HASH` | hash obtenu sur my.telegram.org | **oui** |
| `TELEGRAM_PHONE` | votre numéro au format international `+33...` | **oui** |
| `OPENROUTER_API_KEY` | clé OpenRouter | **oui** |
| `OPENROUTER_FREE_ONLY` | `true` = ne jamais choisir un modèle payant | recommandé |

Règles de sécurité :

- **jamais** de guillemets autour des valeurs, une ligne `CLE=valeur` par variable ;
- **jamais** de commit de ce fichier ;
- les scripts TradePilot n'affichent jamais le contenu d'un secret :
  ils indiquent seulement `renseigné` ou `vide`.

---

## 4. Vérifier l'environnement

À tout moment, sans rien modifier :

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check_environment.ps1
```

Le rapport affiche pour chaque point `[OK]`, `[ATTENTION]` ou `[MANQUANT]` :

```
-- Python et environnement virtuel -------------------------------
[OK]        Python 3.11+                       Python 3.13.7 (...)
[OK]        Environnement virtuel bridge\.venv Python 3.13.7

-- MetaTrader 5 --------------------------------------------------
[OK]        Terminal MetaTrader 5              1 installation(s) trouvée(s)
             -> C:\Program Files\MetaTrader 5 EXNESS\terminal64.exe
[OK]        Processus terminal64 en cours      PID 17876
```

Code de sortie : `0` si l'essentiel est présent, `1` sinon.
Une ligne `[ATTENTION]` n'empêche pas le Bridge de démarrer ; une ligne
`[MANQUANT]` oui.

---

## 5. Démarrage manuel

Fenêtre visible, journaux à l'écran, `Ctrl+C` pour arrêter :

```powershell
.\scripts\start_bridge.ps1
```

Sans tunnel ngrok pour ce lancement uniquement (`bridge\.env` n'est pas modifié) :

```powershell
.\scripts\start_bridge.ps1 -NoNgrok
```

En arrière-plan, **sans aucune fenêtre** :

```powershell
.\scripts\start_bridge_background.ps1
```

Ce script :

- utilise `pythonw.exe` (interpréteur sans console) ;
- écrit le PID dans `bridge\data\bridge.pid` ;
- redirige les sorties vers `bridge\data\logs\bridge-stdout.log` et
  `bridge-stderr.log` ;
- ne relance rien si le Bridge tourne déjà (idempotent) ;
- attend jusqu'à 30 secondes la réponse de `/api/v1/health` ;
- affiche l'URL locale **et** l'URL publique ngrok réelle, lue sur l'API locale
  de l'agent (`http://127.0.0.1:4040/api/tunnels`).

Arrêt :

```powershell
.\scripts\stop_bridge.ps1
```

---

## 6. Démarrage automatique au boot (recommandé)

Objectif : **le Bridge démarre tout seul quand la machine démarre**, en
arrière-plan, avec ngrok sur votre domaine réservé.

Ouvrez une console **PowerShell en administrateur**
(touche Windows → taper `PowerShell` → clic droit → *Exécuter en tant
qu'administrateur*), puis :

```powershell
cd "C:\Users\<votre-nom>\Desktop\trader apk"
.\scripts\install_autostart.ps1 -NgrokDomain "tradepilot-xyz.ngrok-free.app" -NgrokAuthToken "2ab..."
```

Le script crée une tâche planifiée Windows nommée **`TradePilotBridge`** :

| Réglage | Valeur | Pourquoi |
|---|---|---|
| Déclencheur | **à l'ouverture de session** de l'utilisateur courant | voir l'encadré ci-dessous |
| Délai | 60 secondes | laisse le réseau monter et MT5 démarrer |
| Action | `powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File …\scripts\start_bridge_background.ps1` | démarrage sans fenêtre |
| Privilèges | `RunLevel Highest` | accès complet au terminal MT5 |
| Durée max | illimitée (`ExecutionTimeLimit = 0`) | le Bridge tourne en continu |
| Échec | 3 redémarrages, 1 minute d'intervalle | résilience |
| Batterie | démarrage autorisé, pas d'arrêt au passage sur batterie | PC portable |
| Rattrapage | `StartWhenAvailable` | si l'heure prévue a été manquée |

> ### Pourquoi « à l'ouverture de session » et non « au démarrage du système » ?
>
> Le Bridge pilote MetaTrader 5 via le paquet Python `MetaTrader5`, qui dialogue
> avec le terminal **MT5 Desktop** (`terminal64.exe`). Ce terminal est une
> application graphique : il n'existe que dans une **session utilisateur
> interactive** et ne peut pas fonctionner dans la session 0 (session de service,
> sans bureau).
> Une tâche déclenchée « au démarrage du système » s'exécuterait avant toute
> ouverture de session : MT5 ne serait pas lancé, et le Bridge ne pourrait ni
> lire le compte ni passer d'ordre.

Commandes associées :

```powershell
# État de la tâche (ne nécessite pas les droits administrateur)
.\scripts\install_autostart.ps1 -Status

# Tester tout de suite, sans redémarrer
Start-ScheduledTask -TaskName TradePilotBridge

# Désinstaller la tâche (console administrateur)
.\scripts\install_autostart.ps1 -Remove
```

### 6.1 Faire démarrer MetaTrader 5 automatiquement aussi

Le Bridge a besoin que MT5 soit lancé. Ajoutez un raccourci de
`terminal64.exe` dans le dossier de démarrage de Windows :

1. `Windows + R`, taper `shell:startup`, valider ;
2. y glisser un raccourci vers
   `C:\Program Files\MetaTrader 5 <BROKER>\terminal64.exe` ;
3. dans MT5 : *Outils → Options → Serveur* → cocher **Conserver le mot de passe**
   pour que la connexion au compte soit automatique ;
4. dans MT5 : activer le bouton **AutoTrading** (barre d'outils) et cocher
   *Outils → Options → Expert Advisors → Autoriser le trading algorithmique*.

Le délai de 60 secondes de la tâche planifiée laisse à MT5 le temps de se
connecter avant que le Bridge n'essaie de l'utiliser.

---

## 7. Accès distant : ngrok avec domaine réservé

Sans ngrok, le téléphone ne peut joindre le Bridge que sur le **même Wi-Fi**.
Avec ngrok et un **domaine réservé**, l'URL ne change plus jamais : vous la
saisissez une seule fois dans l'application.

### 7.1 Réserver un domaine gratuit

1. Créez un compte gratuit sur <https://ngrok.com> ;
2. récupérez votre token sur
   <https://dashboard.ngrok.com/get-started/your-authtoken> ;
3. ouvrez <https://dashboard.ngrok.com/domains> et cliquez sur **New Domain** ;
   l'offre gratuite inclut **un** domaine statique du type
   `quelque-chose.ngrok-free.app` ;
4. copiez ce domaine **exactement**, sans `https://` ni `/` final.

### 7.2 Configurer TradePilot

```powershell
.\scripts\setup_ngrok.ps1 -AuthToken "2ab..." -Domain "tradepilot-xyz.ngrok-free.app"
```

Le script :

- enregistre le token avec `ngrok config add-authtoken` (jamais affiché) ;
- écrit `NGROK_AUTHTOKEN`, `NGROK_DOMAIN` et `NGROK_ENABLED=true` dans
  `bridge\.env` ;
- génère `bridge\data\ngrok.yml` (format version 3) avec un tunnel nommé
  `tradepilot` : `proto: http`, `addr: <BRIDGE_PORT>`, `domain: <NGROK_DOMAIN>`,
  `schemes: [https]` ;
- rappelle la procédure de réservation du domaine.

Pour vérifier réellement que le tunnel monte (10 secondes puis fermeture) :

```powershell
.\scripts\setup_ngrok.ps1 -Domain "tradepilot-xyz.ngrok-free.app" -Test
```

> **`NGROK_DOMAIN` doit correspondre caractère pour caractère au domaine
> réservé sur le tableau de bord.** Sinon ngrok refuse d'ouvrir le tunnel.

Après configuration, redémarrez le Bridge :

```powershell
.\scripts\stop_bridge.ps1
.\scripts\start_bridge_background.ps1
```

L'URL affichée (`https://tradepilot-xyz.ngrok-free.app`) est celle à saisir
dans l'application Android lors de l'appairage.

---

## 8. Vérifier que ça tourne

```powershell
# 1. Le processus existe-t-il ?
Get-Content bridge\data\bridge.pid
Get-Process -Id (Get-Content bridge\data\bridge.pid)

# 2. L'API locale répond-elle ?
Invoke-RestMethod http://127.0.0.1:8787/api/v1/health

# 3. Le tunnel est-il ouvert ?
(Invoke-RestMethod http://127.0.0.1:4040/api/tunnels).tunnels.public_url

# 4. L'URL publique répond-elle ?
Invoke-RestMethod https://tradepilot-xyz.ngrok-free.app/api/v1/health

# 5. Diagnostic complet
.\scripts\check_environment.ps1
```

Depuis le téléphone, ouvrez simplement l'URL publique suivie de
`/api/v1/health` dans le navigateur : vous devez obtenir une réponse JSON.

---

## 9. Consulter les journaux

| Fichier | Contenu |
|---|---|
| `bridge\data\logs\bridge-stdout.log` | sortie normale du Bridge lancé en arrière-plan |
| `bridge\data\logs\bridge-stderr.log` | erreurs et traces d'exception |
| `bridge\data\logs\` (autres fichiers) | journaux applicatifs du Bridge |

Suivre les journaux en direct :

```powershell
Get-Content bridge\data\logs\bridge-stdout.log -Wait -Tail 50
```

Voir les 40 dernières erreurs :

```powershell
Get-Content bridge\data\logs\bridge-stderr.log -Tail 40
```

Journaux de la tâche planifiée : *Planificateur de tâches* → `TradePilotBridge`
→ onglet **Historique** (à activer une fois via *Action → Activer l'historique
de toutes les tâches*).

Les fichiers de log dépassant 5 Mo sont archivés automatiquement au démarrage
suivant sous la forme `bridge-stdout.20260910-223000.log`.

Pour plus de détail, passez `LOG_LEVEL=DEBUG` dans `bridge\.env` et redémarrez.

---

## 10. Arrêt et désinstallation

```powershell
# Arrêter le Bridge (et les agents ngrok qu'il a lancés)
.\scripts\stop_bridge.ps1

# Supprimer le démarrage automatique (console administrateur)
.\scripts\install_autostart.ps1 -Remove

# Supprimer l'environnement Python (réinstallable avec install_bridge.ps1)
Remove-Item -Recurse -Force bridge\.venv
```

Pour une remise à zéro complète, supprimez également `bridge\data\`
(**attention** : cela efface la base SQLite, l'historique et la session
Telegram) et `bridge\.env` (**attention** : cela efface la `MASTER_KEY`).

---

## 11. Problèmes fréquents

### Le port 8787 est déjà occupé

Symptôme : `[ATTENTION] Port 8787 déjà utilisé par ...` dans le diagnostic, ou
le Bridge s'arrête aussitôt avec `address already in use`.

```powershell
# Qui occupe le port ?
Get-NetTCPConnection -LocalPort 8787 -State Listen | ForEach-Object {
    Get-Process -Id $_.OwningProcess
}
```

Deux solutions :

- il s'agit d'un ancien Bridge resté en mémoire → `.\scripts\stop_bridge.ps1`,
  puis si nécessaire `Stop-Process -Name pythonw -Force` ;
- il s'agit d'un autre logiciel → changez `BRIDGE_PORT=8788` dans
  `bridge\.env`, relancez `setup_ngrok.ps1` (pour regénérer `ngrok.yml` sur le
  nouveau port) puis redémarrez le Bridge.

### MetaTrader 5 non détecté

Symptôme : `[ATTENTION] Terminal MetaTrader 5 : terminal64.exe introuvable`.

- vérifiez que MT5 **Desktop** est installé (l'application mobile MT5 ne
  convient pas, voir la section 2 du cahier des charges) ;
- si MT5 est installé dans un dossier inhabituel, renseignez le chemin complet
  dans `bridge\.env` :
  `MT5_TERMINAL_PATH=C:\Program Files\MetaTrader 5 EXNESS\terminal64.exe` ;
- vérifiez que le terminal est **lancé et connecté** :
  `Get-Process terminal64` doit renvoyer un processus ;
- Python et MT5 doivent tous deux être en **64 bits**.

### La tâche planifiée ne démarre pas

1. Vérifiez son état :
   `.\scripts\install_autostart.ps1 -Status`
   — `Dernier résultat` doit valoir `0`.
2. Testez-la manuellement : `Start-ScheduledTask -TaskName TradePilotBridge`,
   puis regardez `bridge\data\logs\bridge-stderr.log`.
3. Vérifiez que le service **Planificateur de tâches** est démarré :
   `Get-Service Schedule`.
4. La tâche est liée à l'utilisateur qui l'a créée : si vous avez changé de
   compte Windows ou de mot de passe, réinstallez-la depuis une console
   administrateur de **ce** compte.
5. Rappel : la tâche se déclenche **à l'ouverture de session**, pas au simple
   allumage. Si le PC démarre sur l'écran de verrouillage sans que personne ne
   se connecte, le Bridge ne démarre pas (et MT5 non plus). Activez l'ouverture
   de session automatique si le PC est dédié au trading.
6. Le chemin du projet contient des espaces : c'est prévu (les arguments sont
   entre guillemets), mais ne déplacez pas le dossier sans réinstaller la tâche.

### ngrok : `ERR_NGROK_108` (tunnel déjà actif)

L'offre gratuite n'autorise **qu'une seule session d'agent à la fois**. Le
message apparaît si un ngrok tourne déjà (lancé à la main, resté d'un test, ou
d'un précédent Bridge).

```powershell
# Voir les agents ngrok en cours
Get-Process ngrok -ErrorAction SilentlyContinue

# Tout fermer
Stop-Process -Name ngrok -Force

# Puis redémarrer proprement
.\scripts\stop_bridge.ps1
.\scripts\start_bridge_background.ps1
```

Si le message persiste, une session fantôme peut subsister côté ngrok :
ouvrez <https://dashboard.ngrok.com/agents> et arrêtez-la, puis réessayez.

### Pare-feu Windows

Symptôme : le Bridge démarre, `http://127.0.0.1:8787` répond sur le PC, mais le
téléphone ne voit rien sur le réseau local.

- avec ngrok, **aucune ouverture de port n'est nécessaire** : c'est l'agent qui
  sort vers Internet. Vérifiez plutôt que le pare-feu n'empêche pas
  `ngrok.exe` de sortir ;
- pour un accès en Wi-Fi local sans ngrok, il faut d'une part
  `BRIDGE_HOST=0.0.0.0` dans `bridge\.env`, d'autre part une règle de pare-feu :

```powershell
# Console ADMINISTRATEUR
New-NetFirewallRule -DisplayName "TradePilot Bridge" -Direction Inbound `
    -Protocol TCP -LocalPort 8787 -Action Allow -Profile Private
```

- si Windows affiche une fenêtre « Autoriser Python à communiquer sur ces
  réseaux ? », cochez **Réseaux privés** et acceptez ;
- en entreprise, un proxy peut bloquer `api.telegram.org` et `openrouter.ai` :
  le diagnostic le signale dans la section *Connectivité Internet*.

---

## 12. Aide-mémoire des commandes

```powershell
.\scripts\check_environment.ps1                 # diagnostic (ne modifie rien)
.\scripts\install_bridge.ps1                    # installation / mise à jour
.\scripts\install_bridge.ps1 -WithNgrok         # + téléchargement de ngrok
.\scripts\setup_ngrok.ps1 -AuthToken … -Domain … # configuration du tunnel
.\scripts\start_bridge.ps1                      # démarrage au premier plan
.\scripts\start_bridge_background.ps1           # démarrage sans fenêtre
.\scripts\stop_bridge.ps1                       # arrêt
.\scripts\install_autostart.ps1                 # démarrage au boot (admin)
.\scripts\install_autostart.ps1 -Status         # état de la tâche planifiée
.\scripts\install_autostart.ps1 -Remove         # désinstallation (admin)
```

En cas de problème non couvert ici, consultez
[TROUBLESHOOTING.md](TROUBLESHOOTING.md).
