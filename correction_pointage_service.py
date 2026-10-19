import sqlite3
from datetime import datetime
from pathlib import Path


# ============================================================
# CONFIGURATION
# ============================================================

FICHIER_CORRECTIONS = Path(
    "corrections_pointages.db"
)


# ============================================================
# CONNEXION SQLITE
# ============================================================

def _connexion():
    connexion = sqlite3.connect(
        FICHIER_CORRECTIONS
    )

    connexion.row_factory = (
        sqlite3.Row
    )

    return connexion


# ============================================================
# INITIALISER LA BASE
# ============================================================

def initialiser_corrections_pointages():
    connexion = None

    try:
        connexion = _connexion()

        connexion.execute(
            """
            CREATE TABLE IF NOT EXISTS
            corrections_pointages
            (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                pointeuse_id INTEGER NOT NULL,

                matricule TEXT NOT NULL,

                timestamp_original TEXT NOT NULL,

                status_original TEXT,

                punch_original TEXT,

                timestamp_corrige TEXT NOT NULL,

                motif TEXT,

                cree_le TEXT NOT NULL,

                modifie_le TEXT NOT NULL,

                active INTEGER NOT NULL DEFAULT 1,

                UNIQUE
                (
                    pointeuse_id,
                    matricule,
                    timestamp_original,
                    status_original,
                    punch_original
                )
            )
            """
        )

        connexion.commit()

        return {
            "success": True,
            "erreur": None,
        }

    except Exception as erreur:

        return {
            "success": False,
            "erreur": str(
                erreur
            ),
        }

    finally:

        if connexion is not None:

            connexion.close()


# ============================================================
# NORMALISATION
# ============================================================

def _normaliser_timestamp(
    valeur,
):
    if valeur is None:
        return ""

    if isinstance(
        valeur,
        datetime,
    ):
        return valeur.isoformat(
            timespec="seconds"
        )

    texte = str(
        valeur
    ).strip()

    try:

        date = datetime.fromisoformat(
            texte
        )

        return date.isoformat(
            timespec="seconds"
        )

    except Exception:

        return texte


def _normaliser_valeur(
    valeur,
):
    if valeur is None:
        return ""

    return str(
        valeur
    ).strip()


# ============================================================
# CLE UNIQUE D'UN POINTAGE
#
# IMPORTANT :
#
# Plusieurs pointages peuvent appartenir au même matricule
# avec seulement quelques secondes d'écart.
#
# Exemple :
#
# 12345 - 14:59:00
# 12345 - 14:59:01
# 12345 - 14:59:02
#
# On utilise donc :
#
# pointeuse
# + matricule
# + timestamp original
# + status
# + punch
# ============================================================

def cle_pointage(
    pointeuse_id,
    matricule,
    timestamp_original,
    status=None,
    punch=None,
):
    return (
        int(
            pointeuse_id
        ),

        _normaliser_valeur(
            matricule
        ),

        _normaliser_timestamp(
            timestamp_original
        ),

        _normaliser_valeur(
            status
        ),

        _normaliser_valeur(
            punch
        ),
    )


# ============================================================
# ENREGISTRER / MODIFIER UNE CORRECTION
# ============================================================

