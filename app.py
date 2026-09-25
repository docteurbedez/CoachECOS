import os
import time
import json
from datetime import datetime
import streamlit as st
import streamlit.components.v1 as components
from google import genai
from google.genai import types
from streamlit_mic_recorder import mic_recorder

st.set_page_config(page_title="Simulation Oral ECOS", layout="centered")

# -----------------------------------------------------------------------------
# 0. GESTION DES CONFIGURATIONS ET DU SUIVI DES ESSAIS
# -----------------------------------------------------------------------------
CONFIG_FILE = "config_ecos.json"
TRACKING_FILE = "tracking_ecos.json"
ACTIVE_SESSIONS_FILE = "active_sessions.json"

DEFAULT_CONFIG = {
    "require_student_pwd": True,
    "global_password": "ecos",
    "teacher_pwd": "ens",
    "time_restriction": False,
    "start_time": "08:00",
    "end_time": "18:00",
    "max_attempts": 3,
    "max_concurrent": 2
}

def load_json(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except: pass
    return default

def save_json(filepath, data):
    with open(filepath, "w") as f:
        json.dump(data, f)

# Fusion sécurisée de la configuration
saved_config = load_json(CONFIG_FILE, {})
current_config = DEFAULT_CONFIG.copy()
current_config.update(saved_config)

# --- FONCTIONS DE LA FILE D'ATTENTE ---
def clean_active_sessions():
    sessions = load_json(ACTIVE_SESSIONS_FILE, {})
    now = time.time()
    # On supprime les sessions inactives depuis plus de 12 minutes (720s) pour éviter les blocages si fermeture de l'onglet
    cleaned = {k: v for k, v in sessions.items() if now - v < 720}
    if len(cleaned) != len(sessions):
        save_json(ACTIVE_SESSIONS_FILE, cleaned)
    return cleaned

def add_active_session(user_id):
    sessions = clean_active_sessions()
    sessions[user_id] = time.time()
    save_json(ACTIVE_SESSIONS_FILE, sessions)

def remove_active_session(user_id):
    sessions = clean_active_sessions()
    if user_id in sessions:
        del sessions[user_id]
        save_json(ACTIVE_SESSIONS_FILE, sessions)

# --- BARRE LATÉRALE : PANNEAU ENSEIGNANT ---
with st.sidebar:
    st.header("⚙️ Administration ECOS")
    admin_input = st.text_input("Mot de passe administration :", type="password")
    
    if admin_input == st.secrets.get("ADMIN_PWD", "admin123"):
        st.success("Accès autorisé")
        st.divider()
        st.subheader("Règles d'accès étudiants")
        
        # 1. Mode de connexion
        new_req_pwd = st.checkbox("Exiger un mot de passe étudiant", value=current_config["require_student_pwd"])
        new_pwd = st.text_input("Mot de passe étudiant :", value=current_config["global_password"])
        new_teacher_pwd = st.text_input("Mot de passe Enseignant (illimité) :", value=current_config["teacher_pwd"])
        
        st.divider()
        # 2. Horaires
        new_time_rest = st.checkbox("Restreindre par horaires", value=current_config["time_restriction"])
        new_start = st.time_input("Heure d'ouverture", value=datetime.strptime(current_config["start_time"], "%H:%M").time())
        new_end = st.time_input("Heure de fermeture", value=datetime.strptime(current_config["end_time"], "%H:%M").time())
        
        st.divider()
        # 3. Quotas
        new_max_attempts = st.number_input("Essais max / jour / étudiant", min_value=1, value=current_config["max_attempts"])
        new_max_conc = st.number_input("Étudiants en parallèle (File d'attente)", min_value=1, max_value=10, value=current_config["max_concurrent"])
        
        if st.button("💾 Sauvegarder la configuration", use_container_width=True):
            current_config.update({
                "require_student_pwd": new_req_pwd,
                "global_password": new_pwd,
                "teacher_pwd": new_teacher_pwd,
                "time_restriction": new_time_rest,
                "start_time": new_start.strftime("%H:%M"),
                "end_time": new_end.strftime("%H:%M"),
                "max_attempts": new_max_attempts,
                "max_concurrent": new_max_conc
            })
            save_json(CONFIG_FILE, current_config)
            st.success("Paramètres enregistrés avec succès !")
    elif admin_input:
        st.error("Mot de passe incorrect")

# -----------------------------------------------------------------------------
# 0.5. VÉRIFICATION DES RESTRICTIONS (HORAIRES ET AUTHENTIFICATION)
# -----------------------------------------------------------------------------
# 1. Vérification des horaires (si activée)
if current_config["time_restriction"]:
    now = datetime.now().time()
    start_t = datetime.strptime(current_config["start_time"], "%H:%M").time()
    end_t = datetime.strptime(current_config["end_time"], "%H:%M").time()
    
    is_open = (start_t <= now <= end_t) if start_t <= end_t else (now >= start_t or now <= end_t)
    if not is_open:
        st.title("⏳ Épreuve fermée")
        st.warning(f"L'accès à la station d'ECOS n'est autorisé qu'entre {current_config['start_time']} et {current_config['end_time']}.")
        st.stop()

# 2. Gestion de l'authentification et des quotas
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "is_teacher" not in st.session_state:
    st.session_state.is_teacher = False
if "student_id" not in st.session_state:
    st.session_state.student_id = None
if "waiting_in_queue" not in st.session_state:
    st.session_state.waiting_in_queue = False

today_str = datetime.now().strftime("%Y-%m-%d")
tracking_data = load_json(TRACKING_FILE, {})
max_att = current_config["max_attempts"]

if not st.session_state.authenticated:
    st.title("🔒 Accès à l'épreuve ECOS")
    
    with st.form("login_form"):
        student_name = st.text_input("Nom de l'étudiant / Numéro :", placeholder="Ex: Jean Dupont")
        label_pwd = "Mot de passe :" if current_config["require_student_pwd"] else "Mot de passe (réservé Enseignant) :"
        pwd = st.text_input(label_pwd, type="password")
        
        submit = st.form_submit_button("Se connecter", use_container_width=True)
        
        if submit:
            if not student_name.strip():
                st.error("Veuillez saisir votre nom.")
            elif pwd == current_config["teacher_pwd"]:
                st.session_state.authenticated = True
                st.session_state.is_teacher = True
                st.session_state.student_id = f"👨‍🏫 {student_name.strip()}"
                st.rerun()
            else:
                s_id = student_name.strip().lower()
                current_student_attempts = tracking_data.get(s_id, {}).get(today_str, 0)
                
                if current_config["require_student_pwd"] and pwd != current_config["global_password"]:
                    st.error("Mot de passe étudiant incorrect.")
                elif current_student_attempts >= max_att:
                    st.error(f"❌ Quota d'essais atteint pour aujourd'hui pour le profil '{student_name}' ({max_att} max).")
                else:
                    st.session_state.authenticated = True
                    st.session_state.is_teacher = False
                    st.session_state.student_id = student_name.strip()
                    st.rerun()
    st.stop()

# -----------------------------------------------------------------------------
# 1. DÉTECTION ET SÉLECTION DU CAS CLINIQUE (1 À 8)
# -----------------------------------------------------------------------------

CAS_DISPONIBLES = [str(i) for i in range(1, 9) if str(i) in st.secrets]

if not CAS_DISPONIBLES:
    st.error("Erreur : Aucun cas clinique (de '1' à '8') n'a été trouvé dans les Secrets de Streamlit.")
    st.stop()

# Initialisation de l'état de session
if "start_time" not in st.session_state:
    st.session_state.start_time = None
if "messages" not in st.session_state:
    st.session_state.messages = []
if "eval_generated" not in st.session_state:
    st.session_state.eval_generated = False
if "force_end" not in st.session_state:
    st.session_state.force_end = False
if "selected_cas" not in st.session_state:
    url_param = str(st.query_params.get("cas", "")).strip()
    st.session_state.selected_cas = url_param if url_param in CAS_DISPONIBLES else CAS_DISPONIBLES[0]
if "last_audio_id_2" not in st.session_state:
    st.session_state.last_audio_id_2 = None
if "last_audio_id_3" not in st.session_state:
    st.session_state.last_audio_id_3 = None
if "show_help" not in st.session_state:
    st.session_state.show_help = False

# Fonction pour revenir à l'accueil
def reset_to_home():
    if st.session_state.student_id:
        remove_active_session(st.session_state.student_id)
    st.session_state.start_time = None
    st.session_state.messages = []
    st.session_state.eval_generated = False
    st.session_state.force_end = False
    st.session_state.last_audio_id_2 = None
    st.session_state.last_audio_id_3 = None
    st.session_state.waiting_in_queue = False

# --- ÉCRAN DE DÉMARRAGE ET FILE D'ATTENTE ---
if st.session_state.start_time is None:
    
    # Si l'utilisateur a cliqué sur Démarrer et est dans la file d'attente
    if st.session_state.waiting_in_queue:
        st.title("⏳ File d'attente")
        actives = clean_active_sessions()
        
        # Si une place se libère ou si c'est le professeur (qui contourne la file)
        if len(actives) < current_config["max_concurrent"] or st.session_state.is_teacher:
            add_active_session(st.session_state.student_id)
            st.session_state.waiting_in_queue = False
            
            # Consommation de l'essai seulement au moment d'entrer
            if not st.session_state.is_teacher:
                s_id = st.session_state.student_id.lower()
                tracking_data = load_json(TRACKING_FILE, {})
                current_count = tracking_data.get(s_id, {}).get(today_str, 0)
                if s_id not in tracking_data:
                    tracking_data[s_id] = {}
                tracking_data[s_id][today_str] = current_count + 1
                save_json(TRACKING_FILE, tracking_data)
                
            st.session_state.start_time = time.time()
            st.rerun()
        else:
            # File d'attente active
            st.warning("⚠️ Toutes les stations d'examen sont actuellement occupées (limitation de l'API IA).")
            st.info("Vous êtes dans la file d'attente. Votre examen démarrera automatiquement dès qu'une place se libérera.")
            
            with st.spinner("Recherche d'une place disponible..."):
                time.sleep(5) # Rafraîchissement toutes les 5 secondes
                
            if st.button("🚪 Quitter la file d'attente et revenir à l'accueil", use_container_width=True):
                st.session_state.waiting_in_queue = False
                st.rerun()
            
            st.rerun() # Boucle de la file d'attente

    # Si l'utilisateur est sur l'écran d'accueil normal
    else:
        st.title("Station d'ECOS")
        actives = clean_active_sessions()
        
        col_info, col_logout = st.columns([3, 1])
        with col_info:
            st.success(f"Connecté en tant que : **{st.session_state.student_id}**")
            
            # Affichage du compteur en direct
            statut_occupation = len(actives)
            limite_occupation = current_config['max_concurrent']
            color = "🟢" if statut_occupation < limite_occupation else "🔴"
            st.caption(f"{color} **Utilisateurs actuellement en épreuve : {statut_occupation} / {limite_occupation}**")
            
            # Affichage du quota restant pour l'étudiant
            if not st.session_state.is_teacher:
                s_id = st.session_state.student_id.lower()
                current_count = tracking_data.get(s_id, {}).get(today_str, 0)
                st.caption(f"📊 *Essais restants aujourd'hui : {max_att - current_count} / {max_att}*")
                
        with col_logout:
            if st.button("🚪 Déconnexion", use_container_width=True):
                reset_to_home()
                st.session_state.authenticated = False
                st.session_state.is_teacher = False
                st.session_state.student_id = None
                st.rerun()
            
        st.info("L'épreuve comprend 2 minutes de lecture des consignes (saisie bloquée), suivies de 8 minutes d'oral.")

        index_default = CAS_DISPONIBLES.index(st.session_state.selected_cas)
        choix = st.selectbox(
            "Sélectionnez le cas clinique :",
            options=CAS_DISPONIBLES,
            index=index_default,
            format_func=lambda x: f"Cas clinique n° {x}"
        )

        if st.button("Démarrer la station (10 minutes)"):
            # On vérifie si l'étudiant a encore des essais AVANT de le mettre dans la file d'attente
            if not st.session_state.is_teacher:
                s_id = st.session_state.student_id.lower()
                current_count = tracking_data.get(s_id, {}).get(today_str, 0)
                
                if current_count >= current_config["max_attempts"]:
                    st.error("Vous avez épuisé vos essais pour aujourd'hui.")
                    st.session_state.authenticated = False
                    st.rerun()

            st.session_state.selected_cas = choix
            st.session_state.waiting_in_queue = True
            st.rerun()
        st.stop()

# -----------------------------------------------------------------------------
# 2. CHARGEMENT DU CAS SÉLECTIONNÉ ET CONFIGURATION
# -----------------------------------------------------------------------------
id_cas = st.session_state.selected_cas
cas_data = st.secrets[id_cas]

SUJET_ETUDIANT = cas_data["SUJET_ETUDIANT"]
BAREME_SECRET = cas_data["BAREME_SECRET"]
MODE_DIALOGUE = cas_data.get("MODE_INTERACTIF", False)
URL_MODELE_3D = cas_data.get("URL_MODELE_3D", None)

MESSAGE_INITIAL = cas_data.get("MESSAGE_INITIAL", "Bonjour. Vous pouvez démarrer. J'interviendrai si besoin d'informations complémentaires.")

ROLE_PAR_DEFAUT = """Tu es un examinateur neutre et rigoureux pour une station d'examen clinique objectif structuré (ECOS) de 8 minutes.

POSTURE PENDANT L'ÉCHANGE :
- Reste strictement neutre, sobre et professionnel.
- Ne formule aucun encouragement, compliment, ni formule de politesse superflue.
- Relance l'étudiant sur les points cliniques manquants ou demande des précisions.
- Sois très concis (1 à 3 phrases maximum)."""

ROLE_IA_ACTUEL = cas_data.get("ROLE_IA", ROLE_PAR_DEFAUT)

DUREE_LECTURE = 120
DUREE_ECHANGE = 480
DUREE_TOTALE = DUREE_LECTURE + DUREE_ECHANGE

MODEL_NAME = "gemini-3.5-flash-lite"

SYSTEM_INSTRUCTION_ORAL = f"""
{ROLE_IA_ACTUEL}

- INTERDICTION ABSOLUE : Ne donne jamais d'évaluation, de note, de feedback global ou de conclusion. L'épreuve est gérée par un chronomètre externe et continue tant que le temps n'est pas écoulé.
"""

SYSTEM_INSTRUCTION_EVAL = f"""
Tu es le jury d'évaluation pour une station d'ECOS.

GRILLE ET BARÈME CONFIDENTIEL DU CAS CLINIQUE :
{BAREME_SECRET}

CONSIGNES DU BILAN D'ÉVALUATION :
- Calcule la note globale selon le barème secret, basée sur l'ensemble de l'exposé de l'étudiant.
- Classe impérativement la performance dans l'une des 3 catégories suivantes :
  * « Satisfaisant » (note > 70%)
  * « En cours d'acquisition » (note comprise entre 50% et 70%)
  * « Insuffisant » (note < 50%)
- Détaille les points cliniques validés, les erreurs commises et les omissions majeures.
- RÈGLE ABSOLUE DE CONFIDENTIALITÉ : Tu ne dois JAMAIS divulguer les pourcentages, les points précis du barème ou la pondération exacte des critères, même lors du débriefing.
- POSTURE EN DÉBRIEFING : Réponds aux questions sur le raisonnement clinique en refusant fermement de donner la pondération chiffrée.
"""

st.title(f"Station d'ECOS — Cas {id_cas}")

# Initialisation de l'API
api_key = st.secrets.get("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY"))
client = genai.Client(api_key=api_key)

