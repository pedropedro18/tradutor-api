import io
import json
import os
import re
import time
from datetime import date, timedelta

import streamlit as st
from gtts import gTTS

try:
    from google import genai
    from google.genai import types
except Exception:  # sem Gemini, a app usa só o deep-translator
    genai = None
    types = None

try:
    from deep_translator import GoogleTranslator, MyMemoryTranslator
except Exception:
    GoogleTranslator = None
    MyMemoryTranslator = None

# ---------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------
st.set_page_config(page_title="Tradutor PT ⇄ EN", page_icon="🌍", layout="centered")

MODEL_PADRAO = "gemini-3.8-flash"
TIMEOUT_MS = 15000  # mínimo permitido pelo Gemini é 10000
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
MODELOS = [
    m for m in dict.fromkeys(
        [get_secret("GEMINI_MODEL", MODEL_PADRAO), get_secret("GEMINI_MODEL_RESERVA", "")]
    ) if m
]

# ---------------------------------------------------------------
# Acesso com palavra-passe (só se APP_PASSWORD existir nos Secrets)
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

client = genai.Client(api_key=API_KEY) if (genai and API_KEY) else None
if client is None and GoogleTranslator is None:
    st.error("Falta a chave GEMINI_API_KEY ou o pacote deep-translator.")
    st.stop()


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
# Tradução: Gemini (rápido) e, se falhar, Google Translate / MyMemory
# ---------------------------------------------------------------
PT_PALAVRAS = {
    "o", "a", "os", "as", "um", "uma", "de", "do", "da", "que", "e", "é", "não",
    "para", "com", "em", "eu", "tu", "ele", "ela", "nós", "você", "estou", "está",
    "estás", "tenho", "tem", "quero", "gosto", "bom", "boa", "obrigado", "obrigada",
    "ir", "jogar", "casa", "como", "onde", "quando", "porque", "muito", "meu", "minha",
}


def parece_portugues(texto):
    t = texto.lower()
    if re.search(r"[ãõçáéíóúâêô]", t):
        return True
    palavras = set(re.findall(r"[a-zçãõáéíóúâêô]+", t))
    return len(palavras & PT_PALAVRAS) > 0


def alvo_da_direcao(texto, direction):
    if direction == "pt_en":
        return "en"
    if direction == "en_pt":
        return "pt"
    return "en" if parece_portugues(texto) else "pt"


def _config(com_thinking):
    kwargs = dict(
        system_instruction=(
            "És um tradutor entre português de Angola e inglês. "
            "Responde APENAS com a tradução, sem explicações, sem aspas e sem notas."
        ),
        max_output_tokens=300,
        http_options=types.HttpOptions(timeout=TIMEOUT_MS),
    )
    if com_thinking:
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    return types.GenerateContentConfig(**kwargs)


def traduzir_gemini(texto, alvo):
    idioma = "inglês" if alvo == "en" else "português de Angola"
    prompt = f"Traduz para {idioma}:\n{texto}"
    com_thinking = True
    erros = []
    for modelo in MODELOS:
        tentativa = 0
        while tentativa < 2:
            try:
                r = client.models.generate_content(
                    model=modelo, contents=prompt, config=_config(com_thinking)
                )
                saida = (r.text or "").strip()
                if saida:
                    return saida
                erros.append(f"{modelo}: resposta vazia")
                break
            except Exception as e:
                erro = str(e)
                if com_thinking and ("thinking" in erro.lower() or "400" in erro):
                    com_thinking = False
                    continue
                if any(c in erro for c in ("503", "429", "UNAVAILABLE")) and tentativa == 0:
                    time.sleep(1)
                    tentativa += 1
                    continue
                erros.append(f"{modelo}: {erro[:300]}")
                break  # 504, modelo inexistente, etc.: passa ao seguinte
    raise RuntimeError("Gemini indisponível -> " + " || ".join(erros))


