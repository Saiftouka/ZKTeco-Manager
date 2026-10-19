from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

DOSSIER_PROJET = Path(__file__).resolve().parents[2]
DOSSIER_DATA = DOSSIER_PROJET / "data"
FICHIER_DATABASE = DOSSIER_DATA / "zkteco.db"
DOSSIER_BACKUPS = DOSSIER_DATA / "backups_sqlite"
NOMBRE_MAX_BACKUPS = 30


def verifier_base_source():
    if not FICHIER_DATABASE.exists():
        raise FileNotFoundError(f"Base SQLite introuvable : {FICHIER_DATABASE}")
    if not FICHIER_DATABASE.is_file():
        raise RuntimeError(f"Le chemin SQLite n'est pas un fichier : {FICHIER_DATABASE}")
    if FICHIER_DATABASE.stat().st_size <= 0:
        raise RuntimeError("La base SQLite principale est vide.")


def verifier_integrite_sqlite(fichier):
    connexion = None
    try:
        connexion = sqlite3.connect(str(fichier), timeout=30)
        resultat = connexion.execute("PRAGMA integrity_check;").fetchone()
        if resultat is None:
            return False, "PRAGMA integrity_check n'a retourne aucun resultat."
        message = str(resultat[0]).strip()
        if message.lower() == "ok":
            return True, "ok"
        return False, message
    except Exception as erreur:
        return False, str(erreur)
    finally:
        if connexion is not None:
            connexion.close()


def lister_backups_sqlite():
    DOSSIER_BACKUPS.mkdir(parents=True, exist_ok=True)
    fichiers = list(DOSSIER_BACKUPS.glob("zkteco_*.db"))
    fichiers.sort(key=lambda fichier: fichier.stat().st_mtime, reverse=True)
    backups = list()
    for fichier in fichiers:
        try:
            stat = fichier.stat()
            backups.append(dict(
                nom=fichier.name,
                chemin=str(fichier),
                taille=stat.st_size,
                date_modification=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            ))
        except OSError:
            continue
    return dict(success=True, nombre=len(backups), backups=backups, erreur=None)


def nettoyer_anciens_backups(maximum=NOMBRE_MAX_BACKUPS):
    if maximum < 1:
        raise ValueError("Le nombre maximum de backups doit etre superieur a zero.")
    DOSSIER_BACKUPS.mkdir(parents=True, exist_ok=True)
    fichiers = list(DOSSIER_BACKUPS.glob("zkteco_*.db"))
    fichiers.sort(key=lambda fichier: fichier.stat().st_mtime, reverse=True)
    fichiers_a_supprimer = fichiers[maximum:]
    fichiers_supprimes = list()
    for fichier in fichiers_a_supprimer:
        try:
            fichier.unlink()
            fichiers_supprimes.append(fichier.name)
        except OSError as erreur:
            print(f"[SQLITE BACKUP] Impossible de supprimer l'ancien backup {fichier.name} : {erreur}")
    return fichiers_supprimes


def creer_backup_sqlite(nettoyer=True):
    connexion_source = None
    connexion_destination = None
    fichier_temporaire = None
    maintenant = datetime.now()
    try:
        verifier_base_source()
        DOSSIER_BACKUPS.mkdir(parents=True, exist_ok=True)

        horodatage = maintenant.strftime("%Y-%m-%d_%H%M%S_%f")
        nom_final = f"zkteco_{horodatage}.db"
        fichier_final = DOSSIER_BACKUPS / nom_final
        fichier_temporaire = DOSSIER_BACKUPS / f"{nom_final}.tmp"

        if fichier_temporaire.exists():
            fichier_temporaire.unlink()

        taille_source = FICHIER_DATABASE.stat().st_size
        print()
        print("[SQLITE BACKUP] Source :", FICHIER_DATABASE)
        print("[SQLITE BACKUP] Taille source :", taille_source, "octets")
        print("[SQLITE BACKUP] Destination temporaire :", fichier_temporaire)
        print()
        print("[SQLITE BACKUP] Sauvegarde en cours...")

        connexion_source = sqlite3.connect(str(FICHIER_DATABASE), timeout=30)
        connexion_destination = sqlite3.connect(str(fichier_temporaire), timeout=30)
        connexion_source.backup(connexion_destination, pages=1000, sleep=0.05)
        connexion_destination.commit()

        connexion_destination.close()
        connexion_destination = None
        connexion_source.close()
        connexion_source = None

        if not fichier_temporaire.exists():
            raise RuntimeError("Le fichier temporaire n'a pas ete cree.")

        taille_backup = fichier_temporaire.stat().st_size
        if taille_backup <= 0:
            raise RuntimeError("Le backup SQLite genere est vide.")

        print("[SQLITE BACKUP] Taille backup :", taille_backup, "octets")
        print()
        print("[SQLITE BACKUP] Verification de l'integrite...")

        valide, message = verifier_integrite_sqlite(fichier_temporaire)
        if not valide:
            raise RuntimeError("Le controle d'integrite du backup a echoue : " + message)

        print("[SQLITE BACKUP] Integrite : OK")
        fichier_temporaire.replace(fichier_final)
        print()
        print("[SQLITE BACKUP] Sauvegarde validee.")
        print("[SQLITE BACKUP] Fichier :", fichier_final)

        fichiers_supprimes = list()
        if nettoyer:
            fichiers_supprimes = nettoyer_anciens_backups(NOMBRE_MAX_BACKUPS)
            if fichiers_supprimes:
                print("[SQLITE BACKUP] Anciens backups supprimes :", len(fichiers_supprimes))

        return dict(
            success=True,
            fichier=str(fichier_final),
            nom_fichier=fichier_final.name,
            taille=fichier_final.stat().st_size,
            date=maintenant.isoformat(timespec="seconds"),
            integrite="ok",
            anciens_backups_supprimes=fichiers_supprimes,
            erreur=None,
        )
    except Exception as erreur:
        try:
            if connexion_destination is not None:
                connexion_destination.close()
        except Exception:
            pass
        try:
            if connexion_source is not None:
                connexion_source.close()
        except Exception:
            pass
        try:
            if fichier_temporaire is not None and fichier_temporaire.exists():
                fichier_temporaire.unlink()
        except OSError:
            pass
        return dict(
            success=False,
            fichier=None,
            nom_fichier=None,
            taille=0,
            date=datetime.now().isoformat(timespec="seconds"),
            integrite=None,
            anciens_backups_supprimes=list(),
            erreur=str(erreur),
        )


if __name__ == "__main__":
    print()
    print("==============================================")
    print(" ZKTeco Manager - Backup SQLite")
    print("==============================================")
    print()
    print("[INFO] Base source :", FICHIER_DATABASE)
    print("[INFO] Dossier backups :", DOSSIER_BACKUPS)
    print()

    resultat = creer_backup_sqlite(nettoyer=False)

    print()
    print("----------------------------------------------")
    if resultat.get("success"):
        print("[OK] Sauvegarde creee avec succes.")
        print("[OK] Fichier :", resultat.get("fichier"))
        print("[OK] Taille :", resultat.get("taille"), "octets")
        print("[OK] Integrite :", resultat.get("integrite"))
    else:
        print("[ERREUR] Sauvegarde impossible.")
        print("[ERREUR]", resultat.get("erreur"))
    print("----------------------------------------------")
    print()
