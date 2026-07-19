# PinkGift Tool pour Windows

L'application permet de publier les panneaux Discord PinkGift sans utiliser les commandes `/tarifs`, `/valo`, `/cp`, `/solde` ou `/maj_embed`.

## Utilisation

1. Lance `PinkGift-Tool.exe`.
2. Garde l'adresse du panel affichée par défaut.
3. Entre le même mot de passe que pour le panel web.
4. Ouvre **Publier un embed**.
5. Choisis le serveur, le salon et le panneau, puis clique sur **Publier dans le salon**.

Le mot de passe et le token Discord ne sont jamais enregistrés dans l'application. La session se ferme après 30 minutes sans activité.

## Construction locale

Depuis la racine du dépôt :

```powershell
python -m pip install -r desktop/requirements.txt
python -m PyInstaller --noconfirm --clean --onefile --windowed --name PinkGift-Tool --add-data "static/discord_icon.gif;static" desktop/pinkgift_desktop.py
```

Le fichier final est créé dans `dist/PinkGift-Tool.exe`.
