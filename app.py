import streamlit as st
import pandas as pd
from fpdf import FPDF
import tempfile
from datetime import timedelta, date, datetime
import plotly.express as px
import os
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from PIL import Image
import sync_notion
import importlib
from openai import OpenAI

# --- CONFIGURAÇÃO PADRÃO ---
LOGO_PADRAO = "logo.jpg"
icone_padrao = "Icon.ico"
DB_FILE = "tarefas_dbv.csv"

# CORES DBV (RGB)
COR_VERDE_DBV = (32, 53, 47)
COR_DOURADO = (148, 129, 97)
COR_CINZA_CLARO = (245, 245, 245)
COR_VERMELHO_SUAVE = (180, 60, 60)
COR_AZUL_S2 = (52, 73, 94)

# --- CHAVE API OPENAI ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

st.set_page_config(
    page_title="Relatório Oficial DBV", page_icon=icone_padrao, layout="wide"
)


# --- FUNÇÃO IA PREDITIVA (PARSING ROBUSTO) ---
def gerar_resumo_ia(texto_comentarios, api_key, data_atual_str, data_s2_str):
    if not texto_comentarios or len(texto_comentarios) < 10:
        return "Sem dados.", "", "", ""
    try:
        client = OpenAI(api_key=api_key)

        prompt = f"""
        Atue como um PMO Sênior da DBV. Analise o status, datas e comentários.
        
        CONTEXTO:
        - Hoje (Semana Atual): {data_atual_str}
        - Semana Futura (S+2 - Daqui a 15 dias): {data_s2_str}

        Gere 4 seções OBRIGATÓRIAS usando EXATAMENTE estas tags:
        
        [ENTREGAS]: O que foi concluído/avançado NESTA semana.
        [TRAVAS]: O que está impedindo o avanço hoje.
        [ACAO]: O que será feito na semana que vem (S+1).
        [S2]: O que está planejado para a semana S+2 ({data_s2_str}). Se não houver info explícita, PROJETE o próximo passo lógico.

        REGRAS VISUAIS:
        - Use APENAS hífens (-) para os itens.
        - Sem negrito.
        - Texto limpo e direto.
        
        DADOS:
        {texto_comentarios}
        """

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Você é um assistente de PMO."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
        )

        r = response.choices[0].message.content

        # Lógica de Extração Robusta (Parsing)
        # Inicializa variáveis
        ent = "Não identificado."
        trv = "Não identificado."
        aca = "Não identificado."
        s2 = "Não identificado."

        # Tenta quebrar o texto pelas tags
        try:
            if "[ENTREGAS]:" in r:
                ent = r.split("[ENTREGAS]:")[1].split("[TRAVAS]:")[0].strip()

            if "[TRAVAS]:" in r:
                temp = r.split("[TRAVAS]:")[1]
                trv = temp.split("[ACAO]:")[0].strip()

            if "[ACAO]:" in r:
                temp = r.split("[ACAO]:")[1]
                # Pega até o S2, se existir
                if "[S2]:" in temp:
                    aca = temp.split("[S2]:")[0].strip()
                else:
                    aca = temp.strip()

            if "[S2]:" in r:
                s2 = r.split("[S2]:")[1].strip()

        except Exception as parse_error:
            # Fallback simples caso a IA bagunce a formatação
            s2 = f"Erro no formato da IA: {parse_error}. Texto bruto: {r[-100:]}"

        return ent, trv, aca, s2

    except Exception as e:
        return f"Erro OpenAI: {str(e)}", "", "", ""


# --- UTILIDADES ---
def limpar_texto_pdf(texto):
    if not isinstance(texto, str):
        return str(texto)
    texto = texto.replace("*", "")
    mapa = {"–": "-", "—": "-", "“": '"', "”": '"', "‘": "'", "’": "'"}
    for k, v in mapa.items():
        texto = texto.replace(k, v)
    return texto.encode("latin-1", "replace").decode("latin-1")


def salvar_imagem_temporaria(f):
    if not f:
        return None
    try:
        img = Image.open(f)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            img.save(tmp.name, format="JPEG", quality=90)
            return tmp.name
    except:
        return None


