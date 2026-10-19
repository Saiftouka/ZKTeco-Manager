from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path


# ============================================================
# RACINE DU PROJET
# ============================================================

DOSSIER_PROJET = Path(__file__).resolve().parents[2]

# Permet également le lancement direct du fichier :
# python app/services/run_sqlite_backup.py
if str(DOSSIER_PROJET) not in sys.path:
    sys.path.insert(0, str(DOSSIER_PROJET))


# ============================================================
# IMPORT DU SERVICE SQLITE
# ============================================================

from app.services.sqlite_backup_service import creer_backup_sqlite


# ============================================================
# CONFIGURATION DU JOURNAL
# ============================================================

DOSSIER_LOGS = DOSSIER_PROJET / "data" / "logs"

FICHIER_LOG = DOSSIER_LOGS / "sqlite_backup.log"


# ============================================================
# ECRITURE DU JOURNAL
# ============================================================

def ecrire_log(message: str) -> None:

    DOSSIER_LOGS.mkdir(
        parents=True,
        exist_ok=True
    )

    horodatage = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    ligne = (
        f"[{horodatage}] {message}"
    )

    print(ligne)

    try:

        with FICHIER_LOG.open(
            "a",
            encoding="utf-8"
        ) as fichier:

            fichier.write(
                ligne + "\n"
            )

    except Exception as erreur:

        print(
            "[LOG] Impossible d'ecrire dans le journal :",
            erreur
        )


# ============================================================
# EXECUTION DU BACKUP
# ============================================================

def executer_backup() -> int:

    ecrire_log(
        "Debut de la sauvegarde SQLite automatique."
    )

    try:

        # ====================================================
        # nettoyer=True
        #
        # Le backup est d'abord cree et verifie.
        #
        # La rotation des anciens backups intervient seulement
        # apres validation du nouveau backup.
        #
        # Maximum configure dans sqlite_backup_service.py :
        # 30 sauvegardes.
        # ====================================================

        resultat = creer_backup_sqlite(
            nettoyer=True
        )

    except Exception as erreur:

        ecrire_log(
            "ERREUR inattendue pendant le backup : "
            + str(erreur)
        )

        return 1


    # ========================================================
    # BACKUP EN ECHEC
    # ========================================================

    if not resultat.get("success"):

        erreur = resultat.get(
            "erreur"
        ) or "Erreur inconnue."

        ecrire_log(
            "ECHEC de la sauvegarde SQLite : "
            + str(erreur)
        )

        return 1


    # ========================================================
    # BACKUP REUSSI
    # ========================================================

    nom_fichier = resultat.get(
        "nom_fichier"
    ) or "inconnu"

    fichier = resultat.get(
        "fichier"
    ) or "inconnu"

    taille = resultat.get(
        "taille"
    ) or 0

    integrite = resultat.get(
        "integrite"
    ) or "inconnue"

    anciens_supprimes = resultat.get(
        "anciens_backups_supprimes"
    ) or []


    ecrire_log(
        "Sauvegarde SQLite reussie."
    )

    ecrire_log(
        "Fichier : "
        + str(nom_fichier)
    )

    ecrire_log(
        "Chemin : "
        + str(fichier)
    )

    ecrire_log(
        "Taille : "
        + str(taille)
        + " octets."
    )

    ecrire_log(
        "Integrite SQLite : "
        + str(integrite)
        + "."
    )


    # ========================================================
    # ROTATION
    # ========================================================

    if anciens_supprimes:

        ecrire_log(
            str(len(anciens_supprimes))
            + " ancien(s) backup(s) supprime(s)."
        )

        for ancien in anciens_supprimes:

            ecrire_log(
                "Ancien backup supprime : "
                + str(ancien)
            )

    else:

        ecrire_log(
            "Aucun ancien backup a supprimer."
        )


    ecrire_log(
        "Fin de la sauvegarde SQLite automatique."
    )

    return 0


# ============================================================
# POINT D'ENTREE
# ============================================================

if __name__ == "__main__":

    code_retour = executer_backup()

    sys.exit(
        code_retour
    )