def enregistrer_correction_pointage(
    pointeuse_id,
    matricule,
    timestamp_original,
    timestamp_corrige,
    status=None,
    punch=None,
    motif="",
):
    resultat_init = (
        initialiser_corrections_pointages()
    )

    if (
        resultat_init.get(
            "success"
        )
        is not True
    ):
        return resultat_init


    # ========================================================
    # NORMALISATION
    # ========================================================

    try:
        pointeuse_id = int(
            pointeuse_id
        )

    except (
        TypeError,
        ValueError,
    ):
        return {
            "success": False,
            "erreur": (
                "Identifiant de pointeuse invalide."
            ),
        }


    matricule = (
        _normaliser_valeur(
            matricule
        )
    )


    timestamp_original = (
        _normaliser_timestamp(
            timestamp_original
        )
    )


    timestamp_corrige = (
        _normaliser_timestamp(
            timestamp_corrige
        )
    )


    status = (
        _normaliser_valeur(
            status
        )
    )


    punch = (
        _normaliser_valeur(
            punch
        )
    )


    motif = str(
        motif
        or ""
    ).strip()


    if not matricule:

        return {
            "success": False,
            "erreur": (
                "Le matricule est obligatoire."
            ),
        }


    if not timestamp_original:

        return {
            "success": False,
            "erreur": (
                "Le timestamp original est obligatoire."
            ),
        }


    if not timestamp_corrige:

        return {
            "success": False,
            "erreur": (
                "La nouvelle date et heure "
                "sont obligatoires."
            ),
        }


    # ========================================================
    # VERIFIER LE FORMAT CORRIGE
    # ========================================================

    try:

        date_corrigee = (
            datetime.fromisoformat(
                timestamp_corrige
            )
        )

    except Exception:

        return {
            "success": False,
            "erreur": (
                "La nouvelle date et heure "
                "sont invalides."
            ),
        }


    timestamp_corrige = (
        date_corrigee.isoformat(
            timespec="seconds"
        )
    )


    maintenant = (
        datetime.now().isoformat(
            timespec="seconds"
        )
    )


    connexion = None


    try:

        connexion = _connexion()


        # ====================================================
        # RECHERCHER UNE CORRECTION EXISTANTE
        # ====================================================

        existante = connexion.execute(
            """
            SELECT
                id,
                cree_le

            FROM
                corrections_pointages

            WHERE
                pointeuse_id = ?
                AND matricule = ?
                AND timestamp_original = ?
                AND status_original = ?
                AND punch_original = ?
            """,
            (
                pointeuse_id,
                matricule,
                timestamp_original,
                status,
                punch,
            ),
        ).fetchone()


        # ====================================================
        # MODIFICATION
        # ====================================================

        if existante is not None:

            connexion.execute(
                """
                UPDATE
                    corrections_pointages

                SET
                    timestamp_corrige = ?,
                    motif = ?,
                    modifie_le = ?,
                    active = 1

                WHERE
                    id = ?
                """,
                (
                    timestamp_corrige,
                    motif,
                    maintenant,
                    existante["id"],
                ),
            )

            correction_id = (
                existante["id"]
            )

            cree_le = (
                existante["cree_le"]
            )


        # ====================================================
        # CREATION
        # ====================================================

        else:

            curseur = connexion.execute(
                """
                INSERT INTO
                    corrections_pointages
                (
                    pointeuse_id,
                    matricule,
                    timestamp_original,
                    status_original,
                    punch_original,
                    timestamp_corrige,
                    motif,
                    cree_le,
                    modifie_le,
                    active
                )

                VALUES
                (
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    1
                )
                """,
                (
                    pointeuse_id,
                    matricule,
                    timestamp_original,
                    status,
                    punch,
                    timestamp_corrige,
                    motif,
                    maintenant,
                    maintenant,
                ),
            )

            correction_id = (
                curseur.lastrowid
            )

            cree_le = maintenant


        connexion.commit()


        return {
            "success": True,

            "correction": {
                "id": correction_id,

                "pointeuse_id": (
                    pointeuse_id
                ),

                "matricule": (
                    matricule
                ),

                "timestamp_original": (
                    timestamp_original
                ),

                "timestamp_corrige": (
                    timestamp_corrige
                ),

                "status": status,

                "punch": punch,

                "motif": motif,

                "cree_le": cree_le,

                "modifie_le": (
                    maintenant
                ),

                "active": True,
            },

            "message": (
                "La correction du pointage "
                "a été enregistrée."
            ),

            "erreur": None,
        }


    except Exception as erreur:

        return {
            "success": False,

            "erreur": (
                "Impossible d'enregistrer "
                "la correction : "
                + str(erreur)
            ),
        }


    finally:

        if connexion is not None:

            connexion.close()


# ============================================================
# LIRE UNE CORRECTION
# ============================================================

