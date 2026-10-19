import json
import sqlite3
from datetime import datetime
from pathlib import Path

DOSSIER_DATA = Path("data")
FICHIER_DATABASE = DOSSIER_DATA / "zkteco.db"
DOSSIER_CACHE_JSON = DOSSIER_DATA / "pointages"


def ouvrir_database():
    DOSSIER_DATA.mkdir(parents=True, exist_ok=True)
    connexion = sqlite3.connect(str(FICHIER_DATABASE), timeout=30)
    connexion.row_factory = sqlite3.Row
    connexion.execute("PRAGMA journal_mode=WAL")
    connexion.execute("PRAGMA synchronous=NORMAL")
    connexion.execute("PRAGMA foreign_keys=ON")
    return connexion


def _datetime_depuis_valeur(valeur):
    if isinstance(valeur, datetime):
        return valeur
    texte = str(valeur or "").strip()
    if not texte:
        return None
    if texte.endswith("Z"):
        texte = texte[:-1] + "+00:00"
    try:
        resultat = datetime.fromisoformat(texte)
        if resultat.tzinfo is not None:
            resultat = resultat.replace(tzinfo=None)
        return resultat
    except ValueError:
        pass
    for fmt in (
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
    ):
        try:
            return datetime.strptime(texte, fmt)
        except ValueError:
            continue
    return None


def normaliser_timestamp(valeur):
    dt = _datetime_depuis_valeur(valeur)
    return dt.isoformat(timespec="seconds") if dt is not None else str(valeur or "").strip()


def _migrer_timestamps_anciens(connexion):
    """Uniformise les anciens timestamps en YYYY-MM-DDTHH:MM:SS.

    Aucune ligne n'est supprimee. La migration ne fait que corriger la
    representation textuelle afin que les recherches par intervalle soient fiables.
    """
    lignes = connexion.execute(
        """
        SELECT id, timestamp
        FROM pointages
        WHERE timestamp NOT LIKE '____-__-__T__:__:__'
           OR length(timestamp) != 19
        """
    ).fetchall()

    mises_a_jour = []
    for ligne in lignes:
        normalise = normaliser_timestamp(ligne["timestamp"])
        if normalise and normalise != str(ligne["timestamp"] or ""):
            mises_a_jour.append((normalise, ligne["id"]))

    if mises_a_jour:
        # Une collision avec un enregistrement deja normalise ne doit jamais
        # provoquer une suppression implicite. On met donc a jour ligne par ligne
        # et on laisse intacte toute ligne qui entre en conflit avec l'unicite.
        for timestamp, identifiant in mises_a_jour:
            try:
                connexion.execute(
                    "UPDATE pointages SET timestamp = ? WHERE id = ?",
                    (timestamp, identifiant),
                )
            except sqlite3.IntegrityError:
                pass
        connexion.commit()


