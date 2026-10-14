import io
import json
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


# ---------- Palavra-passe ----------
def verificar_acesso():
    if st.session_state.get("autorizado"):
        return
    senha = st.text_input("Palavra-passe", type="password")
    if st.button("Entrar"):
        if senha == st.secrets.get("APP_PASSWORD", ""):
            st.session_state.autorizado = True
            st.rerun()
        else:
            st.error("Palavra-passe errada.")
    st.stop()


verificar_acesso()

NOMES = {"pt": "Português", "en": "English"}
NOMES_MM = {"pt": "portuguese", "en": "english"}
MODELO_GEMINI = "gemini-2.5-flash"


# ---------- Tradução ----------
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
    return LingueeTranslator(
        source=NOMES_MM[origem], target=NOMES_MM[destino]
    ).translate(texto, return_all=False)


def via_pons(texto, origem, destino):
    return PonsTranslator(
        source=NOMES_MM[origem], target=NOMES_MM[destino]
    ).translate(texto, return_all=False)


@st.cache_data(show_spinner=False, ttl=60 * 60 * 24)
def traduzir(texto, origem, destino):
    """Tenta vários serviços, um a seguir ao outro, até um funcionar."""
    metodos = [via_google, via_mymemory]
    if len(texto.split()) <= 3:
        metodos += [via_linguee, via_pons]

    ultimo_erro = None
    for metodo in metodos:
        try:
            return tentar(lambda m=metodo: m(texto, origem, destino))
        except Exception as e:
            ultimo_erro = e

    raise RuntimeError(f"Todos os serviços falharam. Último erro: {ultimo_erro}")


# ---------- Gramática e exemplos (Gemini) ----------
def chave_gemini():
    try:
        return st.secrets.get("GEMINI_API_KEY", None)
    except Exception:
        return None


def modelo_gemini():
    try:
        return st.secrets.get("GEMINI_MODEL", MODELO_GEMINI)
    except Exception:
        return MODELO_GEMINI


@st.cache_data(show_spinner=False, ttl=60 * 60 * 24)
def analisar(original, traducao, origem):
    from google import genai

    ingles = original if origem == "en" else traducao
    portugues = traducao if origem == "en" else original

    prompt = f"""És professor de inglês em Angola. Analisa este texto.

Inglês: {ingles}
Português: {portugues}

Responde APENAS com JSON válido (sem markdown, sem texto extra), neste formato:
{{
  "gramatica": "explicação em português, em tópicos curtos: classes de palavras importantes, tempo verbal, estrutura da frase e um erro comum a evitar",
  "exemplos": [
    {{"en": "frase em inglês", "pt": "tradução em português"}},
    {{"en": "frase em inglês", "pt": "tradução em português"}},
    {{"en": "frase em inglês", "pt": "tradução em português"}}
  ]
}}
Os exemplos devem usar o vocabulário principal do texto, com frases simples."""

    client = genai.Client(api_key=chave_gemini())
    resp = client.models.generate_content(
        model=modelo_gemini(),
        contents=prompt,
        config={"response_mime_type": "application/json"},
    )
    texto = resp.text or ""
    limpo = re.sub(r"json|", "", texto).strip()
    return json.loads(limpo)


# ---------- Estado ----------
if "direcao" not in st.session_state:
    st.session_state.direcao = "pt-en"
if "historico" not in st.session_state:
    st.session_state.historico = []
if "estudo" not in st.session_state:
    st.session_state.estudo = []  # lista de (original, traducao)
if "cartao" not in st.session_state:
    st.session_state.cartao = 0
if "mostrar_resp" not in st.session_state:
    st.session_state.mostrar_resp = False


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
            st.session_state.ultimo = (resultado, destino, texto.strip(), origem)
            st.session_state.analise = None
            st.session_state.historico.insert(
                0, (NOMES[origem], texto, NOMES[destino], resultado)
            )
        except Exception as e:
            st.error(f"Erro ao traduzir: {e}")

# ---------- Resultado ----------
if len(st.session_state.get("ultimo", ())) == 4:
    resultado, lang, original, org = st.session_state.ultimo
    st.subheader("Tradução")
    st.success(resultado)
    st.code(resultado, language=None)  # botão de copiar

    b1, b2, b3 = st.columns(3)

    if b1.button("🔊 Ouvir"):
        try:
            audio = io.BytesIO()
            gTTS(resultado, lang=lang).write_to_fp(audio)
            st.audio(audio.getvalue(), format="audio/mp3")
        except Exception as e:
            st.error(f"Erro no áudio: {e}")

    if b2.button("⭐ Guardar para estudo"):
        par = (original, resultado)
        if par not in st.session_state.estudo:
            st.session_state.estudo.append(par)
            st.toast("Guardado no modo estudo.")
        else:
            st.toast("Já está guardado.")

    if b3.button("📚 Gramática e exemplos"):
        if not chave_gemini():
            st.warning("Falta a GEMINI_API_KEY nos Secrets da app.")
        else:
            try:
                with st.spinner("A analisar..."):
                    st.session_state.analise = analisar(original, resultado, org)
            except Exception as e:
                st.error(f"Erro na análise: {e}")

    analise = st.session_state.get("analise")
    if analise:
        st.subheader("Gramática")
        st.markdown(analise.get("gramatica", ""))
        st.subheader("Exemplos")
        for ex in analise.get("exemplos", []):
            st.markdown(f"🇬🇧 {ex.get('en', '')}  \n🇦🇴 {ex.get('pt', '')}")

# ---------- Modo estudo ----------
if st.session_state.estudo:
    with st.expander(f"🎓 Modo estudo ({len(st.session_state.estudo)})"):
        i = st.session_state.cartao % len(st.session_state.estudo)
        frente, verso = st.session_state.estudo[i]
        st.markdown(f"Cartão {i + 1}/{len(st.session_state.estudo)}")
        st.info(frente)
        if st.session_state.mostrar_resp:
            st.success(verso)
        c1, c2, c3 = st.columns(3)
        if c1.button("👁️ Mostrar resposta"):
            st.session_state.mostrar_resp = True
            st.rerun()
        if c2.button("➡️ Próximo"):
            st.session_state.cartao += 1
            st.session_state.mostrar_resp = False
            st.rerun()
        if c3.button("🗑️ Limpar cartões"):
            st.session_state.estudo = []
            st.session_state.cartao = 0
            st.session_state.mostrar_resp = False
            st.rerun()

# ---------- Histórico ----------
if st.session_state.historico:
    with st.expander("Histórico"):
        for de, t, para, r in st.session_state.historico[:10]:
            st.markdown(f"{de}: {t}  \n*{para}:* {r}")
            st.divider()
        if st.button("Limpar histórico"):
            st.session_state.historico = []
            st.rerun()