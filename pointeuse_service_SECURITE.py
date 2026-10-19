import ipaddress
import json
import platform
import subprocess
from pathlib import Path

from zk import ZK


# ==========================================
# CONFIGURATION
# ==========================================

FICHIER_POINTEUSES = Path("pointeuses.json")
RESEAU_AUTORISE = "10.227.198."


# ==========================================
# LIRE LES POINTEUSES
# ==========================================

def get_pointeuses():
    try:
        if not FICHIER_POINTEUSES.exists():
            return {
                "success": False,
                "pointeuses": [],
                "erreur": "Le fichier pointeuses.json est introuvable.",
            }

        with FICHIER_POINTEUSES.open(
            mode="r",
            encoding="utf-8",
        ) as fichier:
            pointeuses = json.load(fichier)

        if not isinstance(pointeuses, list):
            return {
                "success": False,
                "pointeuses": [],
                "erreur": "Le fichier pointeuses.json doit contenir une liste.",
            }

        return {
            "success": True,
            "pointeuses": pointeuses,
            "erreur": None,
        }

    except Exception as erreur:
        return {
            "success": False,
            "pointeuses": [],
            "erreur": str(erreur),
        }


# ==========================================
# PREMIERE POINTEUSE ACTIVE
# ==========================================

def get_pointeuse_active():
    resultat = get_pointeuses()

    if resultat.get("success") is not True:
        return {
            "success": False,
            "pointeuse": None,
            "erreur": resultat.get("erreur"),
        }

    for pointeuse in resultat.get("pointeuses", []):
        if pointeuse.get("active") is True:
            return {
                "success": True,
                "pointeuse": pointeuse,
                "erreur": None,
            }

    return {
        "success": False,
        "pointeuse": None,
        "erreur": "Aucune pointeuse active.",
    }


# ==========================================
# TOUTES LES POINTEUSES ACTIVES
# ==========================================

def get_pointeuses_actives():
    resultat = get_pointeuses()

    if resultat.get("success") is not True:
        return {
            "success": False,
            "pointeuses": [],
            "nombre": 0,
            "erreur": resultat.get("erreur"),
        }

    pointeuses_actives = []

    for pointeuse in resultat.get("pointeuses", []):
        if pointeuse.get("active") is True:
            pointeuses_actives.append(pointeuse)

    return {
        "success": True,
        "pointeuses": pointeuses_actives,
        "nombre": len(pointeuses_actives),
        "erreur": None,
    }


# ==========================================
# POINTEUSE PAR ID
# ==========================================

def get_pointeuse_par_id(pointeuse_id):
    resultat = get_pointeuses()

    if resultat.get("success") is not True:
        return {
            "success": False,
            "pointeuse": None,
            "erreur": resultat.get("erreur"),
        }

    try:
        pointeuse_id = int(pointeuse_id)

    except (TypeError, ValueError):
        return {
            "success": False,
            "pointeuse": None,
            "erreur": "Identifiant de pointeuse invalide.",
        }

    for pointeuse in resultat.get("pointeuses", []):

        try:
            identifiant = int(
                pointeuse.get("id", 0)
            )

        except (TypeError, ValueError):
            continue

        if identifiant == pointeuse_id:
            return {
                "success": True,
                "pointeuse": pointeuse,
                "erreur": None,
            }

    return {
        "success": False,
        "pointeuse": None,
        "erreur": "Pointeuse introuvable.",
    }


# ==========================================
# VALIDER L'IP
# ==========================================

def valider_adresse_ip(ip):
    ip = str(ip).strip()

    if not ip:
        return {
            "success": False,
            "ip": ip,
            "erreur": "L'adresse IP est obligatoire.",
        }

    try:
        adresse = ipaddress.ip_address(ip)

    except ValueError:
        return {
            "success": False,
            "ip": ip,
            "erreur": "L'adresse IP n'est pas valide.",
        }

    if adresse.version != 4:
        return {
            "success": False,
            "ip": ip,
            "erreur": "Seules les adresses IPv4 sont autorisées.",
        }

    if not ip.startswith(RESEAU_AUTORISE):
        return {
            "success": False,
            "ip": ip,
            "erreur": (
                "La pointeuse doit appartenir "
                "au réseau 10.227.198.x."
            ),
        }

    dernier_octet = int(
        ip.split(".")[-1]
    )

    if dernier_octet in (0, 255):
        return {
            "success": False,
            "ip": ip,
            "erreur": (
                "Cette adresse IP ne peut pas "
                "être utilisée pour une pointeuse."
            ),
        }

    return {
        "success": True,
        "ip": ip,
        "erreur": None,
    }


