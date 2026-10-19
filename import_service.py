import json
import uuid
from pathlib import Path


# ==========================================
# CONFIGURATION
# ==========================================

DOSSIER_IMPORTS = Path("temp_imports")


# ==========================================
# PREPARER LE DOSSIER
# ==========================================

def preparer_dossier_imports():
    DOSSIER_IMPORTS.mkdir(
        parents=True,
        exist_ok=True,
    )


# ==========================================
# CREER UNE SESSION D'IMPORT
# ==========================================

def creer_session_import(
    pointeuse_id,
    employes,
):
    preparer_dossier_imports()

    if not isinstance(employes, list):

        return {
            "success": False,
            "import_id": None,
            "erreur": "La liste des employés est invalide.",
        }

    if not employes:

        return {
            "success": False,
            "import_id": None,
            "erreur": "Aucun employé à importer.",
        }

    try:
        pointeuse_id = int(
            pointeuse_id
        )

    except (TypeError, ValueError):

        return {
            "success": False,
            "import_id": None,
            "erreur": "Identifiant de pointeuse invalide.",
        }

    import_id = uuid.uuid4().hex

    chemin = (
        DOSSIER_IMPORTS
        / f"{import_id}.json"
    )

    donnees = {
        "pointeuse_id": pointeuse_id,
        "employes": employes,
    }

    try:

        with chemin.open(
            mode="w",
            encoding="utf-8",
        ) as fichier:

            json.dump(
                donnees,
                fichier,
                ensure_ascii=False,
                indent=4,
            )

        return {
            "success": True,
            "import_id": import_id,
            "erreur": None,
        }

    except Exception as erreur:

        return {
            "success": False,
            "import_id": None,
            "erreur": (
                "Impossible de préparer "
                "la session d'import : "
                + str(erreur)
            ),
        }


# ==========================================
# LIRE UNE SESSION D'IMPORT
# ==========================================

def lire_session_import(import_id):
    preparer_dossier_imports()

    import_id = str(
        import_id
    ).strip()

    if not import_id:

        return {
            "success": False,
            "donnees": None,
            "erreur": "Identifiant d'import manquant.",
        }

    # Sécurité :
    # UUID hexadécimal attendu.
    if (
        len(import_id) != 32
        or not all(
            caractere in "0123456789abcdef"
            for caractere in import_id.lower()
        )
    ):

        return {
            "success": False,
            "donnees": None,
            "erreur": "Identifiant d'import invalide.",
        }

    chemin = (
        DOSSIER_IMPORTS
        / f"{import_id}.json"
    )

    if not chemin.exists():

        return {
            "success": False,
            "donnees": None,
            "erreur": (
                "La session d'import "
                "est introuvable."
            ),
        }

    try:

        with chemin.open(
            mode="r",
            encoding="utf-8",
        ) as fichier:

            donnees = json.load(
                fichier
            )

        return {
            "success": True,
            "donnees": donnees,
            "erreur": None,
        }

    except Exception as erreur:

        return {
            "success": False,
            "donnees": None,
            "erreur": (
                "Impossible de lire "
                "la session d'import : "
                + str(erreur)
            ),
        }


# ==========================================
# SUPPRIMER UNE SESSION D'IMPORT
# ==========================================

def supprimer_session_import(import_id):
    preparer_dossier_imports()

    import_id = str(
        import_id
    ).strip()

    chemin = (
        DOSSIER_IMPORTS
        / f"{import_id}.json"
    )

    try:

        if chemin.exists():
            chemin.unlink()

        return {
            "success": True,
            "erreur": None,
        }

    except Exception as erreur:

        return {
            "success": False,
            "erreur": str(erreur),
        }