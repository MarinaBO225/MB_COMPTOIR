#!/usr/bin/env python3
"""
Base de démo « flux financier complet » pour Odoo 19 — entreprise de négoce.

Société fictive : COMPTOIR VELLARD SAS, Lyon — négoce de matériel et
consommables pour cafés-hôtels-restaurants (CHR).

Le script alimente une base Odoo 19 FRAÎCHE (Community ou Enterprise) par
XML-RPC, en ordre chronologique sur trois mois (M0, M1, M2 = mois en cours) :

  1. Paramétrage   : société FR, plan comptable français, banque, conditions
                     de paiement, modèles de rapprochement
  2. Référentiels  : fournisseurs (FR, UE), clients (FR, Belgique, Suisse),
                     11 articles stockés + frais de port
  3. Reprise       : à-nouveaux au 1er jour de M0 (banque, stock, clients et
                     fournisseurs ouverts, dettes sociales et fiscales)
                     + inventaire initial cohérent avec le compte 370000
  4. Achats        : commandes, réceptions (dont une partielle + reliquat),
                     factures fournisseurs (dont acquisition intracom.),
                     frais généraux (loyer, télécom, transport)
  5. Ventes        : devis, commandes, livraisons, factures, acompte + solde
                     (export Suisse), livraison intracom. (Belgique), avoir
  6. Règlements    : encaissements clients (dont partiel), décaissements
                     fournisseurs
  7. Paie          : OD de paie mensuelle simplifiée
  8. Banque        : relevés mensuels M0..M2 NON rapprochés (à rapprocher en
                     direct pendant la démo, avec modèles de rapprochement)
  9. Encours       : devis et commandes à traiter en direct, réception non
                     facturée (factures non parvenues), demande de prix

Usage :
    python3 demo_negoce_odoo19.py --url http://localhost:8069 \
        --db demo_negoce --user admin --password admin

Prérequis : base vierge (sans données de démonstration), modules installés :
    sale_management, purchase, stock, stock_account, l10n_fr_account
    (Enterprise : ajouter accountant pour le rapprochement et les rapports)
Le script installe lui-même les modules manquants si l'utilisateur est admin.
"""
import argparse
import calendar
import sys
import unicodedata
import xmlrpc.client
from datetime import date, timedelta

MARKER_REF = "CV-DEMO"  # référence posée sur la société pour éviter un double passage
SCALE = 5  # multiplicateur des quantités (stock, achats, ventes) : CA ≈ 45 k€ HT / mois


# --------------------------------------------------------------------------
# Connexion
# --------------------------------------------------------------------------
class Odoo:
    def __init__(self, url, db, user, password):
        self.url, self.db, self.password = url.rstrip("/"), db, password
        common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common", allow_none=True)
        self.uid = common.authenticate(db, user, password, {})
        if not self.uid:
            sys.exit("Échec d'authentification : vérifiez base, identifiant et mot de passe / clé API.")
        self.models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object", allow_none=True)
        self.ctx = {"lang": "fr_FR", "tz": "Europe/Paris"}

    def call(self, model, method, *args, context=None, **kw):
        ctx = dict(self.ctx, **(context or {}))
        kw["context"] = ctx
        try:
            return self.models.execute_kw(self.db, self.uid, self.password, model, method, list(args), kw)
        except xmlrpc.client.Fault as e:
            # La méthode s'est exécutée (et a été validée) mais a renvoyé None,
            # que le serveur ne sait pas sérialiser en XML-RPC : on l'ignore.
            if "cannot marshal None" in e.faultString:
                return None
            raise

    def create(self, model, vals, context=None):
        return self.call(model, "create", vals, context=context)

    def write(self, model, ids, vals, context=None):
        ids = ids if isinstance(ids, list) else [ids]
        return self.call(model, "write", ids, vals, context=context)

    def search(self, model, domain, limit=None, order=None):
        kw = {}
        if limit:
            kw["limit"] = limit
        if order:
            kw["order"] = order
        return self.call(model, "search", domain, **kw)

    def read(self, model, ids, fields):
        ids = ids if isinstance(ids, list) else [ids]
        return self.call(model, "read", ids, fields)

    def read1(self, model, rid, fields):
        return self.read(model, rid, fields)[0]

    def search_read(self, model, domain, fields, limit=None, order=None):
        kw = {"fields": fields}
        if limit:
            kw["limit"] = limit
        if order:
            kw["order"] = order
        return self.call(model, "search_read", domain, **kw)

    def ref(self, xmlid, raise_if_not_found=True):
        module, name = xmlid.split(".", 1)
        res = self.search_read("ir.model.data", [("module", "=", module), ("name", "=", name)], ["res_id"], limit=1)
        if not res:
            if raise_if_not_found:
                raise ValueError(f"Identifiant externe introuvable : {xmlid}")
            return False
        return res[0]["res_id"]


def log(msg):
    print(f"  • {msg}", flush=True)


def step(msg):
    print(f"\n== {msg}", flush=True)


# --------------------------------------------------------------------------
# Calendrier : M0 = mois N-2, M1 = N-1, M2 = mois en cours (jusqu'au 12)
# --------------------------------------------------------------------------
class Calendar:
    def __init__(self, today):
        # Les évènements de M2 vont jusqu'au 12 : avant le 13, on recule d'un mois.
        anchor = today if today.day >= 13 else (today.replace(day=1) - timedelta(days=1))
        y, m = anchor.year, anchor.month - 2
        if m <= 0:
            y, m = y - 1, m + 12
        self.t0 = date(y, m, 1)
        self.today = today

    def d(self, month_offset, day):
        y, m = self.t0.year, self.t0.month + month_offset
        while m > 12:
            y, m = y + 1, m - 12
        day = min(day, calendar.monthrange(y, m)[1]) if day != 31 else calendar.monthrange(y, m)[1]
        res = date(y, m, day)
        assert res <= self.today, f"date future {res}"
        return res

    def eom(self, month_offset):
        return self.d(month_offset, 31)

    def label(self, month_offset):
        mois = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
                "août", "septembre", "octobre", "novembre", "décembre"]
        dd = self.d(month_offset, 1)
        return f"{mois[dd.month - 1]} {dd.year}"

    def prev_label(self):
        mois = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
                "août", "septembre", "octobre", "novembre", "décembre"]
        p = self.t0 - timedelta(days=1)
        return f"{mois[p.month - 1]} {p.year}"


def s(d):
    return d.strftime("%Y-%m-%d")


def sdt(d, hour=10):
    return f"{s(d)} {hour:02d}:00:00"


