from datetime import datetime
from time import perf_counter, monotonic
from threading import Lock

from zk import ZK, const


# ============================================================
# CONFIGURATION
# ============================================================

DEFAULT_IP = "10.227.198.96"
DEFAULT_PORT = 4370
DEFAULT_TIMEOUT = 5
POINTAGES_TIMEOUT = 120
DEFAULT_PASSWORD = 0


# ============================================================
# CACHE TEMPORAIRE DES POINTAGES
# ============================================================

CACHE_POINTAGES_TTL = 60
_cache_pointages = {}
_cache_pointages_lock = Lock()


def _cle_cache_pointages(ip, port):
    return (str(ip).strip(), int(port))


def _lire_cache_pointages(ip, port):
    cle = _cle_cache_pointages(ip, port)
    maintenant = monotonic()

    with _cache_pointages_lock:
        entree = _cache_pointages.get(cle)
        if not isinstance(entree, dict):
            return None

        cree_a = entree.get("cree_a")
        if not isinstance(cree_a, (int, float)):
            _cache_pointages.pop(cle, None)
            return None

        age = maintenant - cree_a
        if age > CACHE_POINTAGES_TTL:
            _cache_pointages.pop(cle, None)
            return None

        resultat = entree.get("resultat")
        if not isinstance(resultat, dict):
            return None

        copie = dict(resultat)
        pointages = resultat.get("pointages", [])
        if isinstance(pointages, list):
            copie["pointages"] = pointages

        copie["source"] = "cache_terminal"
        copie["cache"] = True
        copie["cache_age_secondes"] = round(age, 3)

        performance_originale = resultat.get("performance")
        if isinstance(performance_originale, dict):
            copie["performance"] = dict(performance_originale)

        return copie


def _enregistrer_cache_pointages(ip, port, resultat):
    if not isinstance(resultat, dict) or resultat.get("success") is not True:
        return

    pointages = resultat.get("pointages")
    if not isinstance(pointages, list):
        return

    cle = _cle_cache_pointages(ip, port)
    with _cache_pointages_lock:
        _cache_pointages[cle] = {
            "cree_a": monotonic(),
            "resultat": resultat,
        }


def invalider_cache_pointages(ip, port):
    try:
        cle = _cle_cache_pointages(ip, port)
    except Exception:
        return False

    with _cache_pointages_lock:
        existait = cle in _cache_pointages
        _cache_pointages.pop(cle, None)
    return existait


def vider_cache_pointages():
    with _cache_pointages_lock:
        _cache_pointages.clear()
    return True


# ============================================================
# CLIENT ZK
# ============================================================

def creer_client_zk(ip, port, timeout=DEFAULT_TIMEOUT):
    ip = str(ip).strip()

    try:
        port = int(port)
    except (TypeError, ValueError):
        raise ValueError("Le port doit etre un nombre entier.")

    try:
        timeout = int(timeout)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT

    if not ip:
        raise ValueError("L'adresse IP est obligatoire.")
    if port < 1 or port > 65535:
        raise ValueError("Le port doit etre compris entre 1 et 65535.")
    if timeout < 1:
        timeout = DEFAULT_TIMEOUT

    return ZK(
        ip,
        port=port,
        timeout=timeout,
        password=DEFAULT_PASSWORD,
        force_udp=False,
        ommit_ping=False,
    )


def normaliser_texte(valeur):
    if valeur is None:
        return ""
    return str(valeur).strip()


def normaliser_badge(valeur):
    if valeur is None:
        return ""
    texte = str(valeur).strip()
    return "" if texte == "0" else texte


# ============================================================
# ETAT TERMINAL
# ============================================================

def get_device_status():
    return get_device_status_pointeuse(DEFAULT_IP, DEFAULT_PORT)


