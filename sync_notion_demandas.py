import pandas as pd
from notion_client import Client
from datetime import datetime, date
import os

# --- CONFIGURAÇÕES ---
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DB_ID_DEMANDAS = os.getenv("NOTION_DB_ID_DEMANDAS")

if not NOTION_TOKEN or not DB_ID_DEMANDAS:
    raise RuntimeError("Variáveis ausentes: NOTION_TOKEN / NOTION_DB_ID_DEMANDAS")

# Inicializa o cliente
notion = Client(auth=NOTION_TOKEN)

# Cache para não ficar consultando a API de usuários toda hora
user_cache = {}


def get_user_name(user_id):
    """Busca o nome do usuário pelo ID (com cache)"""
    if user_id in user_cache:
        return user_cache[user_id]
    try:
        user = notion.users.retrieve(user_id)
        name = user.get("name", "Desconhecido")
        user_cache[user_id] = name
        return name
    except:
        return "Time"


def buscar_comentarios_nativos(page_id):
    """
    Busca o histórico de comentários da página (chat)
    para criar a cronologia que a IA usa.
    """
    try:
        comments = notion.comments.list(block_id=page_id)
        historico = []

        for c in comments.get("results", []):
            # Extrai texto
            texto_parts = [t.get("plain_text", "") for t in c.get("rich_text", [])]
            texto_completo = "".join(texto_parts)

            # Extrai Autor
            user_obj = c.get("created_by", {})
            nome_autor = get_user_name(user_obj.get("id"))

            # Extrai Data (Formato DD/MM)
            raw_date = c.get("created_time")
            data_fmt = ""
            if raw_date:
                dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                data_fmt = dt.strftime("%d/%m")

            if texto_completo:
                # Formata: (Data) [Autor]: Comentário
                historico.append(f"({data_fmt}) [{nome_autor}]: {texto_completo}")

        return "\n".join(historico)
    except:
        return ""


def safe_get(page, prop_name):
    """
    Função auxiliar segura para extrair dados de propriedades complexas do Notion.
    Tenta adivinhar o tipo de dado (Texto, Select, Data, Pessoa, etc).
    """
    if not page or "properties" not in page:
        return None
    props = page["properties"]

    # Tenta achar a propriedade mesmo se maiúscula/minúscula variar
    real_key = next((k for k in props.keys() if k.lower() == prop_name.lower()), None)
    if not real_key:
        return None

    dado = props[real_key]
    tipo = dado["type"]

    try:
        if tipo == "title":
            return dado["title"][0]["plain_text"] if dado["title"] else "Sem Título"
        elif tipo == "rich_text":
            return dado["rich_text"][0]["plain_text"] if dado["rich_text"] else ""
        elif tipo == "select":
            return dado["select"]["name"] if dado["select"] else "Geral"
        elif tipo == "status":
            return dado["status"]["name"] if dado["status"] else "Não Iniciado"
        elif tipo == "multi_select":
            return (
                ", ".join([item["name"] for item in dado["multi_select"]])
                if dado["multi_select"]
                else ""
            )
        elif tipo == "date":
            return dado["date"] if dado["date"] else None
        elif tipo == "people":
            if dado["people"]:
                return ", ".join([p.get("name", "User") for p in dado["people"]])
            return "Time"
        elif tipo == "relation":
            # Retorna apenas o ID se for relação, pois não temos o nome sem outra query
            return "Relacionado"
    except:
        return None
    return None


def atualizar_tarefa_notion(page_id, coluna, novo_valor):
    """Envia atualizações do Streamlit de volta para o Notion"""
    props = {}

    # Mapeamento dos nomes das colunas do CSV para as Propriedades do Notion
    if coluna == "Observacao":
        # Adiciona como comentário nativo para manter histórico
        try:
            notion.comments.create(
                parent={"page_id": page_id},
                rich_text=[{"text": {"content": str(novo_valor)}}],
            )
            return True, "Comentário adicionado"
        except:
            # Fallback: tenta salvar em coluna de texto se comentário falhar
            props["Observação"] = {
                "rich_text": [{"text": {"content": str(novo_valor)}}]
            }

    elif coluna == "Status":
        # Tenta mapear para Status ou Select
        props["Status"] = {"status": {"name": str(novo_valor)}}
        # Se seu Notion usar Select em vez de Status, mude para: {"select": {"name": str(novo_valor)}}

    elif coluna == "Tarefa":
        props["Tarefa"] = {"title": [{"text": {"content": str(novo_valor)}}]}

    if props:
        try:
            notion.pages.update(page_id=page_id, properties=props)
            return True, "Atualizado com sucesso"
        except Exception as e:
            return False, f"Erro Notion: {str(e)}"
    return False, "Nenhuma alteração enviada"


