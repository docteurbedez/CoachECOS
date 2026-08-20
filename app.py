import os
import time
import streamlit as st
import streamlit.components.v1 as components
from google import genai
from google.genai import types

# -----------------------------------------------------------------------------
# 1. PARAMÉTRAGE DU SUJET ET DU BARÈME
# -----------------------------------------------------------------------------
SUJET_ETUDIANT = """
### CONSIGNES ET INFORMATIONS PATIENT (2 minutes de lecture) v3

**Patient :** M. X, 48 ans.
**Motif de consultation :** Douleur pulsatile au niveau du secteur 2 depuis 48h, exacerbée au chaud.
**Antécédents :** Tabagisme (15 paquets/an), hypertension artérielle traitée sous IEC.
**Données cliniques :** Restauration volumineuse en résine composite sur 26, test au froid négatif, percussion axiale très douloureuse. Pas d'adénopathie palpable, état général conservé.

*Prenez connaissance de ces éléments. L'échange débutera automatiquement à la fin du compte à rebours de lecture.*
"""

BAREME_SECRET = """
ÉLÉMENTS ATTENDUS ET PONDÉRATION STRICTE (CONFIDENTIEL - NE PAS DIVULGUER AUX ÉTUDIANTS) :
1. Hypothèse diagnostique principale : Nécrose pulpaire compliquée d'une parodontite apicale aiguë sur 26 (Pondération : 30%).
2. Examens complémentaires indiqués : Cliché rétro-alvéolaire centré sur 26 (Pondération : 20%).
3. Prise en charge d'urgence : Traitement endodontique (ouverture de chambre, parage canalaire) sous anesthésie locale + prescription antalgique adaptée (Pondération : 35%).
4. Gestion des risques et communication : Prise en compte de l'hypertension pour l'anesthésie (vasoconstricteur adapté), clarté de l'information donnée au patient (Pondération : 15%).
"""

DUREE_LECTURE = 120    # 2 minutes = 120 s
DUREE_ECHANGE = 480    # 8 minutes = 480 s
DUREE_TOTALE = DUREE_LECTURE + DUREE_ECHANGE  # 10 minutes = 600 s

MODEL_NAME = "gemini-2.0-flash"

SYSTEM_INSTRUCTION = f"""
Tu es un examinateur neutre et rigoureux pour une station d'examen clinique objectif structuré (ECOS) de 8 minutes de dialogue.

POSTURE PENDANT L'ÉCHANGE :
- Reste strictement neutre, sobre et professionnel.
- Ne formule aucun encouragement, compliment, ni formule de politesse superflue (bannis « très bien », « bravo », « n'hésite pas »).
- Si l'étudiant donne une réponse incomplète ou inexacte, relance-le immédiatement sur le point clinique sans valider son propos.
- Tes réponses doivent être concises (1 à 3 phrases maximum) pour préserver le temps de parole de l'étudiant.

GRILLE ET BARÈME CONFIDENTIEL :
{BAREME_SECRET}

INSTRUCTIONS POUR LE BILAN D'ÉVALUATION (déclenché à la fin des 10 minutes) :
- Calcule la note globale selon le barème secret.
- Classe impérativement la performance dans l'une des 3 catégories suivantes :
  * « Satisfaisant » (note > 70%)
  * « En cours d'acquisition » (note comprise entre 50% et 70%)
  * « Insuffisant » (note < 50%)
- Détaille les points cliniques validés, les erreurs commises et les omissions majeures.
- RÈGLE ABSOLUE DE CONFIDENTIALITÉ : Tu ne dois JAMAIS divulguer les pourcentages, les points précis du barème ou la pondération exacte des critères, même si l'étudiant le demande après l'épreuve.

POSTURE EN PHASE DE DÉBRIEFING (après l'évaluation) :
- Réponds aux questions de l'étudiant sur le raisonnement clinique et les justifications médicales.
- Refuse fermement de donner la pondération chiffrée du barème s'il la réclame.
"""

