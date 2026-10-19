import asyncio
import json
import os
import tempfile
from collections import Counter
from datetime import datetime
from io import BytesIO
from pathlib import Path
from time import perf_counter
from urllib.parse import urlparse
from fastapi import Form, HTTPException
from datetime import datetime

from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.services.auth_service import (
    assurer_admin_initial,
    authentifier,
    get_profil_par_id,
    lister_profils,
    creer_profil,
    modifier_profil,
    changer_mot_de_passe,
)
from app.services.excel_service import lire_fichier_employes_excel
from app.services.import_service import creer_session_import, lire_session_import, supprimer_session_import
from app.services.pointeuse_service import ajouter_pointeuse, get_pointeuse_par_id, get_pointeuses, modifier_pointeuse, supprimer_pointeuse, tester_connexion_pointeuse
from app.services.zkteco_service import (
    get_user_pointeuse, get_users_pointeuse, get_pointages_pointeuse,
    importer_employes, modifier_employe_pointeuse, preparer_import_employes,
    get_proprietes_pointeuse, synchroniser_heure_pointeuse, redemarrer_pointeuse,
    retirer_privileges_admin_pointeuse,
)
from app.services.pointage_cache_service import (
    assurer_pointages_intervalle,
    lire_cache_pointages,
    synchroniser_pointages,
    synchroniser_pointages_automatique,
)
from app.services.pointage_service import creer_excel_pointages
from app.services.correction_pointage_service import appliquer_corrections_pointages, enregistrer_correction_pointage, annuler_correction_pointage
from app.services.backup_service import creer_backup_pointeuse, lister_backups_pointeuse
from app.services.maintenance_service import supprimer_pointages_terminal
from app.services.restauration_service import verifier_backup_restauration, restaurer_backup_sqlite

app = FastAPI(title="ZKTeco Manager", description="Application de gestion des pointeuses ZKTeco", version="2.0.0")
SESSION_SECRET = os.environ.get("ZKTECO_SESSION_SECRET") or "CHANGE-ME-BEFORE-PRODUCTION-ZKTECO-MANAGER-2026"
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, session_cookie="zkteco_session", max_age=8 * 60 * 60, same_site="lax", https_only=False)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

PUBLIC_PATHS = {"/login"}

# ============================================================
# SYNCHRONISATION AUTOMATIQUE DES POINTAGES
# ============================================================
SYNC_AUTO_ACTIVE = True
SYNC_AUTO_INTERVALLE = 60
SYNC_AUTO_DELAI_DEMARRAGE = 10
_tache_sync_auto = None



def est_actif(valeur):
    if valeur is True: return True
    if valeur is False or valeur is None: return False
    if isinstance(valeur, int): return valeur == 1
    if isinstance(valeur, str): return valeur.strip().lower() in ("true", "1", "oui", "yes", "active", "actif", "on")
    return bool(valeur)


def normaliser_timestamp_comparaison(valeur):
    if valeur is None: return ""
    if hasattr(valeur, "isoformat"):
        try: return valeur.isoformat(timespec="seconds")
        except Exception: pass
    return str(valeur).strip()


def normaliser_entier_comparaison(valeur):
    if valeur is None: return None
    try: return int(valeur)
    except (TypeError, ValueError): return str(valeur).strip()


def convertir_datetime_rapport(valeur):
    if isinstance(valeur, datetime): return valeur
    texte = str(valeur or "").strip()
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S"):
        try: return datetime.strptime(texte, fmt)
        except ValueError: pass
    return datetime.fromisoformat(texte)


def cle_pointage_securite(pointage):
    return (str(pointage.get("matricule", "") or "").strip(), normaliser_timestamp_comparaison(pointage.get("timestamp")), normaliser_entier_comparaison(pointage.get("status")), normaliser_entier_comparaison(pointage.get("punch")))


def lire_pointages_users_dat(dossier_backup):
    if not dossier_backup: return {"success": False, "pointages": [], "nombre": 0, "erreur": "Le dossier du backup est introuvable."}
    chemin = Path(dossier_backup) / "Users.dat"
    if not chemin.is_file(): return {"success": False, "pointages": [], "nombre": 0, "erreur": "Users.dat est introuvable dans le dernier backup."}
    try:
        with chemin.open("r", encoding="utf-8") as fichier: contenu = json.load(fichier)
    except Exception as erreur:
        return {"success": False, "pointages": [], "nombre": 0, "erreur": "Impossible de lire Users.dat : " + str(erreur)}
    if not isinstance(contenu, dict) or contenu.get("type") != "pointages_terminal": return {"success": False, "pointages": [], "nombre": 0, "erreur": "Le format de Users.dat est invalide."}
    pointages = contenu.get("data")
    if not isinstance(pointages, list): return {"success": False, "pointages": [], "nombre": 0, "erreur": "Les donnees de Users.dat sont invalides."}
    return {"success": True, "pointages": pointages, "nombre": len(pointages), "erreur": None}


def _safe_next(value):
    value = str(value or "/dashboard").strip()
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc or not value.startswith("/") or value.startswith("//"):
        return "/dashboard"
    if value.startswith("/login"):
        return "/dashboard"
    return value


def _profil_session(request):
    profil_id = request.session.get("profil_id")
    if profil_id is None: return None
    resultat = get_profil_par_id(profil_id, inclure_inactif=False)
    if not isinstance(resultat, dict) or resultat.get("success") is not True:
        request.session.clear(); return None
    return resultat.get("profil")


def _profil_obligatoire(request):
    profil = _profil_session(request)
    if profil is None:
        return None, RedirectResponse(url="/login?next=" + request.url.path, status_code=303)
    return profil, None


def _admin_obligatoire(request):
    profil = _profil_session(request)
    if profil is None:
        return None, RedirectResponse(url='/login', status_code=303)
    if str(profil.get('role', '')).upper() != 'ADMIN':
        return None, JSONResponse(
            status_code=403,
            content={'success': False, 'erreur': 'Acces reserve aux administrateurs.'},
        )
    return profil, None


def _contexte(request, profil, **extra):
    contexte = {"profil_connecte": profil, "is_admin": bool(profil and profil.get("is_admin"))}
    contexte.update(extra)
    return contexte


def _get_pointeuses_profil(profil):


    print(
        "[DEBUG PROFIL]",
        profil
    )

    if not profil:
        return {
            "success": False,
            "pointeuses": [],
            "nombre": 0,
            "erreur": "Profil non authentifie.",
        }

    print(
        "[DEBUG PROFIL ID]",
        profil.get("id")
    )

    resultat = get_pointeuses(
        profil_id=profil.get("id")
    )

    print(
        "[DEBUG NOMBRE]",
        len(
            resultat.get(
                "pointeuses",
                []
            )
        )
    )

    return resultat
def _pointeuse_api(request, pointeuse_id, exiger_active=True):
    profil = _profil_session(request)
    if profil is None:
        return None, JSONResponse(status_code=401, content={"success": False, "erreur": "Authentification requise."})
    resultat = get_pointeuse_par_id(pointeuse_id, profil_id=profil.get("id"))
    if not isinstance(resultat, dict) or resultat.get("success") is not True:
        statut = 403 if isinstance(resultat, dict) and resultat.get("acces_refuse") else 404
        return None, JSONResponse(status_code=statut, content={"success": False, "erreur": resultat.get("erreur") if isinstance(resultat, dict) else "Pointeuse introuvable."})
    pointeuse = resultat.get("pointeuse")
    if not isinstance(pointeuse, dict): return None, JSONResponse(status_code=404, content={"success": False, "erreur": "Pointeuse introuvable."})
    if exiger_active and not est_actif(pointeuse.get("active")): return None, JSONResponse(status_code=400, content={"success": False, "erreur": "La pointeuse est inactive."})
    return pointeuse, None