def rodar_sincronizacao():
    """
    Função Principal:
    1. Varre o banco de dados inteiro (lidando com paginação).
    2. Extrai e limpa os dados.
    3. Salva em CSV para o app ler.
    """
    print(f"🔄 Iniciando sincronização com DB: {DB_ID_DEMANDAS}")

    lista_final = []
    has_more = True
    next_cursor = None
    page_count = 0

    while has_more:
        try:
            # Faz a query no Notion
            query_params = {"database_id": DB_ID_DEMANDAS}
            if next_cursor:
                query_params["start_cursor"] = next_cursor

            response = notion.databases.query(**query_params)
            results = response.get("results", [])

            for page in results:
                page_id = page["id"]

                # --- MAPEAMENTO DE COLUNAS ---
                # Ajuste os nomes à direita ("Nome no Notion") conforme seu banco real
                tarefa = (
                    safe_get(page, "Tarefa")
                    or safe_get(page, "Name")
                    or safe_get(page, "Nome")
                    or "Sem Nome"
                )
                status = safe_get(page, "Status") or "Não Iniciado"
                resp = (
                    safe_get(page, "Responsável")
                    or safe_get(page, "Assignee")
                    or safe_get(page, "Pessoa")
                    or "Time"
                )
                area = safe_get(page, "Área") or safe_get(page, "Team") or "Geral"
                projeto = (
                    safe_get(page, "Projeto") or safe_get(page, "Project") or "Avulso"
                )

                # Datas (Tenta pegar 'Data', 'Prazo' ou 'Timeline')
                data_obj = (
                    safe_get(page, "Data")
                    or safe_get(page, "Prazo")
                    or safe_get(page, "Timeline")
                )

                inicio = None
                fim = None

                if data_obj:
                    inicio = data_obj.get("start")
                    fim = (
                        data_obj.get("end") or inicio
                    )  # Se não tiver fim, assume data única

                # Se não tiver data, coloca hoje para não quebrar o gráfico
                if not inicio:
                    inicio = date.today().isoformat()
                if not fim:
                    fim = inicio

                # Chat / Comentários
                # Tenta pegar coluna de texto 'Observação' E junta com comentários nativos
                obs_texto = safe_get(page, "Observação") or ""
                chat_historico = buscar_comentarios_nativos(page_id)

                obs_final = ""
                if chat_historico:
                    obs_final += chat_historico + "\n"
                if obs_texto:
                    obs_final += f"(Nota Fixa): {obs_texto}"

                # Normalização de Status para o App (Cores)
                st_lower = str(status).lower()
                status_app = "Em Andamento"  # Default
                if "conclu" in st_lower or "done" in st_lower or "final" in st_lower:
                    status_app = "Concluído"
                elif "não" in st_lower or "to do" in st_lower or "backlog" in st_lower:
                    status_app = "Não Iniciado"
                elif "trav" in st_lower or "block" in st_lower or "risco" in st_lower:
                    status_app = "Bloqueado"

                lista_final.append(
                    {
                        "page_id": page_id,
                        "Area": area,
                        "Projeto": projeto,  # Se o projeto for Relation, virá "Relacionado". Ideal é ser Select ou Texto.
                        "Tarefa": tarefa,
                        "Responsavel": resp,
                        "Inicio": inicio,
                        "Fim": fim,
                        "Status": status_app,  # Status normalizado
                        "Status_Original": status,  # Status real do Notion (se precisar)
                        "Observacao": obs_final,
                    }
                )

            # Paginação
            has_more = response.get("has_more")
            next_cursor = response.get("next_cursor")
            page_count += 1
            print(f"   ... Página {page_count} processada ({len(results)} itens)")

        except Exception as e:
            print(f"❌ Erro na sincronização: {e}")
            return False, f"Erro: {e}"

    # Salva no CSV
    if lista_final:
        df = pd.DataFrame(lista_final)
        df.to_csv("tarefas_dbv.csv", index=False)
        return True, f"Sucesso! {len(lista_final)} demandas sincronizadas."
    else:
        return False, "Nenhuma tarefa encontrada no Banco de Dados."


# Teste local (se rodar o arquivo direto)
if __name__ == "__main__":
    sucesso, msg = rodar_sincronizacao()
    print(msg)