# --------------------------------------------------------------------------
# Identifiants fictifs mais valides (clé SIREN Luhn, TVA FR, IBAN modulo 97)
# --------------------------------------------------------------------------
def luhn_siren(base8):
    digits = [int(c) for c in base8]
    for key in range(10):
        full = digits + [key]
        total = 0
        for i, dgt in enumerate(reversed(full)):
            if i % 2 == 1:
                dgt *= 2
                if dgt > 9:
                    dgt -= 9
            total += dgt
        if total % 10 == 0:
            return base8 + str(key)


def fr_vat(siren):
    return f"FR{(12 + 3 * (int(siren) % 97)) % 97:02d}{siren}"


def iban(country, bban):
    conv = "".join(str(int(c, 36)) for c in (bban + country + "00"))
    key = 98 - int(conv) % 97
    return f"{country}{key:02d}{bban}"


def fr_bban(bank, branch, account):
    # RIB : clé = 97 - ((89*banque + 15*guichet + 3*compte) mod 97)
    acc_num = "".join(str(int(c, 36) % 10) if c.isalpha() else c for c in account)
    key = 97 - ((89 * int(bank) + 15 * int(branch) + 3 * int(acc_num)) % 97)
    return f"{bank}{branch}{account}{key:02d}"


# --------------------------------------------------------------------------
# Données de référence
# --------------------------------------------------------------------------
COMPANY_SIREN = luhn_siren("91245873")

SUPPLIERS = {
    "martin": dict(name="Porcelaines Martin & Fils", street="18 avenue du Général Leclerc", zip="87000",
                   city="Limoges", country="FR", siren=luhn_siren("38215467"), term="45d",
                   email="commandes@porcelaines-martin.example", bank=("17806", "00412", "04512378901")),
    "inox": dict(name="Inox Dauphiné Équipements", street="5 rue des Fondeurs", zip="38100",
                 city="Grenoble", country="FR", siren=luhn_siren("45120983"), term="eom30",
                 email="adv@inox-dauphine.example", bank=("30004", "01823", "00010457823")),
    "bassano": dict(name="Coltelleria Bassano S.r.l.", street="Via dei Fabbri 22", zip="36061",
                    city="Bassano del Grappa", country="IT", vat="IT01893450245", term="30d",
                    email="export@coltelleria-bassano.example", fpos="intra"),
    "textiles": dict(name="Textiles Hôteliers de l'Ouest", street="Zone artisanale de la Bergerie", zip="49300",
                     city="Cholet", country="FR", siren=luhn_siren("50318264"), term="30d",
                     email="contact@tho-textiles.example", bank=("14706", "00031", "73211045620")),
    "berthaud": dict(name="Transports Berthaud", street="Port Edouard Herriot, quai Fillon", zip="69007",
                     city="Lyon", country="FR", siren=luhn_siren("33417820"), term="30d",
                     email="factu@transports-berthaud.example"),
    "sci": dict(name="SCI Les Tanneurs", street="2 place Jean Macé", zip="69007",
                city="Lyon", country="FR", siren=luhn_siren("49832105"), term="now",
                email="gestion@sci-tanneurs.example"),
    "telecom": dict(name="RhôneNet Télécom Pro", street="40 cours Lafayette", zip="69003",
                    city="Lyon", country="FR", siren=luhn_siren("52014763"), term="now",
                    email="facturation@rhonenet.example"),
    "urssaf": dict(name="URSSAF Rhône-Alpes", street="6 rue du 19 mars 1962", zip="69691",
                   city="Vénissieux", country="FR", term=None, email=False),
    "dgfip": dict(name="SIE Lyon 7e (DGFiP)", street="165 rue Garibaldi", zip="69003",
                  city="Lyon", country="FR", term=None, email=False),
}

CUSTOMERS = {
    "brasserie": dict(name="Brasserie du Vieux Port", street="12 quai de Rive Neuve", zip="13007",
                      city="Marseille", country="FR", siren=luhn_siren("80124537"), term="30d",
                      email="gerance@brasserie-vieuxport.example"),
    "terrasses": dict(name="Hôtel Les Terrasses du Parc", street="3 avenue d'Albigny", zip="74000",
                      city="Annecy", country="FR", siren=luhn_siren("51273904"), term="45d",
                      email="achats@terrasses-du-parc.example"),
    "epi": dict(name="Restaurant L'Épi Gourmand", street="27 rue Mercière", zip="69002",
                city="Lyon", country="FR", siren=luhn_siren("83350129"), term="now",
                email="contact@epi-gourmand.example"),
    "ferrand": dict(name="Traiteur Maison Ferrand", street="88 cours Émile Zola", zip="69100",
                    city="Villeurbanne", country="FR", siren=luhn_siren("42267318"), term="eom30",
                    email="compta@maison-ferrand.example"),
    "sablon": dict(name="Auberge du Sablon SRL", street="Rue de la Paille 14", zip="1000",
                   city="Bruxelles", country="BE", vat="BE0754328913", term="30d",
                   email="direction@auberge-sablon.example", fpos="intra"),
    "leman": dict(name="Hôtel du Lac Léman SA", street="Grand-Rue 41", zip="1820",
                  city="Montreux", country="CH", vat=False, term="30d",
                  email="economat@hotel-lac-leman.example", fpos="export"),
}

# code: (nom, catégorie, coût, prix de vente, fournisseur, stock initial)
PRODUCTS = {
    "ASS-PL27": ("Assiette plate porcelaine blanche Ø27 cm", "art", 4.20, 8.90, "martin", 200),
    "ASS-CR22": ("Assiette creuse porcelaine blanche Ø22 cm", "art", 3.80, 7.90, "martin", 150),
    "TAS-CAF": ("Tasse à café 9 cl avec soucoupe", "art", 2.10, 4.50, "martin", 200),
    "VER-BAL": ("Verre ballon 35 cl", "art", 1.60, 3.40, "martin", 600),
    "CSR-24": ("Casserole inox 18/10 Ø24 cm", "cuisine", 28.00, 54.00, "inox", 15),
    "BAC-GN11": ("Bac gastronorme inox GN 1/1 – 65 mm", "cuisine", 14.50, 29.00, "inox", 30),
    "FOU-INOX": ("Fouet inox 35 cm", "cuisine", 6.20, 12.90, "inox", 40),
    "COU-CH20": ("Couteau de chef forgé 20 cm", "coutellerie", 18.00, 39.00, "bassano", 25),
    "COU-OFF10": ("Couteau d'office 10 cm", "coutellerie", 5.40, 11.50, "bassano", 60),
    "NAP-50": ("Serviette de table coton 50×50 blanche", "linge", 2.30, 4.90, "textiles", 400),
    "TAB-160": ("Tablier de cuisine coton noir", "linge", 7.80, 16.50, "textiles", 30),
}
CATEGORIES = {"art": "Arts de la table", "cuisine": "Cuisine professionnelle",
              "coutellerie": "Coutellerie", "linge": "Linge hôtelier"}