# ============================================================
# SYNCHRONISATION AUTOMATIQUE TERMINAL -> SQLITE
# Lecture uniquement. Aucune suppression automatique.
# ============================================================
async def executer_cycle_synchronisation_automatique():
    debut_cycle = perf_counter()
    try:
        resultat_pointeuses = get_pointeuses(toutes=True)
        if not isinstance(resultat_pointeuses, dict) or resultat_pointeuses.get("success") is not True:
            erreur = resultat_pointeuses.get("erreur") if isinstance(resultat_pointeuses, dict) else "reponse invalide"
            print(f"[SYNC AUTO] Lecture des pointeuses impossible : {erreur}")
            return

        pointeuses = resultat_pointeuses.get("pointeuses", [])
        if not isinstance(pointeuses, list):
            pointeuses = []

        actives = [p for p in pointeuses if isinstance(p, dict) and est_actif(p.get("active"))]
        if not actives:
            return

        print(f"[SYNC AUTO] Debut cycle - {len(actives)} pointeuse(s) active(s)")

        # Sequentiel volontairement pour ne pas saturer le reseau et les terminaux.
        for pointeuse in actives:
            pointeuse_id = pointeuse.get("id")
            nom = str(pointeuse.get("nom", "") or "")
            ip = str(pointeuse.get("ip", "") or "").strip()
            port = pointeuse.get("port")
            profil_id = pointeuse.get("profil_id")

            if pointeuse_id is None or not ip:
                continue

            try:
                resultat = await asyncio.to_thread(
                    synchroniser_pointages_automatique,
                    pointeuse_id,
                    ip,
                    port,
                )

                if not isinstance(resultat, dict):
                    print(f"[SYNC AUTO] {nom} : reponse invalide")
                    continue

                if resultat.get("success") is not True:
                    print(f"[SYNC AUTO] {nom} : indisponible - {resultat.get('erreur') or ''}")
                    continue

                if resultat.get("ignoree") is True:
                    continue

                nouveaux = int(resultat.get("nombre_nouveaux", 0) or 0)
                total = int(resultat.get("nombre_total", 0) or 0)

                if nouveaux > 0:
                    print(
                        f"[SYNC AUTO] {nom} | profil={profil_id} | "
                        f"+{nouveaux} nouveau(x) | total={total}"
                    )
            except Exception as erreur:
                print(f"[SYNC AUTO] {nom} : erreur - {erreur}")

        print(f"[SYNC AUTO] Fin cycle en {round(perf_counter() - debut_cycle, 3)} s")

    except asyncio.CancelledError:
        raise
    except Exception as erreur:
        print(f"[SYNC AUTO] Erreur generale : {erreur}")


async def boucle_synchronisation_automatique():
    try:
        await asyncio.sleep(SYNC_AUTO_DELAI_DEMARRAGE)
        print(f"[SYNC AUTO] Service demarre. Intervalle : {SYNC_AUTO_INTERVALLE} seconde(s).")

        while True:
            debut_cycle = perf_counter()
            await executer_cycle_synchronisation_automatique()
            duree_cycle = perf_counter() - debut_cycle
            await asyncio.sleep(max(5, SYNC_AUTO_INTERVALLE - duree_cycle))

    except asyncio.CancelledError:
        print("[SYNC AUTO] Service arrete.")
        raise


@app.on_event("startup")
async def demarrer_services_application():
    global _tache_sync_auto
    if not SYNC_AUTO_ACTIVE:
        print("[SYNC AUTO] Service desactive.")
        return
    if _tache_sync_auto is None or _tache_sync_auto.done():
        _tache_sync_auto = asyncio.create_task(boucle_synchronisation_automatique())


@app.on_event("shutdown")
async def arreter_services_application():
    global _tache_sync_auto
    if _tache_sync_auto is None:
        return
    if not _tache_sync_auto.done():
        _tache_sync_auto.cancel()
        try:
            await _tache_sync_auto
        except asyncio.CancelledError:
            pass
    _tache_sync_auto = None


@app.get(
    "/login",
    response_class=HTMLResponse,
    name="login",
)
def login_page(
    request: Request,
    next: str = Query(default="/dashboard"),
):
    if _profil_session(request) is not None:
        return RedirectResponse(
            url=_safe_next(next),
            status_code=303,
        )

    init = assurer_admin_initial()

    message = None
    erreur = None

    if init.get("success") is not True:
        message = (
            "Premier démarrage : configurez "
            "ZKTECO_ADMIN_PASSWORD puis redémarrez "
            "l'application."
        )

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "erreur": erreur,
            "message": message,
            "username": "",
            "next_url": _safe_next(next),
        },
    )


@app.post(
    "/login",
    response_class=HTMLResponse,
    name="login_post",
)
def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/dashboard"),
):
    resultat = authentifier(
        username,
        password,
    )

    if (
        not isinstance(resultat, dict)
        or resultat.get("success") is not True
    ):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "erreur": (
                    resultat.get("erreur")
                    if isinstance(resultat, dict)
                    else "Connexion impossible."
                ),
                "message": None,
                "username": username,
                "next_url": _safe_next(next),
            },
            status_code=401,
        )

    profil = resultat.get("profil")

    if not isinstance(profil, dict):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "erreur": "Profil utilisateur invalide.",
                "message": None,
                "username": username,
                "next_url": _safe_next(next),
            },
            status_code=500,
        )

    request.session.clear()

    request.session["profil_id"] = int(
        profil["id"]
    )

    return RedirectResponse(
        url=_safe_next(next),
        status_code=303,
    )


@app.post(
    "/logout",
    name="logout",
)
def logout(
    request: Request,
):
    request.session.clear()

    return RedirectResponse(
        url="/login",
        status_code=303,
    )


@app.get(
    "/reconnexion",
    name="reconnexion",
)
def reconnexion(
    request: Request,
):
    """
    Ferme uniquement la session du navigateur
    qui appelle cette route.

    Utilisé notamment par le fichier BAT pour
    toujours afficher l'écran d'authentification.
    """

    request.session.clear()

    return RedirectResponse(
        url="/login",
        status_code=303,
    )

@app.get("/", response_class=HTMLResponse, name="accueil")
def accueil(request: Request):
    profil, redirect = _profil_obligatoire(request)
    if redirect: return redirect
    return templates.TemplateResponse(request=request, name="accueil.html", context=_contexte(request, profil, active_page="accueil"))


@app.get("/dashboard", response_class=HTMLResponse, name="dashboard")
def dashboard(request: Request):
    profil, redirect = _profil_obligatoire(request)
    if redirect: return redirect
    resultat = _get_pointeuses_profil(profil); liste = resultat.get("pointeuses", []) if isinstance(resultat, dict) else []
    if not isinstance(liste, list): liste = []
    data = [{"id": p.get("id"), "nom": p.get("nom"), "ip": p.get("ip"), "port": p.get("port"), "active": est_actif(p.get("active")), "connectee": None, "ping": False, "firmware": None, "heure": None, "mac": None, "erreur": None} for p in liste]
    return templates.TemplateResponse(request=request, name="dashboard.html", context=_contexte(request, profil, active_page="dashboard", pointeuses=data))


