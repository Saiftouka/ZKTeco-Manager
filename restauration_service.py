import json
import zipfile
from pathlib import Path
from time import perf_counter

from app.services.pointage_db_service import ajouter_pointages, compter_pointages

NOMS_FICHIERS_ATTENDUS = {"Users.dat", "System.dat"}
TYPE_USERS_ATTENDU = "pointages_terminal"
TYPE_SYSTEM_ATTENDU = "system"


def _charger_json_bytes(donnees, nom_fichier):
    if not donnees:
        raise RuntimeError(nom_fichier + " est vide.")
    try:
        contenu = json.loads(donnees.decode("utf-8"))
    except Exception as erreur:
        raise RuntimeError(nom_fichier + " est illisible : " + str(erreur)) from erreur
    if not isinstance(contenu, dict):
        raise RuntimeError("Le format de " + nom_fichier + " est invalide.")
    return contenu


def lire_dat_json(chemin, nom_fichier):
    chemin = Path(chemin)
    if not chemin.is_file():
        raise RuntimeError(nom_fichier + " est introuvable.")
    return _charger_json_bytes(chemin.read_bytes(), nom_fichier)


def _entier_ou_none(valeur):
    if valeur is None or valeur == "":
        return None
    try:
        return int(valeur)
    except (TypeError, ValueError):
        return None


def convertir_pointage_restauration(pointage):
    if not isinstance(pointage, dict):
        return None
    timestamp = str(pointage.get("timestamp", "") or "").strip()
    if not timestamp:
        return None
    return {
        "uid": _entier_ou_none(pointage.get("uid")),
        "matricule": str(pointage.get("matricule", "") or "").strip(),
        "nom": str(pointage.get("nom", "") or "").strip(),
        "badge": str(pointage.get("badge", "") or "").strip(),
        "timestamp": timestamp,
        "date": str(pointage.get("date", "") or "").strip(),
        "heure": str(pointage.get("heure", "") or "").strip(),
        "status": _entier_ou_none(pointage.get("status")),
        "punch": _entier_ou_none(pointage.get("punch")),
    }


def _verifier_users_contenu(contenu):
    if contenu.get("type") != TYPE_USERS_ATTENDU:
        raise RuntimeError("Users.dat n'est pas un backup de pointages terminal valide.")
    donnees = contenu.get("data")
    if not isinstance(donnees, list):
        raise RuntimeError("La section data de Users.dat doit contenir une liste.")
    pointages = []
    invalides = 0
    for pointage in donnees:
        converti = convertir_pointage_restauration(pointage)
        if converti is None:
            invalides += 1
        else:
            pointages.append(converti)
    return {
        "contenu": contenu,
        "pointages": pointages,
        "nombre_total": len(donnees),
        "nombre_valides": len(pointages),
        "nombre_invalides": invalides,
    }


def verifier_users_dat(chemin):
    return _verifier_users_contenu(lire_dat_json(chemin, "Users.dat"))


def _verifier_system_contenu(contenu):
    if contenu.get("type") != TYPE_SYSTEM_ATTENDU:
        raise RuntimeError("System.dat n'est pas un fichier systeme valide.")
    donnees = contenu.get("data")
    if not isinstance(donnees, dict):
        raise RuntimeError("La section data de System.dat est invalide.")
    return {"contenu": contenu, "system": donnees}


def verifier_system_dat(chemin):
    return _verifier_system_contenu(lire_dat_json(chemin, "System.dat"))


