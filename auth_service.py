import hashlib
import hmac
import os
import secrets
import sqlite3
from datetime import datetime
from pathlib import Path

DOSSIER_DATA = Path("data")
FICHIER_DATABASE = DOSSIER_DATA / "zkteco.db"

ROLE_ADMIN = "ADMIN"
ROLE_USER = "USER"
ROLES_AUTORISES = {ROLE_ADMIN, ROLE_USER}

PBKDF2_ALGORITHME = "sha256"
PBKDF2_ITERATIONS = 600_000
SEL_TAILLE = 32
CLE_TAILLE = 32


# ============================================================
# OUTILS GENERAUX
# ============================================================

def _maintenant():
    return datetime.now().isoformat(timespec="seconds")


def normaliser_username(valeur):
    return str(valeur or "").strip().lower()


def normaliser_nom(valeur):
    return str(valeur or "").strip()


def normaliser_role(valeur):
    role = str(valeur or ROLE_USER).strip().upper()
    return role if role in ROLES_AUTORISES else None


def est_actif(valeur):
    if valeur is True:
        return True
    if valeur is False or valeur is None:
        return False
    if isinstance(valeur, int):
        return valeur == 1
    if isinstance(valeur, str):
        return valeur.strip().lower() in ("true", "1", "oui", "yes", "active", "actif", "on")
    return bool(valeur)


def _ouvrir_database():
    DOSSIER_DATA.mkdir(parents=True, exist_ok=True)
    connexion = sqlite3.connect(str(FICHIER_DATABASE), timeout=30)
    connexion.row_factory = sqlite3.Row
    connexion.execute("PRAGMA journal_mode=WAL")
    connexion.execute("PRAGMA synchronous=NORMAL")
    connexion.execute("PRAGMA foreign_keys=ON")
    return connexion


# ============================================================
# INITIALISATION DES TABLES PROFILS
# ============================================================