@app.get("/api/pointeuses/{pointeuse_id}/etat", name="api_etat_pointeuse")
def api_etat_pointeuse(request: Request, pointeuse_id: int):
    pointeuse, erreur = _pointeuse_api(request, pointeuse_id, False)
    if erreur is not None: return erreur
    if not est_actif(pointeuse.get("active")): return {"success": True, "pointeuse_id": pointeuse_id, "active": False, "connectee": False, "ping": False, "connexion_zkteco": False, "firmware": None, "heure": None, "mac": None, "erreur": None}
    try:
        r = tester_connexion_pointeuse(ip=pointeuse.get("ip"), port=pointeuse.get("port")); ok = isinstance(r, dict) and r.get("success") is True; heure = r.get("heure") if isinstance(r, dict) else None; mac = r.get("mac") if isinstance(r, dict) else None
        return {"success": True, "pointeuse_id": pointeuse_id, "active": True, "connectee": ok, "ping": r.get("ping") is True if isinstance(r, dict) else False, "connexion_zkteco": ok, "firmware": r.get("firmware") if ok else None, "heure": str(heure) if ok and heure is not None else None, "mac": str(mac).strip() if ok and mac else None, "erreur": None if ok else (r.get("erreur") if isinstance(r, dict) else "Reponse invalide.")}
    except Exception as exc: return JSONResponse(status_code=500, content={"success": False, "erreur": str(exc)})


@app.get("/api/pointeuses/{pointeuse_id}/proprietes", name="api_proprietes_pointeuse")
def api_proprietes_pointeuse(request: Request, pointeuse_id: int):
    p,e=_pointeuse_api(request,pointeuse_id)
    if e:return e
    r=get_proprietes_pointeuse(ip=p.get("ip"),port=p.get("port"));
    if r.get("success") is not True:return JSONResponse(status_code=400,content=r)
    r.update({"pointeuse_id":pointeuse_id,"nom":p.get("nom")});return r


@app.post("/api/pointeuses/{pointeuse_id}/synchroniser-heure", name="api_synchroniser_heure_pointeuse")
def api_synchroniser_heure_pointeuse(request: Request,pointeuse_id:int):
    p,e=_pointeuse_api(request,pointeuse_id)
    if e:return e
    r=synchroniser_heure_pointeuse(ip=p.get("ip"),port=p.get("port"));return r if r.get("success") is True else JSONResponse(status_code=400,content=r)


@app.post("/api/pointeuses/{pointeuse_id}/redemarrer", name="api_redemarrer_pointeuse")
def api_redemarrer_pointeuse(request: Request,pointeuse_id:int):
    p,e=_pointeuse_api(request,pointeuse_id)
    if e:return e
    r=redemarrer_pointeuse(ip=p.get("ip"),port=p.get("port"));return r if r.get("success") is True else JSONResponse(status_code=400,content=r)


@app.post("/api/pointeuses/{pointeuse_id}/retirer-admin", name="api_retirer_admin_pointeuse")
def api_retirer_admin_pointeuse(request: Request,pointeuse_id:int):
    p,e=_pointeuse_api(request,pointeuse_id)
    if e:return e
    r=retirer_privileges_admin_pointeuse(ip=p.get("ip"),port=p.get("port"));return r if r.get("success") is True else JSONResponse(status_code=400,content=r)


@app.get("/api/pointeuses/{pointeuse_id}/nombre-pointages", name="api_nombre_pointages_pointeuse")
def api_nombre_pointages_pointeuse(request: Request,pointeuse_id:int):
    p,e=_pointeuse_api(request,pointeuse_id)
    if e:return e
    r=get_pointages_pointeuse(ip=p.get("ip"),port=p.get("port"),forcer_actualisation=True)
    if r.get("success") is not True:return JSONResponse(status_code=400,content=r)
    pts=r.get("pointages",[]);pts=pts if isinstance(pts,list) else []
    return {"success":True,"pointeuse_id":pointeuse_id,"nom":p.get("nom"),"ip":p.get("ip"),"port":p.get("port"),"nombre":len(pts),"source":"terminal_get_attendance","performance":r.get("performance"),"erreur":None}


@app.post("/api/pointeuses/{pointeuse_id}/synchroniser-pointages",name="api_synchroniser_pointages")
def api_synchroniser_pointages(request: Request,pointeuse_id:int):
    p,e=_pointeuse_api(request,pointeuse_id)
    if e:return e
    try:r=synchroniser_pointages(pointeuse_id=pointeuse_id,ip=p.get("ip"),port=p.get("port"))
    except Exception as exc:return JSONResponse(status_code=500,content={"success":False,"pointeuse_id":pointeuse_id,"erreur":"Erreur interne pendant la synchronisation : "+str(exc)})
    if not isinstance(r,dict):return JSONResponse(status_code=500,content={"success":False,"erreur":"Le service de synchronisation a retourne une reponse invalide."})
    return r if r.get("success") is True else JSONResponse(status_code=400,content=r)


@app.get("/pointages", response_class=HTMLResponse, name="pointages")
def pointages(request: Request):
    profil,redirect=_profil_obligatoire(request)
    if redirect:return redirect
    r=_get_pointeuses_profil(profil);liste=r.get("pointeuses",[]) if isinstance(r,dict) else [];liste=liste if isinstance(liste,list) else []
    sortie=[{"id":p.get("id"),"nom":p.get("nom"),"ip":p.get("ip"),"port":p.get("port"),"active":est_actif(p.get("active")),"nombre_terminal":None} for p in liste]
    return templates.TemplateResponse(request=request,name="pointages.html",context=_contexte(request,profil,active_page="pointages",resultat_pointeuses=r,pointeuses=sortie))
@app.post(
    "/pointages/apercu",
    response_class=HTMLResponse
)
def apercu_pointages(
    request: Request,
    pointeuse_id: int = Form(...),
    debut: str = Form(...),
    fin: str = Form(...)
):
    profil, redirect = _profil_obligatoire(request)

    if redirect:
        return redirect

    r = _get_pointeuses_profil(profil)

    liste = (
        r.get("pointeuses", [])
        if isinstance(r, dict)
        else []
    )

    pointeuse = next(
        (
            p
            for p in liste
            if int(p.get("id", 0)) == pointeuse_id
        ),
        None
    )

    if pointeuse is None:
        raise HTTPException(
            status_code=404,
            detail="Pointeuse introuvable."
        )

    statistiques = {
        "nombre_pointages": 0,
        "nombre_employes": 0,
        "premier": "-",
        "dernier": "-"
        
    }
       
    return templates.TemplateResponse(
    request=request,
    name="rapport_pointages.html",
    context={
        "request": request,

        "pointeuse": {
            "id": pointeuse.get("id"),
            "nom": pointeuse.get("nom"),
            "ip": pointeuse.get("ip"),
            "port": pointeuse.get("port")
        },

        "pointages": [],

        "statistiques": {
            "nombre_pointages": 0,
            "nombre_employes": 0,
            "premier": "-",
            "dernier": "-"
        },

        "debut": debut,
        "fin": fin,

        "debut_affichage": debut,
        "fin_affichage": fin,

        "genere_le": datetime.now().strftime(
            "%d/%m/%Y %H:%M:%S"
        )
    }
)