# Dossier patient affiché en haut
with st.expander("Consignes et dossier patient", expanded=True):
    st.markdown(SUJET_ETUDIANT, unsafe_allow_html=True)
    
    if URL_MODELE_3D:
        html_3d = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <script type="module" src="https://unpkg.com/@google/model-viewer/dist/model-viewer.min.js"></script>
            <style>
                body {{ margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }}
                details {{ border: 1px solid #e0e0e0; border-radius: 8px; padding: 10px 14px; background: #ffffff; margin-top: 10px; }}
                summary {{ font-weight: 600; cursor: pointer; color: #1f2937; outline: none; }}
                .viewer-container {{ position: relative; margin-top: 12px; width: 100%; height: 420px; background-color: #f8f9fa; border-radius: 6px; border: 1px solid #dee2e6; overflow: hidden; }}
                .viewer-container:fullscreen {{ border: none; border-radius: 0; }}
                model-viewer {{ width: 100%; height: 100%; outline: none; }}
                .btn-container {{ position: absolute; bottom: 12px; right: 12px; display: flex; gap: 8px; z-index: 10; }}
                .viewer-btn {{ background-color: #ffffff; color: #333333; border: 1px solid #cccccc; border-radius: 6px; padding: 6px 12px; font-size: 13px; font-weight: 500; cursor: pointer; box-shadow: 0 2px 4px rgba(0,0,0,0.1); transition: all 0.2s ease; }}
                .viewer-btn:hover {{ background-color: #f1f1f1; border-color: #999999; }}
            </style>
        </head>
        <body>
            <details open>
                <summary>🦷 <b>Modèle 3D interactif :</b></summary>
                <p style="font-size: 13px; color: #6b7280; margin: 8px 0;">
                    <i>Cliquez-glissez pour manipuler la dent. Utilisez la molette pour zoomer.</i>
                </p>
                <div class="viewer-container" id="fs-container">
                    <model-viewer id="dent-viewer" src="{URL_MODELE_3D}" alt="Modèle 3D dentaire" camera-controls shadow-intensity="1"></model-viewer>
                    <div class="btn-container">
                        <button class="viewer-btn" id="btn-fullscreen">⛶ Plein écran</button>
                        <button class="viewer-btn" id="btn-reset">🔄 Réinitialiser</button>
                    </div>
                </div>
            </details>
            <script>
                const viewer = document.getElementById('dent-viewer');
                const resetBtn = document.getElementById('btn-reset');
                const fullscreenBtn = document.getElementById('btn-fullscreen');
                const container = document.getElementById('fs-container');
                resetBtn.addEventListener('click', () => {{ viewer.cameraOrbit = '0deg 75deg 105%'; viewer.cameraTarget = 'auto auto auto'; viewer.fieldOfView = 'auto'; }});
                fullscreenBtn.addEventListener('click', () => {{
                    if (!document.fullscreenElement) {{ if (container.requestFullscreen) container.requestFullscreen(); else if (container.webkitRequestFullscreen) container.webkitRequestFullscreen(); }} 
                    else {{ if (document.exitFullscreen) document.exitFullscreen(); else if (document.webkitExitFullscreen) document.webkitExitFullscreen(); }}
                }});
                document.addEventListener('fullscreenchange', () => {{
                    if (document.fullscreenElement) fullscreenBtn.innerHTML = '✖ Quitter plein écran'; else fullscreenBtn.innerHTML = '⛶ Plein écran';
                }});
            </script>
        </body>
        </html>
        """
        components.html(html_3d, height=510)

st.divider()

# Calcul du temps écoulé réel
elapsed = time.time() - st.session_state.start_time

# --- PHASE 1 : LECTURE SEULE (0 à 2 minutes) ---
if elapsed < DUREE_LECTURE and not st.session_state.force_end:
    tps_restant = int(DUREE_LECTURE - elapsed)
    
    col1, col2, col3 = st.columns([2, 1, 1])
    with col2:
        if st.button("Passer la lecture", use_container_width=True):
            st.session_state.start_time = time.time() - DUREE_LECTURE
            st.rerun()
    with col3:
        if st.button("🏠 Retour accueil", use_container_width=True):
            reset_to_home()
            st.rerun()

    js_code_lecture = f"""
    <div id="chrono_lecture" style="background:#FFF3CD; color:#856404; padding:10px; border-radius:6px; font-weight:bold; font-size:16px; font-family:monospace; text-align:center; border: 1px solid #FFEEBA;">
        Synchronisation...
    </div>
    <script>
    var duration = {tps_restant};
    var endTime = Date.now() + (duration * 1000);
    var display = document.getElementById("chrono_lecture");
    
    var timer = setInterval(function() {{
        var now = Date.now();
        var remaining = Math.round((endTime - now) / 1000);
        
        if (remaining <= 0) {{
            clearInterval(timer);
            display.innerHTML = "Ouverture de l'oral...";
            window.parent.location.reload();
        }} else {{
            var mins = Math.floor(remaining / 60);
            var secs = remaining % 60;
            var form = (mins < 10 ? "0" : "") + mins + ":" + (secs < 10 ? "0" : "") + secs;
            display.innerHTML = "⏳ Phase de lecture — " + form;
        }}
    }}, 500);
    </script>
    """
    with col1:
        components.html(js_code_lecture, height=50)
        
    st.caption("Le champ de réponse est verrouillé pendant la lecture.")

# --- PHASE 2 : ÉCHANGE / EXPOSÉ (2 à 10 minutes) ---
elif elapsed < DUREE_TOTALE and not st.session_state.force_end:
    tps_restant = int(DUREE_TOTALE - elapsed)
    
    if not st.session_state.messages:
        if MODE_DIALOGUE:
            premier_message = MESSAGE_INITIAL
        else:
            premier_message = "Bonjour. Le jury vous écoute et n'interviendra pas pendant votre exposé. Procédez à votre présentation."
        st.session_state.messages.append({"role": "assistant", "content": premier_message})

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    st.write("---")

    col_chrono, col_cloture, col_retour = st.columns([2, 1, 1])
    with col_cloture:
        if st.button("Clôturer l'épreuve", use_container_width=True):
            st.session_state.force_end = True
            st.rerun()
    with col_retour:
        if st.button("🏠 Retour accueil", use_container_width=True):
            reset_to_home()
            st.rerun()

    js_code = f"""
    <div id="chrono" style="background:#D1ECF1; color:#0C5460; padding:10px; border-radius:6px; font-weight:bold; font-size:16px; font-family:monospace; text-align:center; border: 1px solid #B8DAFF;">
        Synchronisation...
    </div>
    <script>
    var duration = {tps_restant};
    var endTime = Date.now() + (duration * 1000);
    var display = document.getElementById("chrono");
    
    var timer = setInterval(function() {{
        var now = Date.now();
        var remaining = Math.round((endTime - now) / 1000);
        
        if (remaining <= 0) {{
            clearInterval(timer);
            display.innerHTML = "Temps écoulé ! Validation...";
            display.style.background = "#F8D7DA";
            display.style.color = "#721C24";
            
            var buttons = window.parent.document.querySelectorAll('button');
            buttons.forEach(function(btn) {{
                if (btn.innerText.includes("Clôturer l'épreuve")) {{
                    btn.click();
                }}
            }});
        }} else {{
            var mins = Math.floor(remaining / 60);
            var secs = remaining % 60;
            var form = (mins < 10 ? "0" : "") + mins + ":" + (secs < 10 ? "0" : "") + secs;
            display.innerHTML = "⏱️ Phase d'oral — " + form;
        }}
    }}, 500);
    </script>
    """
    with col_chrono:
        components.html(js_code, height=50)

    st.write("") 
    col_vocal, col_help, col_vide = st.columns([1.5, 1.5, 1])
    with col_vocal:
        audio_dict_2 = mic_recorder(
            start_prompt="🎙️ Enregistrer la voix",
            stop_prompt="⏹️ Arrêter et envoyer",
            key="mic_phase2"
        )
    with col_help:
        if st.button("ℹ️ Problème audio ?", key="btn_help_2"):
            st.session_state.show_help = not st.session_state.show_help
            st.rerun()

    if st.session_state.show_help:
        st.info("""**🛠️ Dépannage du microphone :**
- Si l'IA indique qu'elle n'entend aucune voix, votre navigateur enregistre probablement du silence.
- Cliquez sur l'icône de paramètres dans la barre d'adresse de votre navigateur.
- Vérifiez que le périphérique sélectionné est bien le **vrai microphone de votre ordinateur**.""")

    text_input = st.chat_input("Votre réponse par écrit...")

    user_input = None
    audio_id_2 = hash(audio_dict_2["bytes"]) if audio_dict_2 else None
    
    if audio_dict_2 and audio_id_2 != st.session_state.last_audio_id_2:
        st.session_state.last_audio_id_2 = audio_id_2
        audio_bytes = audio_dict_2["bytes"]

        with st.spinner("Transcription de votre voix..."):
            audio_part = types.Part.from_bytes(data=audio_bytes, mime_type="audio/wav")
            prompt_transcription = """Transcris exactement ce qui est dit dans cet enregistrement audio.
            CONSIGNES STRICTES :
            1. Ne génère que le texte prononcé, mot pour mot.
            2. N'inclus JAMAIS d'horodatage ou de timecode.
            3. Ne décris pas les bruits de fond ni les silences.
            4. Si tu n'entends absolument aucune voix humaine, réponds UNIQUEMENT par le mot : [AUDIO_VIDE]"""
            
            try:
                transcription_response = client.models.generate_content(
                    model=MODEL_NAME,
                    contents=[audio_part, prompt_transcription]
                )
                resultat_brut = transcription_response.text.strip()
                
                if "[AUDIO_VIDE]" in resultat_brut or "00:01" in resultat_brut:
                    st.warning("⚠️ L'IA n'a détecté aucune voix. Vérifiez vos paramètres audio (bouton ℹ️).")
                else:
                    user_input = resultat_brut
            except Exception as e:
                st.error(f"Erreur de transcription audio : {str(e)}")
                
    elif text_input:
        user_input = text_input

    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        
        if MODE_DIALOGUE:
            contents = []
            for m in st.session_state.messages:
                r = "model" if m["role"] == "assistant" else "user"
                contents.append(types.Content(role=r, parts=[types.Part.from_text(text=m["content"])]))

            try:
                response = client.models.generate_content(
                    model=MODEL_NAME,
                    contents=contents,
                    config=types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION_ORAL)
                )
                st.session_state.messages.append({"role": "assistant", "content": response.text})
            except Exception as e:
                st.error(f"Erreur API : {str(e)}")
        
        st.rerun()

# --- PHASE 3 : FIN DES 10 MINUTES ET ÉVALUATION ---
else:
    col_err, col_ret = st.columns([3, 1])
    with col_err:
        st.error("L'épreuve est terminée.")
    with col_ret:
        if st.button("🏠 Retour accueil", use_container_width=True):
            reset_to_home()
            st.rerun()

    if not st.session_state.eval_generated:
        with st.spinner("Analyse de la performance et génération du bilan évaluatif..."):
            history_text = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in st.session_state.messages])
            eval_prompt = f"Voici la transcription complète de l'oral de 8 minutes :\n\n{history_text}\n\n[TEMPS ÉCOULÉ] Rédige le bilan évaluatif en appliquant strictement les consignes sans dévoiler la pondération chiffrée."
            
            try:
                response = client.models.generate_content(
                    model=MODEL_NAME,
                    contents=eval_prompt,
                    config=types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION_EVAL)
                )
                st.session_state.messages.append({"role": "assistant", "content": response.text})
                st.session_state.eval_generated = True
            except Exception as e:
                st.error(f"Erreur évaluation : {str(e)}")
                
        st.rerun()

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    st.write("---")

    col_vocal_3, col_help_3, col_vide_3 = st.columns([1.5, 1.5, 1])
    with col_vocal_3:
        audio_dict_3 = mic_recorder(
            start_prompt="🎙️ Poser une question à l'oral",
            stop_prompt="⏹️ Arrêter et envoyer",
            key="mic_phase3"
        )
    with col_help_3:
        if st.button("ℹ️ Problème audio ?", key="btn_help_3"):
            st.session_state.show_help = not st.session_state.show_help
            st.rerun()

    if st.session_state.show_help:
        st.info("""**🛠️ Dépannage du microphone :**
- Si l'IA indique qu'elle n'entend aucune voix, votre navigateur enregistre probablement du silence.
- Cliquez sur l'icône de paramètres dans la barre d'adresse de votre navigateur.
- Vérifiez que le périphérique sélectionné est bien le **vrai microphone de votre ordinateur**.""")
        
    post_eval_text = st.chat_input("Posez vos questions sur le débriefing de l'épreuve...")

    post_eval_input = None
    audio_id_3 = hash(audio_dict_3["bytes"]) if audio_dict_3 else None

    if audio_dict_3 and audio_id_3 != st.session_state.last_audio_id_3:
        st.session_state.last_audio_id_3 = audio_id_3
        audio_bytes = audio_dict_3["bytes"]

        with st.spinner("Transcription de votre question..."):
            audio_part = types.Part.from_bytes(data=audio_bytes, mime_type="audio/wav")
            prompt_transcription = """Transcris exactement ce qui est dit dans cet enregistrement audio.
            CONSIGNES STRICTES :
            1. Ne génère que le texte prononcé, mot pour mot.
            2. N'inclus JAMAIS d'horodatage ou de timecode.
            3. Ne décris pas les bruits de fond ni les silences.
            4. Si tu n'entends absolument aucune voix humaine, réponds UNIQUEMENT par le mot : [AUDIO_VIDE]"""
            
            try:
                transcription_response = client.models.generate_content(
                    model=MODEL_NAME,
                    contents=[audio_part, prompt_transcription]
                )
                resultat_brut = transcription_response.text.strip()
                if "[AUDIO_VIDE]" not in resultat_brut and "00:01" not in resultat_brut:
                    post_eval_input = resultat_brut
                else:
                    st.warning("⚠️ L'IA n'a détecté aucune voix. Vérifiez vos paramètres audio (bouton ℹ️).")
            except Exception as e:
                st.error(f"Erreur de transcription audio : {str(e)}")
    elif post_eval_text:
        post_eval_input = post_eval_text

    if post_eval_input:
        st.session_state.messages.append({"role": "user", "content": post_eval_input})
        
        contents = []
        for m in st.session_state.messages:
            r = "model" if m["role"] == "assistant" else "user"
            contents.append(types.Content(role=r, parts=[types.Part.from_text(text=m["content"])]))

        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=contents,
                config=types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION_EVAL)
            )
            st.session_state.messages.append({"role": "assistant", "content": response.text})
        except Exception as e:
            st.error(f"Erreur débriefing : {str(e)}")
            
        st.rerun()
