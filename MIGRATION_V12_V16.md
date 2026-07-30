# Migration Odoo v12 vers v16

Notes courtes sur les adaptations faites pour rendre `invoice_price_checker`
compatible avec Odoo v16 tout en conservant la compatibilite v12.

## 1. Suppression de `ID_externe`

Constat :
- en v12, la lecture de `ir.model.data` pouvait passer avec les droits utilisateur ;
- en v16, `ir.model.data` est plus restrictif et demande le groupe
  `Administration/Droits d'acces` ;
- l'application n'utilisait pas `ID_externe` pour le matching, les calculs ou
  les ecritures Odoo.

Changement :
- suppression de la lecture de `ir.model.data` ;
- suppression de `ID Externe` / `ID_externe` / `external_id` des bases generees,
  des outputs, du matching, du rapport de mise a jour et des tests.

Effet :
- le chargement Odoo ne depend plus d'un modele technique ;
- les ecritures continuent d'utiliser les IDs numeriques Odoo :
  `product.product.id` et l'ID fournisseur.

## 2. Champ fournisseur dans `product.supplierinfo`

Constat :
- en v12, le fournisseur de `product.supplierinfo` est stocke dans le champ
  `name` ;
- en v16, ce champ est remplace par `partner_id`.

Changement :
- ajout d'une detection runtime du champ disponible sur `product.supplierinfo` ;
- preference pour `partner_id` quand il existe, sinon fallback sur `name`.

Effet :
- pas de branchement par version Odoo ;
- le meme code fonctionne avec v12 et v16 selon les capacites reelles du modele.

## 3. Lecture Odoo par lots

Constat :
- les bases v16 de test peuvent contenir plusieurs milliers de produits et
  fournisseurs ;
- les appels `search_read` globaux sont moins pratiques a diagnostiquer.

Changement :
- lecture en deux temps : `search()` puis `read()` par lots ;
- ajout de `timeout` et `batch_size` configurables dans la configuration Odoo.

Effet :
- meilleure robustesse sur les grosses bases ;
- logs plus exploitables dans le script debug.

## 4. Script debug

Changement :
- `scripts/refresh_odoo_database_debug.py` suit les memes adaptations que le
  code applicatif ;
- il n'interroge plus `ir.model.data` ;
- il affiche le champ fournisseur utilise : `partner_id` ou `name`.

Objectif :
- identifier clairement le modele/champ qui bloque pendant une migration Odoo,
  sans passer par Streamlit.

## 5. Markup Odoo et alias temporaires de categories de marge

Constat :
- le modele Odoo `product.margin.classification` expose une valeur `markup` ;
- cette valeur correspond au coefficient utilise par le programme pour calculer
  `prix_de_vente` ;
- les valeurs historiques hardcodees dans `pricing.py` correspondent aux
  valeurs `markup` observees dans Odoo pour les categories `Taux de marque`.

Changement :
- la base articles Odoo contient maintenant `Catégorie de marge/Markup` ;
- `database.py` normalise cette colonne en `margin_markup` ;
- `matching.py` transmet cette valeur au calcul de prix ;
- `pricing.py` utilise `margin_markup` en priorite, puis retombe sur le
  dictionnaire historique seulement pour les anciennes bases ou fichiers sans
  markup.

Effet :
- les taux de marge suivent la configuration Odoo ;
- le code reste compatible avec les anciennes bases v12 deja exportees.

Constat :
- la base v16 de test contient temporairement des categories nommees
  `21 % de marge sur cout` et `25 % de marge sur cout` ;
- ces articles doivent etre reclasses dans Odoo vers les categories historiques
  `Taux de marque 21%` et `Taux de marque 25%`.

Changement temporaire :
- ajout de `TEMPORARY_V16_MARGIN_ALIASES` dans `pricing.py` ;
- les nouveaux libelles v16 sont mappes vers les categories historiques
  uniquement lorsque la base ne contient pas encore `margin_markup`.

A supprimer :
- retirer `TEMPORARY_V16_MARGIN_ALIASES` et ses tests quand la base Odoo v16 ne
  contient plus ces categories temporaires.

## Principe general retenu

Ne pas coder selon une version Odoo explicite (`if v16`) quand ce n'est pas
necessaire. Preferer une detection des champs/capacites disponibles, puis
utiliser le meme flux metier pour v12 et v16.