def initialiser_auth_database():
    connexion = None
    try:
        connexion = _ouvrir_database()
        connexion.execute(
            """
            CREATE TABLE IF NOT EXISTS profils (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                nom TEXT NOT NULL DEFAULT '',
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'USER',
                active INTEGER NOT NULL DEFAULT 1,
                cree_le TEXT NOT NULL,
                modifie_le TEXT NOT NULL,
                dernier_login TEXT
            )
            """
        )
        connexion.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_profils_role_active
            ON profils (role, active)
            """
        )
        connexion.commit()
        return {"success": True, "database": str(FICHIER_DATABASE), "erreur": None}
    except Exception as erreur:
        return {
            "success": False,
            "database": str(FICHIER_DATABASE),
            "erreur": "Impossible d'initialiser l'authentification : " + str(erreur),
        }
    finally:
        if connexion is not None:
            connexion.close()


# ============================================================
# MOTS DE PASSE
# Format stocke : pbkdf2_sha256$iterations$salt_hex$hash_hex
# ============================================================

def valider_mot_de_passe(mot_de_passe):
    mot_de_passe = str(mot_de_passe or "")
    erreurs = []
    if len(mot_de_passe) < 10:
        erreurs.append("Le mot de passe doit contenir au moins 10 caracteres.")
    if not any(c.islower() for c in mot_de_passe):
        erreurs.append("Le mot de passe doit contenir au moins une lettre minuscule.")
    if not any(c.isupper() for c in mot_de_passe):
        erreurs.append("Le mot de passe doit contenir au moins une lettre majuscule.")
    if not any(c.isdigit() for c in mot_de_passe):
        erreurs.append("Le mot de passe doit contenir au moins un chiffre.")
    return {
        "success": not erreurs,
        "erreurs": erreurs,
        "erreur": erreurs[0] if erreurs else None,
    }


def hacher_mot_de_passe(mot_de_passe):
    validation = valider_mot_de_passe(mot_de_passe)
    if validation.get("success") is not True:
        raise ValueError(validation.get("erreur") or "Mot de passe invalide.")

    sel = os.urandom(SEL_TAILLE)
    derivee = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHME,
        str(mot_de_passe).encode("utf-8"),
        sel,
        PBKDF2_ITERATIONS,
        dklen=CLE_TAILLE,
    )
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERATIONS,
        sel.hex(),
        derivee.hex(),
    )


def verifier_mot_de_passe(mot_de_passe, valeur_stockee):
    try:
        morceaux = str(valeur_stockee or "").split("$")
        if len(morceaux) != 4 or morceaux[0] != "pbkdf2_sha256":
            return False

        iterations = int(morceaux[1])
        sel = bytes.fromhex(morceaux[2])
        attendu = bytes.fromhex(morceaux[3])

        calcule = hashlib.pbkdf2_hmac(
            PBKDF2_ALGORITHME,
            str(mot_de_passe or "").encode("utf-8"),
            sel,
            iterations,
            dklen=len(attendu),
        )
        return hmac.compare_digest(calcule, attendu)
    except Exception:
        return False


# ============================================================
# CONVERSION PROFIL PUBLIC
# ============================================================

def _profil_public(ligne):
    if ligne is None:
        return None
    profil = dict(ligne)
    profil.pop("password_hash", None)
    profil["active"] = bool(profil.get("active"))
    profil["is_admin"] = str(profil.get("role") or "").upper() == ROLE_ADMIN
    return profil


# ============================================================
# COMPTE ADMIN INITIAL
# ============================================================

def assurer_admin_initial(username="admin", mot_de_passe=None, nom="Administrateur"):
    """Cree le premier ADMIN uniquement si aucun profil n'existe.

    Si mot_de_passe est None, la variable d'environnement
    ZKTECO_ADMIN_PASSWORD doit etre definie. Aucun mot de passe par defaut
    n'est code en dur.
    """
    init = initialiser_auth_database()
    if init.get("success") is not True:
        return init

    connexion = None
    try:
        connexion = _ouvrir_database()
        ligne = connexion.execute("SELECT COUNT(*) AS nombre FROM profils").fetchone()
        nombre = int(ligne["nombre"] if ligne else 0)
        if nombre > 0:
            admin = connexion.execute(
                "SELECT * FROM profils WHERE role = ? ORDER BY id ASC LIMIT 1",
                (ROLE_ADMIN,),
            ).fetchone()
            return {
                "success": True,
                "cree": False,
                "profil": _profil_public(admin),
                "erreur": None,
            }

        mot_de_passe = mot_de_passe or os.environ.get("ZKTECO_ADMIN_PASSWORD")
        if not mot_de_passe:
            return {
                "success": False,
                "cree": False,
                "profil": None,
                "erreur": (
                    "Aucun profil n'existe. Definissez ZKTECO_ADMIN_PASSWORD "
                    "avant de creer le compte administrateur initial."
                ),
            }

        username = normaliser_username(username)
        nom = normaliser_nom(nom) or "Administrateur"
        password_hash = hacher_mot_de_passe(mot_de_passe)
        maintenant = _maintenant()

        curseur = connexion.execute(
            """
            INSERT INTO profils (
                username, nom, password_hash, role, active,
                cree_le, modifie_le, dernier_login
            ) VALUES (?, ?, ?, ?, 1, ?, ?, NULL)
            """,
            (username, nom, password_hash, ROLE_ADMIN, maintenant, maintenant),
        )
        connexion.commit()
        profil = connexion.execute("SELECT * FROM profils WHERE id = ?", (curseur.lastrowid,)).fetchone()
        return {"success": True, "cree": True, "profil": _profil_public(profil), "erreur": None}
    except Exception as erreur:
        if connexion is not None:
            connexion.rollback()
        return {"success": False, "cree": False, "profil": None, "erreur": str(erreur)}
    finally:
        if connexion is not None:
            connexion.close()


# ============================================================
# CRUD PROFILS
# ============================================================

def creer_profil(username, mot_de_passe, nom="", role=ROLE_USER, active=True):
    init = initialiser_auth_database()
    if init.get("success") is not True:
        return init

    username = normaliser_username(username)
    nom = normaliser_nom(nom)
    role = normaliser_role(role)

    if len(username) < 3:
        return {"success": False, "profil": None, "erreur": "Le nom d'utilisateur doit contenir au moins 3 caracteres."}
    if not all(c.isalnum() or c in (".", "_", "-") for c in username):
        return {"success": False, "profil": None, "erreur": "Le nom d'utilisateur contient des caracteres non autorises."}
    if role is None:
        return {"success": False, "profil": None, "erreur": "Role invalide."}

    try:
        password_hash = hacher_mot_de_passe(mot_de_passe)
    except ValueError as erreur:
        return {"success": False, "profil": None, "erreur": str(erreur)}

    connexion = None
    try:
        connexion = _ouvrir_database()
        maintenant = _maintenant()
        curseur = connexion.execute(
            """
            INSERT INTO profils (
                username, nom, password_hash, role, active,
                cree_le, modifie_le, dernier_login
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (username, nom, password_hash, role, 1 if est_actif(active) else 0, maintenant, maintenant),
        )
        connexion.commit()
        profil = connexion.execute("SELECT * FROM profils WHERE id = ?", (curseur.lastrowid,)).fetchone()
        return {"success": True, "profil": _profil_public(profil), "erreur": None}
    except sqlite3.IntegrityError:
        return {"success": False, "profil": None, "erreur": "Ce nom d'utilisateur existe deja."}
    except Exception as erreur:
        if connexion is not None:
            connexion.rollback()
        return {"success": False, "profil": None, "erreur": str(erreur)}
    finally:
        if connexion is not None:
            connexion.close()


