from notion_client import Client as NotionClient
import json
import os

# --- CONFIGURAÇÃO ---
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DB_ID_PROJETOS = os.getenv("NOTION_DB_ID_PROJETOS")
DB_ID_TAREFAS = os.getenv("NOTION_DB_ID_TAREFAS")

if not NOTION_TOKEN or not DB_ID_PROJETOS or not DB_ID_TAREFAS:
    raise RuntimeError("Variáveis ausentes: NOTION_TOKEN / NOTION_DB_ID_PROJETOS / NOTION_DB_ID_TAREFAS")

notion = NotionClient(auth=NOTION_TOKEN)


def analisar_banco(db_id, nome_banco):
    print(f"\n{'='*40}")
    print(f"🔍 ANALISANDO BANCO: {nome_banco}")
    print(f"{'='*40}")

    try:
        # Pega apenas a estrutura (schema) do banco
        database = notion.databases.retrieve(database_id=db_id)
        propriedades = database.get("properties", {})
        print(propriedades)
        for nome_coluna, dados in propriedades.items():
            tipo = dados["type"]
            print(f"{nome_coluna:<30} | {tipo}")

    except Exception as e:
        print(f"❌ Erro ao acessar {nome_banco}: {e}")


# Rodar diagnóstico
if __name__ == "__main__":
    analisar_banco(DB_ID_PROJETOS, "PROJETOS")
    analisar_banco(DB_ID_TAREFAS, "TAREFAS")
    print("\n✅ Fim da análise.")
