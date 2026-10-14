import io
import json
import os
import re
import time
from datetime import date, timedelta

import streamlit as st
from google import genai
from google.genai import types
from gtts import gTTS

# ---------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------
st.set_page_config(page_title="Tradutor PT ⇄ EN", page_icon="🌍", layout="centered")

MODEL_PADRAO = "gemini-3.8-flash"
STUDY_FILE = "estudo.json"
# Caixas de Leitner: dias até à próxima revisão
INTERVALS = {1: 0, 2: 1, 3: 3, 4: 7, 5: 14}


def get_secret(name, default=""):
    try:
        return st.secrets[name]
    except Exception:
        return os.environ.get(name, default)


API_KEY = get_secret("GEMINI_API_KEY")
APP_PASSWORD = get_secret("APP_PASSWORD")
# Modelo principal + reserva opcional (GEMINI_MODEL_RESERVA nos Secrets)
MODELOS = [m for m in dict.fromkeys([get_secret("GEMINI_MODEL", MODEL_PADRAO), get_secret("GEMINI_MODEL_RESERVA", "")]) if m]

# ---------------------------------------------------------------
# Acesso com palavra-passe
# ---------------------------------------------------------------
if APP_PASSWORD:
    if not st.session_state.get("auth"):
        st.title("🔒 Tradutor PT ⇄ EN")
        pwd = st.text_input("Palavra-passe", type="password")
        if st.button("Entrar"):
            if pwd == APP_PASSWORD:
                st.session_state["auth"] = True
                st.rerun()
            else:
                st.error("Palavra-passe incorreta.")
        st.stop()

if not API_KEY:
    st.error("Falta a chave GEMINI_API_KEY (em Secrets ou variável de ambiente).")
    st.stop()

client = genai.Client(api_key=API_KEY)