# ==========================================
# VALIDER LE PORT
# ==========================================

def valider_port(port):
    try:
        port = int(port)

    except (TypeError, ValueError):
        return {
            "success": False,
            "port": None,
            "erreur": "Le port doit être un nombre entier.",
        }

    if port < 1 or port > 65535:
        return {
            "success": False,
            "port": port,
            "erreur": "Le port doit être compris entre 1 et 65535.",
        }

    return {
        "success": True,
        "port": port,
        "erreur": None,
    }


# ==========================================
# PING RAPIDE
# ==========================================

def tester_ping(ip):
    validation = valider_adresse_ip(ip)

    if validation.get("success") is not True:
        return {
            "success": False,
            "ping": False,
            "ip": str(ip).strip(),
            "erreur": validation.get("erreur"),
        }

    ip = validation.get("ip")

    try:
        if platform.system().lower() == "windows":
            commande = [
                "ping",
                "-n",
                "1",
                "-w",
                "1000",
                ip,
            ]
        else:
            commande = [
                "ping",
                "-c",
                "1",
                "-W",
                "1",
                ip,
            ]

        resultat = subprocess.run(
            commande,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )

        return {
            "success": True,
            "ping": resultat.returncode == 0,
            "ip": ip,
            "erreur": None,
        }

    except Exception as erreur:
        return {
            "success": False,
            "ping": False,
            "ip": ip,
            "erreur": str(erreur),
        }


# ==========================================
# TEST ZKTECO
# ==========================================

def tester_connexion_pointeuse(ip, port):
    validation_ip = valider_adresse_ip(ip)

    if validation_ip.get("success") is not True:
        return {
            "success": False,
            "ip": str(ip).strip(),
            "port": port,
            "ping": False,
            "firmware": None,
            "heure": None,
            "erreur": validation_ip.get("erreur"),
        }

    validation_port = valider_port(port)

    if validation_port.get("success") is not True:
        return {
            "success": False,
            "ip": validation_ip.get("ip"),
            "port": port,
            "ping": False,
            "firmware": None,
            "heure": None,
            "erreur": validation_port.get("erreur"),
        }

    ip = validation_ip.get("ip")
    port = validation_port.get("port")

    resultat_ping = tester_ping(ip)

    zk = ZK(
        ip,
        port=port,
        timeout=5,
        password=0,
        force_udp=False,
        ommit_ping=False,
    )

    connexion = None

    try:
        connexion = zk.connect()

        firmware = connexion.get_firmware_version()
        heure = connexion.get_time()

        return {
            "success": True,
            "ip": ip,
            "port": port,
            "ping": resultat_ping.get("ping", False),
            "firmware": firmware,
            "heure": heure,
            "erreur": None,
        }

    except Exception as erreur:
        return {
            "success": False,
            "ip": ip,
            "port": port,
            "ping": resultat_ping.get("ping", False),
            "firmware": None,
            "heure": None,
            "erreur": str(erreur),
        }

    finally:
        if connexion is not None:
            try:
                connexion.disconnect()
            except Exception:
                pass


# ==========================================
# AJOUTER UNE POINTEUSE
# ==========================================

def ajouter_pointeuse(
    nom,
    ip,
    port,
    active=True,
):
    nom = str(nom).strip()

    if not nom:
        return {
            "success": False,
            "erreur": "Le nom est obligatoire.",
        }

    validation_ip = valider_adresse_ip(ip)

    if validation_ip.get("success") is not True:
        return {
            "success": False,
            "erreur": validation_ip.get("erreur"),
        }

    validation_port = valider_port(port)

    if validation_port.get("success") is not True:
        return {
            "success": False,
            "erreur": validation_port.get("erreur"),
        }

    ip = validation_ip.get("ip")
    port = validation_port.get("port")

    resultat = get_pointeuses()

    if resultat.get("success") is not True:
        return {
            "success": False,
            "erreur": resultat.get("erreur"),
        }

    pointeuses = resultat.get("pointeuses", [])

    for pointeuse in pointeuses:

        if str(
            pointeuse.get("ip", "")
        ).strip() == ip:

            return {
                "success": False,
                "erreur": (
                    "Une pointeuse avec cette adresse IP "
                    "existe déjà."
                ),
            }

        nom_existant = str(
            pointeuse.get("nom", "")
        ).strip()

        if nom_existant.lower() == nom.lower():

            return {
                "success": False,
                "erreur": (
                    "Une pointeuse avec ce nom "
                    "existe déjà."
                ),
            }

    resultat_test = tester_connexion_pointeuse(
        ip,
        port,
    )

    if resultat_test.get("success") is not True:
        return {
            "success": False,
            "erreur": (
                "Connexion ZKTeco impossible : "
                + str(
                    resultat_test.get("erreur")
                )
            ),
        }

    ids = []

    for pointeuse in pointeuses:
        try:
            ids.append(
                int(
                    pointeuse.get("id", 0)
                )
            )
        except (TypeError, ValueError):
            pass

    nouvel_id = (
        max(ids) + 1
        if ids
        else 1
    )

    nouvelle_pointeuse = {
        "id": nouvel_id,
        "nom": nom,
        "ip": ip,
        "port": port,
        "active": bool(active),
    }

    pointeuses.append(
        nouvelle_pointeuse
    )

    try:
        with FICHIER_POINTEUSES.open(
            mode="w",
            encoding="utf-8",
        ) as fichier:

            json.dump(
                pointeuses,
                fichier,
                ensure_ascii=False,
                indent=4,
            )

    except Exception as erreur:
        return {
            "success": False,
            "erreur": str(erreur),
        }

    return {
        "success": True,
        "pointeuse": nouvelle_pointeuse,
        "ping": resultat_test.get("ping", False),
        "firmware": resultat_test.get("firmware"),
        "heure": resultat_test.get("heure"),
        "erreur": None,
    }