def analyser_backup_zip(chemin_zip):
    t0 = perf_counter()
    chemin_zip = Path(chemin_zip)
    performance = {"zip_secondes": 0.0, "json_secondes": 0.0, "normalisation_secondes": 0.0}

    if not chemin_zip.is_file():
        return {"success": False, "backup_valid": False, "pointages": [], "nombre_pointages": 0, "performance": performance, "erreur": "Le fichier ZIP est introuvable."}

    try:
        t = perf_counter()
        if not zipfile.is_zipfile(chemin_zip):
            raise RuntimeError("Le fichier selectionne n'est pas une archive ZIP valide.")

        with zipfile.ZipFile(chemin_zip, "r") as archive:
            noms = archive.namelist()
            fichiers = set()
            for nom in noms:
                interne = Path(nom)
                if interne.is_absolute() or ".." in interne.parts:
                    raise RuntimeError("Le ZIP contient un chemin interne non autorise.")
                if not nom.endswith("/"):
                    # Refuse les sous-dossiers, meme si basename correspond.
                    if len(interne.parts) != 1:
                        raise RuntimeError("Le ZIP contient des chemins imbriques non autorises.")
                    fichiers.add(interne.name)

            if fichiers != NOMS_FICHIERS_ATTENDUS:
                raise RuntimeError("Le backup doit contenir exactement Users.dat et System.dat.")

            mauvais = archive.testzip()
            if mauvais:
                raise RuntimeError("Le fichier " + str(mauvais) + " est corrompu dans l'archive ZIP.")

            users_brut = archive.read("Users.dat")
            system_brut = archive.read("System.dat")
        performance["zip_secondes"] = perf_counter() - t

        t = perf_counter()
        users_contenu = _charger_json_bytes(users_brut, "Users.dat")
        system_contenu = _charger_json_bytes(system_brut, "System.dat")
        performance["json_secondes"] = perf_counter() - t

        t = perf_counter()
        resultat_users = _verifier_users_contenu(users_contenu)
        resultat_system = _verifier_system_contenu(system_contenu)
        performance["normalisation_secondes"] = perf_counter() - t

        system_data = resultat_system["system"]
        performance = {k: round(v, 3) for k, v in performance.items()}
        performance["total_secondes"] = round(perf_counter() - t0, 3)

        return {
            "success": True,
            "backup_valid": True,
            "pointages": resultat_users["pointages"],
            "nombre_pointages": resultat_users["nombre_valides"],
            "nombre_pointages_total": resultat_users["nombre_total"],
            "nombre_pointages_invalides": resultat_users["nombre_invalides"],
            "pointeuse_id_backup": system_data.get("pointeuse_id"),
            "nom_pointeuse_backup": system_data.get("nom_pointeuse"),
            "ip_backup": system_data.get("ip"),
            "port_backup": system_data.get("port"),
            "source_pointages": system_data.get("source_pointages"),
            "users_valid": True,
            "system_valid": True,
            "performance": performance,
            "erreur": None,
        }
    except Exception as erreur:
        performance = {k: round(v, 3) for k, v in performance.items()}
        performance["total_secondes"] = round(perf_counter() - t0, 3)
        return {
            "success": False,
            "backup_valid": False,
            "pointages": [],
            "nombre_pointages": 0,
            "users_valid": False,
            "system_valid": False,
            "performance": performance,
            "erreur": "Backup invalide : " + str(erreur),
        }


def verifier_correspondance_pointeuse(resultat_backup, pointeuse_id, ip=None, port=None):
    if not isinstance(resultat_backup, dict) or resultat_backup.get("success") is not True:
        return {"success": False, "erreur": resultat_backup.get("erreur") if isinstance(resultat_backup, dict) else "Backup invalide."}
    try:
        attendu = int(pointeuse_id)
        backup_id = int(resultat_backup.get("pointeuse_id_backup"))
    except (TypeError, ValueError):
        return {"success": False, "erreur": "Identifiant de pointeuse invalide dans le backup."}
    if backup_id != attendu:
        return {"success": False, "erreur": "Le backup appartient a une autre pointeuse."}

    ip_backup = str(resultat_backup.get("ip_backup", "") or "").strip()
    ip_actuelle = str(ip or "").strip()
    if ip_backup and ip_actuelle and ip_backup != ip_actuelle:
        return {"success": False, "erreur": f"Adresse IP differente. Backup : {ip_backup} ; actuelle : {ip_actuelle}."}

    port_backup = resultat_backup.get("port_backup")
    if port_backup is not None and port is not None:
        try:
            if int(port_backup) != int(port):
                return {"success": False, "erreur": "Le port du backup ne correspond pas a la pointeuse selectionnee."}
        except (TypeError, ValueError):
            return {"success": False, "erreur": "Le port enregistre dans System.dat est invalide."}
    return {"success": True, "erreur": None}


def verifier_backup_restauration(chemin_zip, pointeuse_id, ip=None, port=None):
    t0 = perf_counter()
    resultat = analyser_backup_zip(chemin_zip)
    if resultat.get("success") is not True:
        return resultat
    correspondance = verifier_correspondance_pointeuse(resultat, pointeuse_id, ip=ip, port=port)
    if correspondance.get("success") is not True:
        return {
            "success": False,
            "backup_valid": False,
            "nombre_pointages": resultat.get("nombre_pointages", 0),
            "users_valid": resultat.get("users_valid", False),
            "system_valid": resultat.get("system_valid", False),
            "performance": resultat.get("performance"),
            "erreur": correspondance.get("erreur"),
        }
    performance = dict(resultat.get("performance") or {})
    performance["verification_totale_secondes"] = round(perf_counter() - t0, 3)
    return {
        "success": True,
        "backup_valid": True,
        "nombre_pointages": resultat.get("nombre_pointages", 0),
        "nombre_pointages_total": resultat.get("nombre_pointages_total", 0),
        "nombre_pointages_invalides": resultat.get("nombre_pointages_invalides", 0),
        "pointeuse_id_backup": resultat.get("pointeuse_id_backup"),
        "nom_pointeuse_backup": resultat.get("nom_pointeuse_backup"),
        "ip_backup": resultat.get("ip_backup"),
        "port_backup": resultat.get("port_backup"),
        "source_pointages": resultat.get("source_pointages"),
        "users_valid": True,
        "system_valid": True,
        "performance": performance,
        "message": f"Backup verifie avec succes. {resultat.get('nombre_pointages', 0)} pointage(s) valide(s) peuvent etre restaures.",
        "erreur": None,
    }