def get_device_status_pointeuse(ip, port):
   def get_device_status_pointeuse(
    ip,
    port,
):
    connexion = None

    try:
        zk = creer_client_zk(
            ip,
            port,
        )

        connexion = zk.connect()

        # ====================================================
        # FIRMWARE
        # ====================================================

        firmware = None

        try:
            firmware = (
                connexion.get_firmware_version()
            )

        except Exception:
            firmware = None


        # ====================================================
        # HEURE
        # ====================================================

        heure = None

        try:
            heure = connexion.get_time()

        except Exception:
            heure = None


        # ====================================================
        # ADRESSE MAC
        # ====================================================

        mac = None

        try:
            mac = connexion.get_mac()

            if mac is not None:

                mac = str(
                    mac
                ).strip()

                if not mac:
                    mac = None

        except Exception:
            mac = None


        # ====================================================
        # RESULTAT
        # ====================================================

        return {
            "success": True,
            "connected": True,

            "ip": str(
                ip
            ).strip(),

            "port": int(
                port
            ),

            "firmware": firmware,

            "heure": heure,

            "mac": mac,

            "erreur": None,
        }


    except Exception as erreur:

        return {
            "success": False,
            "connected": False,

            "ip": str(
                ip
            ).strip(),

            "port": port,

            "firmware": None,

            "heure": None,

            "mac": None,

            "erreur": str(
                erreur
            ),
        }


    finally:

        if connexion is not None:

            try:
                connexion.disconnect()

            except Exception:
                pass

# ============================================================
# UTILISATEURS
# ============================================================

def get_users():
    return get_users_pointeuse(DEFAULT_IP, DEFAULT_PORT)


def get_users_pointeuse(ip, port):
    connexion = None
    try:
        zk = creer_client_zk(ip, port)
        connexion = zk.connect()
        utilisateurs = []

        for utilisateur in connexion.get_users():
            uid = getattr(utilisateur, "uid", None)
            matricule = normaliser_texte(getattr(utilisateur, "user_id", ""))
            nom = normaliser_texte(getattr(utilisateur, "name", ""))
            badge = normaliser_badge(getattr(utilisateur, "card", ""))
            privilege = getattr(utilisateur, "privilege", const.USER_DEFAULT)
            group_id = normaliser_texte(getattr(utilisateur, "group_id", ""))
            role = "Admin" if privilege == const.USER_ADMIN else "Utilisateur normal"

            utilisateurs.append({
                "uid": uid,
                "matricule": matricule,
                "user_id": matricule,
                "nom": nom,
                "badge": badge,
                "privilege": privilege,
                "role": role,
                "group_id": group_id,
            })

        return {
            "success": True,
            "ip": str(ip).strip(),
            "port": int(port),
            "utilisateurs": utilisateurs,
            "nombre": len(utilisateurs),
            "erreur": None,
        }
    except Exception as erreur:
        return {
            "success": False,
            "ip": str(ip).strip(),
            "port": port,
            "utilisateurs": [],
            "nombre": 0,
            "erreur": str(erreur),
        }
    finally:
        if connexion is not None:
            try:
                connexion.disconnect()
            except Exception:
                pass


def get_user_pointeuse(ip, port, uid):
    resultat = get_users_pointeuse(ip, port)
    if resultat.get("success") is not True:
        return {"success": False, "utilisateur": None, "erreur": resultat.get("erreur")}

    try:
        uid = int(uid)
    except (TypeError, ValueError):
        return {"success": False, "utilisateur": None, "erreur": "UID utilisateur invalide."}

    for utilisateur in resultat.get("utilisateurs", []):
        try:
            uid_utilisateur = int(utilisateur.get("uid"))
        except (TypeError, ValueError):
            continue
        if uid_utilisateur == uid:
            return {"success": True, "utilisateur": utilisateur, "erreur": None}

    return {"success": False, "utilisateur": None, "erreur": "Employe introuvable."}