# ---------------------------------------------------------------
# Guardar / carregar cartões de estudo
# ---------------------------------------------------------------
def load_cards():
    if os.path.exists(STUDY_FILE):
        try:
            with open(STUDY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_cards(cards):
    try:
        with open(STUDY_FILE, "w", encoding="utf-8") as f:
            json.dump(cards, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


if "cards" not in st.session_state:
    st.session_state["cards"] = load_cards()
if "result" not in st.session_state:
    st.session_state["result"] = None
if "history" not in st.session_state:
    st.session_state["history"] = []

# ---------------------------------------------------------------
# Claude: tradução + gramática + exemplos + nível CEFR
# ---------------------------------------------------------------
SYSTEM = """És um tradutor e professor de inglês para falantes de português de Angola.
Recebes um texto e a direção pedida (auto, pt_en ou en_pt).
Responde APENAS com JSON válido, sem texto extra e sem , com esta estrutura:
{
 "source_lang": "pt" ou "en",
 "target_lang": "pt" ou "en",
 "translation": "tradução natural",
 "cefr": "A1|A2|B1|B2|C1|C2 (nível da frase em inglês)",
 "grammar": ["classes de palavras ...", "tempo verbal ...", "estrutura ...", "erro comum a evitar ..."],
 "examples": [{"en": "frase em inglês", "pt": "tradução em português de Angola"}],
 "alternatives": [{"text": "variante em inglês", "register": "formal|neutro|informal"}]
}
Regras: explicações da gramática em português de Angola; 2 exemplos curtos; até 2 alternativas; sê breve;
mantém o significado e o tom do texto original."""


def parse_json(text):
    text = text.strip()
    text = re.sub(r"^(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def _config(com_thinking):
    kwargs = dict(
        system_instruction=SYSTEM,
        response_mime_type="application/json",
        max_output_tokens=1200,
        http_options=types.HttpOptions(timeout=45000),
    )
    if com_thinking:
        # Reduz o "pensamento" do modelo para responder mais depressa
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    return types.GenerateContentConfig(**kwargs)


def chamar_gemini(prompt):
    """Tenta cada modelo até 3 vezes; repete em 503/504/429."""
    primeiro_erro = None
    com_thinking = True
    for modelo in MODELOS:
        tentativa = 0
        while tentativa < 3:
            try:
                r = client.models.generate_content(
                    model=modelo, contents=prompt, config=_config(com_thinking)
                )
                return r.text
            except Exception as e:
                erro = str(e)
                if com_thinking and ("thinking" in erro.lower() or "400" in erro):
                    com_thinking = False  # este modelo não aceita a opção: repete sem ela
                    continue
                if primeiro_erro is None:
                    primeiro_erro = e
                if any(c in erro for c in ("503", "504", "429", "UNAVAILABLE", "DEADLINE")):
                    time.sleep(1 + tentativa)
                    tentativa += 1
                    continue
                break  # outro erro (ex.: modelo inexistente): tenta o modelo seguinte
    raise primeiro_erro


@st.cache_data(show_spinner=False, ttl=60 * 60 * 24)
def translate_cached(text, direction):
    raw = chamar_gemini(f"Direção: {direction}\nTexto: {text}")
    return parse_json(raw)


@st.cache_data(show_spinner=False, ttl=60 * 60 * 24)
def speak(text, lang, slow=False):
    buf = io.BytesIO()
    gTTS(text=text, lang=lang, slow=slow).write_to_fp(buf)
    return buf.getvalue()


# ---------------------------------------------------------------
# Páginas
# ---------------------------------------------------------------
DIRECTIONS = {
    "Automático": "auto",
    "Português → Inglês": "pt_en",
    "Inglês → Português": "en_pt",
}


def page_translate():
    st.title("🌍 Tradutor PT ⇄ EN")
    col1, col2 = st.columns([3, 1])
    direction_label = col1.selectbox("Direção", list(DIRECTIONS.keys()))
    text = st.text_area("Texto", height=120, placeholder="Escreve aqui...")

    if st.button("Traduzir", type="primary"):
        if not text.strip():
            st.warning("Escreve um texto primeiro.")
        else:
            try:
                with st.spinner("A traduzir..."):
                    res = translate_cached(text.strip(), DIRECTIONS[direction_label])
                res["original"] = text.strip()
                st.session_state["result"] = res
                hist = st.session_state["history"]
                hist.insert(0, {"original": res["original"], "translation": res["translation"]})
                st.session_state["history"] = hist[:30]
            except Exception as e:
                st.error(f"Erro ao traduzir: {e}")

    res = st.session_state["result"]
    if not res:
        return

    st.subheader("Tradução")
    st.success(res["translation"])
    st.caption(f"Nível CEFR da frase em inglês: *{res.get('cefr', '?')}*")

    c1, c2, c3 = st.columns(3)
    target = res.get("target_lang", "en")
    with c1:
        if st.button("🔊 Ouvir"):
            st.session_state["audio"] = speak(res["translation"], target, False)
    with c2:
        if st.button("🐢 Ouvir devagar"):
            st.session_state["audio"] = speak(res["translation"], target, True)
    with c3:
        if st.button("⭐ Guardar"):
            en = res["translation"] if target == "en" else res["original"]
            pt = res["original"] if target == "en" else res["translation"]
            cards = st.session_state["cards"]
            if not any(c["en"] == en for c in cards):
                cards.append({
                    "en": en, "pt": pt, "cefr": res.get("cefr", ""),
                    "box": 1, "due": date.today().isoformat(),
                })
                save_cards(cards)
                st.toast("Guardado para estudo!")
            else:
                st.toast("Já estava guardado.")

    if st.session_state.get("audio"):
        st.audio(st.session_state["audio"], format="audio/mp3")

    with st.expander("📚 Gramática e exemplos", expanded=True):
        st.markdown("#### Gramática")
        for item in res.get("grammar", []):
            st.markdown(f"- {item}")
        st.markdown("#### Exemplos")
        for ex in res.get("examples", []):
            st.markdown(f"🇬🇧 *{ex['en']}*  \n🇦🇴 {ex['pt']}")
        alts = res.get("alternatives", [])
        if alts:
            st.markdown("#### Outras formas de dizer")
            for a in alts:
                st.markdown(f"- {a['text']} ({a['register']})")

    if st.session_state["history"]:
        with st.expander("🕘 Histórico"):
            for h in st.session_state["history"]:
                st.write(f"{h['original']}  →  *{h['translation']}*")


def page_study():
    st.title("🧠 Modo de estudo")
    cards = st.session_state["cards"]
    if not cards:
        st.info("Ainda não guardaste frases. Traduz e carrega em ⭐ Guardar.")
        return

    today = date.today().isoformat()
    due = [i for i, c in enumerate(cards) if c.get("due", today) <= today]
    st.caption(f"{len(due)} para rever hoje · {len(cards)} no total")

    if not due:
        st.success("Parabéns! Não há mais cartões para hoje. 🎉")
        return

    idx = st.session_state.get("study_idx")
    if idx not in due:
        idx = due[0]
        st.session_state["study_idx"] = idx
        st.session_state["show_answer"] = False

    card = cards[idx]
    st.markdown(f"### {card['pt']}")
    st.caption(f"Caixa {card.get('box', 1)} · Nível {card.get('cefr', '')}")
    answer = st.text_input("Escreve em inglês (opcional)", key=f"ans_{idx}")

    if st.button("Mostrar resposta"):
        st.session_state["show_answer"] = True

    if st.session_state.get("show_answer"):
        st.success(card["en"])
        if answer.strip():
            if answer.strip().lower().rstrip(".!?") == card["en"].lower().rstrip(".!?"):
                st.write("✅ Igual!")
            else:
                st.write("Compara com a tua resposta acima.")
        st.audio(speak(card["en"], "en"), format="audio/mp3")

        k1, k2 = st.columns(2)
        if k1.button("❌ Não sabia"):
            card["box"] = 1
            card["due"] = today
            save_cards(cards)
            st.session_state["show_answer"] = False
            st.session_state["study_idx"] = None
            st.rerun()
        if k2.button("✅ Sabia"):
            card["box"] = min(card.get("box", 1) + 1, 5)
            card["due"] = (date.today() + timedelta(days=INTERVALS[card["box"]])).isoformat()
            save_cards(cards)
            st.session_state["show_answer"] = False
            st.session_state["study_idx"] = None
            st.rerun()


def page_saved():
    st.title("⭐ Frases guardadas")
    cards = st.session_state["cards"]
    if not cards:
        st.info("Nada guardado ainda.")
        return

    for i, c in enumerate(cards):
        a, b = st.columns([6, 1])
        a.write(f"*{c['en']}*  \n{c['pt']}  (CEFR {c.get('cefr', '')})")
        if b.button("🗑️", key=f"del_{i}"):
            cards.pop(i)
            save_cards(cards)
            st.rerun()

    csv = "inglês;português;nível\n" + "\n".join(
        f"{c['en']};{c['pt']};{c.get('cefr', '')}" for c in cards
    )
    st.download_button("⬇️ Exportar CSV (Excel)", csv.encode("utf-8-sig"),
                       "frases_guardadas.csv", "text/csv")


# ---------------------------------------------------------------
# Navegação
# ---------------------------------------------------------------
page = st.sidebar.radio("Menu", ["Traduzir", "Estudar", "Guardadas"])
if page == "Traduzir":
    page_translate()
elif page == "Estudar":
    page_study()
else:
    page_saved()