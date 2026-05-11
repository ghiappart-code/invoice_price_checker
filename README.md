# Invoice Price Checker

Application Streamlit pour verifier des factures fournisseurs PDF, comparer les prix avec une base articles Odoo, preparer un fichier de controle, puis mettre a jour Odoo uniquement si l utilisateur le confirme.

Ce guide est ecrit pour une personne qui n est pas specialiste en informatique.

## 1. Ce que fait l application

L application permet de :

- charger une facture fournisseur au format PDF ;
- lire une base articles locale, par defaut `data_files/var_articles.data` ;
- faire le lien entre les lignes de facture et les articles de la base ;
- calculer les ecarts de prix ;
- isoler les prix modifies, les lignes non trouvees, les ecarts anormaux et les baisses bloquees ;
- telecharger un fichier Excel de controle ;
- preparer les lignes qui peuvent etre envoyees vers Odoo ;
- mettre a jour Odoo seulement apres validation explicite par l utilisateur.

Pour le moment, les fournisseurs implementes sont RELAIS VERT, HALLE BIO OCCITANIE, EKIBIO, AGIDRA, EPICE et DDS.

## 2. Pre-requis

Il faut installer :

1. Python 3.11 ou plus recent.
2. Les fichiers de cette application.
3. Les dependances Python listees dans `requirements.txt`.
4. Des identifiants Odoo personnels si l utilisateur veut rafraichir la base articles ou mettre a jour Odoo.

Sur Mac, Python peut etre installe depuis :

```text
https://www.python.org/downloads/
```

Sur Windows, il faut cocher l option `Add Python to PATH` pendant l installation de Python.

## 3. Copier le dossier de l application

Copier tout le dossier :

```text
invoice_price_checker
```

sur l ordinateur de la personne qui va utiliser l application.

Le dossier doit contenir notamment :

```text
app.py
requirements.txt
README.md
invoice_price_checker/
data_files/
.streamlit/secrets.example.toml
```

Important : ne pas partager le fichier suivant s il existe deja sur votre ordinateur :

```text
.streamlit/secrets.toml
```

Ce fichier contient les codes personnels Odoo.

## 4. Installation

Ouvrir un terminal dans le dossier `invoice_price_checker`.

Sur Mac :

```bash
cd /chemin/vers/invoice_price_checker
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Sur Windows PowerShell :

```powershell
cd C:\chemin\vers\invoice_price_checker
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Si Windows refuse d activer l environnement virtuel, lancer cette commande dans PowerShell, puis recommencer l activation :

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## 5. Configuration des codes Odoo

Chaque utilisateur doit avoir ses propres codes Odoo.

Dans le dossier `.streamlit`, copier le fichier exemple.

Sur Mac :

```bash
cp .streamlit/secrets.example.toml .streamlit/secrets.toml
chmod 600 .streamlit/secrets.toml
```

Sur Windows, copier simplement :

```text
.streamlit/secrets.example.toml
```

vers :

```text
.streamlit/secrets.toml
```

Puis ouvrir `.streamlit/secrets.toml` avec un editeur de texte et remplir :

```toml
[odoo]
url = "odoo.example.org"
port = 443
database = "database_name"
username = "user@example.com"
password = "your-password-or-api-key"
```

Ne jamais envoyer ce fichier par email et ne jamais le mettre dans un depot partage.

Le fichier `.gitignore` protege deja `.streamlit/secrets.toml`, mais il faut quand meme rester prudent.

## 6. Lancer l application

Dans le terminal, depuis le dossier `invoice_price_checker`, activer l environnement virtuel si ce n est pas deja fait.

Sur Mac :

```bash
source .venv/bin/activate
streamlit run app.py
```

Sur Windows PowerShell :

```powershell
.\.venv\Scripts\Activate.ps1
streamlit run app.py
```

Streamlit ouvre normalement une page dans le navigateur. Si la page ne s ouvre pas automatiquement, copier l adresse affichee dans le terminal, par exemple :

```text
http://localhost:8501
```

## 7. Utilisation normale

Dans l application :

1. Choisir le fournisseur dans la barre laterale.
2. Choisir la source de la base articles.
3. Charger la facture PDF.
4. Verifier les resultats a l ecran.
5. Telecharger le classeur Excel de controle.
6. Lire les onglets du fichier Excel avant toute mise a jour Odoo.
7. Si les lignes de mise a jour sont correctes, utiliser la partie `Odoo update`.