@app.get("/pointages/rapport",response_class=HTMLResponse,name="rapport_pointages")
def rapport_pointages(request: Request,pointeuse_id:int=Query(...),debut:str=Query(...),fin:str=Query(...)):
    profil,redirect=_profil_obligatoire(request)
    if redirect:return redirect
    debut_total=perf_counter();pointeuse,erreur=_pointeuse_api(request,pointeuse_id)
    if erreur:return erreur
    debut,fin=str(debut or "").strip(),str(fin or "").strip()
    if not debut or not fin:return JSONResponse(status_code=400,content={"success":False,"erreur":"La periode est obligatoire."})
    try:debut_dt,fin_dt=convertir_datetime_rapport(debut),convertir_datetime_rapport(fin)
    except Exception as exc:return JSONResponse(status_code=400,content={"success":False,"erreur":"Format de periode invalide : "+str(exc)})
    if debut_dt>fin_dt:return JSONResponse(status_code=400,content={"success":False,"erreur":"La date de debut doit etre anterieure ou egale a la date de fin."})
    mesure=perf_counter();resultat=assurer_pointages_intervalle(pointeuse_id=pointeuse_id,ip=pointeuse.get("ip"),port=pointeuse.get("port"),debut=debut_dt,fin=fin_dt);temps_pointages=perf_counter()-mesure
    if not isinstance(resultat,dict) or resultat.get("success") is not True:return JSONResponse(status_code=400,content=resultat if isinstance(resultat,dict) else {"success":False,"erreur":"Reponse SQLite invalide."})
    bruts=resultat.get("pointages",[]);bruts=bruts if isinstance(bruts,list) else []
    mesure=perf_counter();noms={};users=get_users_pointeuse(ip=pointeuse.get("ip"),port=pointeuse.get("port"));temps_utilisateurs=perf_counter()-mesure
    if isinstance(users,dict) and users.get("success") is True:
        utilisateurs=users.get("utilisateurs",[]);utilisateurs=utilisateurs if isinstance(utilisateurs,list) else []
        for utilisateur in utilisateurs:
            if isinstance(utilisateur,dict):
                matricule=str(utilisateur.get("matricule") or "").strip()
                if matricule:noms[matricule]=str(utilisateur.get("nom") or "").strip()
    mesure=perf_counter();originaux=[]
    for pointage in bruts:
        if not isinstance(pointage,dict):continue
        ligne=dict(pointage);timestamp=ligne.get("timestamp")
        if not isinstance(timestamp,datetime):
            try:timestamp=convertir_datetime_rapport(timestamp or (str(ligne.get("date") or "")+" "+str(ligne.get("heure") or "")))
            except Exception:continue
        ligne["timestamp"]=timestamp;matricule=str(ligne.get("matricule") or "").strip();ligne["matricule"]=matricule;ligne["nom"]=noms.get(matricule,ligne.get("nom") or "");originaux.append(ligne)
    temps_preparation=perf_counter()-mesure
    mesure=perf_counter();corrections=appliquer_corrections_pointages(pointeuse_id,originaux);temps_corrections=perf_counter()-mesure
    if not isinstance(corrections,dict) or corrections.get("success") is not True:return JSONResponse(status_code=500,content={"success":False,"erreur":"Impossible d'appliquer les corrections : "+str(corrections.get("erreur") if isinstance(corrections,dict) else "reponse invalide")})
    enrichis=corrections.get("pointages",[]);enrichis=enrichis if isinstance(enrichis,list) else []
    for ligne in enrichis:
        timestamp=ligne.get("timestamp");original=ligne.get("timestamp_original");ligne["date"]=timestamp.strftime("%d/%m/%Y") if isinstance(timestamp,datetime) else "";ligne["heure"]=timestamp.strftime("%H:%M:%S") if isinstance(timestamp,datetime) else "";ligne["timestamp_original_iso"]=original.isoformat(timespec="seconds") if isinstance(original,datetime) else normaliser_timestamp_comparaison(original)
        try:ligne["heure_originale"]=datetime.fromisoformat(ligne["timestamp_original_iso"]).strftime("%H:%M:%S")
        except Exception:ligne["heure_originale"]=""
    enrichis.sort(key=lambda p:p.get("timestamp") if isinstance(p.get("timestamp"),datetime) else datetime.max)
    timestamps=[p.get("timestamp") for p in enrichis if isinstance(p.get("timestamp"),datetime)];matricules={str(p.get("matricule") or "").strip() for p in enrichis if str(p.get("matricule") or "").strip()}
    statistiques={"nombre_pointages":len(enrichis),"nombre_employes":len(matricules),"premier":min(timestamps).strftime("%d/%m/%Y %H:%M:%S") if timestamps else "—","dernier":max(timestamps).strftime("%d/%m/%Y %H:%M:%S") if timestamps else "—","nombre_corrections":int(corrections.get("nombre_corrections",0) or 0)}
    performance_rapport={"sqlite_secondes":round(temps_pointages,3),"lecture_utilisateurs_secondes":round(temps_utilisateurs,3),"corrections_secondes":round(temps_corrections,3),"preparation_secondes":round(temps_preparation,3),"total_secondes":round(perf_counter()-debut_total,3)}
    return templates.TemplateResponse(request=request,name="rapport_pointages.html",context=_contexte(request,profil,active_page="pointages",pointeuse=pointeuse,pointages=enrichis,statistiques=statistiques,debut=debut,fin=fin,debut_affichage=debut_dt.strftime("%d/%m/%Y %H:%M"),fin_affichage=fin_dt.strftime("%d/%m/%Y %H:%M"),genere_le=datetime.now().strftime("%d/%m/%Y a %H:%M:%S"),source=resultat.get("source"),cache=True,performance=performance_rapport,performance_rapport=performance_rapport))
from fastapi import Form
from datetime import datetime


@app.post("/pointages/correction",name="enregistrer_correction_pointage_route")
def enregistrer_correction_pointage_route(request: Request,pointeuse_id:int=Form(...),matricule:str=Form(...),timestamp_original:str=Form(...),timestamp_corrige:str=Form(...),status:str=Form(""),punch:str=Form(""),motif:str=Form("")):
    _,e=_pointeuse_api(request,pointeuse_id,False)
    if e:return e
    r=enregistrer_correction_pointage(pointeuse_id=pointeuse_id,matricule=matricule,timestamp_original=timestamp_original,timestamp_corrige=timestamp_corrige,status=status,punch=punch,motif=motif);return r if isinstance(r,dict) and r.get("success") is True else JSONResponse(status_code=400,content=r if isinstance(r,dict) else {"success":False,"erreur":"Reponse de correction invalide."})


@app.post("/pointages/correction/annuler",name="annuler_correction_pointage_route")
def annuler_correction_pointage_route(request: Request,pointeuse_id:int=Form(...),matricule:str=Form(...),timestamp_original:str=Form(...),status:str=Form(""),punch:str=Form("")):
    _,e=_pointeuse_api(request,pointeuse_id,False)
    if e:return e
    r=annuler_correction_pointage(pointeuse_id=pointeuse_id,matricule=matricule,timestamp_original=timestamp_original,status=status,punch=punch);return r if isinstance(r,dict) and r.get("success") is True else JSONResponse(status_code=400,content=r if isinstance(r,dict) else {"success":False,"erreur":"Reponse d'annulation invalide."})