# ==========================================
# MODIFIER UNE POINTEUSE
# ==========================================

def modifier_pointeuse(
    pointeuse_id,
    nom,
    ip,
    port,
    active,
):
    try:
        pointeuse_id = int(
            pointeuse_id
        )

    except (TypeError, ValueError):
        return {
            "success": False,
            "pointeuse": None,
            "erreur": "Identifiant invalide.",
        }

    nom = str(nom).strip()

    if not nom:
        return {
            "success": False,
            "pointeuse": None,
            "erreur": "Le nom est obligatoire.",
        }

    validation_ip = valider_adresse_ip(ip)

    if validation_ip.get("success") is not True:
        return {
            "success": False,
            "pointeuse": None,
            "erreur": validation_ip.get("erreur"),
        }

    validation_port = valider_port(port)

    if validation_port.get("success") is not True:
        return {
            "success": False,
            "pointeuse": None,
            "erreur": validation_port.get("erreur"),
        }

    ip = validation_ip.get("ip")
    port = validation_port.get("port")

    resultat = get_pointeuses()

    if resultat.get("success") is not True:
        return {
            "success": False,
            "pointeuse": None,
            "erreur": resultat.get("erreur"),
        }

    pointeuses = resultat.get(
        "pointeuses",
        []
    )

    pointeuse_cible = None

    for pointeuse in pointeuses:

        try:
            identifiant = int(
                pointeuse.get("id", 0)
            )

        except (TypeError, ValueError):
            continue

        if identifiant == pointeuse_id:
            pointeuse_cible = pointeuse
            break

    if pointeuse_cible is None:
        return {
            "success": False,
            "pointeuse": None,
            "erreur": "Pointeuse introuvable.",
        }

    # Contrôle des doublons
    for pointeuse in pointeuses:

        try:
            autre_id = int(
                pointeuse.get("id", 0)
            )

        except (TypeError, ValueError):
            continue

        if autre_id == pointeuse_id:
            continue

        if str(
            pointeuse.get("ip", "")
        ).strip() == ip:

            return {
                "success": False,
                "pointeuse": None,
                "erreur": (
                    "Une autre pointeuse utilise déjà "
                    "cette adresse IP."
                ),
            }

        autre_nom = str(
            pointeuse.get("nom", "")
        ).strip()

        if autre_nom.lower() == nom.lower():

            return {
                "success": False,
                "pointeuse": None,
                "erreur": (
                    "Une autre pointeuse utilise déjà "
                    "ce nom."
                ),
            }

    # Modification directe
    pointeuse_cible["nom"] = nom
    pointeuse_cible["ip"] = ip
    pointeuse_cible["port"] = port
    pointeuse_cible["active"] = bool(active)

    # Supprimer un ancien environnement
    pointeuse_cible.pop(
        "environnement",
        None,
    )

    try:
        with FICHIER_POINTEUSES.open(
            mode="w",
            encoding="utf-8",
        ) as fichier:

            json.dump(
                pointeuses,
                fichier,
                ensure_ascii=False,
                indent=4,
            )

    except Exception as erreur:
        return {
            "success": False,
            "pointeuse": None,
            "erreur": (
                "Impossible d'enregistrer : "
                + str(erreur)
            ),
        }

    return {
        "success": True,
        "pointeuse": pointeuse_cible,
        "erreur": None,
    }