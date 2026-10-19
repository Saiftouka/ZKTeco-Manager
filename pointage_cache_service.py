from datetime import datetime
from threading import Lock
from time import perf_counter

from app.services.zkteco_service import get_pointages_pointeuse
from app.services.pointage_db_service import (
    ajouter_pointages,
    compter_pointages,
    enregistrer_synchronisation,
    lire_pointages,
    lire_pointages_intervalle,
    lire_synchronisation,
)

# Un verrou par pointeuse empeche deux lectures physiques simultanees
# (synchronisation automatique + clic manuel, ou plusieurs utilisateurs).
_VERROUS_POINTEUSES = {}
_VERROUS_GARDE = Lock()


def _verrou_pointeuse(pointeuse_id):
    cle = int(pointeuse_id)
    with _VERROUS_GARDE:
        verrou = _VERROUS_POINTEUSES.get(cle)
        if verrou is None:
            verrou = Lock()
            _VERROUS_POINTEUSES[cle] = verrou
        return verrou


def lire_cache_pointages(pointeuse_id):
    resultat_pointages = lire_pointages(pointeuse_id)
    if resultat_pointages.get("success") is not True:
        return {
            "success": False,
            "pointages": [],
            "nombre": 0,
            "derniere_synchronisation": None,
            "source": "sqlite",
            "erreur": resultat_pointages.get("erreur"),
        }

    pointages = resultat_pointages.get("pointages", [])
    if not isinstance(pointages, list):
        pointages = []

    resultat_sync = lire_synchronisation(pointeuse_id)
    derniere = (
        resultat_sync.get("derniere_synchronisation")
        if isinstance(resultat_sync, dict)
        and resultat_sync.get("success") is True
        else None
    )

    return {
        "success": True,
        "pointages": pointages,
        "nombre": len(pointages),
        "derniere_synchronisation": derniere,
        "source": "sqlite",
        "erreur": None,
    }


def compter_cache_pointages(pointeuse_id):
    return compter_pointages(pointeuse_id)


def convertir_pointage_cache(pointage):
    if not isinstance(pointage, dict):
        return None

    timestamp = pointage.get("timestamp")

    if isinstance(timestamp, datetime):
        timestamp_texte = timestamp.isoformat(timespec="seconds")
        date_texte = timestamp.strftime("%d/%m/%Y")
        heure_texte = timestamp.strftime("%H:%M:%S")
    else:
        timestamp_texte = str(timestamp or "").strip()
        date_texte = str(pointage.get("date", "") or "").strip()
        heure_texte = str(pointage.get("heure", "") or "").strip()

    return {
        "uid": pointage.get("uid"),
        "matricule": str(pointage.get("matricule", "") or "").strip(),
        "nom": str(pointage.get("nom", "") or "").strip(),
        "badge": str(pointage.get("badge", "") or "").strip(),
        "timestamp": timestamp_texte,
        "date": date_texte,
        "heure": heure_texte,
        "status": pointage.get("status"),
        "punch": pointage.get("punch"),
    }


