import os
import time
import streamlit as st
import streamlit.components.v1 as components
from google import genai
from google.genai import types
from streamlit_mic_recorder import mic_recorder

st.set_page_config(page_title="Simulation Oral ECOS", layout="centered")

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

# --- ÉCRAN DE DÉMARRAGE AVEC SÉLECTEUR ---
if st.session_state.start_time is None:
    st.title("Station d'ECOS")
    st.info("L'épreuve comprend 2 minutes de lecture des consignes (saisie bloquée), suivies de 8 minutes d'oral.")

    index_default = CAS_DISPONIBLES.index(st.session_state.selected_cas)
    choix = st.selectbox(
        "Sélectionnez le cas clinique :",
        options=CAS_DISPONIBLES,
        index=index_default,
        format_func=lambda x: f"Cas clinique n° {x}"
    )

    if st.button("Démarrer la station (10 minutes)"):
        st.session_state.selected_cas = choix
        st.session_state.start_time = time.time()
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

DUREE_LECTURE = 120    # 2 minutes = 120 s
DUREE_ECHANGE = 480    # 8 minutes = 480 s
DUREE_TOTALE = DUREE_LECTURE + DUREE_ECHANGE  # 10 minutes = 600 s

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
    
# --- BLOC MODIFIÉ POUR AFFICHER LE MODÈLE 3D S'IL EXISTE ---
    if URL_MODELE_3D:
        html_3d = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <script type="module" src="https://unpkg.com/@google/model-viewer/dist/model-viewer.min.js"></script>
            <style>
                body {{
                    margin: 0;
                    padding: 0;
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                }}
                details {{
                    border: 1px solid #e0e0e0;
                    border-radius: 8px;
                    padding: 10px 14px;
                    background: #ffffff;
                    margin-top: 10px;
                }}
                summary {{
                    font-weight: 600;
                    cursor: pointer;
                    color: #1f2937;
                    outline: none;
                }}
                .viewer-container {{
                    position: relative;
                    margin-top: 12px;
                    width: 100%;
                    height: 420px;
                    background-color: #f8f9fa;
                    border-radius: 6px;
                    border: 1px solid #dee2e6;
                    overflow: hidden;
                }}
                .viewer-container:fullscreen {{
                    border: none;
                    border-radius: 0;
                }}
                model-viewer {{
                    width: 100%;
                    height: 100%;
                    outline: none;
                }}
                .btn-container {{
                    position: absolute;
                    bottom: 12px;
                    right: 12px;
                    display: flex;
                    gap: 8px;
                    z-index: 10;
                }}
                .viewer-btn {{
                    background-color: #ffffff;
                    color: #333333;
                    border: 1px solid #cccccc;
                    border-radius: 6px;
                    padding: 6px 12px;
                    font-size: 13px;
                    font-weight: 500;
                    cursor: pointer;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                    transition: all 0.2s ease;
                }}
                .viewer-btn:hover {{
                    background-color: #f1f1f1;
                    border-color: #999999;
                }}
            </style>
        </head>
        <body>
            <details open>
                <summary>🦷 <b>Modèle 3D interactif :</b></summary>
                <p style="font-size: 13px; color: #6b7280; margin: 8px 0;">
                    <i>Cliquez-glissez pour manipuler la dent. Utilisez la molette pour zoomer.</i>
                </p>
                <div class="viewer-container" id="fs-container">
                    <model-viewer 
                        id="dent-viewer"
                        src="{URL_MODELE_3D}" 
                        alt="Modèle 3D dentaire" 
                        camera-controls 
                        shadow-intensity="1">
                    </model-viewer>
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
                
                // Réinitialisation de la caméra
                resetBtn.addEventListener('click', () => {{
                    viewer.cameraOrbit = '0deg 75deg 105%';
                    viewer.cameraTarget = 'auto auto auto';
                    viewer.fieldOfView = 'auto';
                }});

                // Gestion du mode plein écran
                fullscreenBtn.addEventListener('click', () => {{
                    if (!document.fullscreenElement) {{
                        if (container.requestFullscreen) {{
                            container.requestFullscreen();
                        }} else if (container.webkitRequestFullscreen) {{ /* Safari */
                            container.webkitRequestFullscreen();
                        }}
                    }} else {{
                        if (document.exitFullscreen) {{
                            document.exitFullscreen();
                        }} else if (document.webkitExitFullscreen) {{
                            document.webkitExitFullscreen();
                        }}
                    }}
                }});
                
                // Mettre à jour le texte du bouton lors du changement d'état (Échap)
                document.addEventListener('fullscreenchange', () => {{
                    if (document.fullscreenElement) {{
                        fullscreenBtn.innerHTML = '✖ Quitter plein écran';
                    }} else {{
                        fullscreenBtn.innerHTML = '⛶ Plein écran';
                    }}
                }});
            </script>
        </body>
        </html>
        """
        components.html(html_3d, height=510)
    # -----------------------------------------------------------

st.divider()

# Calcul du temps écoulé réel
elapsed = time.time() - st.session_state.start_time

# --- PHASE 1 : LECTURE SEULE (0 à 2 minutes) ---
if elapsed < DUREE_LECTURE and not st.session_state.force_end:
    tps_restant = int(DUREE_LECTURE - elapsed)
    
    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("Passer la lecture", use_container_width=True):
            st.session_state.start_time = time.time() - DUREE_LECTURE
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
    
    # Message initial automatique
    if not st.session_state.messages:
        if MODE_DIALOGUE:
            premier_message = MESSAGE_INITIAL
        else:
            premier_message = "Bonjour. Le jury vous écoute et n'interviendra pas pendant votre exposé. Procédez à votre présentation."
        st.session_state.messages.append({"role": "assistant", "content": premier_message})

    # --- 1. AFFICHAGE DE L'HISTORIQUE (EN PREMIER) ---
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    st.write("---")

    # --- 2. CHRONOMÈTRE GLOBAL ET BOUTON CLÔTURE (DÉPLACÉS EN BAS) ---
    col_chrono, col_cloture = st.columns([3, 1])
    with col_cloture:
        if st.button("Clôturer l'épreuve", use_container_width=True):
            st.session_state.force_end = True
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

    # --- 3. BOUTON VOCAL ET AIDE (EN BAS) ---
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
- Cliquez sur l'icône de paramètres (ou de microphone) dans la barre d'adresse de votre navigateur.
- Vérifiez que le périphérique sélectionné est bien le **vrai microphone de votre ordinateur** (ex: Lenovo Audio) et non un câble virtuel (ex: Virtual Cable ou AudioRelay).""")

    text_input = st.chat_input("Votre réponse par écrit...")

    # --- 4. LOGIQUE DE TRANSCRIPTION STRICTE ---
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
            2. N'inclus JAMAIS d'horodatage ou de timecode (comme 00:01).
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

    # --- ENVOI DE LA RÉPONSE À L'EXAMINATEUR ---
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
    st.error("L'épreuve est terminée.")

    if not st.session_state.eval_generated:
        with st.spinner("Analyse de la performance et génération du bilan évaluatif..."):
            history_text = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in st.session_state.messages])
            eval_prompt = f"Voici la transcription complète de l'oral de 8 minutes :\n\n{history_text}\n\n[TEMPS ÉCOULÉ] Rédige le bilan évaluatif en appliquant strictement les consignes (Satisfaisant / En cours d'acquisition / Insuffisant) sans dévoiler la pondération chiffrée."
            
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

    # Affichage du fil complet avec l'évaluation (EN PREMIER)
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    st.write("---")

    # Bouton vocal et aide en bas pour le débriefing
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
- Cliquez sur l'icône de paramètres (ou de microphone) dans la barre d'adresse de votre navigateur.
- Vérifiez que le périphérique sélectionné est bien le **vrai microphone de votre ordinateur** (ex: Lenovo Audio) et non un câble virtuel (ex: Virtual Cable ou AudioRelay).""")
        
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
            2. N'inclus JAMAIS d'horodatage ou de timecode (comme 00:01).
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