def modifier_employe_pointeuse(ip, port, uid, matricule, nom, badge, role):
    connexion = None

    try:
        uid = int(uid)
    except (TypeError, ValueError):
        return {"success": False, "erreur": "UID invalide."}

    matricule = normaliser_texte(matricule)
    nom = normaliser_texte(nom)
    badge = normaliser_badge(badge)
    role = normaliser_texte(role).lower()

    if not matricule:
        return {"success": False, "erreur": "Le matricule est obligatoire."}
    if not nom:
        return {"success": False, "erreur": "Le nom est obligatoire."}
    if not badge:
        return {"success": False, "erreur": "Le numero de badge est obligatoire."}
    if not badge.isdigit():
        return {"success": False, "erreur": "Le numero de badge doit etre numerique."}

    if role == "admin":
        privilege = const.USER_ADMIN
    elif role in ("utilisateur", "utilisateur normal"):
        privilege = const.USER_DEFAULT
    else:
        return {"success": False, "erreur": "Le statut utilisateur est invalide."}

    resultat_users = get_users_pointeuse(ip, port)
    if resultat_users.get("success") is not True:
        return {"success": False, "erreur": resultat_users.get("erreur")}

    for utilisateur in resultat_users.get("utilisateurs", []):
        try:
            autre_uid = int(utilisateur.get("uid"))
        except (TypeError, ValueError):
            continue
        if autre_uid == uid:
            continue

        autre_matricule = normaliser_texte(utilisateur.get("matricule", ""))
        autre_badge = normaliser_badge(utilisateur.get("badge", ""))

        if autre_matricule.upper() == matricule.upper():
            return {"success": False, "erreur": "Ce matricule est deja utilise par un autre employe."}
        if badge and autre_badge == badge:
            return {"success": False, "erreur": "Ce numero de badge est deja utilise par un autre employe."}

    try:
        zk = creer_client_zk(ip, port)
        connexion = zk.connect()
        connexion.set_user(
            uid=uid,
            name=nom,
            privilege=privilege,
            password="",
            group_id="",
            user_id=matricule,
            card=int(badge),
        )
        return {
            "success": True,
            "uid": uid,
            "matricule": matricule,
            "nom": nom,
            "badge": badge,
            "privilege": privilege,
            "role": "Admin" if privilege == const.USER_ADMIN else "Utilisateur normal",
            "erreur": None,
        }
    except Exception as erreur:
        return {"success": False, "erreur": "Impossible de modifier l'employe : " + str(erreur)}
    finally:
        if connexion is not None:
            try:
                connexion.disconnect()
            except Exception:
                pass


def verifier_nouvel_employe(matricule, nom, prenom="", badge=""):
    matricule = normaliser_texte(matricule)
    nom = normaliser_texte(nom)
    prenom = normaliser_texte(prenom)
    badge = normaliser_badge(badge)
    erreurs = []

    if not matricule:
        erreurs.append("Le matricule est obligatoire.")
    if not nom:
        erreurs.append("Le nom est obligatoire.")
    if badge and not badge.isdigit():
        erreurs.append("Le numero de badge doit etre numerique.")

    nom_complet = (nom + " " + prenom).strip() if prenom else nom
    return {
        "success": len(erreurs) == 0,
        "valide": len(erreurs) == 0,
        "matricule": matricule,
        "nom": nom,
        "prenom": prenom,
        "nom_complet": nom_complet,
        "badge": badge,
        "erreurs": erreurs,
        "erreur": erreurs[0] if erreurs else None,
    }


# ============================================================
# IMPORT EMPLOYES
# ============================================================

