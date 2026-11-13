[README (1).md](https://github.com/user-attachments/files/34811982/README.1.md)
# Démo Odoo 19 — flux financier complet d'un négoce

**Comptoir Vellard SAS** (fictif), Lyon : négoce de matériel et de consommables pour cafés, hôtels et restaurants (CHR). Elle a 4 salariés et un entrepôt à Lyon Gerland. Son CA est d'environ 45 k€ HT par mois. Elle vend en France, en Belgique (intracommunautaire) et en Suisse (export).

Le script `demo_negoce_odoo19.py` alimente une base Odoo 19 vierge. Il passe par l'API XML-RPC, en ordre chronologique, sur **trois mois glissants** :

- **M0** : mois N-2 ;
- **M1** : mois N-1 ;
- **M2** : mois en cours, jusqu'au 12.

Lancé le 13 novembre 2026, il couvre la période du 1er septembre au 12 novembre 2026. Les montants cités plus bas correspondent à ce cas. Les dates suivent le jour du lancement.

---

## 1. Mise en place (≈ 3 min)

1. Créez une **base vierge** : langue *Français*, pays *France*, **sans** données de démonstration. Ajoutez les applis Ventes, Achats, Inventaire et Facturation/Comptabilité. Le script installe lui-même ce qui manque.
2. Lancez le script :

```bash
python3 demo_negoce_odoo19.py --url https://ma-base.odoo.com --db ma-base \
    --user admin@exemple.fr --password <mot de passe ou clé API>
```

Le script n'a besoin que de Python 3.10 ou plus, sans dépendance externe. Il refuse de tourner deux fois sur la même base. Il refuse aussi une base qui contient déjà des écritures sur un autre plan comptable.

**Fonctionnement selon l'édition :**
- **Enterprise** (application *Comptabilité*) : c'est la cible de la démo, avec le rapprochement bancaire, les relances, la déclaration de TVA et les rapports.
- **Community** : tout est créé, mais Odoo ne propose ni rapprochement bancaire ni rapports financiers. Les relevés restent sur le compte d'attente 471.

Option `--today AAAA-MM-JJ` : rejouer la démo à une autre date de référence.

---

## 2. Contenu de la base

### Paramétrage
- Société : plan comptable PCG français, TVA FR, SIRET.
- Exercice : civil.
- Valorisation des stocks : **périodique au coût moyen (AVCO)**. C'est l'usage des PME françaises : achats en 607 et variation de stock à la clôture.
- Journal bancaire *Banque du Rhône* avec IBAN.
- Conditions de paiement : comptant, 30 j, 45 j, « 30 jours fin de mois ».
- Positions fiscales : France, intra-UE B2B, export hors UE.
- Modèles de rapprochement : *Frais bancaires* (627800), *Virement salaires* (421000), *URSSAF* (431000), *TVA DGFiP* (445510).

> Les SIREN, n° de TVA (FR, IT, BE) et IBAN sont **fictifs mais à clé valide**. Ils passent donc les contrôles de saisie d'Odoo.

### Tiers

| Fournisseurs | Pays | Conditions |
|---|---|---|
| Porcelaines Martin & Fils | FR | 45 j |
| Inox Dauphiné Équipements | FR | 30 j fin de mois |
| Coltelleria Bassano S.r.l. | IT, autoliquidation | 30 j |
| Textiles Hôteliers de l'Ouest | FR | 30 j |
| Transports Berthaud | FR | 30 j |
| SCI Les Tanneurs (loyer) | FR | prélèvement |
| RhôneNet Télécom Pro | FR | prélèvement |
| URSSAF Rhône-Alpes | FR | — |
| SIE Lyon 7e | FR | — |

| Clients | Pays | Conditions |
|---|---|---|
| Brasserie du Vieux Port | FR | 30 j |
| Hôtel Les Terrasses du Parc | FR | 45 j |
| Restaurant L'Épi Gourmand | FR | comptant |
| Traiteur Maison Ferrand | FR | 30 j fin de mois |
| Auberge du Sablon SRL | BE, livraison intracom. | 30 j |
| Hôtel du Lac Léman SA | CH, export | acompte 30 % puis 30 j |

### Articles
- **11 articles stockés**, en 4 catégories : arts de la table, cuisine pro, coutellerie, linge.
- Un prix d'achat et un prix de vente par article (marge ≈ 50 %), avec un fournisseur attitré.
- Facturation sur les quantités livrées. Contrôle des factures d'achat sur les quantités reçues.
- Un service *Frais de port* (45 € HT).

### Reprise au 1er jour de M0 (OD d'à-nouveaux)

| Compte | Débit | Crédit |
|---|---:|---:|
| 512 Banque du Rhône | 85 000,00 | |
| 370 Stock (= inventaire initial valorisé) | 29 105,00 | |
| 411 Brasserie du Vieux Port / Terrasses du Parc (2 factures ouvertes) | 35 520,00 | |
| 401 Porcelaines Martin (1 facture ouverte) | | 31 200,00 |
| 421 / 431 Salaires et cotisations du mois précédent | | 17 900,00 |
| 445510 TVA à décaisser du mois précédent | | 3 950,00 |
| 101 Capital / 455 Compte courant d'associé | | 70 000,00 |
| 110 Report à nouveau (solde) | | 26 575,00 |

### Flux générés

| | M0 | M1 | M2 (au 12) |
|---|---|---|---|
| **Achats** | 3 commandes. Réception partielle chez Inox, avec un reliquat. Acquisition intracom. Bassano (autoliquidation 445200/445662). Transport sur achats | Commande de linge. Reliquat reçu. Factures Inox (2) et Textiles | Commande Martin **reçue mais non facturée**. Demande de prix Bassano en brouillon |
| **Ventes** | 4 commandes livrées et facturées, dont une à l'Auberge du Sablon (Belgique, TVA 0 % intra) | Export Suisse : **acompte 30 %** puis facture de solde avec déduction. Avoir de 100 assiettes cassées, lettré sur la facture | 1 commande livrée et facturée. **Devis** Terrasses en cours. **Commande** Sablon à livrer |
| **Règlements** | Encaissements, dont les à-nouveaux. Paiement du fournisseur repris | Encaissements. **Règlement partiel** Terrasses (20 000 € sur 25 530 €). Paiements Bassano et Martin | Solde Suisse encaissé |
| **Frais généraux** | Loyer et télécom (prélèvements), frais bancaires | Idem | Loyer |
| **Paie** | OD de paie (brut 12 600 €, charges patronales 5 300 €) | Idem | — |
| **TVA** | Prélèvement de la TVA du mois précédent (3 950 €) | Prélèvement de la TVA de M0 : 2 301,40 €, calculée sur les écritures | — |
| **Banque** | Relevé M0 : 9 opérations | Relevé M1 : 11 opérations | Relevé M2 : 5 opérations |

Le solde bancaire passe de 85 000 € à 53 283,50 €. **Aucune ligne de relevé n'est rapprochée** : le rapprochement se fait en direct pendant la démo.

### Situation au 13 novembre

**Clients**
- *Hôtel Les Terrasses du Parc* : **5 530 € échus**.
- *Auberge du Sablon* : **19 625 € échus**.
- *Brasserie du Vieux Port* : 7 062 € non échus.
- *Traiteur Maison Ferrand* : 19 002 € non échus (facture moins avoir).
- *L'Épi Gourmand* : 5 292 €, réglés sur le relevé du 10/11 mais pas encore rapprochés.

**Fournisseurs**
- *Textiles Hôteliers de l'Ouest* : 17 544 € **échus**.
- *Transports Berthaud* : 456 € **échus**.
- *Inox Dauphiné* : 20 880 € + 3 360 €, à échéance au 30/11.

**Stock**
- Valeur d'environ 72 k€ au coût moyen, contre 29 k€ à la reprise : le stock a été reconstitué avant la saison d'hiver.
- Inventaire tracé de bout en bout : stock initial, réceptions, livraisons.

---

## 3. Scénario de démo proposé (≈ 60 min)

### Acte 1 — Achat → paiement fournisseur (P2P), 15 min
1. **Achats › Commandes** : montrer P00005 (Porcelaines Martin), *reçue, à facturer*.
2. **Créer la facture** depuis la commande. Montrer le **rapprochement à trois voies** (commandé / reçu / facturé), puis saisir la référence fournisseur et valider.
3. **Achats › P00006** (demande de prix Bassano) : l'envoyer puis la confirmer. Montrer que la position fiscale intra-UE applique l'**autoliquidation**.
4. **Comptabilité › Fournisseurs › Factures**, filtre *En retard* : Textiles et Berthaud. Sélectionner les factures dues, **Enregistrer un paiement** groupé, puis montrer le virement SEPA (si `account_sepa` est installé).

### Acte 2 — Vente → encaissement (O2C), 15 min
1. **Ventes › S00009** (devis Terrasses) : envoyer le devis, le confirmer, puis montrer la **réservation de stock**.
2. **S00010** (Auberge du Sablon) : livrer, facturer, puis montrer la **TVA 0 % intracom.** (position fiscale intra-UE).
3. Montrer S00005 (export Suisse) : la facture d'**acompte**, puis la **facture de solde** qui la déduit.
4. Montrer FAC/…/00007 et son **avoir** lettré (Traiteur Ferrand).

### Acte 3 — Trésorerie, 15 min
1. **Tableau de bord comptable › Banque du Rhône** : 25 lignes à rapprocher sur 3 relevés.
2. **Rapprocher** :
   - Encaissements et virements fournisseurs : rapprochement automatique avec les paiements et factures.
   - Salaires, URSSAF, TVA et frais bancaires : en un clic grâce aux **modèles de rapprochement**.
   - Ligne *L'Épi Gourmand* du 10/11 : la rapprocher directement avec la facture ouverte FAC/…/00009.
3. **Balance âgée clients** : Terrasses et Sablon en retard.
4. Lancer les **relances** (*Suivi des paiements*) et montrer le niveau 1.

### Acte 4 — Pilotage et clôture, 15 min
1. **Déclaration de TVA** (rapport de TVA) d'octobre : montrer les cases CA3 (ventes intracom., exports, autoliquidation), puis **clôturer** la période pour générer l'OD de liquidation vers 445510.
2. **Compte de résultat et bilan** : montrer les à-nouveaux et la paie.
3. **Inventaire › Rapports › Valorisation** : **écriture de variation de stock** proposée par la valorisation périodique.
4. **Grand livre** et **lettrage** d'un compte client.
5. Export **FEC** pour la remise à l'expert-comptable.

---

## 4. À savoir

- **Pas de rapprochement par script.** Les rapprochements bancaires ne sont volontairement pas faits par le script : en Community, ils sont impossibles, et en Enterprise, ils sont la partie la plus parlante de la démo.
- **Dates de stock.** Les dates des réceptions et livraisons sont rétro-datées après validation. Comme la valorisation est périodique, cela n'a aucun effet comptable.
- **Valorisation permanente.** Pour montrer la valorisation permanente (`real_time`), passez les catégories d'articles en *Permanent* **avant** de lancer le script. En v19, les écritures de stock sont alors générées **à la facturation**.
- **Volume des données.** Une seule constante, `SCALE`, multiplie toutes les quantités (5 par défaut).
- **Rejouer la démo.** Dupliquez la base juste après le script (gestionnaire de bases, ou odoo.sh *staging*). Vous pourrez ainsi rejouer la démo sans relancer le script.