# --------------------------------------------------------------------------
# Générateur
# --------------------------------------------------------------------------
class DemoBuilder:
    def __init__(self, odoo, cal):
        self.o, self.cal = odoo, cal
        self.partners, self.products, self.terms, self.taxes = {}, {}, {}, {}
        self.bank_lines = []  # (date, libellé, montant, partner_id)

    # ---------------------------------------------------------------- setup
    def ensure_modules(self):
        step("Modules")
        needed = ["sale_management", "purchase", "stock", "stock_account", "l10n_fr_account"]
        mods = self.o.search_read("ir.module.module", [("name", "in", needed)], ["name", "state"])
        todo = [m["id"] for m in mods if m["state"] != "installed"]
        if todo:
            log(f"installation : {', '.join(m['name'] for m in mods if m['state'] != 'installed')} (patience…)")
            self.o.call("ir.module.module", "button_immediate_install", todo)
        log("modules OK")

    def setup_company(self):
        step("Société et plan comptable")
        o = self.o
        self.company_id = o.search_read("res.users", [("id", "=", o.uid)], ["company_id"])[0]["company_id"][0]
        comp = o.read1("res.company", self.company_id, ["chart_template", "company_registry"])
        if comp["company_registry"] and MARKER_REF in (comp["company_registry"] or ""):
            sys.exit("Cette base contient déjà la démo Comptoir Vellard : repartez d'une base vierge.")
        fr = o.ref("base.fr")
        eur = o.ref("base.EUR")
        o.write("res.currency", eur, {"active": True})
        posted = o.search("account.move", [("company_id", "=", self.company_id), ("state", "=", "posted")], limit=1)
        vals = dict(name="Comptoir Vellard SAS", street="14 rue des Tanneurs", zip="69007", city="Lyon",
                    country_id=fr, phone="+33 4 72 00 00 00", email="contact@comptoir-vellard.example",
                    website="https://comptoir-vellard.example", vat=fr_vat(COMPANY_SIREN),
                    company_registry=f"{COMPANY_SIREN}00017")
        if comp["chart_template"] != "fr":
            if posted:
                sys.exit("La société a déjà des écritures avec un autre plan comptable : utilisez une base vierge.")
            vals["currency_id"] = eur
            o.write("res.company", self.company_id, vals)
            log("chargement du plan comptable français (PCG)…")
            wiz = o.create("res.config.settings", {"chart_template": "fr"})
            o.call("res.config.settings", "execute", [wiz])
        else:
            o.write("res.company", self.company_id, vals)
        o.write("res.company", self.company_id, {"company_registry": f"{COMPANY_SIREN}00017"})
        # Langue FR active pour l'admin
        langs = o.search("res.lang", [("code", "=", "fr_FR"), ("active", "=", True)])
        if not langs:
            o.call("base.language.install", "lang_install",
                   [o.create("base.language.install", {"lang_ids": [(6, 0, [o.search("res.lang", [("code", "=", "fr_FR"), ("active", "=", False)])[0]])]})])
        o.write("res.users", o.uid, {"lang": "fr_FR", "tz": "Europe/Paris"})
        # Fonctionnalités comptables complètes (déjà acquis en Enterprise, nécessaire en Community)
        o.write("res.users", o.uid, {"group_ids": [(4, o.ref("account.group_account_user"))]})
        o.write("res.partner", o.read1("res.company", self.company_id, ["partner_id"])["partner_id"][0],
                {"lang": "fr_FR"})
        # Exercice fiscal civil, date de reprise
        o.write("res.company", self.company_id, {"fiscalyear_last_month": "12", "fiscalyear_last_day": 31})
        log("Comptoir Vellard SAS — SIREN %s — %s" % (COMPANY_SIREN, fr_vat(COMPANY_SIREN)))

        cid = self.company_id

        def tax(xml):
            return o.ref(f"account.{cid}_{xml}")
        self.taxes = {
            "vente20": tax("tva_normale"),
            "achat20": tax("tva_acq_normale"),
        }

        def acc(code):
            r = o.search("account.account", [("code", "=", code)], limit=1)
            if not r:
                raise ValueError(f"compte {code} introuvable")
            return r[0]
        self.acc = acc
        self.terms = {
            "now": o.ref("account.account_payment_term_immediate"),
            "30d": o.ref("account.account_payment_term_30days"),
            "45d": o.ref("account.account_payment_term_45days"),
            "eom30": self._term_eom30(),
        }
        # Journaux
        self.j_sale = o.search("account.journal", [("type", "=", "sale"), ("company_id", "=", cid)], limit=1)[0]
        self.j_purchase = o.search("account.journal", [("type", "=", "purchase"), ("company_id", "=", cid)], limit=1)[0]
        self.j_misc = o.search("account.journal", [("type", "=", "general"), ("code", "=", "OD"), ("company_id", "=", cid)], limit=1)
        self.j_misc = self.j_misc[0] if self.j_misc else o.search("account.journal", [("type", "=", "general"), ("company_id", "=", cid)], limit=1)[0]
        self.j_bank = o.search("account.journal", [("type", "=", "bank"), ("company_id", "=", cid)], limit=1)[0]
        bank_id = o.create("res.bank", {"name": "Banque du Rhône (fictive)", "bic": "BDRHFRPPLYO"})
        company_partner = o.read1("res.company", cid, ["partner_id"])["partner_id"][0]
        acc_number = iban("FR", fr_bban("18207", "00350", "04123456789"))
        pbank = o.create("res.partner.bank", {"acc_number": acc_number, "partner_id": company_partner,
                                              "bank_id": bank_id, "allow_out_payment": True})
        o.write("account.journal", self.j_bank, {"name": "Banque du Rhône", "code": "BDR",
                                                 "bank_account_id": pbank})
        log(f"journal banque « Banque du Rhône » — {acc_number}")

    def _term_eom30(self):
        o = self.o
        found = o.search("account.payment.term", [("name", "=", "30 jours fin de mois")])
        if found:
            return found[0]
        return o.create("account.payment.term", {
            "name": "30 jours fin de mois",
            "line_ids": [(0, 0, {"value": "percent", "value_amount": 100.0,
                                 "nb_days": 30, "delay_type": "days_end_of_month_on_the",
                                 "days_next_month": "0"})],
        })

    def setup_reco_models(self):
        step("Modèles de rapprochement bancaire")
        o = self.o
        models = [
            ("Frais bancaires", "FRAIS", "627800", None),
            ("Virement salaires", "SALAIRES", "421000", None),
            ("URSSAF", "URSSAF", "431000", "urssaf"),
            ("TVA DGFiP", "DGFIP", "445510", "dgfip"),
        ]
        for name, label, code, partner in models:
            o.create("account.reconcile.model", {
                "name": name, "trigger": "manual",
                "match_journal_ids": [(6, 0, [self.j_bank])],
                "match_label": "contains", "match_label_param": label,
                "mapped_partner_id": self.partners[partner] if partner else False,
                "line_ids": [(0, 0, {"account_id": self.acc(code), "amount_type": "percentage",
                                     "amount_string": "100", "label": name})],
            })
            log(f"{name} → {code}")

    # ---------------------------------------------------------- référentiel
    def create_partners(self):
        step("Tiers")
        o = self.o
        countries = {c: o.ref(f"base.{c.lower()}") for c in ("FR", "IT", "BE", "CH")}
        cid = self.company_id
        fpos = {
            "intra": o.ref(f"account.{cid}_fiscal_position_template_intraeub2b"),
            "export": o.ref(f"account.{cid}_fiscal_position_template_import_export"),
        }
        for kind, data in (("supplier", SUPPLIERS), ("customer", CUSTOMERS)):
            for key, p in data.items():
                vals = dict(name=p["name"], is_company=True, street=p["street"], zip=p["zip"],
                            city=p["city"], country_id=countries[p["country"]], email=p["email"],
                            lang="fr_FR", ref=f"{'F' if kind == 'supplier' else 'C'}-{key.upper()[:6]}")
                if p.get("siren"):
                    vals["vat"] = fr_vat(p["siren"])
                    vals["company_registry"] = p["siren"] + "00012"
                elif p.get("vat"):
                    vals["vat"] = p["vat"]
                if p.get("fpos"):
                    vals["property_account_position_id"] = fpos[p["fpos"]]
                if p.get("term"):
                    field = "property_supplier_payment_term_id" if kind == "supplier" else "property_payment_term_id"
                    vals[field] = self.terms[p["term"]]
                pid = o.create("res.partner", vals)
                if p.get("bank"):
                    o.create("res.partner.bank", {"partner_id": pid, "acc_number": iban("FR", fr_bban(*p["bank"])),
                                                  "allow_out_payment": True})
                self.partners[key] = pid
                log(f"{'Fournisseur' if kind == 'supplier' else 'Client'} : {p['name']}")

    def create_products(self):
        step("Articles")
        o = self.o
        parent = o.create("product.category", {"name": "Négoce CHR"})
        categ = {}
        for k, name in CATEGORIES.items():
            categ[k] = o.create("product.category", {
                "name": name, "parent_id": parent,
                "property_cost_method": "average", "property_valuation": "periodic",
            })
        for code, (name, cat, cost, price, sup, _qty) in PRODUCTS.items():
            tmpl = o.create("product.template", {
                "name": name, "default_code": code, "type": "consu", "is_storable": True,
                "categ_id": categ[cat], "standard_price": cost, "list_price": price,
                "invoice_policy": "delivery", "purchase_method": "receive",
                "taxes_id": [(6, 0, [self.taxes["vente20"]])],
                "supplier_taxes_id": [(6, 0, [self.taxes["achat20"]])],
                "seller_ids": [(0, 0, {"partner_id": self.partners[sup], "price": cost, "delay": 5})],
            })
            self.products[code] = o.read1("product.template", tmpl, ["product_variant_id"])["product_variant_id"][0]
            log(f"{code} {name} — PA {cost:.2f} / PV {price:.2f}")
        tmpl = o.create("product.template", {
            "name": "Frais de port et livraison", "default_code": "PORT", "type": "service",
            "list_price": 45.0, "invoice_policy": "order", "sale_ok": True, "purchase_ok": False,
            "taxes_id": [(6, 0, [self.taxes["vente20"]])],
        })
        self.products["PORT"] = o.read1("product.template", tmpl, ["product_variant_id"])["product_variant_id"][0]
        log("PORT Frais de port — 45,00 HT")

    # --------------------------------------------------------- à-nouveaux
    def opening(self):
        step(f"Reprise des soldes au {s(self.cal.t0)}")
        o, cal = self.o, self.cal
        # Inventaire initial
        wh_loc = o.search_read("stock.warehouse", [("company_id", "=", self.company_id)], ["lot_stock_id"], limit=1)[0]["lot_stock_id"][0]
        o.write("stock.warehouse", o.search("stock.warehouse", [("company_id", "=", self.company_id)], limit=1),
                {"name": "Entrepôt Lyon Gerland"})
        stock_value = 0.0
        quant_ids = []
        for code, (_n, _c, cost, _p, _s, qty) in PRODUCTS.items():
            q = o.create("stock.quant", {"product_id": self.products[code], "location_id": wh_loc,
                                         "inventory_quantity": qty * SCALE}, context={"inventory_mode": True})
            quant_ids.append(q)
            stock_value += round(cost * qty * SCALE, 2)
        o.call("stock.quant", "action_apply_inventory", quant_ids)
        moves = o.search("stock.move", [("is_inventory", "=", True), ("state", "=", "done")])
        o.write("stock.move", moves, {"date": sdt(cal.t0, 7)})
        o.write("stock.move.line", o.search("stock.move.line", [("move_id", "in", moves)]), {"date": sdt(cal.t0, 7)})
        log(f"inventaire initial : {len(PRODUCTS)} articles, valeur {stock_value:,.2f} €")

        # Écriture d'à-nouveaux
        P = self.partners
        recv = o.read1("res.partner", P["brasserie"], ["property_account_receivable_id"])["property_account_receivable_id"][0]
        pay = o.read1("res.partner", P["martin"], ["property_account_payable_id"])["property_account_payable_id"][0]
        bank_acc = o.read1("account.journal", self.j_bank, ["default_account_id"])["default_account_id"][0]
        prev = cal.prev_label()
        due = s(cal.d(0, 15))
        lines = [
            ("Banque du Rhône — solde au relevé", bank_acc, 85000.00, 0, False, False),
            ("Stock de marchandises (inventaire)", self.acc("370000"), stock_value, 0, False, False),
            ("FAC-ANC-0412 Brasserie du Vieux Port", recv, 14400.00, 0, P["brasserie"], due),
            ("FAC-ANC-0418 Hôtel Les Terrasses du Parc", recv, 21120.00, 0, P["terrasses"], s(cal.d(0, 30))),
            ("FF Porcelaines Martin n° PM-25871", pay, 0, 31200.00, P["martin"], s(cal.d(0, 20))),
            (f"Salaires nets {prev}", self.acc("421000"), 0, 9800.00, False, False),
            (f"Cotisations sociales {prev}", self.acc("431000"), 0, 8100.00, P["urssaf"], False),
            (f"TVA à décaisser {prev}", self.acc("445510"), 0, 3950.00, P["dgfip"], False),
            ("Capital social", self.acc("101300"), 0, 50000.00, False, False),
            ("Compte courant d'associé — M. Vellard", self.acc("455100"), 0, 20000.00, False, False),
        ]
        debit = sum(line[2] for line in lines)
        credit = sum(line[3] for line in lines)
        plug = round(debit - credit, 2)
        lines.append(("Report à nouveau / résultat de la période", self.acc("110000") if plug > 0 else self.acc("119000"),
                      0 if plug > 0 else -plug, plug if plug > 0 else 0, False, False))
        move = o.create("account.move", {
            "move_type": "entry", "journal_id": self.j_misc, "date": s(cal.t0),
            "ref": f"À-nouveaux — reprise de balance au {(cal.t0 - timedelta(days=1)).strftime('%d/%m/%Y')}",
            "line_ids": [(0, 0, {"name": n, "account_id": a, "debit": d, "credit": c,
                                 "partner_id": p, "date_maturity": m}) for n, a, d, c, p, m in lines],
        })
        o.call("account.move", "action_post", [move])
        self.opening_move = move
        o.write("res.company", self.company_id, {"account_opening_date": s(cal.t0)})
        log(f"à-nouveaux comptabilisés (total {debit:,.2f} €, report à nouveau {plug:,.2f} €)")

    def _opening_line(self, partner_key):
        return self.o.search("account.move.line", [("move_id", "=", self.opening_move),
                                                   ("partner_id", "=", self.partners[partner_key]),
                                                   ("account_id.account_type", "in", ["asset_receivable", "liability_payable"])])

    # --------------------------------------------------------------- achats
    def purchase(self, sup, d, lines, ref=None):
        o = self.o
        po = o.create("purchase.order", {
            "partner_id": self.partners[sup], "date_order": sdt(d, 9), "partner_ref": ref or False,
            "order_line": [(0, 0, {"product_id": self.products[c], "product_qty": q * SCALE,
                                   **({"price_unit": pu} if pu else {})}) for c, q, pu in
                           [(x[0], x[1], x[2] if len(x) > 2 else None) for x in lines]],
        })
        o.call("purchase.order", "button_confirm", [po])
        o.write("purchase.order", po, {"date_order": sdt(d, 9), "date_approve": sdt(d, 9)})
        name = o.read1("purchase.order", po, ["name"])["name"]
        log(f"{name} {SUPPLIERS[sup]['name']} confirmée le {d.strftime('%d/%m')}")
        return po

    def receive(self, po, d, qty_by_code=None):
        """Réceptionne les quantités (tout par défaut) ; crée un reliquat si partiel."""
        o = self.o
        picks = o.search("stock.picking", [("purchase_id", "=", po), ("state", "not in", ["done", "cancel"])])
        return self._validate_picking(picks[0], d, qty_by_code)

    def _validate_picking(self, pick, d, qty_by_code=None):
        o = self.o
        o.call("stock.picking", "action_assign", [pick])
        moves = o.search_read("stock.move", [("picking_id", "=", pick)], ["product_id", "product_uom_qty"])
        code_of = {v: k for k, v in self.products.items()}
        partial = False
        for m in moves:
            code = code_of[m["product_id"][0]]
            qty = m["product_uom_qty"] if not qty_by_code or code not in qty_by_code else qty_by_code[code] * SCALE
            partial |= qty < m["product_uom_qty"]
            o.write("stock.move", m["id"], {"quantity": qty, "picked": True})
        o.call("stock.picking", "button_validate", [pick], context={"skip_backorder": True, "skip_sms": True})
        o.write("stock.picking", pick, {"date_done": sdt(d, 11), "scheduled_date": sdt(d, 11)})
        mv = o.search("stock.move", [("picking_id", "=", pick)])
        o.write("stock.move", mv, {"date": sdt(d, 11)})
        o.write("stock.move.line", o.search("stock.move.line", [("move_id", "in", mv)]), {"date": sdt(d, 11)})
        info = o.read1("stock.picking", pick, ["name", "state"])
        assert info["state"] == "done", info
        log(f"{info['name']} validé le {d.strftime('%d/%m')}{' (partiel, reliquat créé)' if partial else ''}")
        return pick

    def bill_from_po(self, po, d, supplier_ref):
        o = self.o
        o.call("purchase.order", "action_create_invoice", [po])
        bills = o.search("account.move", [("move_type", "=", "in_invoice"), ("state", "=", "draft"),
                                          ("invoice_line_ids.purchase_line_id.order_id", "=", po)])
        bill = bills[-1]
        o.write("account.move", bill, {"invoice_date": s(d), "date": s(d), "ref": supplier_ref})
        o.call("account.move", "action_post", [bill])
        r = o.read1("account.move", bill, ["name", "amount_total"])
        log(f"facture fournisseur {r['name']} ({supplier_ref}) {r['amount_total']:,.2f} € TTC")
        return bill

    def expense_bill(self, sup, d, ref, label, account_code, amount_ht):
        o = self.o
        bill = o.create("account.move", {
            "move_type": "in_invoice", "partner_id": self.partners[sup], "invoice_date": s(d), "date": s(d),
            "ref": ref, "journal_id": self.j_purchase,
            "invoice_line_ids": [(0, 0, {"name": label, "quantity": 1, "price_unit": amount_ht,
                                         "account_id": self.acc(account_code),
                                         "tax_ids": [(6, 0, [self.taxes["achat20"]])]})],
        })
        o.call("account.move", "action_post", [bill])
        r = o.read1("account.move", bill, ["name", "amount_total"])
        log(f"{r['name']} {SUPPLIERS[sup]['name']} — {label} {r['amount_total']:,.2f} € TTC")
        return bill

    # ---------------------------------------------------------------- ventes
    def sale(self, cust, d, lines, confirm=True, note=None):
        o = self.o
        so = o.create("sale.order", {
            "partner_id": self.partners[cust], "date_order": sdt(d, 9),
            "client_order_ref": note or False,
            "order_line": [(0, 0, {"product_id": self.products[c],
                                   "product_uom_qty": q if c == "PORT" else q * SCALE}) for c, q in lines],
        })
        if confirm:
            o.call("sale.order", "action_confirm", [so])
            o.write("sale.order", so, {"date_order": sdt(d, 9)})
        name = o.read1("sale.order", so, ["name"])["name"]
        log(f"{name} {CUSTOMERS[cust]['name']} {'confirmée' if confirm else 'devis'} le {d.strftime('%d/%m')}")
        return so

    def deliver(self, so, d):
        o = self.o
        pick = o.search("stock.picking", [("sale_id", "=", so), ("state", "not in", ["done", "cancel"])])[0]
        return self._validate_picking(pick, d)

    def invoice_so(self, so, d, method="delivered", amount=None):
        o = self.o
        vals = {"advance_payment_method": method, "sale_order_ids": [(6, 0, [so])]}
        if amount:
            vals["amount"] = amount
        ctx = {"active_model": "sale.order", "active_ids": [so], "active_id": so}
        wiz = o.create("sale.advance.payment.inv", vals, context=ctx)
        o.call("sale.advance.payment.inv", "create_invoices", [wiz], context=ctx)
        inv = o.search("account.move", [("move_type", "=", "out_invoice"), ("state", "=", "draft"),
                                        ("line_ids.sale_line_ids.order_id", "=", so)])[-1]
        o.write("account.move", inv, {"invoice_date": s(d), "date": s(d)})
        o.call("account.move", "action_post", [inv])
        r = o.read1("account.move", inv, ["name", "amount_total", "invoice_date_due"])
        kind = "acompte" if method != "delivered" else "facture"
        log(f"{kind} {r['name']} {r['amount_total']:,.2f} € TTC — échéance {r['invoice_date_due']}")
        return inv

    def credit_note(self, inv, d, reason, lines):
        """Avoir partiel : lignes (code, qté)."""
        o = self.o
        src = o.read1("account.move", inv, ["partner_id", "name", "fiscal_position_id"])
        price = {c: o.search_read("account.move.line", [("move_id", "=", inv), ("product_id", "=", self.products[c])],
                                  ["price_unit"], limit=1)[0]["price_unit"] for c, _q in lines}
        rf = o.create("account.move", {
            "move_type": "out_refund", "partner_id": src["partner_id"][0], "invoice_date": s(d), "date": s(d),
            "ref": f"Avoir sur {src['name']} — {reason}", "reversed_entry_id": inv,
            "fiscal_position_id": src["fiscal_position_id"] and src["fiscal_position_id"][0],
            "invoice_line_ids": [(0, 0, {"product_id": self.products[c], "quantity": q * SCALE, "price_unit": price[c],
                                         "tax_ids": [(6, 0, [self.taxes["vente20"]])]}) for c, q in lines],
        })
        o.call("account.move", "action_post", [rf])
        # Lettrage avoir / facture
        lines_ids = o.search("account.move.line", [("move_id", "in", [inv, rf]),
                                                   ("account_id.account_type", "=", "asset_receivable")])
        o.call("account.move.line", "reconcile", lines_ids)
        r = o.read1("account.move", rf, ["name", "amount_total"])
        log(f"avoir {r['name']} {r['amount_total']:,.2f} € TTC lettré sur {src['name']}")
        return rf

    # ----------------------------------------------------------- règlements
    def pay(self, move_ids=None, line_ids=None, d=None, amount=None, memo=None, bank_label=None):
        """Enregistre un règlement (wizard standard) et ajoute la ligne de relevé bancaire."""
        o = self.o
        if move_ids:
            ctx = {"active_model": "account.move", "active_ids": move_ids}
        else:
            ctx = {"active_model": "account.move.line", "active_ids": line_ids}
        vals = {"payment_date": s(d), "journal_id": self.j_bank}
        if amount:
            vals["amount"] = amount
            vals["payment_difference_handling"] = "open"
        if memo:
            vals["communication"] = memo
        wiz = o.create("account.payment.register", vals, context=ctx)
        w = o.read1("account.payment.register", wiz, ["amount", "partner_id", "payment_type", "communication"])
        o.call("account.payment.register", "action_create_payments", [wiz], context=ctx)
        signed = w["amount"] if w["payment_type"] == "inbound" else -w["amount"]
        label = bank_label or (("VIR RECU " if signed > 0 else "VIR SEPA ") + f"{w['partner_id'][1].upper()} {w['communication'] or ''}").strip()
        self.bank_lines.append((d, label, signed, w["partner_id"][0]))
        log(f"règlement {w['partner_id'][1]} {signed:+,.2f} € le {d.strftime('%d/%m')}")

    def bank_only(self, d, label, amount, partner=None):
        self.bank_lines.append((d, label, amount, self.partners[partner] if partner else False))

    @staticmethod
    def bank_label(text):
        """Libellé façon relevé bancaire : majuscules sans accents."""
        return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().upper()

    # ------------------------------------------------------------------ paie
    def payroll(self, month_offset):
        o, cal = self.o, self.cal
        d = cal.eom(month_offset)
        brut, net, patronal = 12600.00, 9800.00, 5300.00
        mv = o.create("account.move", {
            "move_type": "entry", "journal_id": self.j_misc, "date": s(d),
            "ref": f"Paie {cal.label(month_offset)} (4 salariés) — journal de paie externe",
            "line_ids": [
                (0, 0, {"name": "Salaires bruts", "account_id": self.acc("641100"), "debit": brut}),
                (0, 0, {"name": "Charges patronales URSSAF", "account_id": self.acc("645100"), "debit": patronal}),
                (0, 0, {"name": "Salaires nets à payer", "account_id": self.acc("421000"), "credit": net}),
                (0, 0, {"name": "Cotisations sociales à payer", "account_id": self.acc("431000"),
                        "partner_id": self.partners["urssaf"], "credit": brut - net + patronal}),
            ],
        })
        o.call("account.move", "action_post", [mv])
        log(f"OD de paie {cal.label(month_offset)} : brut {brut:,.0f} €, net {net:,.0f} €")

    def vat_due(self, month_offset):
        """TVA nette du mois (collectée − déductible) calculée depuis les écritures."""
        o, cal = self.o, self.cal
        start, end = cal.d(month_offset, 1), cal.eom(month_offset)
        res = o.search_read("account.move.line",
                            [("parent_state", "=", "posted"), ("date", ">=", s(start)), ("date", "<=", s(end)),
                             ("tax_line_id", "!=", False)], ["balance"])
        return round(-sum(r["balance"] for r in res), 2)

    # ---------------------------------------------------------------- banque
    def bank_statements(self):
        step("Relevés bancaires (non rapprochés)")
        o, cal = self.o, self.cal
        balance = 85000.00
        for m in range(3):
            start = cal.d(m, 1)
            end = cal.eom(m) if m < 2 else cal.d(2, 12)
            lines = sorted([b for b in self.bank_lines if start <= b[0] <= end], key=lambda b: (b[0], -b[2]))
            ids = []
            for d, label, amount, partner in lines:
                ids.append(o.create("account.bank.statement.line", {
                    "journal_id": self.j_bank, "date": s(d), "payment_ref": self.bank_label(label),
                    "amount": round(amount, 2), "partner_id": partner}))
            total = round(sum(b[2] for b in lines), 2)
            end_bal = round(balance + total, 2)
            o.create("account.bank.statement", {
                "name": f"Relevé BDR {start.strftime('%m/%Y')}", "date": s(end),
                "balance_start": balance, "balance_end_real": end_bal,
                "line_ids": [(6, 0, ids)]})
            log(f"relevé {start.strftime('%m/%Y')} : {len(ids)} opérations, solde {balance:,.2f} → {end_bal:,.2f} €")
            balance = end_bal

    # ============================================================ SCÉNARIO
    def run(self):
        cal, P = self.cal, self.partners
        self.ensure_modules()
        self.setup_company()
        self.create_partners()
        self.create_products()
        self.setup_reco_models()
        self.opening()

        # ---------------------------------------------------------- MOIS M0
        step(f"Mois M0 — {cal.label(0)}")
        self.expense_bill("sci", cal.d(0, 1), f"QUIT-{cal.d(0,1):%Y%m}", f"Loyer entrepôt et bureaux — {cal.label(0)}", "613200", 2400.00)
        po1 = self.purchase("martin", cal.d(0, 2), [("ASS-PL27", 600), ("ASS-CR22", 400), ("TAS-CAF", 500)])
        po2 = self.purchase("bassano", cal.d(0, 3), [("COU-CH20", 150), ("COU-OFF10", 300)])
        self.pay(move_ids=None, line_ids=self._opening_line("brasserie"), d=cal.d(0, 4),
                 bank_label="VIR RECU BRASSERIE DU VIEUX PORT FAC-ANC-0412")
        self.pay(move_ids=[self.sci_bill(0)], d=cal.d(0, 5), bank_label=f"PRLV SEPA SCI LES TANNEURS LOYER {cal.d(0,1):%m/%Y}")
        self.receive(po1, cal.d(0, 5))
        self.bill_from_po(po1, cal.d(0, 6), "PM-26114")
        self.bank_only(cal.d(0, 8), f"VIR SALAIRES {cal.prev_label().upper()}", -9800.00)
        so1 = self.sale("brasserie", cal.d(0, 8), [("ASS-PL27", 120), ("ASS-CR22", 80), ("VER-BAL", 240), ("PORT", 1)])
        self.deliver(so1, cal.d(0, 10))
        inv1 = self.invoice_so(so1, cal.d(0, 10))
        self.receive(po2, cal.d(0, 12))
        self.bill_from_po(po2, cal.d(0, 12), "CB-2026/1187")
        self.expense_bill("berthaud", cal.d(0, 12), "TB-48211", "Transport Italie → Lyon (coutellerie Bassano)", "624100", 380.00)
        so2 = self.sale("terrasses", cal.d(0, 12), [("TAS-CAF", 150), ("ASS-PL27", 200), ("NAP-50", 300), ("TAB-160", 20)])
        po3 = self.purchase("inox", cal.d(0, 15), [("CSR-24", 60), ("BAC-GN11", 120), ("FOU-INOX", 100)])
        self.bank_only(cal.d(0, 15), f"PRLV URSSAF RHONE-ALPES {cal.prev_label().upper()}", -8100.00, "urssaf")
        self.deliver(so2, cal.d(0, 16))
        inv2 = self.invoice_so(so2, cal.d(0, 16))
        so3 = self.sale("epi", cal.d(0, 18), [("COU-CH20", 12), ("CSR-24", 6), ("BAC-GN11", 10), ("FOU-INOX", 8)])
        self.deliver(so3, cal.d(0, 18))
        inv3 = self.invoice_so(so3, cal.d(0, 18))
        self.pay(move_ids=[inv3], d=cal.d(0, 19))
        self.bank_only(cal.d(0, 19), f"PRLV DGFIP TVA {cal.prev_label().upper()}", -3950.00, "dgfip")
        self.pay(line_ids=self._opening_line("martin"), d=cal.d(0, 20), bank_label="VIR SEPA PORCELAINES MARTIN PM-25871")
        self.receive(po3, cal.d(0, 22), {"CSR-24": 40})
        so4 = self.sale("sablon", cal.d(0, 25), [("ASS-PL27", 150), ("ASS-CR22", 100), ("COU-CH20", 30), ("VER-BAL", 180), ("PORT", 2)])
        self.pay(line_ids=self._opening_line("terrasses"), d=cal.d(0, 28), bank_label="VIR RECU HOTEL LES TERRASSES DU PARC FAC-ANC-0418")
        self.deliver(so4, cal.d(0, 29))
        inv4 = self.invoice_so(so4, cal.d(0, 29))
        tel0 = self.expense_bill("telecom", cal.eom(0), f"RN-{cal.d(0,1):%Y%m}-0388", f"Abonnement fibre + 5 lignes mobiles — {cal.label(0)}", "626000", 89.00)
        self.payroll(0)
        self.bank_only(cal.eom(0), f"FRAIS TENUE DE COMPTE ET COMMISSIONS {cal.d(0,1):%m/%Y}", -38.50)

        # ---------------------------------------------------------- MOIS M1
        step(f"Mois M1 — {cal.label(1)}")
        self.expense_bill("sci", cal.d(1, 1), f"QUIT-{cal.d(1,1):%Y%m}", f"Loyer entrepôt et bureaux — {cal.label(1)}", "613200", 2400.00)
        po4 = self.purchase("textiles", cal.d(1, 1), [("NAP-50", 1000), ("TAB-160", 80)])
        so5 = self.sale("leman", cal.d(1, 2), [("CSR-24", 30), ("BAC-GN11", 60), ("COU-CH20", 40), ("COU-OFF10", 80), ("PORT", 3)],
                        note="Réouverture saison d'hiver")
        dp5 = self.invoice_so(so5, cal.d(1, 2), method="percentage", amount=30)
        self.pay(move_ids=[self.sci_bill(1)], d=cal.d(1, 5), bank_label=f"PRLV SEPA SCI LES TANNEURS LOYER {cal.d(1,1):%m/%Y}")
        self.pay(move_ids=[tel0], d=cal.d(1, 5), bank_label=f"PRLV SEPA RHONENET TELECOM {cal.d(0,1):%m/%Y}")
        self.pay(move_ids=[dp5], d=cal.d(1, 6), bank_label="VIR RECU HOTEL DU LAC LEMAN SA ACOMPTE")
        self.pay(move_ids=[inv1], d=cal.d(1, 8))
        self.bank_only(cal.d(1, 8), f"VIR SALAIRES {cal.label(0).upper()}", -9800.00)
        self.bill_from_po(po3, cal.d(1, 2), "IDE-F-9921")  # facture des quantités reçues en M0
        self.receive(po3, cal.d(1, 8))  # reliquat casseroles
        self.receive(po4, cal.d(1, 9))
        self.bill_from_po(po3, cal.d(1, 10), "IDE-F-10037")
        self.bill_from_po(po4, cal.d(1, 10), "THO-2026-5512")
        self.pay(move_ids=[self._bill_of(po2)], d=cal.d(1, 10))
        so6 = self.sale("ferrand", cal.d(1, 13), [("NAP-50", 400), ("TAB-160", 30), ("ASS-PL27", 100)])
        self.deliver(so5, cal.d(1, 14))
        inv5 = self.invoice_so(so5, cal.d(1, 14))
        self.bank_only(cal.d(1, 15), f"PRLV URSSAF RHONE-ALPES {cal.label(0).upper()}", -8100.00, "urssaf")
        self.deliver(so6, cal.d(1, 15))
        inv6 = self.invoice_so(so6, cal.d(1, 15))
        vat0 = self.vat_due(0)
        if vat0 > 0:
            self.bank_only(cal.d(1, 19), f"PRLV DGFIP TVA {cal.label(0).upper()}", -vat0, "dgfip")
            log(f"TVA {cal.label(0)} à décaisser : {vat0:,.2f} €")
        else:
            log(f"crédit de TVA {cal.label(0)} reporté : {-vat0:,.2f} €")
        self.pay(move_ids=[self._bill_of(po1)], d=cal.d(1, 20))
        self.credit_note(inv6, cal.d(1, 20), "20 assiettes cassées à la livraison", [("ASS-PL27", 20)])
        so7 = self.sale("brasserie", cal.d(1, 20), [("COU-OFF10", 40), ("FOU-INOX", 20), ("TAS-CAF", 100), ("PORT", 1)])
        self.deliver(so7, cal.d(1, 22))
        inv7 = self.invoice_so(so7, cal.d(1, 22))
        self.pay(move_ids=[inv2], d=cal.eom(1), amount=20000.00, memo="Acompte sur facture",
                 bank_label="VIR RECU HOTEL LES TERRASSES DU PARC REGLEMENT PARTIEL")
        tel1 = self.expense_bill("telecom", cal.eom(1), f"RN-{cal.d(1,1):%Y%m}-0412", f"Abonnement fibre + 5 lignes mobiles — {cal.label(1)}", "626000", 89.00)
        self.payroll(1)
        self.bank_only(cal.eom(1), f"FRAIS TENUE DE COMPTE ET COMMISSIONS {cal.d(1,1):%m/%Y}", -41.20)

        # ---------------------------------------------------------- MOIS M2
        step(f"Mois M2 — {cal.label(2)} (jusqu'au 12)")
        self.expense_bill("sci", cal.d(2, 1), f"QUIT-{cal.d(2,1):%Y%m}", f"Loyer entrepôt et bureaux — {cal.label(2)}", "613200", 2400.00)
        po5 = self.purchase("martin", cal.d(2, 3), [("VER-BAL", 1200), ("ASS-PL27", 300)])
        so8 = self.sale("epi", cal.d(2, 4), [("ASS-CR22", 60), ("VER-BAL", 120)])
        self.pay(move_ids=[self.sci_bill(2)], d=cal.d(2, 5), bank_label=f"PRLV SEPA SCI LES TANNEURS LOYER {cal.d(2,1):%m/%Y}")
        self.pay(move_ids=[tel1], d=cal.d(2, 5), bank_label=f"PRLV SEPA RHONENET TELECOM {cal.d(1,1):%m/%Y}")
        self.pay(move_ids=[inv5], d=cal.d(2, 5))
        self.bank_only(cal.d(2, 6), f"VIR SALAIRES {cal.label(1).upper()}", -9800.00)
        self.deliver(so8, cal.d(2, 6))
        inv8 = self.invoice_so(so8, cal.d(2, 6))
        self.receive(po5, cal.d(2, 10))            # reçue, NON facturée : facture à saisir en démo
        self.bank_only(cal.d(2, 10), "VIR RECU RESTAURANT L EPI GOURMAND " +
                       self.o.read1("account.move", inv8, ["name"])["name"],
                       self.o.read1("account.move", inv8, ["amount_total"])["amount_total"], "epi")
        # Encours à dérouler en direct
        self.sale("terrasses", cal.d(2, 10), [("ASS-PL27", 150), ("TAS-CAF", 120), ("VER-BAL", 300)], confirm=False,
                  note="Devis renouvellement vaisselle restaurant")
        self.sale("sablon", cal.d(2, 12), [("COU-CH20", 20), ("BAC-GN11", 25), ("NAP-50", 200), ("PORT", 1)])
        rfq = self.o.create("purchase.order", {"partner_id": P["bassano"], "date_order": sdt(cal.d(2, 12), 9),
                                               "order_line": [(0, 0, {"product_id": self.products["COU-CH20"], "product_qty": 120}),
                                                              (0, 0, {"product_id": self.products["COU-OFF10"], "product_qty": 200})]})
        log(f"demande de prix {self.o.read1('purchase.order', rfq, ['name'])['name']} Coltelleria Bassano (brouillon)")

        self.bank_statements()

    # helpers scénario
    def sci_bill(self, m):
        return self.o.search("account.move", [("partner_id", "=", self.partners["sci"]), ("move_type", "=", "in_invoice"),
                                              ("invoice_date", "=", s(self.cal.d(m, 1)))], limit=1)[0]

    def _bill_of(self, po, first=False):
        bills = self.o.search("account.move", [("move_type", "=", "in_invoice"), ("state", "=", "posted"),
                                               ("invoice_line_ids.purchase_line_id.order_id", "=", po)], order="id asc")
        return bills[0] if first else bills[-1]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://localhost:8069")
    ap.add_argument("--db", required=True)
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="admin", help="mot de passe ou clé API")
    ap.add_argument("--today", help="date de référence AAAA-MM-JJ (défaut : aujourd'hui)")
    a = ap.parse_args()
    today = date.fromisoformat(a.today) if a.today else date.today()
    cal = Calendar(today)
    print(f"Démo Comptoir Vellard — période du {cal.t0:%d/%m/%Y} au {cal.d(2, 12):%d/%m/%Y}")
    DemoBuilder(Odoo(a.url, a.db, a.user, a.password), cal).run()
    print("\nTerminé. Connectez-vous et suivez le scénario du README.")


if __name__ == "__main__":
    main()