def get_correction_pointage(
    pointeuse_id,
    matricule,
    timestamp_original,
    status=None,
    punch=None,
):
    resultat_init = (
        initialiser_corrections_pointages()
    )

    if (
        resultat_init.get(
            "success"
        )
        is not True
    ):
        return resultat_init


    try:

        cle = cle_pointage(
            pointeuse_id,
            matricule,
            timestamp_original,
            status,
            punch,
        )

    except Exception as erreur:

        return {
            "success": False,
            "correction": None,
            "erreur": str(
                erreur
            ),
        }


    connexion = None


    try:

        connexion = _connexion()


        ligne = connexion.execute(
            """
            SELECT
                *

            FROM
                corrections_pointages

            WHERE
                pointeuse_id = ?
                AND matricule = ?
                AND timestamp_original = ?
                AND status_original = ?
                AND punch_original = ?
                AND active = 1

            LIMIT 1
            """,
            cle,
        ).fetchone()


        if ligne is None:

            return {
                "success": True,
                "correction": None,
                "erreur": None,
            }


        return {
            "success": True,

            "correction": dict(
                ligne
            ),

            "erreur": None,
        }


    except Exception as erreur:

        return {
            "success": False,
            "correction": None,
            "erreur": str(
                erreur
            ),
        }


    finally:

        if connexion is not None:

            connexion.close()


# ============================================================
# LISTER LES CORRECTIONS D'UNE POINTEUSE
# ============================================================

def get_corrections_pointeuse(
    pointeuse_id,
):
    resultat_init = (
        initialiser_corrections_pointages()
    )

    if (
        resultat_init.get(
            "success"
        )
        is not True
    ):
        return resultat_init


    try:

        pointeuse_id = int(
            pointeuse_id
        )

    except (
        TypeError,
        ValueError,
    ):

        return {
            "success": False,
            "corrections": [],
            "nombre": 0,
            "erreur": (
                "Identifiant de pointeuse invalide."
            ),
        }


    connexion = None


    try:

        connexion = _connexion()


        lignes = connexion.execute(
            """
            SELECT
                *

            FROM
                corrections_pointages

            WHERE
                pointeuse_id = ?
                AND active = 1

            ORDER BY
                timestamp_original ASC
            """,
            (
                pointeuse_id,
            ),
        ).fetchall()


        corrections = [
            dict(
                ligne
            )
            for ligne in lignes
        ]


        return {
            "success": True,

            "corrections": (
                corrections
            ),

            "nombre": len(
                corrections
            ),

            "erreur": None,
        }


    except Exception as erreur:

        return {
            "success": False,
            "corrections": [],
            "nombre": 0,
            "erreur": str(
                erreur
            ),
        }


    finally:

        if connexion is not None:

            connexion.close()


# ============================================================
# INDEX DES CORRECTIONS
#
# Optimisé pour appliquer rapidement les corrections
# sur un rapport contenant plusieurs centaines de lignes.
# ============================================================

def construire_index_corrections(
    pointeuse_id,
):
    resultat = (
        get_corrections_pointeuse(
            pointeuse_id
        )
    )


    if (
        resultat.get(
            "success"
        )
        is not True
    ):

        return {
            "success": False,
            "index": {},
            "nombre": 0,
            "erreur": (
                resultat.get(
                    "erreur"
                )
            ),
        }


    index = {}


    for correction in (
        resultat.get(
            "corrections",
            [],
        )
    ):

        cle = (
            int(
                correction.get(
                    "pointeuse_id"
                )
            ),

            _normaliser_valeur(
                correction.get(
                    "matricule"
                )
            ),

            _normaliser_timestamp(
                correction.get(
                    "timestamp_original"
                )
            ),

            _normaliser_valeur(
                correction.get(
                    "status_original"
                )
            ),

            _normaliser_valeur(
                correction.get(
                    "punch_original"
                )
            ),
        )


        index[
            cle
        ] = correction


    return {
        "success": True,
        "index": index,
        "nombre": len(
            index
        ),
        "erreur": None,
    }


# ============================================================
# APPLIQUER LES CORRECTIONS SUR UNE LISTE DE POINTAGES
#
# IMPORTANT :
#
# timestamp_original
# reste toujours conservé.
#
# timestamp devient la valeur corrigée destinée :
#
# - à l'aperçu ;
# - au fichier Excel.
# ============================================================