def synchroniser_pointages(pointeuse_id, ip, port, attendre_si_occupee=True):
    """Lecture physique terminal -> ajout SQLite, sans aucune suppression.

    Le verrou empeche deux synchronisations simultanees sur la meme pointeuse.
    - attendre_si_occupee=True : le clic manuel attend son tour.
    - attendre_si_occupee=False : la tache automatique ignore ce cycle si une
      synchronisation est deja en cours.
    """
    debut_total = perf_counter()
    verrou = _verrou_pointeuse(pointeuse_id)
    acquis = verrou.acquire(blocking=bool(attendre_si_occupee))

    if not acquis:
        return {
            "success": True,
            "pointeuse_id": int(pointeuse_id),
            "ignoree": True,
            "raison": "synchronisation_deja_en_cours",
            "nombre_total": None,
            "nombre_nouveaux": 0,
            "lecture_forcee": False,
            "stockage": "sqlite",
            "message": "Synchronisation ignoree : une lecture est deja en cours.",
            "erreur": None,
        }

    try:
        resultat_avant = compter_pointages(pointeuse_id)
        if not isinstance(resultat_avant, dict) or resultat_avant.get("success") is not True:
            return {
                "success": False,
                "pointeuse_id": int(pointeuse_id),
                "nombre_total": 0,
                "nombre_nouveaux": 0,
                "erreur": (
                    resultat_avant.get("erreur")
                    if isinstance(resultat_avant, dict)
                    else "Compteur SQLite invalide."
                ),
            }

        try:
            nombre_avant = int(resultat_avant.get("nombre", 0) or 0)
        except (TypeError, ValueError):
            nombre_avant = 0

        debut_terminal = perf_counter()
        try:
            resultat_terminal = get_pointages_pointeuse(
                ip=ip,
                port=port,
                forcer_actualisation=True,
            )
        except Exception as exc:
            return {
                "success": False,
                "pointeuse_id": int(pointeuse_id),
                "nombre_total": nombre_avant,
                "nombre_nouveaux": 0,
                "performance": {
                    "terminal_secondes": round(perf_counter() - debut_terminal, 3),
                    "total_secondes": round(perf_counter() - debut_total, 3),
                },
                "erreur": "Impossible de relire la pointeuse : " + str(exc),
            }

        temps_terminal = perf_counter() - debut_terminal

        if not isinstance(resultat_terminal, dict) or resultat_terminal.get("success") is not True:
            return {
                "success": False,
                "pointeuse_id": int(pointeuse_id),
                "nombre_total": nombre_avant,
                "nombre_nouveaux": 0,
                "performance_terminal": (
                    resultat_terminal.get("performance")
                    if isinstance(resultat_terminal, dict)
                    else None
                ),
                "performance": {
                    "terminal_secondes": round(temps_terminal, 3),
                    "total_secondes": round(perf_counter() - debut_total, 3),
                },
                "erreur": (
                    resultat_terminal.get("erreur")
                    if isinstance(resultat_terminal, dict)
                    else "Reponse terminal invalide."
                ),
            }

        pointages_terminal = resultat_terminal.get("pointages", [])
        if not isinstance(pointages_terminal, list):
            pointages_terminal = []

        debut_conversion = perf_counter()
        pointages_sqlite = []
        for pointage in pointages_terminal:
            converti = convertir_pointage_cache(pointage)
            if isinstance(converti, dict) and converti.get("timestamp"):
                pointages_sqlite.append(converti)
        temps_conversion = perf_counter() - debut_conversion

        debut_sqlite = perf_counter()
        try:
            resultat_ajout = ajouter_pointages(pointeuse_id, pointages_sqlite)
        except Exception as exc:
            return {
                "success": False,
                "pointeuse_id": int(pointeuse_id),
                "nombre_total": nombre_avant,
                "nombre_nouveaux": 0,
                "nombre_terminal": len(pointages_terminal),
                "erreur": "Impossible d'enregistrer les pointages : " + str(exc),
            }

        temps_sqlite = perf_counter() - debut_sqlite

        if not isinstance(resultat_ajout, dict) or resultat_ajout.get("success") is not True:
            return {
                "success": False,
                "pointeuse_id": int(pointeuse_id),
                "nombre_total": nombre_avant,
                "nombre_nouveaux": 0,
                "nombre_terminal": len(pointages_terminal),
                "erreur": (
                    resultat_ajout.get("erreur")
                    if isinstance(resultat_ajout, dict)
                    else "Reponse SQLite invalide."
                ),
            }

        try:
            nombre_nouveaux = int(resultat_ajout.get("nombre_ajoutes", 0) or 0)
        except (TypeError, ValueError):
            nombre_nouveaux = 0

        resultat_apres = compter_pointages(pointeuse_id)
        try:
            nombre_total = (
                int(resultat_apres.get("nombre", 0) or 0)
                if isinstance(resultat_apres, dict)
                and resultat_apres.get("success") is True
                else nombre_avant + nombre_nouveaux
            )
        except (TypeError, ValueError):
            nombre_total = nombre_avant + nombre_nouveaux

        resultat_sync = enregistrer_synchronisation(pointeuse_id, nombre_total)
        derniere = (
            resultat_sync.get("derniere_synchronisation")
            if isinstance(resultat_sync, dict)
            and resultat_sync.get("success") is True
            else None
        )

        performance = {
            "terminal_secondes": round(temps_terminal, 3),
            "conversion_secondes": round(temps_conversion, 3),
            "sqlite_secondes": round(temps_sqlite, 3),
            "total_secondes": round(perf_counter() - debut_total, 3),
        }

        if nombre_nouveaux > 0:
            print(
                f"[SYNC AUTO/MANUEL] pointeuse={pointeuse_id} "
                f"nouveaux={nombre_nouveaux} total={nombre_total} "
                f"temps={performance['total_secondes']}s"
            )

        return {
            "success": True,
            "pointeuse_id": int(pointeuse_id),
            "ignoree": False,
            "nombre_avant": nombre_avant,
            "nombre_total": nombre_total,
            "nombre_nouveaux": nombre_nouveaux,
            "nombre_terminal": len(pointages_terminal),
            "nombre_valides_terminal": len(pointages_sqlite),
            "derniere_synchronisation": derniere,
            "stockage": "sqlite",
            "lecture_forcee": True,
            "source_terminal": resultat_terminal.get("source"),
            "performance_terminal": resultat_terminal.get("performance"),
            "performance": performance,
            "message": (
                f"{nombre_nouveaux} nouveau(x) pointage(s) recupere(s). "
                f"{nombre_total} pointage(s) au total dans l'historique local."
            ),
            "erreur": None,
        }
    finally:
        verrou.release()


