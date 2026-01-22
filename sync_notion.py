import pandas as pd
from notion_client import Client
from datetime import date, datetime
import os

# --- CONFIGURAÇÃO ---
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DB_ID_PROJETOS = os.getenv("NOTION_DB_ID_PROJETOS")
DB_ID_TAREFAS = os.getenv("NOTION_DB_ID_TAREFAS")

# Debug temporário para validar variáveis no Railway
print("ENV CHECK:",
      "NOTION_TOKEN:", bool(os.getenv("NOTION_TOKEN")),
      "NOTION_DB_ID_PROJETOS:", bool(os.getenv("NOTION_DB_ID_PROJETOS")),
      "NOTION_DB_ID_TAREFAS:", bool(os.getenv("NOTION_DB_ID_TAREFAS")))

if not NOTION_TOKEN or not DB_ID_PROJETOS or not DB_ID_TAREFAS:
    raise RuntimeError("Variáveis ausentes: NOTION_TOKEN / NOTION_DB_ID_PROJETOS / NOTION_DB_ID_TAREFAS")

notion = Client(auth=NOTION_TOKEN)

# Cache de usuários
user_cache = {}


def get_user_name(user_id):
    if user_id in user_cache:
        return user_cache[user_id]
    try:
        user = notion.users.retrieve(user_id)
        name = user.get("name", "Usuário")
        user_cache[user_id] = name
        return name
    except:
        return "Alguém"


def buscar_comentarios_nativos(page_id):
    """Busca o chat com DATA para cronologia"""
    try:
        comments = notion.comments.list(block_id=page_id)
        historico = []

        # Notion retorna do mais antigo para o mais novo
        for c in comments.get("results", []):
            # Texto
            texto_parts = [t.get("plain_text", "") for t in c.get("rich_text", [])]
            texto_completo = "".join(texto_parts)

            # Autor
            user_obj = c.get("created_by", {})
            nome_autor = get_user_name(user_obj.get("id"))

            # Data (ISO 8601 -> DD/MM)
            raw_date = c.get("created_time")  # ex: 2023-10-27T10:00:00.000Z
            data_fmt = ""
            if raw_date:
                dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                data_fmt = dt.strftime("%d/%m")

            if texto_completo:
                # Formato: (25/10) [Nome]: Comentário
                historico.append(f"({data_fmt}) [{nome_autor}]: {texto_completo}")

        return "\n".join(historico)
    except:
        return ""


def safe_get(page, prop_name):
    if not page or "properties" not in page:
        return None
    props = page["properties"]
    if prop_name not in props:
        return None
    dado = props[prop_name]
    tipo = dado["type"]
    try:
        if tipo == "title":
            return dado["title"][0]["plain_text"] if dado["title"] else ""
        elif tipo == "rich_text":
            return dado["rich_text"][0]["plain_text"] if dado["rich_text"] else ""
        elif tipo == "select":
            return dado["select"]["name"] if dado["select"] else None
        elif tipo == "multi_select":
            opcoes = [item["name"] for item in dado["multi_select"]]
            return ", ".join(opcoes) if opcoes else None
        elif tipo == "date":
            return dado["date"] if dado["date"] else None
        elif tipo == "relation":
            return dado["relation"][0]["id"] if dado["relation"] else None
    except:
        return None
    return None


def mapear_projetos():
    print("1. Mapeando Projetos...")
    todos_projetos = {}
    has_more = True
    next_cursor = None
    while has_more:
        try:
            query = notion.databases.query(
                database_id=DB_ID_PROJETOS, start_cursor=next_cursor
            )
            for page in query.get("results", []):
                proj_id = page["id"]
                nome = safe_get(page, "Projeto") or "Sem Nome"
                area = safe_get(page, "Área") or "Geral"
                todos_projetos[proj_id] = {"Projeto": nome, "Area": area}
            has_more = query.get("has_more")
            next_cursor = query.get("next_cursor")
        except:
            break
    return todos_projetos


def buscar_tarefas(mapa_projetos):
    print("2. Buscando Tarefas e Chat Cronológico...")
    lista_final = []
    has_more = True
    next_cursor = None

    while has_more:
        try:
            query = notion.databases.query(
                database_id=DB_ID_TAREFAS, start_cursor=next_cursor
            )
            for page in query.get("results", []):
                page_id = page["id"]
                tarefa = safe_get(page, "Tarefa") or "Sem Nome"
                status = safe_get(page, "Status") or "Não Iniciado"
                resp = safe_get(page, "Responsável") or "Time"

                # --- LÓGICA DE OBSERVAÇÃO ---
                obs_coluna = safe_get(page, "Observação") or ""
                chat_nativo = buscar_comentarios_nativos(page_id)

                # Junta tudo, dando preferência ao chat cronológico
                obs_final = chat_nativo if chat_nativo else obs_coluna

                # Datas
                obj_ent = safe_get(page, "Data Entrega")
                obj_ini = safe_get(page, "Data Inicio")
                inicio = (
                    obj_ini.get("start")
                    if obj_ini
                    else (obj_ent.get("start") if obj_ent else None)
                )
                fim = obj_ent.get("start") if obj_ent else inicio

                # Projeto
                pid = safe_get(page, "Projeto")
                if pid and pid in mapa_projetos:
                    nm_proj, nm_area = (
                        mapa_projetos[pid]["Projeto"],
                        mapa_projetos[pid]["Area"],
                    )
                else:
                    nm_proj, nm_area = "Avulso", safe_get(page, "Área") or "Geral"

                # Status Normalizado
                st_l = str(status).lower()
                st_f = (
                    "Concluído"
                    if "conclu" in st_l or "done" in st_l
                    else (
                        "Em Andamento"
                        if "andamento" in st_l or "aprov" in st_l
                        else (
                            "Bloqueado"
                            if "cancel" in st_l or "stand" in st_l
                            else "Não Iniciado"
                        )
                    )
                )

                lista_final.append(
                    {
                        "page_id": page_id,
                        "Area": nm_area,
                        "Projeto": nm_proj,
                        "Tarefa": tarefa,
                        "Responsavel": resp,
                        "Inicio": inicio,
                        "Fim": fim,
                        "Status": st_f,
                        "Observacao": obs_final,
                    }
                )
            has_more = query.get("has_more")
            next_cursor = query.get("next_cursor")
        except:
            break
    return lista_final


def atualizar_tarefa_notion(page_id, coluna, novo_valor):
    props = {}
    if coluna == "Observacao":
        props["Observação"] = {"rich_text": [{"text": {"content": str(novo_valor)}}]}
    elif coluna == "Status":
        mapa = {
            "Concluído": "Concluída",
            "Em Andamento": "Em andamento",
            "Não Iniciado": "Não iniciado",
            "Bloqueado": "Stand By",
        }
        props["Status"] = {"select": {"name": mapa.get(novo_valor, novo_valor)}}

    if props:
        try:
            notion.pages.update(page_id=page_id, properties=props)
            return True, "Ok"
        except Exception as e:
            return False, str(e)
    return False, "Campo inv"


def rodar_sincronizacao():
    try:
        mapa = mapear_projetos()
        dados = buscar_tarefas(mapa)
        if not dados:
            return False, "0 tarefas"
        df = pd.DataFrame(dados)
        hj = date.today()
        df["Inicio"] = df["Inicio"].fillna(hj)
        df["Fim"] = df["Fim"].fillna(hj)
        df.to_csv("tarefas_dbv.csv", index=False)
        return True, f"{len(df)} tarefas atualizadas."
    except Exception as e:
        return False, str(e)