def carregar_dados():
    cols = [
        "page_id",
        "Area",
        "Projeto",
        "Tarefa",
        "Responsavel",
        "Inicio",
        "Fim",
        "Status",
        "Observacao",
    ]
    if not os.path.exists(DB_FILE):
        return pd.DataFrame(columns=cols)
    df = pd.read_csv(DB_FILE)
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    if not df.empty:
        df["Inicio"] = pd.to_datetime(df["Inicio"], errors="coerce").dt.date
        df["Fim"] = pd.to_datetime(df["Fim"], errors="coerce").dt.date
        df["Observacao"] = df["Observacao"].fillna("")
        df["Responsavel"] = df["Responsavel"].fillna("-")
    return df


def gerar_imagem_gantt(area, projs=None):
    df = carregar_dados()
    if df.empty:
        return None
    df["Area_Upper"] = df["Area"].astype(str).str.upper()
    df_area = df[df["Area_Upper"] == str(area).upper()].copy()
    if projs:
        df_area = df_area[df_area["Projeto"].isin(projs)]
    if df_area.empty:
        return None

    df_area = df_area.sort_values(by="Inicio")
    h = max(6, len(df_area) * 0.5)

    plt.style.use("default")
    fig, ax = plt.subplots(figsize=(12, h))
    cores = {
        "Não Iniciado": "gray",
        "Em Andamento": "#4da6ff",
        "Bloqueado": "#ff4d4d",
        "Concluído": "#00cc66",
    }
    y_lbl, y_pos = [], []
    for i, (idx, r) in enumerate(df_area.iterrows()):
        s, e = mdates.date2num(r["Inicio"]), mdates.date2num(r["Fim"])
        if e - s == 0:
            e += 1
        ax.barh(
            i,
            e - s,
            left=s,
            height=0.6,
            color=cores.get(r["Status"], "#4da6ff"),
            alpha=0.8,
        )
        pl = limpar_texto_pdf(str(r["Projeto"]))[:15]
        tl = limpar_texto_pdf(str(r["Tarefa"]))[:20]
        y_lbl.append(f"{pl}.. - {tl}")
        y_pos.append(i)
        ax.text(
            s + (e - s) / 2,
            i,
            limpar_texto_pdf(str(r["Responsavel"])),
            ha="center",
            va="center",
            color="white",
            fontsize=7,
            fontweight="bold",
        )
    ax.set_yticks(y_pos)
    ax.set_yticklabels(y_lbl, fontsize=9)
    ax.xaxis_date()
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    plt.title(
        f"CRONOGRAMA: {limpar_texto_pdf(area).upper()}",
        fontsize=14,
        fontweight="bold",
        color="#20352f",
    )
    plt.grid(axis="x", linestyle="--", alpha=0.5)
    plt.tight_layout()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
    plt.savefig(tmp.name, dpi=100)
    plt.close()
    return tmp.name


# --- PDF ESTILIZADO ---
class PDF(FPDF):
    def header(self):
        if os.path.exists(LOGO_PADRAO):
            try:
                self.image(LOGO_PADRAO, 10, 8, 33)
            except:
                pass
        self.set_font("Arial", "B", 15)
        self.set_text_color(*COR_VERDE_DBV)
        self.cell(0, 10, "RELATORIO DE STATUS", 0, 1, "R")
        self.set_draw_color(*COR_DOURADO)
        self.set_line_width(0.5)
        self.line(10, 25, 200, 25)
        self.ln(15)

    def footer(self):
        self.set_y(-15)
        self.set_font("Arial", "I", 8)
        self.set_text_color(*COR_DOURADO)
        self.cell(0, 10, f"DBV Capital - Pagina {self.page_no()}", 0, 0, "C")

    def chapter_block(self, title, content, color_header):
        if not content or len(content) < 3:
            return
        self.set_fill_color(*color_header)
        self.set_text_color(255, 255, 255)
        self.set_font("Arial", "B", 10)
        self.cell(0, 7, f"  {title}", 0, 1, "L", True)
        self.set_fill_color(250, 250, 250)
        self.set_text_color(0, 0, 0)
        self.set_font("Arial", "", 10)
        self.set_draw_color(*color_header)
        self.set_line_width(0.5)

        lines = content.split("\n")
        for line in lines:
            line = line.strip()
            if not line or line == "**" or line == "*":
                continue
            if line.startswith("-") or line.startswith("*"):
                clean_line = line[1:].strip()
                texto_formatado = f"  {chr(149)}  {clean_line}"
            else:
                texto_formatado = f"  {line}"
            self.multi_cell(
                0, 6, limpar_texto_pdf(texto_formatado), border="L", fill=True
            )
        self.ln(3)