def preparer_import_employes(ip, port, employes):
    if not isinstance(employes, list):
        return {"success": False, "valides": [], "erreurs": [], "nombre_valides": 0, "nombre_erreurs": 0, "erreur": "La liste des employes est invalide."}
    if not employes:
        return {"success": False, "valides": [], "erreurs": [], "nombre_valides": 0, "nombre_erreurs": 0, "erreur": "Aucun employe a preparer."}

    resultat_users = get_users_pointeuse(ip, port)
    if resultat_users.get("success") is not True:
        return {"success": False, "valides": [], "erreurs": [], "nombre_valides": 0, "nombre_erreurs": 0, "erreur": resultat_users.get("erreur")}

    matricules_existants = set()
    badges_existants = set()
    uids_utilises = set()

    for utilisateur in resultat_users.get("utilisateurs", []):
        matricule = normaliser_texte(utilisateur.get("matricule", ""))
        badge = normaliser_badge(utilisateur.get("badge", ""))
        if matricule:
            matricules_existants.add(matricule.upper())
        if badge:
            badges_existants.add(badge)
        try:
            uid = int(utilisateur.get("uid"))
            if uid > 0:
                uids_utilises.add(uid)
        except (TypeError, ValueError):
            pass

    valides = []
    erreurs = []
    matricules_import = set()
    badges_import = set()
    prochain_uid = 1

    def obtenir_uid_libre():
        nonlocal prochain_uid
        while prochain_uid in uids_utilises:
            prochain_uid += 1
        uid_libre = prochain_uid
        uids_utilises.add(uid_libre)
        prochain_uid += 1
        return uid_libre

    for employe in employes:
        ligne = employe.get("ligne")
        matricule = normaliser_texte(employe.get("matricule", ""))
        nom = normaliser_texte(employe.get("nom", ""))
        badge = normaliser_badge(employe.get("badge", ""))
        erreurs_ligne = []
        matricule_normalise = matricule.upper()

        if not matricule:
            erreurs_ligne.append("Matricule manquant.")
        elif matricule_normalise in matricules_existants:
            erreurs_ligne.append("Matricule deja present.")
        elif matricule_normalise in matricules_import:
            erreurs_ligne.append("Matricule duplique.")

        if not nom:
            erreurs_ligne.append("Nom manquant.")

        if not badge:
            erreurs_ligne.append("Badge manquant.")
        elif not badge.isdigit():
            erreurs_ligne.append("Badge invalide.")
        elif badge in badges_existants:
            erreurs_ligne.append("Badge deja present.")
        elif badge in badges_import:
            erreurs_ligne.append("Badge duplique.")

        if erreurs_ligne:
            erreurs.append({"ligne": ligne, "matricule": matricule, "nom": nom, "badge": badge, "erreurs": erreurs_ligne})
            continue

        matricules_import.add(matricule_normalise)
        badges_import.add(badge)
        valides.append({
            "ligne": ligne,
            "uid": obtenir_uid_libre(),
            "matricule": matricule,
            "nom": nom,
            "badge": badge,
            "profil": "Utilisateur normal",
            "etat": "Pret a importer",
        })

    return {
        "success": True,
        "ip": str(ip).strip(),
        "port": int(port),
        "valides": valides,
        "erreurs": erreurs,
        "nombre_valides": len(valides),
        "nombre_erreurs": len(erreurs),
        "erreur": None,
    }


def importer_employes(ip, port, employes):
    connexion = None
    importes = []
    erreurs = []

    if not employes:
        return {"success": False, "importes": [], "erreurs": [], "nombre_importes": 0, "nombre_erreurs": 0, "erreur": "Aucun employe a importer."}

    try:
        zk = creer_client_zk(ip, port)
        connexion = zk.connect()

        for employe in employes:
            try:
                uid = int(employe.get("uid"))
                matricule = normaliser_texte(employe.get("matricule", ""))
                nom = normaliser_texte(employe.get("nom", ""))
                badge = normaliser_badge(employe.get("badge", ""))
                connexion.set_user(
                    uid=uid,
                    name=nom,
                    privilege=const.USER_DEFAULT,
                    password="",
                    group_id="",
                    user_id=matricule,
                    card=int(badge),
                )
                importes.append({"ligne": employe.get("ligne"), "uid": uid, "matricule": matricule, "nom": nom, "badge": badge})
            except Exception as erreur:
                erreurs.append({"ligne": employe.get("ligne"), "matricule": employe.get("matricule"), "erreurs": [str(erreur)]})

        return {
            "success": len(erreurs) == 0,
            "ip": str(ip).strip(),
            "port": int(port),
            "importes": importes,
            "erreurs": erreurs,
            "nombre_importes": len(importes),
            "nombre_erreurs": len(erreurs),
            "erreur": None if not erreurs else "Certains employes n'ont pas pu etre importes.",
        }
    except Exception as erreur:
        return {"success": False, "importes": importes, "erreurs": erreurs, "nombre_importes": len(importes), "nombre_erreurs": len(erreurs), "erreur": str(erreur)}
    finally:
        if connexion is not None:
            try:
                connexion.disconnect()
            except Exception:
                pass


