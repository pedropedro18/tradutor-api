import io
import re
import time

import streamlit as st
from deep_translator import (
    GoogleTranslator,
    LingueeTranslator,
    MyMemoryTranslator,
    PonsTranslator,
)
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
        if not f.strip():
            continue
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
    # Opcional: com email o MyMemory permite muito mais pedidos por dia
    try:
        return st.secrets.get("MYMEMORY_EMAIL", None)
    except Exception:
        return None


def tentar(funcao, tentativas=2, espera=1.5):
    """Tenta de novo depois de uma pequena pausa (ajuda com limite de pedidos)."""
    ultimo_erro = None
    for i in range(tentativas):
        try:
            resultado = funcao()
            if resultado and str(resultado).strip():
                return resultado
        except Exception as e:
            ultimo_erro = e
        if i < tentativas - 1:
            time.sleep(espera)
    raise ultimo_erro or RuntimeError("Sem resultado")


def via_google(texto, origem, destino):
    return GoogleTranslator(source=origem, target=destino).translate(texto)


def via_mymemory(texto, origem, destino):
    mm = MyMemoryTranslator(
        source=NOMES_MM[origem],
        target=NOMES_MM[destino],
        email=email_mymemory(),
    )
    return " ".join(mm.translate(p) for p in partir_texto(texto))


def via_linguee(texto, origem, destino):
    # Bom para palavras soltas e expressões curtas
    return LingueeTranslator(
        source=NOMES_MM[origem], target=NOMES_MM[destino]
    ).translate(texto, return_all=False)


def via_pons(texto, origem, destino):
    # Bom para palavras soltas
    return PonsTranslator(
        source=NOMES_MM[origem], target=NOMES_MM[destino]
    ).translate(texto, return_all=False)


@st.cache_data(show_spinner=False, ttl=60 * 60 * 24)
def traduzir(texto, origem, destino):
    """Tenta vários serviços, um a seguir ao outro, até um funcionar."""
    metodos = [via_google, via_mymemory]
    # Para textos curtos (palavras/expressões), há mais opções
    if len(texto.split()) <= 3:
        metodos += [via_linguee, via_pons]

    erros = []
    for metodo in metodos:
        try:
            return tentar(lambda: metodo(texto, origem, destino))
        except Exception as e:
            erros.append(f"{metodo._name_}: {e}")

    raise RuntimeError(
        "Todos os serviços estão ocupados. Espera um minuto e tenta de novo."
    )


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
col1.markdown(f"De: {NOMES[origem]}")
col2.button("⇄ Inverter", on_click=inverter)
col3.markdown(f"Para: {NOMES[destino]}")

texto = st.text_area("Texto", height=150, placeholder="Escreve aqui...")

if st.button("Traduzir", type="primary"):
    if not texto.strip():
        st.warning("Escreve um texto primeiro.")
    else:
        try:
            with st.spinner("A traduzir..."):
                resultado = traduzir(texto.strip(), origem, destino)
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
            st.markdown(f"{de}: {t}  \n*{para}:* {r}")
            st.divider()
        if st.button("Limpar histórico"):
            st.session_state.historico = []
            st.rerun()