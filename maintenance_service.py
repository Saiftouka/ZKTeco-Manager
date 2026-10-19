from time import perf_counter

from app.services.zkteco_service import creer_client_zk, invalider_cache_pointages

MAINTENANCE_TIMEOUT = 120


def _convertir_pointages(pointages_bruts):
    if pointages_bruts is None:
        return []
    try:
        return list(pointages_bruts)
    except TypeError:
        return []


def supprimer_pointages_terminal(ip, port):
    """Supprime les pointages physiques avec controle avant/apres.

    Une seule connexion ZKTeco est utilisee pour:
    1. relire physiquement les pointages juste avant suppression;
    2. clear_attendance();
    3. relire physiquement le terminal juste apres suppression.

    Cette fonction ne modifie jamais SQLite.
    """
    connexion = None
    debut_total = perf_counter()
    temps_connexion = 0.0
    temps_lecture_avant = 0.0
    temps_suppression = 0.0
    temps_lecture_apres = 0.0

    def performance():
        return {
            "connexion_secondes": round(temps_connexion, 3),
            "lecture_avant_secondes": round(temps_lecture_avant, 3),
            "suppression_secondes": round(temps_suppression, 3),
            "lecture_apres_secondes": round(temps_lecture_apres, 3),
            "total_secondes": round(perf_counter() - debut_total, 3),
        }

    def echec(
        message,
        nombre_avant=None,
        nombre_supprimes=0,
        nombre_apres=None,
        suppression_executee=False,
        clear_result=None,
    ):
        return {
            "success": False,
            "ip": str(ip).strip(),
            "port": port,
            "nombre_avant": nombre_avant,
            "nombre_supprimes": nombre_supprimes,
            "nombre_apres": nombre_apres,
            "terminal_vide": False,
            "suppression_executee": suppression_executee,
            "clear_result": clear_result,
            "historique_modifie": False,
            "cache_pointages_invalide": False,
            "performance": performance(),
            "erreur": message,
        }

    try:
        ip = str(ip).strip()
        try:
            port = int(port)
        except (TypeError, ValueError):
            return echec("Le port de la pointeuse est invalide.")

        if not ip:
            return echec("L'adresse IP de la pointeuse est obligatoire.")

        # ====================================================
        # 1. CONNEXION UNIQUE
        # ====================================================
        phase = perf_counter()
        zk = creer_client_zk(ip=ip, port=port, timeout=MAINTENANCE_TIMEOUT)
        connexion = zk.connect()
        temps_connexion = perf_counter() - phase

        if connexion is None:
            return echec("Suppression annulee : impossible d'ouvrir la connexion de maintenance.")

        # ====================================================
        # 2. LECTURE PHYSIQUE JUSTE AVANT
        # ====================================================
        phase = perf_counter()
        pointages_avant = _convertir_pointages(connexion.get_attendance())
        temps_lecture_avant = perf_counter() - phase
        nombre_avant = len(pointages_avant)

        if nombre_avant == 0:
            cache_invalide = invalider_cache_pointages(ip=ip, port=port)
            result = {
                "success": True,
                "ip": ip,
                "port": port,
                "nombre_avant": 0,
                "nombre_supprimes": 0,
                "nombre_apres": 0,
                "terminal_vide": True,
                "suppression_executee": False,
                "clear_result": None,
                "historique_modifie": False,
                "cache_pointages_invalide": bool(cache_invalide),
                "source_avant": "terminal_get_attendance",
                "source_apres": "terminal_get_attendance",
                "performance": performance(),
                "message": "La pointeuse est deja vide. Aucune suppression n'a ete executee.",
                "erreur": None,
            }
            print(
                "[PERF NETTOYAGE SERVICE] "
                f"connexion={result['performance']['connexion_secondes']}s "
                f"avant={result['performance']['lecture_avant_secondes']}s "
                f"suppression=0.0s apres=0.0s "
                f"total={result['performance']['total_secondes']}s"
            )
            return result

        # ====================================================
        # 3. SUPPRESSION PHYSIQUE
        # ====================================================
        phase = perf_counter()
        resultat_clear = connexion.clear_attendance()
        temps_suppression = perf_counter() - phase

        # Toute copie RAM precedente est maintenant invalide.
        invalider_cache_pointages(ip=ip, port=port)

        # ====================================================
        # 4. RELECTURE PHYSIQUE SUR LA MEME CONNEXION
        # ====================================================
        phase = perf_counter()
        pointages_apres = _convertir_pointages(connexion.get_attendance())
        temps_lecture_apres = perf_counter() - phase
        nombre_apres = len(pointages_apres)
        nombre_supprimes = max(0, nombre_avant - nombre_apres)

        # On invalide encore le cache pour qu'aucun ecran ne recycle
        # un etat anterieur a la maintenance.
        invalider_cache_pointages(ip=ip, port=port)

        perf = performance()

        print(
            "[PERF NETTOYAGE SERVICE] "
            f"connexion={perf['connexion_secondes']}s "
            f"avant={perf['lecture_avant_secondes']}s "
            f"suppression={perf['suppression_secondes']}s "
            f"apres={perf['lecture_apres_secondes']}s "
            f"total={perf['total_secondes']}s"
        )

        if nombre_apres != 0:
            return {
                "success": False,
                "ip": ip,
                "port": port,
                "nombre_avant": nombre_avant,
                "nombre_supprimes": nombre_supprimes,
                "nombre_apres": nombre_apres,
                "terminal_vide": False,
                "suppression_executee": True,
                "clear_result": resultat_clear,
                "historique_modifie": False,
                "cache_pointages_invalide": True,
                "source_avant": "terminal_get_attendance",
                "source_apres": "terminal_get_attendance",
                "performance": perf,
                "erreur": (
                    "La suppression n'est pas complete. "
                    + str(nombre_apres)
                    + " pointage(s) restent dans la pointeuse."
                ),
            }

        return {
            "success": True,
            "ip": ip,
            "port": port,
            "nombre_avant": nombre_avant,
            "nombre_supprimes": nombre_supprimes,
            "nombre_apres": 0,
            "terminal_vide": True,
            "suppression_executee": True,
            "clear_result": resultat_clear,
            "historique_modifie": False,
            "cache_pointages_invalide": True,
            "source_avant": "terminal_get_attendance",
            "source_apres": "terminal_get_attendance",
            "performance": perf,
            "message": (
                "Les pointages presents dans la pointeuse ont ete supprimes. "
                "La relecture physique confirme que le terminal contient maintenant 0 pointage."
            ),
            "erreur": None,
        }

    except Exception as erreur:
        try:
            invalider_cache_pointages(ip=ip, port=port)
        except Exception:
            pass

        return {
            "success": False,
            "ip": str(ip).strip(),
            "port": port,
            "nombre_avant": None,
            "nombre_supprimes": 0,
            "nombre_apres": None,
            "terminal_vide": False,
            "suppression_executee": False,
            "historique_modifie": False,
            "cache_pointages_invalide": True,
            "performance": performance(),
            "erreur": "Impossible d'effectuer le nettoyage du terminal : " + str(erreur),
        }

    finally:
        if connexion is not None:
            try:
                connexion.disconnect()
            except Exception:
                pass