La mise a jour Odoo ne doit etre lancee qu apres verification du fichier de controle.

## 8. Base articles

Par defaut, l application cherche la base ici :

```text
data_files/var_articles.data
```

Si ce fichier existe, l application peut l utiliser directement.

Si les identifiants Odoo sont configures, le bouton de rafraichissement permet de recreer cette base depuis Odoo.

## 9. Fichier Excel produit

Le classeur Excel contient plusieurs onglets, notamment :

- `calculation_notes` : explication des colonnes et des calculs ;
- `price_changes` : articles dont le prix change ;
- `odoo_update_review` : lignes preparees pour une mise a jour Odoo ;
- `unmatched` : lignes de facture non retrouvees dans la base ;
- `abnormal_changes` : ecarts de prix juges anormaux ;
- `blocked_decreases` : baisses de prix bloquees par une remise temporaire ;
- `all_checked` : toutes les lignes analysees.

Le nom du fichier Excel est base sur le nom de la facture, par exemple :

```text
FC12402686_price_review.xlsx
```

## 10. Regles RELAIS VERT / HALLE BIO OCCITANIE actuellement implementees

Pour RELAIS VERT et HALLE BIO OCCITANIE :

- RELAIS VERT utilise l ID fournisseur `254` ;
- HALLE BIO OCCITANIE utilise l ID fournisseur `3329` ;
- EKIBIO utilise l ID fournisseur `358` ;
- AGIDRA utilise l ID fournisseur `329` ;
- EPICE utilise l ID fournisseur `262` ;
- DDS utilise l ID fournisseur `2784` ;
- la ligne `GAZOLE` est traitee comme une surcharge en pourcentage ;
- cette surcharge est appliquee aux prix facture avant comparaison ;
- les produits de categorie `Fruits & Legumes` sont exclus de la base avant matching ;
- les lignes non trouvees sont listees dans `unmatched` ;
- un prix est considere modifie seulement si l ecart sort des bornes configurees ;
- un ecart trop important est isole dans `abnormal_changes` ;
- une baisse de prix est bloquee si `Q*`, `P` ou `E` est non nul ;
- la colonne `G` n est pas utilisee pour bloquer les baisses ;
- `prix_de_vente` est recalcule a partir du nouveau cout, de la TVA et du taux de marque.

## 11. Dependances Python

Les dependances sont dans `requirements.txt` :

```text
streamlit
pandas
pdfplumber
pypdf
PyMuPDF
openpyxl
```

Elles s installent avec :

```bash
pip install -r requirements.txt
```

## 12. En cas de probleme

Si la commande `streamlit run app.py` ne marche pas :

1. Verifier que le terminal est bien dans le dossier `invoice_price_checker`.
2. Verifier que l environnement virtuel est active.
3. Relancer :

```bash
pip install -r requirements.txt
```

4. Copier le message d erreur complet et l envoyer a la personne qui maintient l application.

Si l application ne peut pas se connecter a Odoo :

1. Verifier `.streamlit/secrets.toml`.
2. Verifier l adresse du serveur, le nom de la base, l utilisateur et le mot de passe.
3. Verifier que l utilisateur a les droits suffisants dans Odoo.

## 13. Ajouter un nouveau fournisseur

La partie commune du programme reste la meme :

- lecture de la base ;
- extraction des lignes ;
- matching ;
- calcul des ecarts ;
- generation des sorties ;
- preparation de la mise a jour Odoo.

La partie specifique fournisseur est dans :

```text
invoice_price_checker/suppliers/
```

Pour ajouter un fournisseur, il faut ajouter un nouveau parseur PDF dans ce dossier, puis l enregistrer dans :

```text
invoice_price_checker/suppliers/__init__.py
```

Un modele de depart existe ici :

```text
invoice_price_checker/suppliers/template.py
```

## 14. Fichiers a ne pas partager

Ne pas partager :

```text
.streamlit/secrets.toml
.venv/
__pycache__/
*.pyc
```

Partager plutot :

```text
app.py
requirements.txt
README.md
invoice_price_checker/
data_files/
.streamlit/secrets.example.toml
```
