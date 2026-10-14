import io
import re

import streamlit as st
from deep_translator import GoogleTranslator, MyMemoryTranslator
from gtts import gTTS

st.set_page_config(page_title="Tradutor PT ⇄ EN", page_icon="🌍")
st.title("🌍 Tradutor Português ⇄ Inglês")

NOMES = {"pt": "Português", "en": "English"}
NOMES_MM = {"pt": "portuguese", "en": "english"}


def partir_texto(texto, limite=450):
    """Divide o texto em pedaços pequenos (o MyMemory aceita ~500 caracteres)."""
    frases = re.split(r"(?<=[.!?])\s+|\n", texto)
    pedacos, atual = [], ""
    for f in frases:
        if len(atual) + len(f) + 1 <= limite:
            atual = f"{atual} {f}".strip()
        else:
            if atual:
                pedacos.append(atual)
            atual = f[:limite]
    if atual:
        pedacos.append(atual)
    return pedacos


def email_mymemory():
    # Opcional: com email o MyMemory permite muito mais caracteres por dia
    try:
        return st.secrets.get("MYMEMORY_EMAIL", None)
    except Exception:
        return None


def traduzir(texto, origem, destino):
    # 1.º tenta o Google; se falhar (limite de pedidos), usa o MyMemory
    try:
        return GoogleTranslator(source=origem, target=destino).translate(texto)
    except Exception:
        mm = MyMemoryTranslator(
            source=NOMES_MM[origem],
            target=NOMES_MM[destino],
            email=email_mymemory(),
        )
        return " ".join(mm.translate(p) for p in partir_texto(texto))


# Estado
if "direcao" not in st.session_state:
    st.session_state.direcao = "pt-en"
if "historico" not in st.session_state:
    st.session_state.historico = []


def inverter():
    st.session_state.direcao = (
        "en-pt" if st.session_state.direcao == "pt-en" else "pt-en"
    )


origem, destino = st.session_state.direcao.split("-")

col1, col2, col3 = st.columns([5, 2, 5])
col1.markdown(f"*De:* {NOMES[origem]}")
col2.button("⇄ Inverter", on_click=inverter)
col3.markdown(f"*Para:* {NOMES[destino]}")

texto = st.text_area("Texto", height=150, placeholder="Escreve aqui...")

if st.button("Traduzir", type="primary"):
    if not texto.strip():
        st.warning("Escreve um texto primeiro.")
    else:
        try:
            with st.spinner("A traduzir..."):
                resultado = traduzir(texto, origem, destino)
            st.session_state.ultimo = (resultado, destino)
            st.session_state.historico.insert(
                0, (NOMES[origem], texto, NOMES[destino], resultado)
            )
        except Exception as e:
            st.error(f"Erro ao traduzir: {e}")

if "ultimo" in st.session_state:
    resultado, lang = st.session_state.ultimo
    st.subheader("Tradução")
    st.success(resultado)
    st.code(resultado, language=None)  # botão de copiar

    if st.button("🔊 Ouvir"):
        try:
            audio = io.BytesIO()
            gTTS(resultado, lang=lang).write_to_fp(audio)
            st.audio(audio.getvalue(), format="audio/mp3")
        except Exception as e:
            st.error(f"Erro no áudio: {e}")

if st.session_state.historico:
    with st.expander("Histórico"):
        for de, t, para, r in st.session_state.historico[:10]:
            st.markdown(f"*{de}:* {t}  \n*{para}:* {r}")
            st.divider()
        if st.button("Limpar histórico"):
            st.session_state.historico = []
            st.rerun()