def traduzir_deep(texto, alvo):
    origem = "pt" if alvo == "en" else "en"
    erros = []
    if GoogleTranslator is not None:
        try:
            return GoogleTranslator(source=origem, target=alvo).translate(texto)
        except Exception as e:
            erros.append(f"Google Translate: {str(e)[:150]}")
    if MyMemoryTranslator is not None:
        try:
            src = "portuguese" if origem == "pt" else "english"
            dst = "english" if alvo == "en" else "portuguese"
            return MyMemoryTranslator(source=src, target=dst).translate(texto)
        except Exception as e:
            erros.append(f"MyMemory: {str(e)[:150]}")
    raise RuntimeError(" | ".join(erros) or "Nenhum tradutor disponível")


@st.cache_data(show_spinner=False, ttl=60 * 60 * 24)
def translate_cached(texto, direction):
    alvo = alvo_da_direcao(texto, direction)
    motor = "Gemini"
    try:
        if client is None:
            raise RuntimeError("client é None (chave não lida dos Secrets?)")
        traducao = traduzir_gemini(texto, alvo)
    except Exception as e:
        erro_gemini = str(e)
        try:
            traducao = traduzir_deep(texto, alvo)
            motor = "Google Translate / MyMemory"
        except Exception as e2:
            raise RuntimeError(f"{erro_gemini} | {e2}")
    return {"translation": traducao, "target_lang": alvo, "motor": motor}


@st.cache_data(show_spinner=False, ttl=60 * 60 * 24)
def speak(texto, lang, slow=False):
    buf = io.BytesIO()
    gTTS(text=texto, lang=lang, slow=slow).write_to_fp(buf)
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
    direction_label = st.selectbox("Direção", list(DIRECTIONS.keys()))
    text = st.text_area("Texto", height=120, placeholder="Escreve aqui...")

    if st.button("Traduzir", type="primary"):
        if not text.strip():
            st.warning("Escreve um texto primeiro.")
        else:
            try:
                with st.spinner("A traduzir..."):
                    res = translate_cached(text.strip(), DIRECTIONS[direction_label])
                res = dict(res)
                res["original"] = text.strip()
                st.session_state["result"] = res
                st.session_state["audio"] = None
                hist = st.session_state["history"]
                hist.insert(0, {"original": res["original"], "translation": res["translation"]})
                st.session_state["history"] = hist[:30]
            except Exception as e:
                st.error(f"Erro ao traduzir: {e}")

    res = st.session_state["result"]
    if not res:
        return

    target = res.get("target_lang", "en")
    st.subheader("Tradução")
    st.success(res["translation"])
    st.caption(f"Motor: {res.get('motor', '?')}")

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("🔊 Ouvir"):
            try:
                st.session_state["audio"] = speak(res["translation"], target, False)
            except Exception:
                st.warning("Não foi possível gerar o áudio agora.")
    with c2:
        if st.button("🐢 Ouvir devagar"):
            try:
                st.session_state["audio"] = speak(res["translation"], target, True)
            except Exception:
                st.warning("Não foi possível gerar o áudio agora.")
    with c3:
        if st.button("⭐ Guardar"):
            en = res["translation"] if target == "en" else res["original"]
            pt = res["original"] if target == "en" else res["translation"]
            cards = st.session_state["cards"]
            if not any(c["en"] == en for c in cards):
                cards.append({"en": en, "pt": pt, "box": 1, "due": date.today().isoformat()})
                save_cards(cards)
                st.toast("Guardado para estudo!")
            else:
                st.toast("Já estava guardado.")

    if st.session_state.get("audio"):
        st.audio(st.session_state["audio"], format="audio/mp3")

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
    st.caption(f"Caixa {card.get('box', 1)}")
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
        try:
            st.audio(speak(card["en"], "en"), format="audio/mp3")
        except Exception:
            pass

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
        a.write(f"*{c['en']}*  \n{c['pt']}")
        if b.button("🗑️", key=f"del_{i}"):
            cards.pop(i)
            save_cards(cards)
            st.rerun()

    csv = "inglês;português\n" + "\n".join(f"{c['en']};{c['pt']}" for c in cards)
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