# ============================================================
# PROPRIETES DU TERMINAL
# ============================================================
def get_proprietes_pointeuse(ip, port):
    connexion = None

    try:
        zk = creer_client_zk(ip, port)
        connexion = zk.connect()

        def lire(methode, valeur_defaut=None):
            try:
                return methode()
            except Exception:
                return valeur_defaut

        firmware = lire(connexion.get_firmware_version)
        heure = lire(connexion.get_time)
        nom_terminal = lire(connexion.get_device_name)
        numero_serie = lire(connexion.get_serialnumber)
        plateforme = lire(connexion.get_platform)

        mac = lire(
            connexion.get_mac,
            None
        )

        if mac is not None:
            mac = str(mac).strip()

        if not mac:
            mac = "Non disponible"

        utilisateurs = lire(
            connexion.get_users,
            []
        ) or []

        nombre_admins = sum(
            1
            for u in utilisateurs
            if getattr(u, "privilege", None) == const.USER_ADMIN
        )

        return {
            "success": True,
            "connectee": True,
            "ip": str(ip).strip(),
            "port": int(port),
            "firmware": str(firmware) if firmware is not None else None,
            "heure": str(heure) if heure is not None else None,
            "mac": mac,
            "nom_terminal": str(nom_terminal) if nom_terminal is not None else None,
            "numero_serie": str(numero_serie) if numero_serie is not None else None,
            "plateforme": str(plateforme) if plateforme is not None else None,
            "nombre_utilisateurs": len(utilisateurs),
            "nombre_admins": nombre_admins,
            "erreur": None,
        }

    except Exception as erreur:

        return {
            "success": False,
            "connectee": False,
            "ip": str(ip).strip(),
            "port": port,
            "firmware": None,
            "heure": None,
            "mac": None,
            "nom_terminal": None,
            "numero_serie": None,
            "plateforme": None,
            "nombre_utilisateurs": None,
            "nombre_admins": None,
            "erreur": str(erreur),
        }

    finally:

        if connexion is not None:

            try:
                connexion.disconnect()

            except Exception:
                pass


def synchroniser_heure_pointeuse(ip, port):
    connexion = None

    try:

    
        zk = creer_client_zk(ip, port)
        connexion = zk.connect()

        try:
            heure_avant = connexion.get_time()
        except Exception:
            heure_avant = None

        heure_serveur = datetime.now()

        resultat_set = connexion.set_time(
            heure_serveur
        )

        heure_apres = connexion.get_time()

        return {
            "success": True,
            "heure_avant": str(heure_avant) if heure_avant is not None else None,
            "heure_serveur": str(heure_serveur),
            "heure_apres": str(heure_apres),
            "commande_envoyee": resultat_set,
            "message": "L'heure de la pointeuse a ete synchronisee avec succes.",
            "erreur": None,
        }

    except Exception as erreur:

        return {
            "success": False,
            "erreur": "Impossible de synchroniser l'heure : " + str(erreur),
        }

    finally:

        if connexion is not None:

            try:
                connexion.disconnect()

            except Exception:
                pass
    

def redemarrer_pointeuse(ip, port):
    connexion = None

    try:
        zk = creer_client_zk(ip, port)
        connexion = zk.connect()

        resultat = connexion.restart()

        return {
            "success": True,
            "commande_envoyee": resultat,
            "message": "La commande de redemarrage a ete envoyee a la pointeuse.",
            "erreur": None,
        }

    except Exception as erreur:

        return {
            "success": False,
            "erreur": "Impossible de redemarrer la pointeuse : " + str(erreur),
        }

    finally:

        if connexion is not None:

            try:
                connexion.disconnect()

            except Exception:
                pass


