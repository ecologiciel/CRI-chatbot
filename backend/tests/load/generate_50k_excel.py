"""Generate a 50,000-row Excel file for dossier import load testing.

Column headers match the import service alias sets defined in
backend/app/services/dossier/import_service.py (lines 80-106).

Usage:
    cd backend
    python tests/load/generate_50k_excel.py
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

import openpyxl

# ---------------------------------------------------------------------------
# Data pools
# ---------------------------------------------------------------------------

STATUTS = ["en_cours", "validé", "rejeté", "en_attente", "complément", "incomplet"]

TYPES_PROJET = [
    "Création",
    "Extension",
    "Restructuration",
    "Diversification",
    "Mise à niveau",
]

SECTEURS = [
    "Industrie",
    "Agriculture",
    "Services",
    "Tourisme",
    "Commerce",
    "BTP",
    "Artisanat",
    "Pêche maritime",
    "Technologies",
    "Énergie renouvelable",
]

REGIONS = [
    "Rabat-Salé-Kénitra",
    "Casablanca-Settat",
    "Marrakech-Safi",
    "Tanger-Tétouan-Al Hoceïma",
    "Fès-Meknès",
    "Oriental",
    "Souss-Massa",
    "Béni Mellal-Khénifra",
    "Drâa-Tafilalet",
    "Laâyoune-Sakia El Hamra",
    "Dakhla-Oued Ed Dahab",
    "Guelmim-Oued Noun",
]

PRENOMS = [
    "Mohamed", "Ahmed", "Youssef", "Karim", "Hassan",
    "Fatima", "Amina", "Khadija", "Nadia", "Sara",
]

NOMS = [
    "Alaoui", "Benali", "El Idrissi", "Berrada", "Tazi",
    "Fassi", "Cherkaoui", "Benmoussa", "Lahlou", "Sqalli",
]

FORMES_JURIDIQUES = ["SARL", "SA", "SNC", "Auto-entrepreneur", "Coopérative"]

ACTIVITES = [
    "Import-Export", "Consulting", "Agroalimentaire", "Textile",
    "Immobilier", "Restauration", "Logistique", "Formation",
    "BTP", "Technologies", "Énergie", "Tourisme",
]

ROW_COUNT = 50_000
OUTPUT_DIR = Path(__file__).parent / "data"
OUTPUT_FILE = OUTPUT_DIR / "dossiers_50k.xlsx"


def _random_phone() -> str:
    prefix = random.choice(["6", "7"])
    return f"+212{prefix}{random.randint(10000000, 99999999)}"


def _random_date(start: date, end: date) -> str:
    delta = (end - start).days
    d = start + timedelta(days=random.randint(0, delta))
    return d.strftime("%d/%m/%Y")


def _random_company() -> str:
    prenom = random.choice(PRENOMS)
    nom = random.choice(NOMS)
    activite = random.choice(ACTIVITES)
    forme = random.choice(FORMES_JURIDIQUES)
    return f"{prenom} {nom} {activite} {forme}"


def _random_montant() -> int:
    return random.randint(50_000, 100_000_000)


def generate() -> None:
    """Generate the 50K-row Excel file."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.Workbook(write_only=True)
    ws = wb.create_sheet(title="Dossiers")

    # Headers matching import_service.py alias sets
    headers = [
        "Numéro Dossier",        # -> numero (NUMERO_ALIASES)
        "Statut",                 # -> statut (STATUT_ALIASES)
        "Type Projet",            # -> type_projet (TYPE_PROJET_ALIASES)
        "Raison Sociale",         # -> raison_sociale (RAISON_SOCIALE_ALIASES)
        "Montant Investissement", # -> montant_investissement (MONTANT_ALIASES)
        "Région",                 # -> region (REGION_ALIASES)
        "Secteur",                # -> secteur (SECTEUR_ALIASES)
        "Date Dépôt",            # -> date_depot (DATE_DEPOT_ALIASES)
        "Téléphone",             # -> phone (PHONE_ALIASES)
        "Observations",           # -> observations (OBSERVATIONS_ALIASES)
    ]
    ws.append(headers)

    start_date = date(2023, 1, 1)
    end_date = date(2025, 12, 31)

    for i in range(ROW_COUNT):
        row = [
            f"2024-{i + 1:06d}",                   # Numéro Dossier
            random.choice(STATUTS),                  # Statut
            random.choice(TYPES_PROJET),             # Type Projet
            _random_company(),                       # Raison Sociale
            _random_montant(),                       # Montant Investissement
            random.choice(REGIONS),                  # Région
            random.choice(SECTEURS),                 # Secteur
            _random_date(start_date, end_date),      # Date Dépôt
            _random_phone(),                         # Téléphone
            f"Observation {i + 1}" if random.random() > 0.7 else None,  # Observations
        ]
        ws.append(row)

    wb.save(str(OUTPUT_FILE))
    file_size = OUTPUT_FILE.stat().st_size / (1024 * 1024)
    print(f"Generated: {OUTPUT_FILE} ({ROW_COUNT:,} rows, {file_size:.1f} MB)")


if __name__ == "__main__":
    generate()
