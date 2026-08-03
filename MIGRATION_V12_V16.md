# Migration Odoo v12 vers v16

Notes de migration pour rendre `invoice_price_checker` compatible avec Odoo
v16 tout en conservant le fonctionnement valide en Odoo v12.

Le principe retenu est de ne pas coder une branche par version Odoo quand ce
n'est pas necessaire. Le code detecte les champs et capacites disponibles dans
la base connectee, puis garde le meme flux metier pour v12 et v16.

## Etat initial

- L'application fonctionnait en v12 avec le workflow local Streamlit.
- Le chargement initial d'une base v16 echouait avant toute ecriture Odoo.
- L'erreur venait de la lecture de `ir.model.data`, modele technique devenu
  inaccessible avec les droits utilisateur disponibles en v16.
- Les droits metier etaient similaires en v12 et v16, mais l'acces a ce modele
  technique n'etait pas garanti.

## 1. Suppression de `ID_externe`

Constat :

- en v12, la lecture de `ir.model.data` pouvait passer avec les droits
  utilisateur ;
- en v16, `ir.model.data` demande des droits d'administration ;
- `ID_externe` n'etait pas necessaire au matching, aux calculs ni a l'ecriture
  des prix dans Odoo.

Changements :

- suppression de la lecture de `ir.model.data` ;
- suppression de `ID Externe`, `ID_externe` et `external_id` des bases generees,
  des outputs, du matching, des rapports et des tests ;
- conservation de l'utilisation des IDs numeriques Odoo : `product.product.id`,
  `product.template.id`, fournisseur et `product.supplierinfo.id`.

Effet :

- le chargement Odoo ne depend plus d'un modele technique ;
- les bases v12 et v16 sont traitees avec les memes identifiants metier utiles ;
- les exports utilisateur ne contiennent plus de colonne obsolete.

## 2. Compatibilite `product.supplierinfo`

Constat :

- en v12, le fournisseur de `product.supplierinfo` est porte par le champ
  `name` ;
- en v16, ce champ est remplace par `partner_id`.

Changements :

- ajout du helper `supplierinfo_partner_field` ;
- detection runtime des champs disponibles sur `product.supplierinfo` ;
- preference pour `partner_id` quand il existe, fallback sur `name` sinon ;
- utilisation du champ detecte dans la lecture de la base articles, le dry-run
  et l'ecriture reelle des prix.

Effet :

- aucune condition explicite `if v16` n'est necessaire ;
- le meme code fonctionne sur les deux schemas Odoo.

## 3. Lecture Odoo par lots

Constat :

- les bases Odoo contiennent plusieurs milliers d'articles et lignes
  fournisseurs ;
- les appels globaux sont moins robustes et plus difficiles a diagnostiquer.

Changements :

- ajout de `timeout` et `batch_size` dans `OdooConfig` ;
- ajout de `_search_read_all`, qui fait `search()` puis `read()` par lots ;
- ajout de `_read_with_retry` pour retenter une lecture de lot en cas d'erreur ;
- application de cette lecture par lots aux produits, fournisseurs, unites,
  taxes, categories et classifications de marge.

Effet :

- chargement plus robuste sur grosses bases ;
- diagnostic plus simple en cas de blocage ;
- compatibilite conservee avec les bases v12.

## 4. Markup Odoo et calcul du prix de vente

Constat :

- Odoo expose les classifications de marge via
  `product.margin.classification` ;
- le champ `markup` correspond a la valeur utilisee par l'application pour
  calculer le prix de vente ;
- les valeurs historiques codees dans `pricing.py` correspondent aux valeurs
  `markup` observees pour les categories `Taux de marque`.

Changements :

- recuperation de `Catégorie de marge/Markup` pendant le chargement Odoo ;
- normalisation de cette colonne en `margin_markup` ;
- transmission de `margin_markup` au matching et aux workbooks ;
- calcul du prix de vente avec le markup Odoo en priorite ;
- conservation du dictionnaire historique `MARGIN_RATES` comme fallback pour
  les anciennes bases locales qui ne contiennent pas encore le markup.

Cas temporaire v16 :

- certaines bases v16 de test contenaient des categories temporaires du type
  `21 % de marge sur cout` et `25 % de marge sur cout` ;
- ajout de `TEMPORARY_V16_MARGIN_ALIASES` pour mapper ces libelles vers les
  categories historiques uniquement lorsque le markup Odoo est absent ;
- ce bloc est volontairement visible et documente comme temporaire.

A supprimer plus tard :

- retirer `TEMPORARY_V16_MARGIN_ALIASES` et ses tests quand les categories
  temporaires n'existent plus dans les bases Odoo utilisees.

## 5. Dry-run et ecriture Odoo des prix

Changements :

- ajout de `dry_run_odoo_price_updates` ;
- verification sans ecriture de l'existence du produit, du template produit et
  de la ligne fournisseur ;