def initialiser_database():
    connexion = None
    try:
        connexion = ouvrir_database()
        connexion.execute(
            """
            CREATE TABLE IF NOT EXISTS pointages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pointeuse_id INTEGER NOT NULL,
                uid INTEGER,
                matricule TEXT NOT NULL DEFAULT '',
                nom TEXT NOT NULL DEFAULT '',
                badge TEXT NOT NULL DEFAULT '',
                timestamp TEXT NOT NULL,
                date TEXT NOT NULL DEFAULT '',
                heure TEXT NOT NULL DEFAULT '',
                status INTEGER,
                punch INTEGER,
                cree_le TEXT NOT NULL,
                UNIQUE (pointeuse_id, matricule, timestamp, status, punch)
            )
            """
        )
        connexion.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_pointages_pointeuse_timestamp
            ON pointages (pointeuse_id, timestamp)
            """
        )
        connexion.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_pointages_matricule
            ON pointages (matricule)
            """
        )
        connexion.execute(
            """
            CREATE TABLE IF NOT EXISTS synchronisations (
                pointeuse_id INTEGER PRIMARY KEY,
                derniere_synchronisation TEXT,
                nombre_total INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connexion.commit()
        _migrer_timestamps_anciens(connexion)
        return {"success": True, "database": str(FICHIER_DATABASE), "erreur": None}
    except Exception as erreur:
        return {"success": False, "database": str(FICHIER_DATABASE), "erreur": "Impossible d'initialiser la base SQLite : " + str(erreur)}
    finally:
        if connexion is not None:
            connexion.close()


def _entier_ou_none(valeur):
    if valeur is None or valeur == "":
        return None
    try:
        return int(valeur)
    except (TypeError, ValueError):
        return None


def ajouter_pointages(pointeuse_id, pointages):
    if not isinstance(pointages, list):
        return {"success": False, "nombre_recus": 0, "nombre_valides": 0, "nombre_ajoutes": 0, "erreur": "La liste des pointages est invalide."}

    init = initialiser_database()
    if init.get("success") is not True:
        return {"success": False, "nombre_recus": len(pointages), "nombre_valides": 0, "nombre_ajoutes": 0, "erreur": init.get("erreur")}

    connexion = None
    try:
        pid = int(pointeuse_id)
        connexion = ouvrir_database()
        maintenant = datetime.now().isoformat(timespec="seconds")
        donnees = []

        for pointage in pointages:
            if not isinstance(pointage, dict):
                continue
            timestamp = normaliser_timestamp(pointage.get("timestamp"))
            dt = _datetime_depuis_valeur(timestamp)
            if dt is None:
                continue
            timestamp = dt.isoformat(timespec="seconds")
            date_texte = dt.strftime("%d/%m/%Y")
            heure_texte = dt.strftime("%H:%M:%S")
            donnees.append(
                (
                    pid,
                    _entier_ou_none(pointage.get("uid")),
                    str(pointage.get("matricule", "") or "").strip(),
                    str(pointage.get("nom", "") or "").strip(),
                    str(pointage.get("badge", "") or "").strip(),
                    timestamp,
                    date_texte,
                    heure_texte,
                    _entier_ou_none(pointage.get("status")),
                    _entier_ou_none(pointage.get("punch")),
                    maintenant,
                )
            )

        avant = connexion.total_changes
        connexion.executemany(
            """
            INSERT OR IGNORE INTO pointages (
                pointeuse_id, uid, matricule, nom, badge,
                timestamp, date, heure, status, punch, cree_le
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            donnees,
        )
        connexion.commit()
        ajoutes = connexion.total_changes - avant
        return {"success": True, "nombre_recus": len(pointages), "nombre_valides": len(donnees), "nombre_ajoutes": ajoutes, "erreur": None}
    except Exception as erreur:
        if connexion is not None:
            connexion.rollback()
        return {"success": False, "nombre_recus": len(pointages), "nombre_valides": 0, "nombre_ajoutes": 0, "erreur": "Impossible d'enregistrer les pointages dans SQLite : " + str(erreur)}
    finally:
        if connexion is not None:
            connexion.close()


def compter_pointages(pointeuse_id):
    init = initialiser_database()
    if init.get("success") is not True:
        return {"success": False, "nombre": 0, "erreur": init.get("erreur")}
    connexion = None
    try:
        connexion = ouvrir_database()
        ligne = connexion.execute("SELECT COUNT(*) AS nombre FROM pointages WHERE pointeuse_id = ?", (int(pointeuse_id),)).fetchone()
        return {"success": True, "nombre": int(ligne["nombre"]) if ligne else 0, "erreur": None}
    except Exception as erreur:
        return {"success": False, "nombre": 0, "erreur": str(erreur)}
    finally:
        if connexion is not None:
            connexion.close()


def _ligne_pointage(ligne):
    resultat = dict(ligne)
    dt = _datetime_depuis_valeur(resultat.get("timestamp"))
    if dt is not None:
        resultat["timestamp"] = dt.isoformat(timespec="seconds")
        resultat["date"] = dt.strftime("%d/%m/%Y")
        resultat["heure"] = dt.strftime("%H:%M:%S")
    return resultat


def lire_pointages(pointeuse_id):
    init = initialiser_database()
    if init.get("success") is not True:
        return {"success": False, "pointages": [], "nombre": 0, "erreur": init.get("erreur")}
    connexion = None
    try:
        connexion = ouvrir_database()
        lignes = connexion.execute(
            """
            SELECT uid, matricule, nom, badge, timestamp, date, heure, status, punch
            FROM pointages
            WHERE pointeuse_id = ?
            ORDER BY timestamp ASC
            """,
            (int(pointeuse_id),),
        ).fetchall()
        pointages = [_ligne_pointage(ligne) for ligne in lignes]
        return {"success": True, "pointages": pointages, "nombre": len(pointages), "erreur": None}
    except Exception as erreur:
        return {"success": False, "pointages": [], "nombre": 0, "erreur": str(erreur)}
    finally:
        if connexion is not None:
            connexion.close()


def lire_pointages_intervalle(pointeuse_id, debut, fin):
    date_debut = _datetime_depuis_valeur(debut)
    date_fin = _datetime_depuis_valeur(fin)
    if date_debut is None or date_fin is None:
        return {"success": False, "pointages": [], "nombre": 0, "debut": None, "fin": None, "erreur": "Format de date/heure invalide."}
    if date_debut > date_fin:
        return {"success": False, "pointages": [], "nombre": 0, "debut": date_debut, "fin": date_fin, "erreur": "La date de debut doit etre anterieure ou egale a la date de fin."}

    init = initialiser_database()
    if init.get("success") is not True:
        return {"success": False, "pointages": [], "nombre": 0, "debut": date_debut, "fin": date_fin, "erreur": init.get("erreur")}

    borne_debut = date_debut.isoformat(timespec="seconds")
    borne_fin = date_fin.isoformat(timespec="seconds")
    connexion = None
    try:
        connexion = ouvrir_database()
        lignes = connexion.execute(
            """
            SELECT uid, matricule, nom, badge, timestamp, date, heure, status, punch
            FROM pointages
            WHERE pointeuse_id = ?
              AND timestamp >= ?
              AND timestamp <= ?
            ORDER BY timestamp ASC
            """,
            (int(pointeuse_id), borne_debut, borne_fin),
        ).fetchall()
        pointages = [_ligne_pointage(ligne) for ligne in lignes]
        return {
            "success": True,
            "pointages": pointages,
            "nombre": len(pointages),
            "debut": date_debut,
            "fin": date_fin,
            "borne_debut": borne_debut,
            "borne_fin": borne_fin,
            "erreur": None,
        }
    except Exception as erreur:
        return {"success": False, "pointages": [], "nombre": 0, "debut": date_debut, "fin": date_fin, "erreur": str(erreur)}
    finally:
        if connexion is not None:
            connexion.close()


def enregistrer_synchronisation(pointeuse_id, nombre_total):
    init = initialiser_database()
    if init.get("success") is not True:
        return {"success": False, "derniere_synchronisation": None, "erreur": init.get("erreur")}
    connexion = None
    try:
        connexion = ouvrir_database()
        maintenant = datetime.now().isoformat(timespec="seconds")
        connexion.execute(
            """
            INSERT INTO synchronisations (pointeuse_id, derniere_synchronisation, nombre_total)
            VALUES (?, ?, ?)
            ON CONFLICT(pointeuse_id) DO UPDATE SET
                derniere_synchronisation = excluded.derniere_synchronisation,
                nombre_total = excluded.nombre_total
            """,
            (int(pointeuse_id), maintenant, int(nombre_total)),
        )
        connexion.commit()
        return {"success": True, "derniere_synchronisation": maintenant, "erreur": None}
    except Exception as erreur:
        return {"success": False, "derniere_synchronisation": None, "erreur": str(erreur)}
    finally:
        if connexion is not None:
            connexion.close()


def lire_synchronisation(pointeuse_id):
    init = initialiser_database()
    if init.get("success") is not True:
        return {"success": False, "derniere_synchronisation": None, "nombre_total": 0, "erreur": init.get("erreur")}
    connexion = None
    try:
        connexion = ouvrir_database()
        ligne = connexion.execute(
            "SELECT derniere_synchronisation, nombre_total FROM synchronisations WHERE pointeuse_id = ?",
            (int(pointeuse_id),),
        ).fetchone()
        if ligne is None:
            return {"success": True, "derniere_synchronisation": None, "nombre_total": 0, "erreur": None}
        return {"success": True, "derniere_synchronisation": ligne["derniere_synchronisation"], "nombre_total": int(ligne["nombre_total"]), "erreur": None}
    except Exception as erreur:
        return {"success": False, "derniere_synchronisation": None, "nombre_total": 0, "erreur": str(erreur)}
    finally:
        if connexion is not None:
            connexion.close()


def migrer_cache_json(fichier):
    try:
        fichier = Path(fichier)
        if not fichier.stem.startswith("pointeuse_"):
            return {"success": False, "fichier": str(fichier), "erreur": "Nom de cache invalide."}
        pointeuse_id = int(fichier.stem[len("pointeuse_"):])
        with fichier.open("r", encoding="utf-8") as flux:
            donnees = json.load(flux)
        pointages = donnees.get("pointages", [])
        if not isinstance(pointages, list):
            pointages = []
        resultat = ajouter_pointages(pointeuse_id, pointages)
        if resultat.get("success") is not True:
            return {"success": False, "pointeuse_id": pointeuse_id, "fichier": str(fichier), "nombre_json": len(pointages), "nombre_ajoutes": 0, "erreur": resultat.get("erreur")}
        total = compter_pointages(pointeuse_id)
        resultat_sync = enregistrer_synchronisation(pointeuse_id, total.get("nombre", 0) if total.get("success") else 0)
        return {
            "success": True,
            "pointeuse_id": pointeuse_id,
            "fichier": str(fichier),
            "nombre_json": len(pointages),
            "nombre_ajoutes": resultat.get("nombre_ajoutes", 0),
            "derniere_synchronisation": donnees.get("derniere_synchronisation"),
            "synchronisation_sqlite": resultat_sync.get("success"),
            "erreur": None,
        }
    except Exception as erreur:
        return {"success": False, "fichier": str(fichier), "erreur": str(erreur)}


def migrer_tous_les_caches_json():
    init = initialiser_database()
    if init.get("success") is not True:
        return {"success": False, "resultats": [], "erreur": init.get("erreur")}
    if not DOSSIER_CACHE_JSON.exists():
        return {"success": True, "database": str(FICHIER_DATABASE), "resultats": [], "erreur": None}
    resultats = [migrer_cache_json(f) for f in sorted(DOSSIER_CACHE_JSON.glob("pointeuse_*.json"))]
    success = all(r.get("success") is True for r in resultats)
    return {"success": success, "database": str(FICHIER_DATABASE), "resultats": resultats, "erreur": None if success else "Au moins une migration a echoue."}
