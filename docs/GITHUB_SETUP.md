# Publication sur GitHub

Le dépôt local utilise la branche `main` et l'identité Git suivante :

- Nom : `zolacdo`
- E-mail : `zolacdojeff@gmail.com`

Cette configuration est propre à ce projet ; elle ne change pas l'identité Git
des autres projets sur la machine.

## Créer un nouveau dépôt

Depuis la racine du projet, avec GitHub CLI connecté au compte `zolacdo` :

```powershell
gh repo create zolacdo/tradepilot --private --source . --remote origin --push
```

Cette commande crée un dépôt privé et y envoie le commit local. Adaptez le nom
`tradepilot` si vous souhaitez un autre nom de dépôt.

## Utiliser un dépôt existant

Créez un dépôt GitHub vide (sans README, licence ni `.gitignore`), puis remplacez
`NOM_DU_DEPOT` dans les commandes suivantes :

```powershell
git remote add origin https://github.com/zolacdo/NOM_DU_DEPOT.git
git push -u origin main
```

Si `origin` est déjà configuré, vérifiez sa destination avec `git remote -v`
avant d'envoyer les commits.

## Après le clonage

Les fichiers de configuration locaux ne sont pas inclus dans le dépôt :
`.env`, bases de données, sessions Telegram, clé maître, clés de signature Android
et fichiers Firebase. Les caches et les dossiers de compilation sont également
exclus.

Pour reconstruire le projet sur une autre machine, suivez
[l'installation du Bridge Windows](BRIDGE_WINDOWS_SETUP.md) et
[la construction Android](ANDROID_SETUP.md). Copiez `.env.example` vers
`bridge/.env` et renseignez les paramètres sur cette machine. Restaurez également
`mobile/android/app/google-services.json` depuis votre projet Firebase avant de
compiler l'application Android, ainsi que la configuration SDK et, si nécessaire,
la clé de signature.

La publication du code sur GitHub ne démarre pas le Bridge : celui-ci s'exécute
sur le PC Windows qui héberge MetaTrader 5.