def appliquer_corrections_pointages(
    pointeuse_id,
    pointages,
):
    if not isinstance(
        pointages,
        list,
    ):

        return {
            "success": False,
            "pointages": [],
            "nombre_corrections": 0,
            "erreur": (
                "La liste de pointages est invalide."
            ),
        }


    resultat_index = (
        construire_index_corrections(
            pointeuse_id
        )
    )


    if (
        resultat_index.get(
            "success"
        )
        is not True
    ):

        return {
            "success": False,
            "pointages": [],
            "nombre_corrections": 0,
            "erreur": (
                resultat_index.get(
                    "erreur"
                )
            ),
        }


    index = (
        resultat_index.get(
            "index",
            {},
        )
    )


    sortie = []

    nombre_corrections = 0


    for pointage in pointages:

        if not isinstance(
            pointage,
            dict,
        ):
            continue


        ligne = dict(
            pointage
        )


        timestamp_original = (
            ligne.get(
                "timestamp"
            )
        )


        ligne[
            "timestamp_original"
        ] = timestamp_original


        cle = cle_pointage(
            pointeuse_id,
            ligne.get(
                "matricule"
            ),
            timestamp_original,
            ligne.get(
                "status"
            ),
            ligne.get(
                "punch"
            ),
        )


        correction = (
            index.get(
                cle
            )
        )


        if correction is not None:

            try:

                timestamp_corrige = (
                    datetime.fromisoformat(
                        correction.get(
                            "timestamp_corrige"
                        )
                    )
                )

            except Exception:

                timestamp_corrige = None


            if timestamp_corrige is not None:

                ligne[
                    "timestamp"
                ] = timestamp_corrige


                ligne[
                    "corrige"
                ] = True


                ligne[
                    "correction_id"
                ] = correction.get(
                    "id"
                )


                ligne[
                    "motif_correction"
                ] = correction.get(
                    "motif"
                )


                ligne[
                    "timestamp_corrige"
                ] = timestamp_corrige


                nombre_corrections += 1


        else:

            ligne[
                "corrige"
            ] = False


            ligne[
                "correction_id"
            ] = None


            ligne[
                "motif_correction"
            ] = None


            ligne[
                "timestamp_corrige"
            ] = None


        sortie.append(
            ligne
        )


    return {
        "success": True,

        "pointages": sortie,

        "nombre_corrections": (
            nombre_corrections
        ),

        "erreur": None,
    }


# ============================================================
# ANNULER UNE CORRECTION
#
# On ne supprime pas la ligne SQLite.
#
# active = 0
#
# Cela permet de conserver une trace.
# ============================================================

def annuler_correction_pointage(
    pointeuse_id,
    matricule,
    timestamp_original,
    status=None,
    punch=None,
):
    resultat_init = (
        initialiser_corrections_pointages()
    )

    if (
        resultat_init.get(
            "success"
        )
        is not True
    ):
        return resultat_init


    try:

        cle = cle_pointage(
            pointeuse_id,
            matricule,
            timestamp_original,
            status,
            punch,
        )

    except Exception as erreur:

        return {
            "success": False,
            "erreur": str(
                erreur
            ),
        }


    connexion = None


    try:

        connexion = _connexion()


        curseur = connexion.execute(
            """
            UPDATE
                corrections_pointages

            SET
                active = 0,
                modifie_le = ?

            WHERE
                pointeuse_id = ?
                AND matricule = ?
                AND timestamp_original = ?
                AND status_original = ?
                AND punch_original = ?
                AND active = 1
            """,
            (
                datetime.now().isoformat(
                    timespec="seconds"
                ),
                *cle,
            ),
        )


        connexion.commit()


        if curseur.rowcount == 0:

            return {
                "success": False,
                "erreur": (
                    "Aucune correction active "
                    "n'a été trouvée."
                ),
            }


        return {
            "success": True,

            "message": (
                "La correction a été annulée. "
                "Le pointage original sera "
                "de nouveau utilisé."
            ),

            "erreur": None,
        }


    except Exception as erreur:

        return {
            "success": False,

            "erreur": (
                "Impossible d'annuler "
                "la correction : "
                + str(erreur)
            ),
        }


    finally:

        if connexion is not None:

            connexion.close()


# ============================================================
# INITIALISATION AU CHARGEMENT DU MODULE
# ============================================================

initialiser_corrections_pointages()