def retirer_privileges_admin_pointeuse(ip, port):
    connexion = None
    terminal_desactive = False

    try:
        zk = creer_client_zk(ip, port)
        connexion = zk.connect()

        utilisateurs = connexion.get_users() or []

        administrateurs = [
            u for u in utilisateurs
            if getattr(u, "privilege", None) == const.USER_ADMIN
        ]

        if not administrateurs:

            return {
                "success": True,
                "nombre_modifies": 0,
                "nombre_erreurs": 0,
                "admins_restants": 0,
                "modifies": [],
                "erreurs": [],
                "message": "Aucun utilisateur Admin n'est present sur cette pointeuse.",
                "erreur": None,
            }

        connexion.disable_device()
        terminal_desactive = True

        modifies = []
        erreurs = []

        for utilisateur in administrateurs:

            try:

                connexion.set_user(
                    uid=utilisateur.uid,
                    name=getattr(utilisateur, "name", "") or "",
                    privilege=const.USER_DEFAULT,
                    password=getattr(utilisateur, "password", "") or "",
                    group_id=getattr(utilisateur, "group_id", "") or "",
                    user_id=getattr(utilisateur, "user_id", "") or "",
                    card=getattr(utilisateur, "card", 0) or 0,
                )

                modifies.append({
                    "uid": utilisateur.uid,
                    "matricule": getattr(utilisateur, "user_id", "") or "",
                    "nom": getattr(utilisateur, "name", "") or "",
                })

            except Exception as erreur_user:

                erreurs.append({
                    "uid": getattr(utilisateur, "uid", None),
                    "erreur": str(erreur_user),
                })

        utilisateurs_apres = connexion.get_users() or []

        admins_restants = sum(
            1
            for u in utilisateurs_apres
            if getattr(u, "privilege", None) == const.USER_ADMIN
        )

        succes = (
            not erreurs
            and admins_restants == 0
        )

        return {
            "success": succes,
            "nombre_modifies": len(modifies),
            "nombre_erreurs": len(erreurs),
            "admins_restants": admins_restants,
            "modifies": modifies,
            "erreurs": erreurs,
            "message": str(len(modifies)) + " privilege(s) Admin retire(s).",
            "erreur": None if succes else "Certains privileges Admin n'ont pas pu etre retires.",
        }

    except Exception as erreur:

        return {
            "success": False,
            "nombre_modifies": 0,
            "nombre_erreurs": 1,
            "admins_restants": None,
            "modifies": [],
            "erreurs": [],
            "erreur": "Impossible de modifier les privileges Admin : " + str(erreur),
        }

    finally:

        if connexion is not None:

            if terminal_desactive:

                try:
                    connexion.enable_device()
                except Exception:
                    pass

            try:
                connexion.disconnect()
            except Exception:
                pass

# ============================================================
# CONVERTIR DATETIME / POINTAGES
# ============================================================

def convertir_datetime(valeur):
    if isinstance(valeur, datetime):
        return valeur

    texte = normaliser_texte(valeur)
    if not texte:
        raise ValueError("La date et l'heure sont obligatoires.")

    formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"]
    for format_datetime in formats:
        try:
            return datetime.strptime(texte, format_datetime)
        except ValueError:
            continue
    raise ValueError("Format de date/heure invalide.")