- rapport detaille avec valeurs actuelles et futures :
  `current_cost`, `current_supplier_price`, `current_sale_price`,
  `supplierinfo_id`, `status`, `message` ;
- ajout de `update_odoo_prices` compatible v12/v16 avec detection du champ
  fournisseur ;
- remplacement de `Product.browse(...).product_tmpl_id` par `Product.read(...)`
  pour fiabiliser le comportement OdooRPC en v16 ;
- ecriture de `product.supplierinfo.price` quand la ligne fournisseur existe ;
- ecriture de `product.product.standard_price` et `product.product.list_price`.

Effet :

- le dry-run permet de controler les lignes avant ecriture ;
- les erreurs sont remontees ligne par ligne dans un rapport CSV ;
- l'ecriture reelle a ete validee sur v12 et v16 apres correction.

Limite volontaire :

- l'ecriture reste ligne par ligne, car chaque produit recoit des valeurs
  differentes. La lecture est optimisee par lots, mais les `write()` Odoo
  appliquent un meme dictionnaire de valeurs a tous les IDs fournis.

## 6. Mode developpeur

Objectif :

- conserver les outils de diagnostic utiles sans les exposer aux utilisateurs
  standards.

Activation :

- variable d'environnement `INVOICE_PRICE_CHECKER_DEV_TOOLS=1` ;
- ou configuration Streamlit :

```toml
[app]
developer_tools = true
```

Outils visibles en mode developpeur :

- dry-run Odoo avant ecriture des prix ;
- telechargement de la base Odoo dans `Downloads` ;
- enregistrement de la base Odoo dans `data_files/var_articles.data` ;
- acces aux rapports techniques de validation.

Comportement utilisateur standard :

- pas d'acces direct aux actions de debug ;
- chargement et analyse restent concentres sur le workflow metier ;
- l'application affiche clairement l'etat courant : base articles chargee,
  nombre d'articles, nom de la base Odoo et facture prete a analyser.

## 7. Script debug Odoo

Changements :

- ajout de `scripts/refresh_odoo_database_debug.py` ;
- lecture de la configuration Odoo depuis `.streamlit/secrets.toml` ;
- connexion avec `timeout` ;
- chargement par lots avec logs chronometres ;
- detection et affichage du champ fournisseur utilise :
  `partner_id` ou `name` ;
- inspection de `margin_classification_id` et des valeurs `markup` /
  `profit_margin` disponibles ;
- ecriture de la base locale dans `data_files/var_articles.data`.

Utilite :

- reproduire et diagnostiquer un chargement Odoo sans passer par Streamlit ;
- identifier le modele, champ ou lot qui bloque pendant une migration ;
- reutiliser cette methode pour de futurs debugs developpeur.

## 8. Interface Streamlit

Changements :

- message principal enrichi quand une base articles est chargee ;
- affichage du vrai nom de base Odoo, par exemple `demain` ou `demain-mig16` ;
- affichage du nombre d'articles charges ;
- message indiquant quand la facture PDF est prete a etre analysee ;
- option "utiliser la base locale actuelle" masquee quand aucune base locale
  n'est disponible ;
- separation plus claire entre charger depuis Odoo, enregistrer dans
  `data_files` et telecharger dans `Downloads`.

Effet :

- l'utilisateur sait sur quelle base il travaille ;
- les actions developpeur ne perturbent plus le workflow standard.

## 9. Tests ajoutes ou adaptes

Tests couverts :

- suppression de `ID_externe` des outputs ;
- detection `partner_id` v16 et `name` v12 ;
- configuration `timeout` et `batch_size` ;
- lecture Odoo par lots ;
- helper de relation Odoo sous forme liste/scalar ;
- dry-run et rapport d'ecriture ;
- priorite du markup Odoo sur les valeurs historiques ;
- fallback historique des taux de marque ;
- alias temporaires v16 de marge sur cout.

Validation locale :

- la suite de tests Python passe avec 40 tests valides.

## 10. Validations fonctionnelles

Validations realisees :

- chargement de base v12 depuis Streamlit ;
- chargement de base v16 depuis Streamlit ;
- analyse de factures avec base v12 ;
- analyse de factures avec base v16 ;
- recuperation du markup Odoo en v12 et v16 ;
- disparition de `ID_externe` dans les workbooks de controle ;
- dry-run prix avec lignes `ready` ;
- ecriture reelle des prix sur base v16 de test ;
- rechargement de la base apres ecriture confirmant 0 changement restant ;
- tests sur base de production v12 avec plusieurs fournisseurs ;
- tests sur base v16 avec plusieurs fournisseurs.

Conclusion :

- le flux lecture, analyse, calcul et ecriture des prix est valide en v12 et
  v16 ;
- les outils developpeur sont disponibles pour diagnostiquer sans encombrer
  l'interface utilisateur standard ;
- le projet reste autonome et pret pour la migration Odoo v16.