def synchroniser_pointages_automatique(pointeuse_id, ip, port):
    """Version non bloquante pour le planificateur automatique."""
    return synchroniser_pointages(
        pointeuse_id=pointeuse_id,
        ip=ip,
        port=port,
        attendre_si_occupee=False,
    )


def get_pointages_cache_intervalle(pointeuse_id, debut, fin):
    resultat = lire_pointages_intervalle(pointeuse_id, debut, fin)
    if not isinstance(resultat, dict) or resultat.get("success") is not True:
        return {
            "success": False,
            "pointages": [],
            "nombre": 0,
            "debut": None,
            "fin": None,
            "derniere_synchronisation": None,
            "source": "sqlite",
            "erreur": (
                resultat.get("erreur")
                if isinstance(resultat, dict)
                else "Reponse SQLite invalide."
            ),
        }

    pointages = resultat.get("pointages", [])
    if not isinstance(pointages, list):
        pointages = []

    resultat_sync = lire_synchronisation(pointeuse_id)
    derniere = (
        resultat_sync.get("derniere_synchronisation")
        if isinstance(resultat_sync, dict)
        and resultat_sync.get("success") is True
        else None
    )

    return {
        "success": True,
        "pointages": pointages,
        "nombre": len(pointages),
        "debut": resultat.get("debut"),
        "fin": resultat.get("fin"),
        "derniere_synchronisation": derniere,
        "source": "sqlite",
        "erreur": None,
    }


def assurer_pointages_intervalle(pointeuse_id, ip, port, debut, fin):
    compteur = compter_pointages(pointeuse_id)
    if not isinstance(compteur, dict) or compteur.get("success") is not True:
        return {
            "success": False,
            "pointages": [],
            "nombre": 0,
            "source": "sqlite",
            "synchronisation_effectuee": False,
            "erreur": (
                compteur.get("erreur")
                if isinstance(compteur, dict)
                else "Historique local inaccessible."
            ),
        }

    try:
        nombre_local = int(compteur.get("nombre", 0) or 0)
    except (TypeError, ValueError):
        nombre_local = 0

    synchronisation = None
    if nombre_local == 0:
        synchronisation = synchroniser_pointages(
            pointeuse_id,
            ip,
            port,
            attendre_si_occupee=True,
        )
        if not isinstance(synchronisation, dict) or synchronisation.get("success") is not True:
            return {
                "success": False,
                "pointages": [],
                "nombre": 0,
                "source": "sqlite",
                "synchronisation_effectuee": True,
                "synchronisation": synchronisation,
                "erreur": (
                    synchronisation.get("erreur")
                    if isinstance(synchronisation, dict)
                    else "Synchronisation initiale impossible."
                ),
            }

    resultat = get_pointages_cache_intervalle(pointeuse_id, debut, fin)
    if resultat.get("success") is not True:
        return resultat

    resultat["synchronisation_effectuee"] = synchronisation is not None
    resultat["synchronisation"] = synchronisation
    return resultat


def reinitialiser_cache_pointages(pointeuse_id):
    resultat = compter_pointages(pointeuse_id)
    if resultat.get("success") is not True:
        return {
            "success": False,
            "nombre": None,
            "historique_conserve": True,
            "derniere_synchronisation": None,
            "message": "Aucun pointage local n'a ete supprime.",
            "erreur": resultat.get("erreur"),
        }

    resultat_sync = lire_synchronisation(pointeuse_id)
    derniere = (
        resultat_sync.get("derniere_synchronisation")
        if isinstance(resultat_sync, dict)
        and resultat_sync.get("success") is True
        else None
    )

    return {
        "success": True,
        "nombre": resultat.get("nombre", 0),
        "historique_conserve": True,
        "derniere_synchronisation": derniere,
        "message": "Historique SQLite conserve. Aucun pointage local n'a ete supprime.",
        "erreur": None,
    }