# --- INTERFACE ---
df_geral = carregar_dados()
st.title("📊 Relatório Oficial DBV")

with st.sidebar:
    st.header("🤖 Configuração")
    api_key = st.text_input("OpenAI API Key", value=OPENAI_API_KEY, type="password")

tab1, tab2, tab3, tab4 = st.tabs(
    [
        "📝 Relatório S-1",
        "🔨 Central Notion",
        "🔎 Tarefas Avulsas",
        "📅 Planejamento S+2",
    ]
)

# Estado Global para Seleção de Projetos
if "sel_projs_global" not in st.session_state:
    st.session_state.sel_projs_global = []

# === ABA 1: RELATÓRIO ===
with tab1:
    c1, c2 = st.columns(2)
    dt = c1.date_input("Início da Semana", date.today())
    st.session_state.sem = (
        f"{dt.strftime('%d/%m')} a {(dt+timedelta(days=4)).strftime('%d/%m')}"
    )

    dt_s2_inicio = dt + timedelta(days=14)
    dt_s2_fim = dt_s2_inicio + timedelta(days=4)
    str_s2 = f"{dt_s2_inicio.strftime('%d/%m')} a {dt_s2_fim.strftime('%d/%m')}"

    areas = sorted(df_geral["Area"].dropna().unique().tolist())
    if not areas:
        areas = ["Sincronize"]
    area_sel = c1.selectbox("Área", [x for x in areas if str(x).strip() != ""])
    resp = c2.text_input("Responsável")

    st.markdown("---")
    cr1, cr2 = st.columns(2)
    vit = cr1.text_input("🏆 Vitória")
    ris = cr2.text_input("⚠️ Risco")
    dec = cr1.text_input("🛑 Decisão")
    dep = cr2.text_input("🔗 Dependências")

    st.markdown("### 2. Projetos")
    projs = []
    if not df_geral.empty:
        mask = df_geral["Area"].astype(str).str.upper() == str(area_sel).upper()
        projs = df_geral[mask]["Projeto"].unique().tolist()

    sel_projs = st.multiselect("Selecione:", projs) if projs else []
    st.session_state.sel_projs_global = sel_projs
    infos = {}

    if sel_projs:
        st.markdown("---")
        up_geral = st.file_uploader("📸 Visão Geral", type=["png", "jpg"])

        for p in sel_projs:
            with st.expander(f"📂 {p}", expanded=True):
                # INICIALIZAÇÃO DE VARIÁVEIS NA SESSÃO
                for k in [f"ent_{p}", f"trv_{p}", f"aca_{p}", f"plan_s2_{p}"]:
                    if k not in st.session_state:
                        st.session_state[k] = ""

                ts_prev = df_geral[
                    (df_geral["Projeto"] == p)
                    & (
                        df_geral["Area"].astype(str).str.upper()
                        == str(area_sel).upper()
                    )
                ]

                # --- BOTÃO GPT ---
                if not ts_prev.empty and api_key:
                    if st.button(f"✨ Gerar Resumo Completo - {p}"):
                        with st.spinner(f"Criando S+2 para {str_s2}..."):
                            txt = ""
                            for _, r in ts_prev.iterrows():
                                txt += f"- {r['Tarefa']} ({r['Status']}) [Data: {r['Fim']}]: {r['Observacao']}\n"

                            e, t, a, s2_predito = gerar_resumo_ia(
                                txt, api_key, st.session_state.sem, str_s2
                            )

                            # Atualiza Fonte da Verdade
                            st.session_state[f"ent_{p}"] = e
                            st.session_state[f"trv_{p}"] = t
                            st.session_state[f"aca_{p}"] = a
                            st.session_state[f"plan_s2_{p}"] = s2_predito

                            # LIMPEZA DE CACHE DO WIDGET (O Segredo!)
                            # Remove as chaves dos widgets para obrigar o Streamlit a ler o novo valor do session_state
                            if f"widget_s2_tab1_{p}" in st.session_state:
                                del st.session_state[f"widget_s2_tab1_{p}"]
                            if f"widget_s2_tab4_{p}" in st.session_state:
                                del st.session_state[f"widget_s2_tab4_{p}"]

                            st.success("Gerado!")
                            st.rerun()

                if not ts_prev.empty:
                    tot = len(ts_prev)
                    done = len(ts_prev[ts_prev["Status"] == "Concluído"])
                    st.caption(f"📊 {tot} Tarefas | ✅ {done} Concluídas")

                c1, c2 = st.columns(2)
                ic = c1.file_uploader(f"Card ({p})", key=f"c_{p}")
                ia = c2.file_uploader(f"Ativ ({p})", key=f"a_{p}")

                # Campos de Texto
                ent = st.text_area("Entregas", key=f"ent_{p}", height=100)
                trv = st.text_area("Travas", key=f"trv_{p}", height=100)
                aca = st.text_area("Ações (S+1)", key=f"aca_{p}", height=100)

                # Campo S+2 Sincronizado
                st.markdown(f"**📅 Planejamento S+2 ({str_s2})**")

                # Pega valor atual
                val_atual = st.session_state[f"plan_s2_{p}"]

                # Widget com chave única para Tab 1
                new_s2 = st.text_area(
                    f"S+2 para {p}",
                    value=val_atual,
                    key=f"widget_s2_tab1_{p}",
                    height=100,
                )

                # Se editar, atualiza a fonte da verdade
                if new_s2 != val_atual:
                    st.session_state[f"plan_s2_{p}"] = new_s2

                infos[p] = {
                    "ic": ic,
                    "ia": ia,
                    "ent": ent,
                    "trv": trv,
                    "aca": aca,
                    "plan_s2": st.session_state[f"plan_s2_{p}"],
                }

    st.markdown("---")
    st.markdown("### 3. KPIs & Rotina")
    up_rot = st.file_uploader("📸 Rotina", type=["png", "jpg"])
    obs_rot = st.text_input("Obs Rotina")

    ck1, ck2 = st.columns(2)
    with ck1:
        if "kpi_c" not in st.session_state:
            st.session_state.kpi_c = pd.DataFrame(
                [
                    {
                        "KPI": "Vendas",
                        "Meta": "100",
                        "Real": "80",
                        "Var": "-20%",
                        "Leitura": "Baixo",
                    }
                ]
            )
        ed_kc = st.data_editor(st.session_state.kpi_c, num_rows="dynamic")
    with ck2:
        if "kpi_o" not in st.session_state:
            st.session_state.kpi_o = pd.DataFrame(
                [
                    {
                        "KPI": "SLA",
                        "Meta": "2h",
                        "Real": "1h",
                        "Var": "Ok",
                        "Leitura": "Bom",
                    }
                ]
            )
        ed_ko = st.data_editor(st.session_state.kpi_o, num_rows="dynamic")

    st.markdown("### Encerramento")
    imp = st.text_area("Impacto")
    dir = st.text_area("Direcionamentos")

    def pdf_gen():
        pdf = PDF()
        pdf.add_page()
        pdf.set_auto_page_break(True, 20)

        pdf.set_font("Arial", "B", 12)
        pdf.set_text_color(*COR_VERDE_DBV)
        pdf.cell(0, 5, f"AREA: {limpar_texto_pdf(area_sel.upper())}", ln=True)
        pdf.set_font("Arial", size=10)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(
            0,
            5,
            f"Resp: {limpar_texto_pdf(resp)} | Sem: {st.session_state.sem}",
            ln=True,
        )
        pdf.ln(5)

        pdf.chapter_block(
            "RESUMO EXECUTIVO",
            limpar_texto_pdf(
                f"Vitoria: {vit}\nRisco: {ris}\nDecisao: {dec}\nDependencias: {dep}"
            ),
            COR_VERDE_DBV,
        )

        if up_geral:
            p = salvar_imagem_temporaria(up_geral)
            if p:
                if pdf.get_y() > 200:
                    pdf.add_page()
                pdf.image(p, w=180)
                pdf.ln(5)

        pdf.set_font("Arial", "B", 11)
        pdf.set_text_color(*COR_VERDE_DBV)
        pdf.cell(0, 8, "DETALHAMENTO POR PROJETO", ln=True)
        pdf.set_draw_color(*COR_DOURADO)
        pdf.line(pdf.get_x(), pdf.get_y(), 200, pdf.get_y())
        pdf.ln(3)

        mask = df_geral["Area"].astype(str).str.upper() == str(area_sel).upper()
        df_b = df_geral[mask].copy()

        if not sel_projs:
            pdf.set_text_color(0, 0, 0)
            pdf.cell(0, 10, "Nenhum.", ln=True)
        else:
            for p in sel_projs:
                if pdf.get_y() > 220:
                    pdf.add_page()
                pdf.ln(2)

                pdf.set_font("Arial", "B", 14)
                pdf.set_text_color(*COR_VERDE_DBV)
                pdf.cell(0, 8, f"{limpar_texto_pdf(p)}", ln=True)
                pdf.ln(2)

                dm = infos.get(p, {})
                ic, ia = dm.get("ic"), dm.get("ia")
                if ic or ia:
                    if pdf.get_y() > 180:
                        pdf.add_page()
                    y = pdf.get_y() + 2
                    if ic:
                        im = salvar_imagem_temporaria(ic)
                        if im:
                            pdf.image(im, x=10, y=y, w=90, h=50)
                    if ia:
                        im = salvar_imagem_temporaria(ia)
                        if im:
                            pdf.image(im, x=105, y=y, w=90, h=50)
                    pdf.set_y(y + 55)

                ent, trv, aca, ps2 = map(
                    lambda x: limpar_texto_pdf(dm.get(x, "")),
                    ["ent", "trv", "aca", "plan_s2"],
                )
                pdf.chapter_block("ENTREGAS (VISAO DO MOMENTO)", ent, COR_VERDE_DBV)
                pdf.chapter_block("TRAVAS", trv, COR_VERMELHO_SUAVE)
                pdf.chapter_block("PROXIMOS PASSOS (S+1)", aca, COR_DOURADO)

                if ps2:
                    pdf.chapter_block(
                        f"PLANEJAMENTO S+2: {limpar_texto_pdf(p)} ({str_s2})",
                        ps2,
                        COR_AZUL_S2,
                    )

                ts = df_b[df_b["Projeto"] == p]
                if not ts.empty:
                    pdf.ln(2)
                    pdf.set_font("Arial", "B", 9)
                    pdf.set_text_color(0, 0, 0)
                    pdf.set_fill_color(*COR_CINZA_CLARO)
                    pdf.cell(30, 6, "STATUS", 1, 0, "C", True)
                    pdf.cell(110, 6, "TAREFA", 1, 0, "L", True)
                    pdf.cell(50, 6, "RESPONSAVEL", 1, 1, "L", True)
                    pdf.set_font("Arial", "", 9)
                    for _, r in ts.iterrows():
                        stt = limpar_texto_pdf(r["Status"])
                        tn = limpar_texto_pdf(str(r["Tarefa"]))[:65]
                        rnm = limpar_texto_pdf(str(r["Responsavel"]))[:25]
                        pdf.set_text_color(0, 0, 0)
                        if "Concluído" in stt:
                            pdf.set_text_color(0, 100, 0)
                        elif "Atrasado" in stt:
                            pdf.set_text_color(200, 0, 0)
                        elif "Andamento" in stt:
                            pdf.set_text_color(0, 0, 200)
                        pdf.cell(30, 6, stt, 1, 0, "C")
                        pdf.set_text_color(0, 0, 0)
                        pdf.cell(110, 6, f" {tn}", 1, 0, "L")
                        pdf.cell(50, 6, f" {rnm}", 1, 1, "L")
                pdf.ln(5)

        pdf.add_page()
        pdf.chapter_block(
            "KPIs & ROTINA", limpar_texto_pdf(f"Obs: {obs_rot}"), COR_VERDE_DBV
        )
        if up_rot:
            im = salvar_imagem_temporaria(up_rot)
            if im:
                pdf.image(im, w=180)
                pdf.ln(5)

        pdf.set_font("Arial", size=9)
        for dfk in [ed_kc, ed_ko]:
            for _, r in dfk.iterrows():
                if r["KPI"]:
                    pdf.set_text_color(*COR_VERDE_DBV)
                    pdf.cell(30, 6, limpar_texto_pdf(f"{r['KPI']}:"), 0)
                    pdf.set_text_color(0, 0, 0)
                    pdf.cell(
                        0,
                        6,
                        limpar_texto_pdf(f"{r['Real']} / {r['Meta']} ({r['Leitura']})"),
                        0,
                        1,
                    )

        pdf.ln(5)
        pdf.chapter_block(
            "ENCERRAMENTO",
            limpar_texto_pdf(f"Impacto:\n{imp}\n\nDirecionamentos:\n{dir}"),
            COR_VERDE_DBV,
        )

        im = gerar_imagem_gantt(str(area_sel), sel_projs)
        if im:
            pdf.add_page()
            pdf.image(im, x=10, y=10, w=190)
        return pdf.output(dest="S").encode("latin-1", "replace")

    if st.button("📥 BAIXAR PDF", type="primary"):
        if area_sel and resp and sel_projs:
            st.download_button(
                "Salvar",
                data=pdf_gen(),
                file_name="Relatorio.pdf",
                mime="application/pdf",
            )
        else:
            st.error("Preencha tudo.")

