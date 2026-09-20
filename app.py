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
    
    col1, col2 = st.columns([3, 1])
    with col2:
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
    with col1:
        components.html(js_code, height=50)

    # --- PLACEMENT FIXE DU BOUTON VOCAL EN HAUT ---
    st.write("---")
    col_vocal, col_vide = st.columns([2, 1])
    with col_vocal:
        audio_dict_2 = mic_recorder(
            start_prompt="🎙️ Enregistrer la voix",
            stop_prompt="⏹️ Arrêter et envoyer",
            key="mic_phase2"
        )
    st.caption("*(Autorisez le micro lors du 1er clic. Le bouton restera toujours visible ici)*")
    st.divider()

    # Message initial automatique
    if not st.session_state.messages:
        if MODE_DIALOGUE:
            premier_message = MESSAGE_INITIAL
        else:
            premier_message = "Bonjour. Le jury vous écoute et n'interviendra pas pendant votre exposé. Procédez à votre présentation."
        st.session_state.messages.append({"role": "assistant", "content": premier_message})

    # Affichage de l'historique
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Champ de texte classique en bas
    text_input = st.chat_input("Votre réponse par écrit...")

    # --- LOGIQUE DE TRAITEMENT DE L'ENTRÉE (VOIX OU TEXTE) ---
    user_input = None
    
    # 1. On vérifie si un nouvel audio a été enregistré via un hash de l'audio
    audio_id_2 = hash(audio_dict_2["bytes"]) if audio_dict_2 else None
    
    if audio_dict_2 and audio_id_2 != st.session_state.last_audio_id_2:
        # C'est un nouvel enregistrement ! On met à jour l'ID
        st.session_state.last_audio_id_2 = audio_id_2
        
        with st.spinner("Transcription de votre voix par l'IA..."):
            audio_bytes = audio_dict_2["bytes"]
            audio_part = types.Part.from_bytes(data=audio_bytes, mime_type="audio/webm")
            
            try:
                # On demande à Gemini de faire uniquement de la transcription
                transcription_response = client.models.generate_content(
                    model=MODEL_NAME,
                    contents=[
                        audio_part, 
                        "Transcris exactement cet enregistrement vocal en français. Ne réponds pas à l'audio, écris uniquement ce qui est dit, sans commentaires."
                    ]
                )
                user_input = transcription_response.text
            except Exception as e:
                st.error(f"Erreur de transcription audio : {str(e)}")
                
    # 2. Sinon, on vérifie si l'utilisateur a tapé du texte
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

    # Synthèse évaluative
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

    # Bouton vocal pour la phase de débriefing
    st.write("---")
    col_vocal_3, col_vide_3 = st.columns([2, 1])
    with col_vocal_3:
        audio_dict_3 = mic_recorder(
            start_prompt="🎙️ Poser une question à l'oral",
            stop_prompt="⏹️ Arrêter et envoyer",
            key="mic_phase3"
        )
    st.divider()

    # Affichage du fil complet avec l'évaluation
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Champ texte pour la phase de débriefing
    post_eval_text = st.chat_input("Posez vos questions sur le débriefing de l'épreuve...")

    # Logique de traitement de la question de débriefing
    post_eval_input = None
    audio_id_3 = hash(audio_dict_3["bytes"]) if audio_dict_3 else None

    if audio_dict_3 and audio_id_3 != st.session_state.last_audio_id_3:
        st.session_state.last_audio_id_3 = audio_id_3
        with st.spinner("Transcription de votre question..."):
            audio_bytes = audio_dict_3["bytes"]
            audio_part = types.Part.from_bytes(data=audio_bytes, mime_type="audio/webm")
            try:
                transcription_response = client.models.generate_content(
                    model=MODEL_NAME,
                    contents=[audio_part, "Transcris exactement cet enregistrement vocal en français. N'ajoute aucun commentaire."]
                )
                post_eval_input = transcription_response.text
            except Exception as e:
                st.error(f"Erreur de transcription audio : {str(e)}")
    elif post_eval_text:
        post_eval_input = post_eval_text

    # Envoi de la question
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