def restaurer_backup_sqlite(chemin_zip, pointeuse_id, ip=None, port=None):
    """Restaure uniquement dans SQLite. Aucun acces ni changement du terminal."""
    t0 = perf_counter()
    resultat = analyser_backup_zip(chemin_zip)
    if resultat.get("success") is not True:
        return {"success": False, "backup_valid": False, "nombre_backup": 0, "nombre_avant": 0, "nombre_ajoutes": 0, "nombre_ignores": 0, "nombre_apres": 0, "performance": resultat.get("performance"), "erreur": resultat.get("erreur")}

    correspondance = verifier_correspondance_pointeuse(resultat, pointeuse_id, ip=ip, port=port)
    if correspondance.get("success") is not True:
        return {"success": False, "backup_valid": False, "nombre_backup": resultat.get("nombre_pointages", 0), "nombre_avant": 0, "nombre_ajoutes": 0, "nombre_ignores": 0, "nombre_apres": 0, "performance": resultat.get("performance"), "erreur": correspondance.get("erreur")}

    pointages = resultat.get("pointages", [])
    if not isinstance(pointages, list):
        return {"success": False, "backup_valid": False, "nombre_backup": 0, "nombre_avant": 0, "nombre_ajoutes": 0, "nombre_ignores": 0, "nombre_apres": 0, "erreur": "La liste de pointages du backup est invalide."}

    t = perf_counter()
    avant = compter_pointages(pointeuse_id)
    temps_compteur_avant = perf_counter() - t
    if not isinstance(avant, dict) or avant.get("success") is not True:
        return {"success": False, "backup_valid": True, "nombre_backup": len(pointages), "nombre_avant": 0, "nombre_ajoutes": 0, "nombre_ignores": 0, "nombre_apres": 0, "erreur": "Impossible de verifier SQLite avant restauration."}
    nombre_avant = int(avant.get("nombre", 0) or 0)

    t = perf_counter()
    ajout = ajouter_pointages(pointeuse_id, pointages)
    temps_ajout = perf_counter() - t
    if not isinstance(ajout, dict) or ajout.get("success") is not True:
        return {"success": False, "backup_valid": True, "nombre_backup": len(pointages), "nombre_avant": nombre_avant, "nombre_ajoutes": 0, "nombre_ignores": 0, "nombre_apres": nombre_avant, "erreur": "Impossible de restaurer les pointages dans SQLite : " + str(ajout.get("erreur") if isinstance(ajout, dict) else "reponse invalide")}

    nombre_ajoutes = int(ajout.get("nombre_ajoutes", 0) or 0)
    nombre_valides = int(ajout.get("nombre_valides", len(pointages)) or 0)
    nombre_ignores = max(0, nombre_valides - nombre_ajoutes)

    t = perf_counter()
    apres = compter_pointages(pointeuse_id)
    temps_compteur_apres = perf_counter() - t
    if not isinstance(apres, dict) or apres.get("success") is not True:
        return {"success": False, "backup_valid": True, "nombre_backup": len(pointages), "nombre_avant": nombre_avant, "nombre_ajoutes": nombre_ajoutes, "nombre_ignores": nombre_ignores, "nombre_apres": None, "erreur": "Controle final SQLite impossible."}
    nombre_apres = int(apres.get("nombre", 0) or 0)

    attendu = nombre_avant + nombre_ajoutes
    if nombre_apres != attendu:
        return {"success": False, "backup_valid": True, "nombre_backup": len(pointages), "nombre_avant": nombre_avant, "nombre_ajoutes": nombre_ajoutes, "nombre_ignores": nombre_ignores, "nombre_apres": nombre_apres, "erreur": f"Controle SQLite incorrect. Attendu : {attendu}, trouve : {nombre_apres}."}

    performance = dict(resultat.get("performance") or {})
    performance.update({
        "compteur_avant_secondes": round(temps_compteur_avant, 3),
        "ajout_sqlite_secondes": round(temps_ajout, 3),
        "compteur_apres_secondes": round(temps_compteur_apres, 3),
        "restauration_totale_secondes": round(perf_counter() - t0, 3),
    })

    print(
        "[PERF RESTAURATION] "
        f"pointeuse={pointeuse_id} "
        f"analyse={performance.get('total_secondes', 0)}s "
        f"sqlite={performance['ajout_sqlite_secondes']}s "
        f"total={performance['restauration_totale_secondes']}s"
    )

    if nombre_ajoutes == 0:
        message = "Restauration verifiee. Tous les pointages du backup etaient deja presents dans SQLite."
    else:
        message = f"Restauration terminee. {nombre_ajoutes} pointage(s) ajoute(s) et {nombre_ignores} doublon(s) ignores."

    return {
        "success": True,
        "backup_valid": True,
        "pointeuse_id": int(pointeuse_id),
        "nombre_backup": len(pointages),
        "nombre_avant": nombre_avant,
        "nombre_ajoutes": nombre_ajoutes,
        "nombre_ignores": nombre_ignores,
        "nombre_apres": nombre_apres,
        "historique_conserve": True,
        "terminal_modifie": False,
        "stockage": "sqlite",
        "performance": performance,
        "message": message,
        "erreur": None,
    }