def get_profil_par_id(profil_id, inclure_inactif=True):
    init = initialiser_auth_database()
    if init.get("success") is not True:
        return {"success": False, "profil": None, "erreur": init.get("erreur")}
    try:
        profil_id = int(profil_id)
    except (TypeError, ValueError):
        return {"success": False, "profil": None, "erreur": "Identifiant de profil invalide."}

    connexion = None
    try:
        connexion = _ouvrir_database()
        requete = "SELECT * FROM profils WHERE id = ?"
        params = [profil_id]
        if not inclure_inactif:
            requete += " AND active = 1"
        ligne = connexion.execute(requete, params).fetchone()
        if ligne is None:
            return {"success": False, "profil": None, "erreur": "Profil introuvable."}
        return {"success": True, "profil": _profil_public(ligne), "erreur": None}
    except Exception as erreur:
        return {"success": False, "profil": None, "erreur": str(erreur)}
    finally:
        if connexion is not None:
            connexion.close()


def get_profil_par_username(username, inclure_inactif=True, inclure_hash=False):
    init = initialiser_auth_database()
    if init.get("success") is not True:
        return {"success": False, "profil": None, "erreur": init.get("erreur")}

    username = normaliser_username(username)
    connexion = None
    try:
        connexion = _ouvrir_database()
        requete = "SELECT * FROM profils WHERE username = ?"
        params = [username]
        if not inclure_inactif:
            requete += " AND active = 1"
        ligne = connexion.execute(requete, params).fetchone()
        if ligne is None:
            return {"success": False, "profil": None, "erreur": "Profil introuvable."}
        profil = dict(ligne) if inclure_hash else _profil_public(ligne)
        return {"success": True, "profil": profil, "erreur": None}
    except Exception as erreur:
        return {"success": False, "profil": None, "erreur": str(erreur)}
    finally:
        if connexion is not None:
            connexion.close()


def lister_profils():
    init = initialiser_auth_database()
    if init.get("success") is not True:
        return {"success": False, "profils": [], "nombre": 0, "erreur": init.get("erreur")}
    connexion = None
    try:
        connexion = _ouvrir_database()
        lignes = connexion.execute(
            "SELECT * FROM profils ORDER BY CASE role WHEN 'ADMIN' THEN 0 ELSE 1 END, username ASC"
        ).fetchall()
        profils = [_profil_public(ligne) for ligne in lignes]
        return {"success": True, "profils": profils, "nombre": len(profils), "erreur": None}
    except Exception as erreur:
        return {"success": False, "profils": [], "nombre": 0, "erreur": str(erreur)}
    finally:
        if connexion is not None:
            connexion.close()