@app.post("/pointages/telecharger",name="telecharger_pointages")
def telecharger_pointages(request: Request,pointeuse_id:int=Form(...),debut:str=Form(...),fin:str=Form(...)):
    p,e=_pointeuse_api(request,pointeuse_id)
    if e:return e
    try:r=creer_excel_pointages(pointeuse_id=pointeuse_id,nom_pointeuse=p.get("nom"),ip=p.get("ip"),port=p.get("port"),date_heure_debut=debut,date_heure_fin=fin)
    except Exception as exc:return JSONResponse(status_code=500,content={"success":False,"erreur":"Erreur pendant la generation Excel : "+str(exc)})
    if not isinstance(r,dict) or r.get("success") is not True:return JSONResponse(status_code=400,content=r if isinstance(r,dict) else {"success":False,"erreur":"Reponse Excel invalide."})
    contenu=r.get("contenu")
    if not isinstance(contenu,bytes) or not contenu:return JSONResponse(status_code=500,content={"success":False,"erreur":"Le contenu Excel est invalide."})
    return StreamingResponse(BytesIO(contenu),media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",headers={"Content-Disposition":f'attachment; filename="{r.get("nom_fichier") or "pointages.xlsx"}"'})


@app.get("/employes",response_class=HTMLResponse,name="employes")
def employes(request: Request,pointeuse_id:int|None=Query(default=None)):
    profil,redirect=_profil_obligatoire(request)
    if redirect:return redirect
    rp=_get_pointeuses_profil(profil);liste=rp.get("pointeuses",[]) if isinstance(rp,dict) else [];liste=liste if isinstance(liste,list) else []
    selection=next((p for p in liste if str(p.get("id"))==str(pointeuse_id)),None) if pointeuse_id is not None else None
    r=get_users_pointeuse(ip=selection.get("ip"),port=selection.get("port")) if selection else {"success":False,"utilisateurs":[],"nombre":0,"erreur":"Aucune pointeuse selectionnee."}
    return templates.TemplateResponse(request=request,name="employes.html",context=_contexte(request,profil,active_page="pointeuses",resultat=r,utilisateurs=r.get("utilisateurs",[]),pointeuse_selectionnee=selection,pointeuse_id=pointeuse_id))


@app.get("/employes/{uid}/modifier",response_class=HTMLResponse,name="modifier_employe_page")
def modifier_employe_page(request: Request,uid:int,pointeuse_id:int=Query(...)):
    profil,redirect=_profil_obligatoire(request)
    if redirect:return redirect
    p,e=_pointeuse_api(request,pointeuse_id,False)
    if e:return e
    r=get_user_pointeuse(ip=p.get("ip"),port=p.get("port"),uid=uid)
    if r.get("success") is not True:return JSONResponse(status_code=404,content=r)
    return templates.TemplateResponse(request=request,name="modifier_employe.html",context=_contexte(request,profil,active_page="pointeuses",pointeuse=p,utilisateur=r.get("utilisateur")))


@app.post("/employes/{uid}/modifier",name="enregistrer_modification_employe")
def enregistrer_modification_employe(request: Request,uid:int,pointeuse_id:int=Form(...),matricule:str=Form(...),nom:str=Form(...),badge:str=Form(...),role:str=Form(...)):
    p,e=_pointeuse_api(request,pointeuse_id,False)
    if e:return e
    r=modifier_employe_pointeuse(ip=p.get("ip"),port=p.get("port"),uid=uid,matricule=matricule,nom=nom,badge=badge,role=role);return r if r.get("success") is True else JSONResponse(status_code=400,content=r)


@app.get("/employes/ajouter",response_class=HTMLResponse,name="ajouter_employe")
def ajouter_employe(request: Request,pointeuse_id:int=Query(...)):
    profil,redirect=_profil_obligatoire(request)
    if redirect:return redirect
    p,e=_pointeuse_api(request,pointeuse_id,False)
    if e:return e
    return templates.TemplateResponse(request=request,name="ajouter_employe.html",context=_contexte(request,profil,active_page="pointeuses",pointeuse=p,pointeuse_id=pointeuse_id,resultat=None,form_data={"matricule":"","nom":"","badge":"","role":"Utilisateur normal"}))


@app.post("/employes/ajouter",response_class=HTMLResponse,name="enregistrer_nouvel_employe")
def enregistrer_nouvel_employe(request: Request,pointeuse_id:int=Form(...),matricule:str=Form(...),nom:str=Form(...),badge:str=Form(...),role:str=Form("Utilisateur normal")):
    profil,redirect=_profil_obligatoire(request)
    if redirect:return redirect
    p,e=_pointeuse_api(request,pointeuse_id,False)
    if e:return e
    matricule,nom,badge,role=matricule.strip(),nom.strip(),badge.strip(),role.strip();erreurs=[];form_data={"matricule":matricule,"nom":nom,"badge":badge,"role":role}
    if not matricule:erreurs.append("Le matricule est obligatoire.")
    if not nom:erreurs.append("Le nom et prenom sont obligatoires.")
    if not badge or not badge.isdigit():erreurs.append("Le badge doit contenir uniquement des chiffres.")
    if role not in ("Utilisateur normal","Admin"):erreurs.append("Le statut utilisateur est invalide.")
    if not erreurs:
        prep=preparer_import_employes(ip=p.get("ip"),port=p.get("port"),employes=[{"ligne":1,"matricule":matricule,"nom":nom,"badge":badge}]);valides=prep.get("valides",[]) if isinstance(prep,dict) else []
        if valides:
            emp=dict(valides[0]);imp=importer_employes(ip=p.get("ip"),port=p.get("port"),employes=[emp])
            if imp.get("success") is True:
                rr=modifier_employe_pointeuse(ip=p.get("ip"),port=p.get("port"),uid=emp.get("uid"),matricule=matricule,nom=nom,badge=badge,role=role)
                if rr.get("success") is True:return templates.TemplateResponse(request=request,name="ajouter_employe.html",context=_contexte(request,profil,active_page="pointeuses",pointeuse=p,pointeuse_id=pointeuse_id,resultat={"success":True,"message":"L'employe a ete ajoute avec succes."},form_data={"matricule":"","nom":"","badge":"","role":"Utilisateur normal"}))
                erreurs.append(rr.get("erreur") or "Statut impossible a appliquer.")
            else:erreurs.append(imp.get("erreur") or "Import impossible.")
        else:erreurs.append(prep.get("erreur") if isinstance(prep,dict) else "Preparation invalide.")
    return templates.TemplateResponse(request=request,name="ajouter_employe.html",context=_contexte(request,profil,active_page="pointeuses",pointeuse=p,pointeuse_id=pointeuse_id,resultat={"success":False,"erreurs":erreurs,"erreur":erreurs[0] if erreurs else "Erreur."},form_data=form_data))


@app.get("/pointeuses",response_class=HTMLResponse,name="pointeuses")
def pointeuses(request: Request):
    profil,redirect=_profil_obligatoire(request)
    if redirect:return redirect
    r=_get_pointeuses_profil(profil);return templates.TemplateResponse(request=request,name="pointeuses.html",context=_contexte(request,profil,active_page="pointeuses",resultat=r,pointeuses=r.get("pointeuses",[])))


@app.get("/pointeuses/ajouter",response_class=HTMLResponse,name="ajouter_pointeuse")
def page_ajouter_pointeuse(request: Request):
    profil,redirect=_profil_obligatoire(request)
    if redirect:return redirect
    return templates.TemplateResponse(request=request,name="ajouter_pointeuse.html",context=_contexte(request,profil,active_page="pointeuses",resultat_test=None,form_data={"nom":"","ip":"","port":"4370"}))


@app.post("/pointeuses/tester",response_class=HTMLResponse,name="tester_pointeuse")
def tester_pointeuse(request: Request,nom:str=Form(...),ip:str=Form(...),port:str=Form(...)):
    profil,redirect=_profil_obligatoire(request)
    if redirect:return redirect
    r=tester_connexion_pointeuse(ip=ip.strip(),port=port.strip());return templates.TemplateResponse(request=request,name="ajouter_pointeuse.html",context=_contexte(request,profil,active_page="pointeuses",resultat_test=r,form_data={"nom":nom.strip(),"ip":ip.strip(),"port":port.strip()}))


@app.post("/pointeuses/enregistrer", name="enregistrer_pointeuse")
def enregistrer_pointeuse(
    request: Request,
    nom: str = Form(...),
    ip: str = Form(...),
    port: str = Form(...),
):
    profil = _profil_session(request)

    if not profil:
        return JSONResponse(
            status_code=401,
            content={
                "success": False,
                "erreur": "Authentification requise."
            }
        )

    r = ajouter_pointeuse(
        nom=nom.strip(),
        ip=ip.strip(),
        port=port.strip(),
        active=True,
        profil_id=profil.get("id"),
    )

    print("===== AJOUT POINTEUSE =====")
    print(r)
    print("===========================")

    if r.get("success"):
        return r

    return JSONResponse(
        status_code=400,
        content=r,
    )

@app.get("/pointeuses/{pointeuse_id}/modifier",response_class=HTMLResponse,name="modifier_pointeuse_page")
def modifier_pointeuse_page(request: Request,pointeuse_id:int):
    profil,redirect=_profil_obligatoire(request)
    if redirect:return redirect
    r=get_pointeuse_par_id(pointeuse_id,profil_id=profil.get("id"));return templates.TemplateResponse(request=request,name="modifier_pointeuse.html",context=_contexte(request,profil,active_page="pointeuses",pointeuse=r.get("pointeuse") if r.get("success") else None,erreur=None if r.get("success") else r.get("erreur")),status_code=200 if r.get("success") else 403 if r.get("acces_refuse") else 404)


@app.post("/pointeuses/{pointeuse_id}/tester-modification",name="tester_modification_pointeuse")
def tester_modification_pointeuse(request: Request,pointeuse_id:int,nom:str=Form(...),ip:str=Form(...),port:str=Form(...),active:str=Form("false")):
    _,e=_pointeuse_api(request,pointeuse_id,False)
    if e:return e
    r=tester_connexion_pointeuse(ip=ip.strip(),port=port.strip());h=r.get("heure");return {"success":r.get("success",False),"ip":r.get("ip"),"port":r.get("port"),"ping":r.get("ping",False),"firmware":r.get("firmware"),"heure":str(h) if h is not None else None,"mac":r.get("mac"),"erreur":r.get("erreur")}


@app.post("/pointeuses/{pointeuse_id}/enregistrer-modification",name="enregistrer_modification_pointeuse")
def enregistrer_modification_pointeuse(request: Request,pointeuse_id:int,nom:str=Form(...),ip:str=Form(...),port:str=Form(...),active:str=Form("false")):
    profil=_profil_session(request)
    if not profil:return JSONResponse(status_code=401,content={"success":False,"erreur":"Authentification requise."})
    r=modifier_pointeuse(pointeuse_id=pointeuse_id,nom=nom.strip(),ip=ip.strip(),port=port.strip(),active=est_actif(active),profil_id=profil.get("id"));return {"success":True,"message":"Modifications enregistrees.","pointeuse":r.get("pointeuse"),"erreur":None} if r.get("success") else JSONResponse(status_code=403 if r.get("acces_refuse") else 400,content=r)


@app.get("/import-excel",response_class=HTMLResponse,name="import_excel")
def import_excel(request: Request):
    profil,redirect=_profil_obligatoire(request)
    if redirect:return redirect
    r=_get_pointeuses_profil(profil);l=r.get("pointeuses",[]);l=l if isinstance(l,list) else [];return templates.TemplateResponse(request=request,name="import_excel.html",context=_contexte(request,profil,active_page="pointeuses",pointeuses=l,pointeuse_id=None,analyse_excel=None,preparation_import=None,import_id=None,resultat_import=None))


@app.post("/import-excel/analyser",response_class=HTMLResponse,name="analyser_import_excel")
async def analyser_import_excel(request: Request,pointeuse_id:int=Form(...),fichier:UploadFile=File(...)):
    profil,redirect=_profil_obligatoire(request)
    if redirect:return redirect
    r=_get_pointeuses_profil(profil);l=r.get("pointeuses",[]);l=l if isinstance(l,list) else [];sel=next((p for p in l if str(p.get("id"))==str(pointeuse_id)),None);analyse=preparation=import_id=chemin=None
    try:
        contenu=await fichier.read()
        if sel is None:analyse={"success":False,"employes":[],"nombre":0,"erreurs":["Pointeuse introuvable."],"nombre_erreurs":1}
        elif not contenu:analyse={"success":False,"employes":[],"nombre":0,"erreurs":["Fichier vide."],"nombre_erreurs":1}
        else:
            with tempfile.NamedTemporaryFile(delete=False,suffix=".xlsx") as tmp:tmp.write(contenu);chemin=Path(tmp.name)
            analyse=lire_fichier_employes_excel(chemin);emps=analyse.get("employes",[]) if isinstance(analyse,dict) else []
            if emps:preparation=preparer_import_employes(ip=sel.get("ip"),port=sel.get("port"),employes=emps)
            if isinstance(preparation,dict) and preparation.get("success") is True and preparation.get("valides"):
                ses=creer_session_import(pointeuse_id=pointeuse_id,employes=preparation.get("valides"));import_id=ses.get("import_id") if ses.get("success") else None
    finally:
        if chemin:
            try:chemin.unlink(missing_ok=True)
            except Exception:pass
        await fichier.close()
    return templates.TemplateResponse(request=request,name="import_excel.html",context=_contexte(request,profil,active_page="pointeuses",pointeuses=l,pointeuse_id=pointeuse_id,analyse_excel=analyse,preparation_import=preparation,import_id=import_id,resultat_import=None))


@app.post("/import-excel/importer",response_class=HTMLResponse,name="importer_excel")
def importer_excel(request: Request,import_id:str=Form(...)):
    profil,redirect=_profil_obligatoire(request)
    if redirect:return redirect
    r=_get_pointeuses_profil(profil);l=r.get("pointeuses",[]);l=l if isinstance(l,list) else [];ses=lire_session_import(import_id);pid=None;prep=None;ri={"success":False,"erreur":"Session invalide."}
    if isinstance(ses,dict) and ses.get("success"):
        d=ses.get("donnees",{});pid=d.get("pointeuse_id");emps=d.get("employes",[]);sel=next((p for p in l if str(p.get("id"))==str(pid)),None)
        if sel and emps:
            prep=preparer_import_employes(ip=sel.get("ip"),port=sel.get("port"),employes=emps);val=prep.get("valides",[]) if isinstance(prep,dict) else [];ri=importer_employes(ip=sel.get("ip"),port=sel.get("port"),employes=val) if val else {"success":False,"erreur":"Aucun employe a importer."}
    supprimer_session_import(import_id);return templates.TemplateResponse(request=request,name="import_excel.html",context=_contexte(request,profil,active_page="pointeuses",pointeuses=l,pointeuse_id=pid,analyse_excel=None,preparation_import=prep,import_id=None,resultat_import=ri))




# ============================================================
# ADMINISTRATION - PROFILS
# ============================================================

@app.get('/administration/profils', response_class=HTMLResponse, name='administration_profils')
def administration_profils(request: Request):
    profil, erreur = _admin_obligatoire(request)
    if erreur is not None:
        return erreur

    resultat = lister_profils()
    if not isinstance(resultat, dict) or resultat.get('success') is not True:
        return JSONResponse(
            status_code=500,
            content={
                'success': False,
                'erreur': resultat.get('erreur') if isinstance(resultat, dict) else 'Impossible de lire les profils.',
            },
        )

    profils = resultat.get('profils', [])
    if not isinstance(profils, list):
        profils = []

    for item in profils:
        if not isinstance(item, dict):
            continue
        derniere = item.get('derniere_connexion')
        item['derniere_connexion_affichage'] = 'Jamais'
        if derniere:
            try:
                item['derniere_connexion_affichage'] = datetime.fromisoformat(str(derniere)).strftime('%d/%m/%Y %H:%M:%S')
            except Exception:
                item['derniere_connexion_affichage'] = str(derniere)

    statistiques = {
        'nombre_profils': len(profils),
        'nombre_actifs': sum(1 for item in profils if est_actif(item.get('active'))),
        'nombre_admins': sum(1 for item in profils if str(item.get('role', '')).upper() == 'ADMIN'),
    }

    return templates.TemplateResponse(
        request=request,
        name='profils.html',
        context=_contexte(
            request,
            profil,
            active_page='profils',
            profils=profils,
            statistiques=statistiques,
        ),
    )


@app.post('/administration/profils/creer', name='administration_creer_profil')
def administration_creer_profil(
    request: Request,
    nom: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form('USER'),
    active: str = Form('true'),
):
    _, erreur = _admin_obligatoire(request)
    if erreur is not None:
        return erreur

    nom = str(nom or '').strip()
    username = str(username or '').strip()
    role = str(role or 'USER').strip().upper()

    if role not in ('ADMIN', 'USER'):
        return JSONResponse(status_code=400, content={'success': False, 'erreur': 'Le role doit etre ADMIN ou USER.'})

    resultat = creer_profil(
        username=username,
        mot_de_passe=password,
        nom=nom,
        role=role,
        active=est_actif(active),
    )

    if not isinstance(resultat, dict) or resultat.get('success') is not True:
        return JSONResponse(
            status_code=400,
            content=resultat if isinstance(resultat, dict) else {'success': False, 'erreur': 'Reponse de creation invalide.'},
        )

    return {
        'success': True,
        'profil': resultat.get('profil'),
        'message': 'Le profil ' + username + ' a ete cree avec succes.',
        'erreur': None,
    }


@app.post('/administration/profils/{profil_id}/modifier', name='administration_modifier_profil')
def administration_modifier_profil(
    request: Request,
    profil_id: int,
    nom: str = Form(...),
    username: str = Form(''),
    role: str = Form(...),
    active: str = Form('true'),
):
    profil_admin, erreur = _admin_obligatoire(request)
    if erreur is not None:
        return erreur

    role = str(role or '').strip().upper()
    if role not in ('ADMIN', 'USER'):
        return JSONResponse(status_code=400, content={'success': False, 'erreur': 'Le role doit etre ADMIN ou USER.'})

    if int(profil_admin.get('id')) == int(profil_id) and (role != 'ADMIN' or not est_actif(active)):
        return JSONResponse(
            status_code=400,
            content={'success': False, 'erreur': 'Vous ne pouvez pas retirer votre propre role ADMIN ni desactiver votre compte.'},
        )

    resultat = modifier_profil(
        profil_id=profil_id,
        nom=str(nom or '').strip(),
        role=role,
        active=est_actif(active),
    )

    if not isinstance(resultat, dict) or resultat.get('success') is not True:
        return JSONResponse(
            status_code=400,
            content=resultat if isinstance(resultat, dict) else {'success': False, 'erreur': 'Reponse de modification invalide.'},
        )

    return {'success': True, 'profil': resultat.get('profil'), 'message': 'Le profil a ete modifie avec succes.', 'erreur': None}


@app.post('/administration/profils/{profil_id}/mot-de-passe', name='administration_mot_de_passe_profil')
def administration_mot_de_passe_profil(
    request: Request,
    profil_id: int,
    password: str = Form(...),
):
    _, erreur = _admin_obligatoire(request)
    if erreur is not None:
        return erreur

    resultat = changer_mot_de_passe(
        profil_id=profil_id,
        nouveau_mot_de_passe=password,
    )

    if not isinstance(resultat, dict) or resultat.get('success') is not True:
        return JSONResponse(
            status_code=400,
            content=resultat if isinstance(resultat, dict) else {'success': False, 'erreur': 'Impossible de modifier le mot de passe.'},
        )

    return {'success': True, 'message': 'Le mot de passe a ete modifie avec succes.', 'erreur': None}


@app.post('/administration/profils/{profil_id}/etat', name='administration_etat_profil')
def administration_etat_profil(
    request: Request,
    profil_id: int,
    active: str = Form(...),
):
    profil_admin, erreur = _admin_obligatoire(request)
    if erreur is not None:
        return erreur

    nouvel_etat = est_actif(active)
    if int(profil_admin.get('id')) == int(profil_id) and not nouvel_etat:
        return JSONResponse(
            status_code=400,
            content={'success': False, 'erreur': 'Vous ne pouvez pas desactiver votre propre compte administrateur.'},
        )

    resultat_profil = get_profil_par_id(profil_id, inclure_inactif=True)
    if not isinstance(resultat_profil, dict) or resultat_profil.get('success') is not True:
        return JSONResponse(status_code=404, content={'success': False, 'erreur': 'Profil introuvable.'})

    cible = resultat_profil.get('profil')
    if not isinstance(cible, dict):
        return JSONResponse(status_code=404, content={'success': False, 'erreur': 'Profil introuvable.'})

    resultat = modifier_profil(
        profil_id=profil_id,
        nom=cible.get('nom'),
        role=cible.get('role'),
        active=nouvel_etat,
    )

    if not isinstance(resultat, dict) or resultat.get('success') is not True:
        return JSONResponse(
            status_code=400,
            content=resultat if isinstance(resultat, dict) else {'success': False, 'erreur': "Impossible de modifier l'etat du profil."},
        )

    return {
        'success': True,
        'profil': resultat.get('profil'),
        'message': 'Profil active.' if nouvel_etat else 'Profil desactive.',
        'erreur': None,
    }


BACKUP_FILES={"users":"Users.dat","system":"System.dat"}
def get_dernier_backup(pointeuse_id):
    r=lister_backups_pointeuse(pointeuse_id);b=r.get("backups",[]) if r.get("success") else [];return b[0] if b else None

def retrouver_archive_backup(dossier_backup):
    if not dossier_backup:return None
    d=Path(dossier_backup);a=sorted(d.parent.glob("*.zip"),reverse=True) if d.exists() else [];return next((x for x in a if d.name in x.name),a[0] if a else None)


@app.get("/parametres",response_class=HTMLResponse,name="parametres")
def parametres(request: Request,pointeuse_id:int|None=Query(default=None)):
    profil,redirect=_profil_obligatoire(request)
    if redirect:return redirect
    r=_get_pointeuses_profil(profil);l=r.get("pointeuses",[]);l=l if isinstance(l,list) else []
    if pointeuse_id is None and l:
        try:pointeuse_id=int(l[0].get("id"))
        except Exception:pointeuse_id=None
    s=next((p for p in l if str(p.get("id"))==str(pointeuse_id)),None) if pointeuse_id is not None else None
    return templates.TemplateResponse(request=request,name="parametres.html",context=_contexte(request,profil,active_page="parametres",resultat_pointeuses=r,pointeuses=l,nombre_pointeuses=len(l),nombre_actives=sum(1 for p in l if est_actif(p.get("active"))),pointeuse_id=pointeuse_id,pointeuse_selectionnee=s,dernier_backup=get_dernier_backup(pointeuse_id) if s else None))


@app.post("/parametres/backup/creer",name="creer_backup_route")
def creer_backup_route(request: Request,pointeuse_id:int=Form(...)):
    p,e=_pointeuse_api(request,pointeuse_id)
    if e:return e
    r=creer_backup_pointeuse(pointeuse_id=pointeuse_id,nom_pointeuse=p.get("nom"),ip=p.get("ip"),port=p.get("port"));return r if r.get("success") else JSONResponse(status_code=400,content=r)


@app.get("/parametres/backup/{pointeuse_id}/{type_fichier}",name="telecharger_backup_dat")
def telecharger_backup_dat(request: Request,pointeuse_id:int,type_fichier:str):
    _,e=_pointeuse_api(request,pointeuse_id,False)
    if e:return e
    nom=BACKUP_FILES.get(type_fichier);b=get_dernier_backup(pointeuse_id);chemin=Path(b.get("dossier"))/nom if nom and b and b.get("dossier") else None
    if chemin is None or not chemin.is_file():return JSONResponse(status_code=404,content={"success":False,"erreur":"Fichier introuvable."})
    return FileResponse(path=str(chemin),media_type="application/octet-stream",filename=nom)


@app.get("/parametres/backup/{pointeuse_id}/zip/complet",name="telecharger_backup_zip")
def telecharger_backup_zip(request: Request,pointeuse_id:int):
    _,e=_pointeuse_api(request,pointeuse_id,False)
    if e:return e
    b=get_dernier_backup(pointeuse_id);a=retrouver_archive_backup(b.get("dossier") if b else None)
    if not a:return JSONResponse(status_code=404,content={"success":False,"erreur":"Archive introuvable."})
    return FileResponse(path=str(a),media_type="application/zip",filename="Backup.zip")


async def _sauver_zip_temp(fichier:UploadFile):
    contenu=await fichier.read()
    if not fichier.filename or not fichier.filename.lower().endswith(".zip") or not contenu:return None,JSONResponse(status_code=400,content={"success":False,"erreur":"ZIP invalide."})
    with tempfile.NamedTemporaryFile(delete=False,suffix=".zip") as tmp:tmp.write(contenu);return Path(tmp.name),None


@app.post("/parametres/restauration/verifier",name="verifier_restauration_route")
async def verifier_restauration_route(request: Request,pointeuse_id:int=Form(...),fichier:UploadFile=File(...)):
    p,e=_pointeuse_api(request,pointeuse_id,False)
    if e:return e
    chemin=None
    try:
        chemin,err=await _sauver_zip_temp(fichier)
        if err:return err
        r=verifier_backup_restauration(chemin_zip=chemin,pointeuse_id=pointeuse_id,ip=p.get("ip"),port=p.get("port"));return r if r.get("success") else JSONResponse(status_code=400,content=r)
    finally:
        await fichier.close()
        if chemin:chemin.unlink(missing_ok=True)


@app.post("/parametres/restauration/restaurer",name="restaurer_backup_route")
async def restaurer_backup_route(request: Request,pointeuse_id:int=Form(...),fichier:UploadFile=File(...)):
    p,e=_pointeuse_api(request,pointeuse_id,False)
    if e:return e
    chemin=None
    try:
        chemin,err=await _sauver_zip_temp(fichier)
        if err:return err
        r=restaurer_backup_sqlite(chemin_zip=chemin,pointeuse_id=pointeuse_id,ip=p.get("ip"),port=p.get("port"));return r if r.get("success") else JSONResponse(status_code=400,content=r)
    finally:
        await fichier.close()
        if chemin:chemin.unlink(missing_ok=True)


@app.post("/parametres/maintenance/nettoyer-pointages",name="nettoyer_pointages_route")
def nettoyer_pointages_route(request: Request,pointeuse_id:int=Form(...)):
    p,e=_pointeuse_api(request,pointeuse_id)
    if e:return e
    b=get_dernier_backup(pointeuse_id)
    if not b or b.get("backup_valid") is not True:return JSONResponse(status_code=400,content={"success":False,"historique_conserve":True,"erreur":"Suppression interdite : backup valide obligatoire."})
    rb=lire_pointages_users_dat(b.get("dossier"))
    if rb.get("success") is not True:return JSONResponse(status_code=400,content=rb)
    rt=get_pointages_pointeuse(ip=p.get("ip"),port=p.get("port"),forcer_actualisation=True)
    if rt.get("success") is not True:return JSONResponse(status_code=400,content=rt)
    terminal=rt.get("pointages",[]) if isinstance(rt.get("pointages"),list) else [];sauvegarde=rb.get("pointages",[])
    if len(sauvegarde)!=len(terminal) or Counter(map(cle_pointage_securite,sauvegarde))!=Counter(map(cle_pointage_securite,terminal)):return JSONResponse(status_code=409,content={"success":False,"historique_conserve":True,"erreur":"Backup different du terminal."})
    avant=lire_cache_pointages(pointeuse_id)
    if avant.get("success") is not True:return JSONResponse(status_code=500,content={"success":False,"erreur":"Historique SQLite non verifiable."})
    n=int(avant.get("nombre",0) or 0);net=supprimer_pointages_terminal(ip=p.get("ip"),port=p.get("port"))
    if not isinstance(net,dict) or net.get("success") is not True:return JSONResponse(status_code=400,content=net if isinstance(net,dict) else {"success":False,"erreur":"Reponse invalide."})
    apres=lire_cache_pointages(pointeuse_id);n2=int(apres.get("nombre",-1) or 0) if apres.get("success") is True else -1
    if n2!=n:return JSONResponse(status_code=500,content={"success":False,"historique_conserve":False,"erreur":"ALERTE : historique SQLite modifie."})
    return {"success":True,"nombre_supprimes":net.get("nombre_supprimes",0),"historique_local":n2,"historique_conserve":True,"message":"Nettoyage termine."}