def get_pointages_pointeuse(ip, port, forcer_actualisation=False):
    connexion = None
    debut_total = perf_counter()
    temps_connexion = 0.0
    temps_lecture = 0.0
    temps_conversion = 0.0
    ip_normalisee = str(ip).strip()

    try:
        port_normalise = int(port)
    except (TypeError, ValueError):
        return {
            "success": False, "ip": ip_normalisee, "port": port, "pointages": [], "nombre": 0,
            "source": "terminal", "cache": False, "cache_age_secondes": None,
            "performance": {"connexion_secondes": 0.0, "lecture_pointages_secondes": 0.0, "conversion_secondes": 0.0, "total_secondes": 0.0},
            "erreur": "Le port est invalide.",
        }

    if not forcer_actualisation:
        resultat_cache = _lire_cache_pointages(ip_normalisee, port_normalise)
        if resultat_cache is not None:
            performance_cache = dict(resultat_cache.get("performance", {}))
            performance_cache["total_secondes"] = round(perf_counter() - debut_total, 3)
            performance_cache["depuis_cache"] = True
            resultat_cache["performance"] = performance_cache
            return resultat_cache

    try:
        debut = perf_counter()
        zk = creer_client_zk(ip_normalisee, port_normalise, timeout=POINTAGES_TIMEOUT)
        connexion = zk.connect()
        temps_connexion = perf_counter() - debut
        if connexion is None:
            raise RuntimeError("Impossible de se connecter a la pointeuse.")

        debut = perf_counter()
        pointages_bruts = connexion.get_attendance()
        temps_lecture = perf_counter() - debut
        if pointages_bruts is None:
            pointages_bruts = []
        pointages_bruts = list(pointages_bruts)
        nombre_terminal = len(pointages_bruts)

        debut = perf_counter()
        pointages = []
        for pointage in pointages_bruts:
            matricule = normaliser_texte(getattr(pointage, "user_id", ""))
            timestamp = getattr(pointage, "timestamp", None)
            uid = getattr(pointage, "uid", None)
            if isinstance(timestamp, datetime):
                date_texte = timestamp.strftime("%d/%m/%Y")
                heure_texte = timestamp.strftime("%H:%M:%S")
            else:
                date_texte = ""
                heure_texte = ""
            pointages.append({
                "uid": uid, "matricule": matricule, "nom": "", "badge": "", "timestamp": timestamp,
                "date": date_texte, "heure": heure_texte,
                "status": getattr(pointage, "status", None), "punch": getattr(pointage, "punch", None),
            })
        temps_conversion = perf_counter() - debut

        total = perf_counter() - debut_total
        resultat = {
            "success": True, "ip": ip_normalisee, "port": port_normalise, "pointages": pointages,
            "nombre": nombre_terminal, "source": "terminal_get_attendance", "cache": False, "cache_age_secondes": 0.0,
            "performance": {
                "connexion_secondes": round(temps_connexion, 3), "lecture_pointages_secondes": round(temps_lecture, 3),
                "conversion_secondes": round(temps_conversion, 3), "total_secondes": round(total, 3), "depuis_cache": False,
            },
            "erreur": None,
        }
        _enregistrer_cache_pointages(ip_normalisee, port_normalise, resultat)
        return resultat
    except Exception as erreur:
        total = perf_counter() - debut_total
        message_erreur = str(erreur)
        if "timed out" in message_erreur.lower() or "timeout" in message_erreur.lower():
            message_erreur = "La lecture des pointages a depasse le delai de " + str(POINTAGES_TIMEOUT) + " secondes."
        return {
            "success": False, "ip": ip_normalisee, "port": port_normalise, "pointages": [], "nombre": 0,
            "source": "terminal", "cache": False, "cache_age_secondes": None,
            "performance": {
                "connexion_secondes": round(temps_connexion, 3), "lecture_pointages_secondes": round(temps_lecture, 3),
                "conversion_secondes": round(temps_conversion, 3), "total_secondes": round(total, 3), "depuis_cache": False,
            },
            "erreur": "Impossible de lire les pointages : " + message_erreur,
        }
    finally:
        if connexion is not None:
            try:
                connexion.disconnect()
            except Exception:
                pass


def get_pointages_intervalle(ip, port, date_heure_debut, date_heure_fin, forcer_actualisation=False):
    try:
        debut = convertir_datetime(date_heure_debut)
        fin = convertir_datetime(date_heure_fin)
    except ValueError as erreur:
        return {"success": False, "ip": str(ip).strip(), "port": port, "debut": None, "fin": None, "pointages": [], "nombre": 0, "source": "terminal", "performance": None, "erreur": str(erreur)}

    if debut > fin:
        return {"success": False, "ip": str(ip).strip(), "port": port, "debut": debut, "fin": fin, "pointages": [], "nombre": 0, "source": "terminal", "performance": None, "erreur": "La date et l'heure de debut doivent etre anterieures ou egales a la date et l'heure de fin."}

    resultat = get_pointages_pointeuse(ip=ip, port=port, forcer_actualisation=forcer_actualisation)
    if resultat.get("success") is not True:
        return {
            "success": False, "ip": str(ip).strip(), "port": port, "debut": debut, "fin": fin,
            "pointages": [], "nombre": 0, "source": resultat.get("source"), "cache": resultat.get("cache", False),
            "performance": resultat.get("performance"), "erreur": resultat.get("erreur"),
        }

    filtres = []
    for pointage in resultat.get("pointages", []):
        timestamp = pointage.get("timestamp")
        if isinstance(timestamp, datetime) and debut <= timestamp <= fin:
            filtres.append(pointage)

    return {
        "success": True, "ip": str(ip).strip(), "port": int(port), "debut": debut, "fin": fin,
        "pointages": filtres, "nombre": len(filtres), "source": resultat.get("source", "terminal_get_attendance"),
        "cache": resultat.get("cache", False), "cache_age_secondes": resultat.get("cache_age_secondes"),
        "performance": resultat.get("performance"), "erreur": None,
    }