# === ABA 2 ===
with tab2:
    st.markdown("### 🔄 Central")
    if st.button("🔄 Puxar"):
        with st.spinner("..."):
            importlib.reload(sync_notion)
            s, m = sync_notion.rodar_sincronizacao()
            if s:
                st.success(m)
                st.rerun()
            else:
                st.error(m)

    if not df_geral.empty:
        if areas and areas[0] != "Sincronize":
            ag = st.selectbox("1. Área:", areas)
            dfa = df_geral[
                df_geral["Area"].astype(str).str.upper() == str(ag).upper()
            ].copy()
            p_ativos = [
                p
                for p in dfa["Projeto"].unique()
                if not dfa[(dfa["Projeto"] == p) & (dfa["Status"] != "Concluído")].empty
            ]

            if p_ativos:
                pg = st.selectbox("2. Projeto:", p_ativos)
                dff = dfa[dfa["Projeto"] == pg].sort_values("Inicio")

                st.markdown(f"#### {pg}")
                fig = px.timeline(
                    dff,
                    x_start="Inicio",
                    x_end="Fim",
                    y="Tarefa",
                    color="Status",
                    hover_data=["Responsavel", "Observacao"],
                    title=pg,
                )
                fig.update_layout(
                    plot_bgcolor="#ffffff", paper_bgcolor="#ffffff", font_color="black"
                )
                fig.update_yaxes(autorange="reversed")
                st.plotly_chart(fig, use_container_width=True)

                st.markdown("### ✏️ Editar")
                dfe = dff[
                    [
                        "Tarefa",
                        "Status",
                        "Inicio",
                        "Fim",
                        "Responsavel",
                        "Observacao",
                        "page_id",
                    ]
                ].copy()
                dfe = dfe.rename(columns={"Observacao": "Chat"})
                edited = st.data_editor(
                    dfe, key="edit", num_rows="dynamic", column_config={"page_id": None}
                )

                if st.button("💾 Salvar"):
                    pb = st.progress(0)
                    tot = len(edited)
                    at = 0
                    importlib.reload(sync_notion)
                    for i, (idx, r) in enumerate(edited.iterrows()):
                        pid = r["page_id"]
                        if pid in dff["page_id"].values:
                            org = dff[dff["page_id"] == pid].iloc[0]
                            if r["Status"] != org["Status"]:
                                sync_notion.atualizar_tarefa_notion(
                                    pid, "Status", r["Status"]
                                )
                                at += 1
                            if r["Chat"] != org["Observacao"]:
                                sync_notion.atualizar_tarefa_notion(
                                    pid, "Observacao", r["Chat"]
                                )
                                at += 1
                            if r["Tarefa"] != org["Tarefa"]:
                                sync_notion.atualizar_tarefa_notion(
                                    pid, "Tarefa", r["Tarefa"]
                                )
                                at += 1
                        pb.progress((i + 1) / tot)
                    if at > 0:
                        st.success(f"{at} salvos!")
                        sync_notion.rodar_sincronizacao()
                        st.rerun()
                    else:
                        st.info("Nada mudou.")
            else:
                st.info("Tudo concluído!")