def modifier_profil(profil_id, nom=None, role=None, active=None):
    existant = get_profil_par_id(profil_id, inclure_inactif=True)
    if existant.get("success") is not True:
        return existant
    profil = existant["profil"]

    nouveau_nom = profil.get("nom") if nom is None else normaliser_nom(nom)
    nouveau_role = profil.get("role") if role is None else normaliser_role(role)
    nouvel_actif = profil.get("active") if active is None else est_actif(active)
    if nouveau_role is None:
        return {"success": False, "profil": None, "erreur": "Role invalide."}

    # Evite de desactiver ou retrograder le dernier ADMIN actif.
    if profil.get("role") == ROLE_ADMIN and profil.get("active") and (
        nouveau_role != ROLE_ADMIN or not nouvel_actif
    ):
        connexion = _ouvrir_database()
        try:
            ligne = connexion.execute(
                "SELECT COUNT(*) AS nombre FROM profils WHERE role = ? AND active = 1",
                (ROLE_ADMIN,),
            ).fetchone()
            if int(ligne["nombre"] if ligne else 0) <= 1:
                return {"success": False, "profil": None, "erreur": "Impossible de desactiver ou retrograder le dernier administrateur actif."}
        finally:
            connexion.close()

    connexion = None
    try:
        connexion = _ouvrir_database()
        connexion.execute(
            "UPDATE profils SET nom = ?, role = ?, active = ?, modifie_le = ? WHERE id = ?",
            (nouveau_nom, nouveau_role, 1 if nouvel_actif else 0, _maintenant(), int(profil_id)),
        )
        connexion.commit()
        return get_profil_par_id(profil_id, inclure_inactif=True)
    except Exception as erreur:
        if connexion is not None:
            connexion.rollback()
        return {"success": False, "profil": None, "erreur": str(erreur)}
    finally:
        if connexion is not None:
            connexion.close()


def changer_mot_de_passe(profil_id, nouveau_mot_de_passe):
    try:
        password_hash = hacher_mot_de_passe(nouveau_mot_de_passe)
    except ValueError as erreur:
        return {"success": False, "erreur": str(erreur)}

    connexion = None
    try:
        connexion = _ouvrir_database()
        curseur = connexion.execute(
            "UPDATE profils SET password_hash = ?, modifie_le = ? WHERE id = ?",
            (password_hash, _maintenant(), int(profil_id)),
        )
        connexion.commit()
        if curseur.rowcount != 1:
            return {"success": False, "erreur": "Profil introuvable."}
        return {"success": True, "erreur": None}
    except Exception as erreur:
        if connexion is not None:
            connexion.rollback()
        return {"success": False, "erreur": str(erreur)}
    finally:
        if connexion is not None:
            connexion.close()


# ============================================================
# AUTHENTIFICATION
# ============================================================

def authentifier(username, mot_de_passe):
    username = normaliser_username(username)
    # Message volontairement generique pour ne pas reveler l'existence d'un compte.
    message_echec = "Identifiant ou mot de passe incorrect."

    resultat = get_profil_par_username(username, inclure_inactif=True, inclure_hash=True)
    if resultat.get("success") is not True:
        # Calcul factice pour reduire la difference de temps compte existant/inexistant.
        faux_sel = bytes(SEL_TAILLE)
        hashlib.pbkdf2_hmac(
            PBKDF2_ALGORITHME,
            str(mot_de_passe or "").encode("utf-8"),
            faux_sel,
            PBKDF2_ITERATIONS,
            dklen=CLE_TAILLE,
        )
        return {"success": False, "profil": None, "erreur": message_echec}

    profil_prive = resultat["profil"]
    if not verifier_mot_de_passe(mot_de_passe, profil_prive.get("password_hash")):
        return {"success": False, "profil": None, "erreur": message_echec}

    if not bool(profil_prive.get("active")):
        return {"success": False, "profil": None, "erreur": "Ce profil est desactive."}

    connexion = None
    try:
        connexion = _ouvrir_database()
        connexion.execute(
            "UPDATE profils SET dernier_login = ? WHERE id = ?",
            (_maintenant(), int(profil_prive["id"])),
        )
        connexion.commit()
        ligne = connexion.execute("SELECT * FROM profils WHERE id = ?", (int(profil_prive["id"]),)).fetchone()
        return {"success": True, "profil": _profil_public(ligne), "erreur": None}
    except Exception as erreur:
        return {"success": False, "profil": None, "erreur": "Authentification impossible : " + str(erreur)}
    finally:
        if connexion is not None:
            connexion.close()


def profil_est_admin(profil):
    return isinstance(profil, dict) and str(profil.get("role") or "").upper() == ROLE_ADMIN


def generer_secret_session():
    """Utilitaire optionnel pour generer une cle SESSION_SECRET robuste."""
    return secrets.token_urlsafe(48)