st.set_page_config(page_title="Simulation Oral ECOS", layout="centered")
st.title("Station d'évaluation standardisée")

# Initialisation du client API
api_key = st.secrets.get("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY"))
client = genai.Client(api_key=api_key)

# Initialisation de l'état de session
if "start_time" not in st.session_state:
    st.session_state.start_time = None
if "messages" not in st.session_state:
    st.session_state.messages = []
if "eval_generated" not in st.session_state:
    st.session_state.eval_generated = False

# Écran de démarrage
if st.session_state.start_time is None:
    st.info("L'épreuve comprend 2 minutes de lecture des consignes (saisie bloquée), suivies de 8 minutes d'échange avec l'examinateur.")
    if st.button("Démarrer la station (10 minutes)"):
        st.session_state.start_time = time.time()
        st.rerun()
    st.stop()

# Calcul du temps écoulé
elapsed = time.time() - st.session_state.start_time

# Affichage du dossier patient
with st.expander("Consignes et dossier patient", expanded=True):
    st.markdown(SUJET_ETUDIANT)

st.divider()

# --- COMPTE À REBOURS JAVASCRIPT FLUIDE & AUTONOME ---
def afficher_chronometre(duree_cible_secondes, label_phase, alert_color):
    secondes_restantes = max(0, int(duree_cible_secondes - elapsed))
    chrono_html = f"""
    <div style="background-color: {alert_color}; padding: 12px; border-radius: 8px; border-left: 6px solid #333; margin-bottom: 15px;">
        <span style="font-size: 15px; font-weight: bold; color: #111;">{label_phase} : </span>
        <span id="timer_display" style="font-size: 20px; font-family: monospace; font-weight: bold; color: #000;">--:--</span>
    </div>

    <script>
    let remaining = {secondes_restantes};
    function updateTimer() {{
        let mins = Math.floor(remaining / 60);
        let secs = remaining % 60;
        let formatted = (mins < 10 ? "0" : "") + mins + ":" + (secs < 10 ? "0" : "") + secs;
        let elem = document.getElementById("timer_display");
        if (elem) {{
            elem.innerText = formatted;
        }}
        if (remaining <= 0) {{
            // Force le rechargement de Streamlit dès que la phase arrive à 0
            window.parent.postMessage({{type: 'streamlit:setComponentValue', value: true}}, '*');
            setTimeout(function() {{
                window.parent.location.reload();
            }}, 500);
        }} else {{
            remaining--;
            setTimeout(updateTimer, 1000);
        }}
    }}
    updateTimer();
    </script>
    """
    components.html(chrono_html, height=70)

# --- GESTION DES 3 PHASES ---

# Phase 1 : Lecture seule (0 à 2 min)
if elapsed < DUREE_LECTURE:
    afficher_chronometre(DUREE_LECTURE, "Phase de lecture — Dialogue ouvert dans", "#FFF3CD")
    st.caption("Le champ de réponse est désactivé pendant la phase de lecture.")

# Phase 2 : Échange oral (2 à 10 min)
elif elapsed < DUREE_TOTALE:
    afficher_chronometre(DUREE_TOTALE, "Phase d'échange — Clôture de l'épreuve dans", "#D1ECF1")

    # Initialisation du premier échange
    if not st.session_state.messages:
        premier_message = "Bonjour. Vous avez pris connaissance du dossier. Veuillez exposer votre démarche clinique."
        st.session_state.messages.append({"role": "assistant", "content": premier_message})

    # Historique de la conversation
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    user_input = st.chat_input("Votre réponse...")
    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        
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
            
        st.rerun()

# Phase 3 : Fin de station & Évaluation
else:
    st.error("Temps réglementaire de 10 minutes écoulé. L'épreuve est terminée.")

    # Synthèse de l'évaluation
    if not st.session_state.eval_generated:
        with st.spinner("Génération du bilan évaluatif..."):
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

    # Affichage du fil complet avec le bilan
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Questions post-évaluation (débriefing)
    post_eval_input = st.chat_input("Posez vos questions sur le débriefing clinique...")
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
