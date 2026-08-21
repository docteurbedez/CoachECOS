import os
import time
import streamlit as st
import streamlit.components.v1 as components
from google import genai
from google.genai import types

# -----------------------------------------------------------------------------
# 1. PARAMÉTRAGE DYNAMIQUE DU CAS (1 À 8) VIA L'URL
# -----------------------------------------------------------------------------

# Récupération du paramètre "cas" dans l'URL (par défaut : "1")
id_cas = str(st.query_params.get("cas", "1")).strip()

# Liste des identifiants valides
CAS_VALIDES = [str(i) for i in range(1, 9)]

if id_cas not in CAS_VALIDES or id_cas not in st.secrets:
    st.error(f"Erreur : Le dossier clinique '{id_cas}' n'existe pas ou n'est pas configuré. Veuillez utiliser un numéro de 1 à 8 valide.")
    st.stop()

# Chargement des paramètres du cas sélectionné
cas_data = st.secrets[id_cas]
SUJET_ETUDIANT = cas_data["SUJET_ETUDIANT"]
BAREME_SECRET = cas_data["BAREME_SECRET"]
MODE_DIALOGUE = cas_data.get("MODE_INTERACTIF", False)

DUREE_LECTURE = 120    # 2 minutes = 120 s
DUREE_ECHANGE = 480    # 8 minutes = 480 s
DUREE_TOTALE = DUREE_LECTURE + DUREE_ECHANGE  # 10 minutes = 600 s

MODEL_NAME = "gemini-3.6-flash"

SYSTEM_INSTRUCTION = f"""
Tu es un examinateur neutre et rigoureux pour une station d'examen clinique objectif structuré (ECOS) de 8 minutes.

POSTURE PENDANT L'ÉCHANGE (si mode interactif activé) :
- Reste strictement neutre, sobre et professionnel.
- Ne formule aucun encouragement, compliment, ni formule de politesse superflue.
- Relance l'étudiant sur les points cliniques manquants.
- Sois très concis (1 à 3 phrases).

GRILLE ET BARÈME CONFIDENTIEL DU CAS CLINIQUE :
{BAREME_SECRET}

INSTRUCTIONS POUR LE BILAN D'ÉVALUATION (déclenché à la fin des 10 minutes) :
- Calcule la note globale selon le barème secret, basée sur l'ensemble de l'exposé de l'étudiant.
- Classe impérativement la performance dans l'une des 3 catégories suivantes :
  * « Satisfaisant » (note > 70%)
  * « En cours d'acquisition » (note comprise entre 50% et 70%)
  * « Insuffisant » (note < 50%)
- Détaille les points cliniques validés, les erreurs commises et les omissions majeures.
- RÈGLE ABSOLUE DE CONFIDENTIALITÉ : Tu ne dois JAMAIS divulguer les pourcentages, les points précis du barème ou la pondération exacte des critères, même lors du débriefing.

POSTURE EN PHASE DE DÉBRIEFING (après l'évaluation) :
- Réponds aux questions de l'étudiant sur le raisonnement clinique.
- Refuse fermement de donner la pondération chiffrée.
"""

st.set_page_config(page_title=f"ECOS — Station {id_cas}", layout="centered")
st.title(f"Station d'évaluation standardisée — Cas {id_cas}")

# Initialisation de l'API
api_key = st.secrets.get("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY"))
client = genai.Client(api_key=api_key)

# Gestion de l'état de session
if "start_time" not in st.session_state:
    st.session_state.start_time = None
if "messages" not in st.session_state:
    st.session_state.messages = []
if "eval_generated" not in st.session_state:
    st.session_state.eval_generated = False
if "force_end" not in st.session_state:
    st.session_state.force_end = False

# Écran de démarrage
if st.session_state.start_time is None:
    st.info("L'épreuve comprend 2 minutes de lecture des consignes (saisie bloquée), suivies de 8 minutes d'exposé ou de dialogue.")
    
    if st.button("Démarrer la station (10 minutes)"):
        st.session_state.start_time = time.time()
        st.rerun()
    st.stop()

# Dossier patient affiché en haut
with st.expander("Consignes et dossier patient", expanded=True):
    st.markdown(SUJET_ETUDIANT)

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
            display.innerHTML = "⏱️ Phase d'exposé — " + form;
        }}
    }}, 500);
    </script>
    """
    with col1:
        components.html(js_code, height=50)

    # Message initial automatique adapté au mode
    if not st.session_state.messages:
        if MODE_DIALOGUE:
            premier_message = "Bonjour. Vous pouvez démarrer. J'interviendrai si besoin d'informations complémentaires."
        else:
            premier_message = "Bonjour. Le jury vous écoute et n'interviendra pas pendant votre exposé. Procédez à votre présentation."
        st.session_state.messages.append({"role": "assistant", "content": premier_message})

    # Affichage de l'historique
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Zone de saisie
    user_input = st.chat_input("Votre réponse...")
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
                    config=types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION)
                )
                st.session_state.messages.append({"role": "assistant", "content": response.text})
            except Exception as e:
                st.error(f"Erreur API : {str(e)}")
        else:
            # Mode Exposé (sans patient standardisé) : pas d'appel API intermédiaire
            pass
            
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
                    config=types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION)
                )
                st.session_state.messages.append({"role": "assistant", "content": response.text})
                st.session_state.eval_generated = True
            except Exception as e:
                st.error(f"Erreur évaluation : {str(e)}")
                
        st.rerun()

    # Affichage du fil complet avec l'évaluation
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Questions post-évaluation
    post_eval_input = st.chat_input("Posez vos questions sur le débriefing de l'épreuve...")
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
                config=types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION)
            )
            st.session_state.messages.append({"role": "assistant", "content": response.text})
        except Exception as e:
            st.error(f"Erreur débriefing : {str(e)}")
            
        st.rerun()