# === ABA 3 ===
with tab3:
    st.markdown("### 🔎 Avulsas")
    if not df_geral.empty:
        usrs = sorted(
            list(
                set(
                    [
                        u.strip()
                        for sl in df_geral["Responsavel"].str.split(",")
                        for u in sl
                        if u.strip() not in ["-", ""]
                    ]
                )
            )
        )
        u = st.selectbox("Resp:", ["Todos"] + usrs)
        msk = (
            df_geral["Projeto"].isin(["Avulso", "Sem Nome", "Geral", ""])
            | df_geral["Projeto"].isna()
        )
        dfa = df_geral[msk].copy()
        if u != "Todos":
            dfa = dfa[dfa["Responsavel"].str.contains(u, na=False)]

        if not dfa.empty:
            st.write(f"{len(dfa)} tarefas.")
            dfa = dfa.rename(columns={"Observacao": "Chat"})
            edt = st.data_editor(
                dfa[["Tarefa", "Status", "Responsavel", "Chat", "page_id"]],
                key="av",
                num_rows="dynamic",
                column_config={"page_id": None},
            )
            if st.button("💾 Salvar Avulsas"):
                importlib.reload(sync_notion)
                cnt = 0
                pbb = st.progress(0)
                tott = len(edt)
                for i, (idx, r) in enumerate(edt.iterrows()):
                    pid = r["page_id"]
                    if pid in dfa["page_id"].values:
                        org = dfa[dfa["page_id"] == pid].iloc[0]
                        if r["Chat"] != org["Observacao"]:
                            sync_notion.atualizar_tarefa_notion(
                                pid, "Observacao", r["Chat"]
                            )
                            cnt += 1
                        if r["Status"] != org["Status"]:
                            sync_notion.atualizar_tarefa_notion(
                                pid, "Status", r["Status"]
                            )
                            cnt += 1
                    pbb.progress((i + 1) / tott)
                if cnt > 0:
                    st.success("Salvo!")
                    sync_notion.rodar_sincronizacao()
                    st.rerun()
        else:
            st.info("Nada.")

# === ABA 4: S+2 ===
with tab4:
    st.markdown(f"### 🔭 Planejamento S+2 ({str_s2})")

    projetos_selecionados = st.session_state.get("sel_projs_global", [])
    if not projetos_selecionados:
        st.warning("⚠️ Selecione projetos na aba 'Relatório S-1' para preencher o S+2.")
    else:
        st.write("Preencha o que será feito na semana S+2 para cada projeto:")
        for p in projetos_selecionados:
            st.markdown(f"**{p}**")

            # Inicializa se não existir
            if f"plan_s2_{p}" not in st.session_state:
                st.session_state[f"plan_s2_{p}"] = ""

            val_central = st.session_state[f"plan_s2_{p}"]

            # Widget Tab 4 com Key Diferente
            new_s2_t4 = st.text_area(
                f"Planejamento para {p}",
                value=val_central,
                key=f"widget_s2_tab4_{p}",
                height=100,
            )

            # Sincroniza se editar
            if new_s2_t4 != val_central:
                st.session_state[f"plan_s2_{p}"] = new_s2_t4

            st.divider()
