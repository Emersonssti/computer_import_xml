import os
import sys
import csv
import platform
import oracledb
from datetime import datetime
from xml.dom import minidom

# -------------------------------------------------------------------------
# ETAPA 0: AMBIENTES DISPONÍVEIS (DSN/USER/PASSWORD por ambiente)
# -------------------------------------------------------------------------
AMBIENTES = {
    "OPER1": {
        "user": "ts",
        "password": "tsclonebi",
        "dsn": """
(DESCRIPTION =
    (ADDRESS = (PROTOCOL = TCP)(HOST = cnu-exa-kzspz-scan.subvcpexadbpriv.vcnvcpexa.oraclevcn.com)(PORT = 1521))
    (CONNECT_DATA =
      (SERVER = DEDICATED)
      (SERVICE_NAME = CLONE6.complexo.unimed)
    )
)
""",
    },
}


def get_base_dir():
    """Diretório base para CSV / pasta log / Instant Client / XMLs. Script ou executável PyInstaller."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# -------------------------------------------------------------------------
# ETAPA 1: CONFIGURAÇÕES (sobrescritas via setters / GUI)
# -------------------------------------------------------------------------
def _instant_client_default():
    base = get_base_dir()
    if platform.system() == "Windows":
        return os.path.join(base, "instantclient-basic-windows")
    return os.path.join(base, "instantclient-basic-macos.arm64-23.26.1.0.0")


CAMINHO_INSTANT_CLIENT = _instant_client_default()
DSN = AMBIENTES["OPER1"]["dsn"]
USER = AMBIENTES["OPER1"]["user"]
PASSWORD = AMBIENTES["OPER1"]["password"]

# Diretório onde os arquivos XML estão armazenados.
DIRETORIO_LOCAL = os.path.join(get_base_dir(), "arquivos_ptu")

# Nome da procedure alvo, reutilizada em todos os modos.
NOME_PROCEDURE = "PTU_XML_IMPORTA_A550.PTU_IMPORTA_550"

# -------------------------------------------------------------------------
# CHAVE DE LIGA/DESLIGA DO IMPORT EM MASSA
# -------------------------------------------------------------------------
# True  -> executa DELETEs + chama a procedure (importa o XML).
# False -> executa SOMENTE os DELETEs, ignora a chamada da procedure.
EXECUTAR_IMPORT_MASSA = True

# -------------------------------------------------------------------------
# HOOKS DE INTEGRAÇÃO (GUI / CLI)
# -------------------------------------------------------------------------
LOG_CALLBACK = None
ORACLE_CLIENT_INICIADO = False
# True  -> conecta em thin mode (sem Instant Client)
# False -> conecta em thick mode (requer Instant Client)
# Obs.: thin mode falha com DPY-3015 quando o usuário Oracle usa password verifier antigo (10G).
# Default = False para garantir compatibilidade com bancos legados.
USAR_THIN_MODE = False


def set_ambiente(nome_ambiente):
    global DSN, USER, PASSWORD
    if nome_ambiente not in AMBIENTES:
        raise ValueError(f"Ambiente desconhecido: {nome_ambiente}")
    cfg = AMBIENTES[nome_ambiente]
    DSN = cfg["dsn"]
    USER = cfg["user"]
    PASSWORD = cfg["password"]


def set_diretorio_local(path):
    global DIRETORIO_LOCAL
    DIRETORIO_LOCAL = path


def set_instant_client_path(path):
    global CAMINHO_INSTANT_CLIENT, ORACLE_CLIENT_INICIADO
    CAMINHO_INSTANT_CLIENT = path
    ORACLE_CLIENT_INICIADO = False


def set_executar_import_massa(flag):
    global EXECUTAR_IMPORT_MASSA
    EXECUTAR_IMPORT_MASSA = bool(flag)


def set_log_callback(callback):
    global LOG_CALLBACK
    LOG_CALLBACK = callback


def set_usar_thin_mode(flag):
    global USAR_THIN_MODE
    USAR_THIN_MODE = bool(flag)


def _emitir_log(msg):
    print(msg)
    if LOG_CALLBACK:
        try:
            LOG_CALLBACK(msg)
        except Exception:
            pass


def iniciar_oracle_client():
    """Inicializa o Oracle Instant Client (thick) ou pula se estiver em thin mode."""
    global ORACLE_CLIENT_INICIADO
    if USAR_THIN_MODE:
        _emitir_log("[LOG] Conexão em modo THIN (sem Instant Client).")
        return
    if ORACLE_CLIENT_INICIADO:
        return
    try:
        oracledb.init_oracle_client(lib_dir=CAMINHO_INSTANT_CLIENT)
        _emitir_log(f"[LOG] Oracle Instant Client (thick) inicializado em: {CAMINHO_INSTANT_CLIENT}")
        ORACLE_CLIENT_INICIADO = True
    except Exception as e:
        _emitir_log(f"[AVISO] Cliente Oracle já inicializado ou erro ao inicializar: {e}")
        ORACLE_CLIENT_INICIADO = True

# -------------------------------------------------------------------------
# ETAPA 2: DEFINIÇÃO DOS FLUXOS DE TABELAS (ordem de tentativa no modo individual)
# Cada fluxo tem:
#   - nome: descrição do fluxo
#   - tabela_lookup: tabela usada no SELECT inicial para identificar registros
#   - deletes: lista de DELETEs a executar antes de chamar a procedure
#       cada delete tem: tabela e flag usa_cod_lote (se filtra por cod_lote).
#       Opcional: usa_cod_prestador_ts (default True); False omite esse filtro (ex.: itens_pagamento).
# -------------------------------------------------------------------------
FLUXOS_INDIVIDUAL = [
    {
        "nome": "Intercâmbio a cobrar - revisão fechada",
        "tabela_lookup": "ctm_grd_cob_r",
        "deletes": [
            {"tabela": "itens_pagamento", "usa_cod_lote": False,"usa_cod_prestador_ts": True, "usa_data_solicitacao_rev": True},
            {"tabela": "ctm_itens_contas_cob_r", "usa_cod_lote": False},
            {"tabela": "ctm_contas_cob_r", "usa_cod_lote": False},
            {"tabela": "ctm_grd_cob_r", "usa_cod_lote": True},
            {"tabela": "ctm_revisao_prestador_in", "usa_cod_lote": False},
        ],
    },
    {
        "nome": "Intercâmbio a cobrar - revisão aberta",
        "tabela_lookup": "ctm_grd_in_r",
        "query_lookup": """
            SELECT a.cod_lote,
                   a.num_grd,
                   a.cod_prestador_ts,
                   a.mes_ano_ref,
                   MAX(b.data_solicitacao_rev) AS ultima_data
              FROM ctm_grd_in_r a
              INNER JOIN ctm_revisao_prestador_in b
                ON a.num_grd          = b.num_grd
               AND a.cod_prestador_ts = b.cod_prestador_ts
               AND a.mes_ano_ref      = b.mes_ano_ref
             WHERE a.cod_lote = :cod_lote
             GROUP BY a.cod_lote, a.num_grd, a.cod_prestador_ts, a.mes_ano_ref
        """,
        "deletes": [
            {"tabela": "itens_pagamento", "usa_cod_lote": False,"usa_cod_prestador_ts": True, "usa_data_solicitacao_rev": True},
            {"tabela": "ctm_itens_contas_in_r", "usa_cod_lote": False, "usa_data_solicitacao_rev": False},
            {"tabela": "ctm_contas_in_r", "usa_cod_lote": False, "usa_data_solicitacao_rev": False},
            {"tabela": "ctm_grd_in_r", "usa_cod_lote": False, "usa_data_solicitacao_rev": False},
            {"tabela": "ctm_revisao_prestador_in", "usa_cod_lote": False},
        ],
    },


    {
        "nome": "Intercâmbio a pagar - revisão fechada",
        "tabela_lookup": "ctm_grd_pag_r",
        "query_lookup": """
            SELECT a.cod_lote,
                   a.num_grd,
                   a.cod_prestador_ts,
                   a.mes_ano_ref,
                   MAX(b.data_solicitacao_rev) AS ultima_data
              FROM ctm_grd_pag_r a
              INNER JOIN ctm_revisao_prestador b
                ON a.num_grd          = b.num_grd
               AND a.cod_prestador_ts = b.cod_prestador_ts
               AND a.mes_ano_ref      = b.mes_ano_ref
             WHERE a.cod_lote = :cod_lote
             GROUP BY a.cod_lote, a.num_grd, a.cod_prestador_ts, a.mes_ano_ref
        """,
        "deletes": [
            {"tabela": "itens_pagamento", "usa_cod_lote": False,"usa_cod_prestador_ts": True, "usa_data_solicitacao_rev": True},
            {"tabela": "ctm_itens_contas_pag_r", "usa_cod_lote": False, "usa_data_solicitacao_rev": True},
            {"tabela": "ctm_contas_pag_r", "usa_cod_lote": False, "usa_data_solicitacao_rev": True},
            {"tabela": "ctm_grd_pag_r", "usa_cod_lote": True, "usa_data_solicitacao_rev": True},
            {"tabela": "ctm_revisao_prestador", "usa_cod_lote": False, "usa_data_solicitacao_rev": True},
        ],
    },


    {
        "nome": "Intercâmbio a pagar - revisão aberta",
        "tabela_lookup": "ctm_grd",
        "query_lookup": """
            SELECT a.cod_lote,
                   a.num_grd,
                   a.cod_prestador_ts,
                   a.mes_ano_ref,
                   MAX(b.data_solicitacao_rev) AS ultima_data
              FROM ctm_grd a
              INNER JOIN ctm_revisao_prestador b
                ON a.num_grd          = b.num_grd
               AND a.cod_prestador_ts = b.cod_prestador_ts
               AND a.mes_ano_ref      = b.mes_ano_ref
             WHERE a.cod_lote = :cod_lote
             GROUP BY a.cod_lote, a.num_grd, a.cod_prestador_ts, a.mes_ano_ref
        """,
        "deletes": [
            {"tabela": "itens_pagamento", "usa_cod_lote": False,"usa_cod_prestador_ts": True, "usa_data_solicitacao_rev": True},
            {"tabela": "ctm_itens_contas", "usa_cod_lote": False, "usa_data_solicitacao_rev": False},
            {"tabela": "ctm_contas", "usa_cod_lote": False, "usa_data_solicitacao_rev": False},
            {"tabela": "ctm_grd", "usa_cod_lote": True, "usa_data_solicitacao_rev": False},
            {"tabela": "ctm_revisao_prestador", "usa_cod_lote": False},
        ],
    },
]


# -------------------------------------------------------------------------
# ETAPA 3: UTILITÁRIOS DE LOG E I/O
# -------------------------------------------------------------------------
def criar_logger(prefixo_arquivo, identificador):
    """Cria estrutura de log em memória + caminho de arquivo final na pasta log."""
    logs = []
    timestamp_inicio = datetime.now()
    timestamp_nome_arquivo = timestamp_inicio.strftime("%Y%m%d_%H%M%S")
    identificador_seguro = str(identificador).replace("/", "_").replace("\\", "_").replace(" ", "_")
    diretorio_log = os.path.join(get_base_dir(), "log")
    caminho_log = os.path.join(
        diretorio_log,
        f"{prefixo_arquivo}_{identificador_seguro}_{timestamp_nome_arquivo}.txt"
    )

    def registrar(mensagem):
        mensagem_str = str(mensagem)
        print(mensagem_str)
        logs.append(mensagem_str)
        if LOG_CALLBACK:
            try:
                LOG_CALLBACK(mensagem_str)
            except Exception:
                pass

    def gravar_arquivo():
        os.makedirs(diretorio_log, exist_ok=True)
        with open(caminho_log, "w", encoding="utf-8") as arquivo_log:
            arquivo_log.write("\n".join(logs))
        msg = f"[LOG] Arquivo de log gerado em: {caminho_log}"
        print(msg)
        if LOG_CALLBACK:
            try:
                LOG_CALLBACK(msg)
            except Exception:
                pass

    return registrar, gravar_arquivo, timestamp_inicio, caminho_log


def formatar_xml_para_log(xml_texto):
    """Formata XML com indentação para facilitar leitura no log."""
    try:
        xml_dom = minidom.parseString(xml_texto.encode("utf-8"))
        return xml_dom.toprettyxml(indent="  ")
    except Exception:
        return xml_texto


# -------------------------------------------------------------------------
# ETAPA 4: UTILITÁRIOS DE INPUT MANUAL
# -------------------------------------------------------------------------
def ler_inteiro_obrigatorio(rotulo, registrar):
    while True:
        valor = input(rotulo).strip()
        if not valor:
            registrar("[AVISO] Campo obrigatório. Informe um valor numérico.")
            continue
        try:
            return int(valor)
        except ValueError:
            registrar("[AVISO] Valor inválido. Informe um número inteiro.")


def ler_inteiro_opcional(rotulo, registrar):
    valor = input(rotulo).strip()
    if not valor:
        return None
    try:
        return int(valor)
    except ValueError:
        registrar("[AVISO] Valor opcional inválido. Será enviado como None.")
        return None


def ler_data_opcional(rotulo, registrar):
    valor = input(rotulo).strip()
    if not valor:
        return None
    try:
        return datetime.strptime(valor, "%Y-%m-%d")
    except ValueError:
        registrar("[AVISO] Data opcional inválida. Valor será enviado como None.")
        return None


# -------------------------------------------------------------------------
# ETAPA 5: CONEXÃO ORACLE
# -------------------------------------------------------------------------
def abrir_conexao(registrar):
    """Abre conexão Oracle e valida com SELECT 1 FROM DUAL."""
    registrar("[LOG] Validando conexão com o banco de dados...")
    try:
        connection = oracledb.connect(user=USER, password=PASSWORD, dsn=DSN)
        cursor = connection.cursor()
        cursor.execute("SELECT 1 FROM DUAL")
        resultado = cursor.fetchone()
        registrar(f"[LOG] Conexão validada com sucesso! Teste do banco retornou: {resultado[0]}")
        return connection, cursor
    except Exception as e:
        registrar(f"[ERRO CRÍTICO] Falha na validação da conexão com o banco de dados: {e}")
        return None, None


# -------------------------------------------------------------------------
# ETAPA 6: SELECT POR FLUXO (lookup do cod_lote em cada tabela)
# -------------------------------------------------------------------------
def buscar_registros_fluxo(cursor, fluxo, cod_lote_alvo, registrar):
    """Executa o SELECT do fluxo (custom em query_lookup ou padrão por tabela_lookup)."""
    tabela_lookup = fluxo["tabela_lookup"]
    query = fluxo.get("query_lookup")
    if not query:
        query = f"""
            SELECT
                cod_lote,
                num_grd,
                cod_prestador_ts,
                mes_ano_ref,
                MAX(a.data_solicitacao_rev) AS ultima_data
            FROM {tabela_lookup} a
            WHERE a.cod_lote = :cod_lote
            GROUP BY
                cod_lote,
                num_grd,
                cod_prestador_ts,
                mes_ano_ref
        """
    registrar(f"[LOG] Buscando registros em '{tabela_lookup}' para cod_lote = '{cod_lote_alvo}'...")
    cursor.execute(query, cod_lote=cod_lote_alvo)
    registros = cursor.fetchall()
    registrar(f"[LOG] {len(registros)} registro(s) encontrado(s) em '{tabela_lookup}'.")
    return registros


# -------------------------------------------------------------------------
# ETAPA 7: EXECUÇÃO DOS DELETES DE UM FLUXO
# -------------------------------------------------------------------------
def executar_deletes_fluxo(cursor, deletes, num_grd, cod_prestador_ts, mes_ano_ref, ultima_data, cod_lote, registrar):
    """Executa cada DELETE configurado em um fluxo.

    Continua a execução mesmo se um DELETE falhar, registrando o erro específico de cada tabela.
    Ao final, se houver qualquer erro, lança RuntimeError com o resumo para que o chamador
    realize rollback.
    """
    total_excluido = 0
    detalhes = []
    for item in deletes:
        tabela = item["tabela"]
        usa_cod_lote = item.get("usa_cod_lote", False)
        usa_data_solicitacao_rev = item.get("usa_data_solicitacao_rev", True)
        usa_cod_prestador_ts = item.get("usa_cod_prestador_ts", True)

        try:
            condicoes = [
                "num_grd = :num_grd",
            ]
            binds = {"num_grd": num_grd}
            if usa_cod_prestador_ts:
                condicoes.append("cod_prestador_ts = :cod_prestador_ts")
                binds["cod_prestador_ts"] = cod_prestador_ts
            condicoes.append("mes_ano_ref = :mes_ano_ref")
            binds["mes_ano_ref"] = mes_ano_ref
            if usa_data_solicitacao_rev:
                condicoes.append("a.data_solicitacao_rev = :ultima_data")
                binds["ultima_data"] = ultima_data
            if usa_cod_lote:
                condicoes.append("a.cod_lote = :cod_lote")
                binds["cod_lote"] = cod_lote

            sql = f"DELETE FROM {tabela} a\n WHERE " + "\n   AND ".join(condicoes)

            descricao_filtros = []
            if usa_cod_lote:
                descricao_filtros.append("cod_lote")
            if not usa_cod_prestador_ts:
                descricao_filtros.append("sem cod_prestador_ts")
            if not usa_data_solicitacao_rev:
                descricao_filtros.append("sem data_solicitacao_rev")
            sufixo = f" ({', '.join(descricao_filtros)})" if descricao_filtros else ""
            registrar(f"      [LOG] Executando DELETE em '{tabela}'{sufixo}...")

            cursor.execute(sql, **binds)

            deletados = cursor.rowcount or 0
            total_excluido += deletados
            detalhes.append({"tabela": tabela, "deletados": deletados, "erro": None})
            registrar(f"      [LOG] Deletados {deletados} registro(s) em '{tabela}'.")

        except Exception as e:
            erro_str = str(e).strip()
            registrar(f"      [ERRO] Falha no DELETE da tabela '{tabela}': {erro_str}")
            detalhes.append({"tabela": tabela, "deletados": 0, "erro": erro_str})

    # --- Consolida erros ao final ---
    erros = [d for d in detalhes if d["erro"]]
    if erros:
        registrar("      [ERRO] Resumo dos DELETEs com falha:")
        for d in erros:
            registrar(f"        * {d['tabela']}: {d['erro']}")
        raise RuntimeError(
            "Falha em "
            + str(len(erros))
            + " DELETE(s): "
            + "; ".join(f"{d['tabela']} -> {d['erro']}" for d in erros)
        )

    return total_excluido, detalhes


# -------------------------------------------------------------------------
# ETAPA 8: LEITURA DO XML
# -------------------------------------------------------------------------
def ler_xml_do_lote(nome_arquivo, registrar):
    """Lê o XML do diretório local pelo nome do arquivo (cod_lote)."""
    caminho_arquivo = os.path.join(DIRETORIO_LOCAL, nome_arquivo)
    registrar(f"      [LOG] Tentando ler o arquivo XML em: '{caminho_arquivo}'")
    try:
        with open(caminho_arquivo, 'r', encoding='utf-8') as f:
            conteudo_xml = f.read()
        registrar(f"      [LOG] Arquivo XML lido com sucesso (Tamanho: {len(conteudo_xml)} caracteres).")
        return conteudo_xml
    except FileNotFoundError:
        registrar(f"      [ERRO] Arquivo '{nome_arquivo}' não encontrado no diretório '{DIRETORIO_LOCAL}'.")
        raise


# -------------------------------------------------------------------------
# ETAPA 9: CHAMADA DA PROCEDURE
# -------------------------------------------------------------------------
def chamar_procedure(
    cursor,
    conteudo_xml,
    nome_arquivo,
    cod_prestador_ts,
    mes_ano_ref,
    num_grd,
    p_mes_ano_ref_vinc,
    p_dt_prev_pgto,
    p_tipo,
    registrar,
    incluir_xml_no_log=True,
):
    """Executa a procedure PTU_IMPORTA_550 e registra os parâmetros enviados."""
    out_cod_retorno = cursor.var(oracledb.NUMBER)
    out_msg_retorno = cursor.var(oracledb.STRING)

    registrar(f"      [LOG] Executando a procedure '{NOME_PROCEDURE}'...")
    registrar("      [LOG] Parâmetros de entrada enviados para a procedure:")
    registrar(f"            p_nom_arquivo: {nome_arquivo}")
    registrar(f"            p_cod_prestador_ts: {cod_prestador_ts}")
    registrar(f"            p_mes_ano_ref: {mes_ano_ref}")
    registrar(f"            p_num_grd: {num_grd}")
    registrar(f"            p_mes_ano_ref_vinc: {p_mes_ano_ref_vinc}")
    registrar(f"            p_dt_prev_pgto: {p_dt_prev_pgto}")
    registrar(f"            p_tipo: {p_tipo}")

    if incluir_xml_no_log:
        registrar("            p_arquivo (XML) - INÍCIO")
        registrar(conteudo_xml)
        registrar("            p_arquivo (XML) - FIM")
        registrar("            p_arquivo (XML FORMATADO) - INÍCIO")
        registrar(formatar_xml_para_log(conteudo_xml))
        registrar("            p_arquivo (XML FORMATADO) - FIM")
    else:
        registrar(f"            p_arquivo (XML): conteúdo omitido no log (tamanho {len(conteudo_xml)} caracteres).")

    cursor.callproc(
        NOME_PROCEDURE,
        [
            conteudo_xml,
            nome_arquivo,
            cod_prestador_ts,
            mes_ano_ref,
            num_grd,
            p_mes_ano_ref_vinc,
            p_dt_prev_pgto,
            p_tipo,
            out_cod_retorno,
            out_msg_retorno,
        ],
    )

    cod_retorno = out_cod_retorno.getvalue()
    msg_retorno = out_msg_retorno.getvalue()
    registrar("      [LOG] Procedure executada com sucesso.")
    registrar(f"            Código de retorno: {cod_retorno}")
    registrar(f"            Mensagem de retorno: {msg_retorno}")
    return cod_retorno, msg_retorno


# -------------------------------------------------------------------------
# ETAPA 10: MODO INDIVIDUAL
# -------------------------------------------------------------------------
def processar_individual(cod_lote_alvo, parametros_manuais_pre=None):
    """Processa um único cod_lote tentando os 4 fluxos. Se não encontrar, modo manual.

    parametros_manuais_pre: dict opcional vindo da GUI para evitar chamadas a input().
        Chaves esperadas: cod_prestador_ts (obrigatório se cair no manual),
        mes_ano_ref, num_grd, mes_ano_ref_vinc, dt_prev_pgto, tipo.
    """
    registrar, gravar_arquivo, timestamp_inicio, _ = criar_logger("log_lote", cod_lote_alvo)
    connection = None
    cursor = None

    try:
        iniciar_oracle_client()
        registrar(f"[INÍCIO] Modo INDIVIDUAL | cod_lote: {cod_lote_alvo}")
        registrar(f"[LOG] Diretório configurado para leitura: {DIRETORIO_LOCAL}\n")

        connection, cursor = abrir_conexao(registrar)
        if not connection:
            registrar("[LOG] Processo interrompido pois a conexão falhou.")
            return

        # --- Tenta cada fluxo na ordem definida ---
        fluxo_encontrado = None
        registros = []
        for fluxo in FLUXOS_INDIVIDUAL:
            registrar("=" * 70)
            registrar(f"[LOG] Tentando fluxo: '{fluxo['nome']}' (tabela {fluxo['tabela_lookup']})")
            try:
                resultado = buscar_registros_fluxo(cursor, fluxo, cod_lote_alvo, registrar)
            except Exception as e:
                registrar(f"[ERRO] Falha ao consultar '{fluxo['tabela_lookup']}': {e}")
                continue

            if resultado:
                fluxo_encontrado = fluxo
                registros = resultado
                registrar(f"[LOG] Fluxo selecionado: '{fluxo['nome']}'.")
                break
            registrar(f"[LOG] Nenhum registro em '{fluxo['tabela_lookup']}', tentando próximo fluxo.")

        modo_manual = False
        parametros_manuais = {}

        # --- Se nenhum fluxo trouxe registros, entra em modo manual ---
        if not fluxo_encontrado:
            registrar("=" * 70)
            registrar(
                f"[AVISO] cod_lote '{cod_lote_alvo}' NÃO retornou registros em nenhum dos 4 fluxos "
                f"(ctm_grd_cob_r, ctm_grd_in, ctm_grd_pag_r, ctm_grd)."
            )
            registrar("[AVISO] Nenhum DELETE será executado neste cod_lote.")
            registrar("[LOG] Entrando em modo manual para informar os parâmetros da procedure.")

            if parametros_manuais_pre is not None:
                cod_prestador_ts_manual = parametros_manuais_pre.get("cod_prestador_ts")
                if not cod_prestador_ts_manual:
                    registrar("[ERRO] cod_prestador_ts não informado para modo manual. Abortando.")
                    return
                try:
                    cod_prestador_ts_manual = int(cod_prestador_ts_manual)
                except (TypeError, ValueError):
                    registrar(f"[ERRO] cod_prestador_ts inválido: {cod_prestador_ts_manual}")
                    return
                mes_ano_ref_manual = parametros_manuais_pre.get("mes_ano_ref")
                num_grd_manual = parametros_manuais_pre.get("num_grd")
                mes_ano_ref_vinc_manual = parametros_manuais_pre.get("mes_ano_ref_vinc")
                dt_prev_pgto_manual = parametros_manuais_pre.get("dt_prev_pgto")
                tipo_manual = parametros_manuais_pre.get("tipo") or None
                registrar(
                    "[LOG] Parâmetros manuais recebidos via GUI: "
                    f"cod_prestador_ts={cod_prestador_ts_manual}, mes_ano_ref={mes_ano_ref_manual}, "
                    f"num_grd={num_grd_manual}, mes_ano_ref_vinc={mes_ano_ref_vinc_manual}, "
                    f"dt_prev_pgto={dt_prev_pgto_manual}, tipo={tipo_manual}"
                )
            else:
                cod_prestador_ts_manual = ler_inteiro_obrigatorio("Informe p_cod_prestador_ts (obrigatório): ", registrar)
                mes_ano_ref_manual = ler_data_opcional("Informe p_mes_ano_ref (YYYY-MM-DD) ou ENTER para None: ", registrar)
                num_grd_manual = ler_inteiro_opcional("Informe p_num_grd ou ENTER para None: ", registrar)
                mes_ano_ref_vinc_manual = ler_data_opcional("Informe p_mes_ano_ref_vinc (YYYY-MM-DD) ou ENTER para None: ", registrar)
                dt_prev_pgto_manual = ler_data_opcional("Informe p_dt_prev_pgto (YYYY-MM-DD) ou ENTER para None: ", registrar)
                tipo_manual = input("Informe p_tipo ou ENTER para None: ").strip() or None

            registros = [(cod_lote_alvo, num_grd_manual, cod_prestador_ts_manual, mes_ano_ref_manual, None)]
            parametros_manuais = {
                "p_mes_ano_ref_vinc": mes_ano_ref_vinc_manual,
                "p_dt_prev_pgto": dt_prev_pgto_manual,
                "p_tipo": tipo_manual,
            }
            modo_manual = True

        # --- Processa cada registro encontrado (ou sintético do modo manual) ---
        for row in registros:
            cod_lote, num_grd, cod_prestador_ts, mes_ano_ref, ultima_data = row

            registrar("-" * 70)
            registrar(f"[LOG] Processando PTU | cod_lote: {cod_lote}")
            registrar(
                f"      Dados - num_grd: {num_grd} | Prestador: {cod_prestador_ts} | "
                f"Mês/Ano: {mes_ano_ref} | Data: {ultima_data}"
            )

            try:
                p_mes_ano_ref_vinc = None
                p_dt_prev_pgto = None
                p_tipo = None

                if modo_manual:
                    p_mes_ano_ref_vinc = parametros_manuais["p_mes_ano_ref_vinc"]
                    p_dt_prev_pgto = parametros_manuais["p_dt_prev_pgto"]
                    p_tipo = parametros_manuais["p_tipo"]
                    registrar("      [LOG] Modo manual ativo: etapa de DELETE foi ignorada.")
                else:
                    registrar(f"      [LOG] Iniciando DELETEs do fluxo '{fluxo_encontrado['nome']}'.")
                    total_excluido, _ = executar_deletes_fluxo(
                        cursor,
                        fluxo_encontrado["deletes"],
                        num_grd,
                        cod_prestador_ts,
                        mes_ano_ref,
                        ultima_data,
                        cod_lote,
                        registrar,
                    )
                    registrar(f"      [LOG] Total geral de exclusões neste registro: {total_excluido}.")

                conteudo_xml = ler_xml_do_lote(cod_lote, registrar)

                chamar_procedure(
                    cursor,
                    conteudo_xml=conteudo_xml,
                    nome_arquivo=cod_lote,
                    cod_prestador_ts=cod_prestador_ts,
                    mes_ano_ref=mes_ano_ref,
                    num_grd=num_grd,
                    p_mes_ano_ref_vinc=p_mes_ano_ref_vinc,
                    p_dt_prev_pgto=p_dt_prev_pgto,
                    p_tipo=p_tipo,
                    registrar=registrar,
                    incluir_xml_no_log=True,
                )

                connection.commit()
                registrar(f"      [LOG] Transação (Commit) efetivada com sucesso para o lote '{cod_lote}'.\n")

            except Exception as e:
                if connection:
                    connection.rollback()
                registrar(f"\n      [ERRO] Falha ao processar a etapa para o lote {cod_lote}: {e}")
                registrar("      [LOG] Rollback realizado para evitar inconsistência.\n")

        registrar("[FIM] Processamento concluído.")

    except Exception as e:
        registrar(f"[ERRO] Erro inesperado no fluxo individual: {e}")

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

        timestamp_fim = datetime.now()
        registrar(f"[LOG] Início do processamento: {timestamp_inicio.strftime('%Y-%m-%d %H:%M:%S')}")
        registrar(f"[LOG] Fim do processamento: {timestamp_fim.strftime('%Y-%m-%d %H:%M:%S')}")
        gravar_arquivo()


# -------------------------------------------------------------------------
# ETAPA 11: MODO LOTE (CSV)
# -------------------------------------------------------------------------
def processar_em_lote(caminho_csv):
    """Lê lote.csv, processa cada linha chamando a procedure com xml + cod_prestador_ts."""
    registrar, gravar_arquivo, timestamp_inicio, _ = criar_logger("log_massa", "lote_csv")
    connection = None
    cursor = None
    sucessos = []
    falhas = []

    total_exclusoes_geral = 0
    sem_fluxo = []

    try:
        iniciar_oracle_client()
        registrar("[INÍCIO] Modo LOTE (CSV)")
        registrar(f"[LOG] Arquivo CSV: {caminho_csv}")
        registrar(f"[LOG] Diretório configurado para leitura dos XMLs: {DIRETORIO_LOCAL}")
        registrar(f"[LOG] EXECUTAR_IMPORT_MASSA = {EXECUTAR_IMPORT_MASSA} "
                  f"({'procedure será chamada' if EXECUTAR_IMPORT_MASSA else 'apenas exclusões'}).\n")

        # --- Abre CSV ---
        if not os.path.exists(caminho_csv):
            registrar(f"[ERRO CRÍTICO] Arquivo CSV não encontrado: {caminho_csv}")
            return

        connection, cursor = abrir_conexao(registrar)
        if not connection:
            registrar("[LOG] Processo interrompido pois a conexão falhou.")
            return

        with open(caminho_csv, "r", encoding="utf-8-sig", newline="") as f:
            # --- Detecta delimitador (vírgula ou ponto-e-vírgula) ---
            amostra = f.read(2048)
            f.seek(0)
            try:
                dialect = csv.Sniffer().sniff(amostra, delimiters=",;|\t")
            except csv.Error:
                dialect = csv.excel

            leitor = csv.DictReader(f, dialect=dialect)
            colunas = leitor.fieldnames or []
            registrar(f"[LOG] Colunas detectadas no CSV: {colunas}")

            # --- Identifica colunas requeridas ---
            mapa_colunas = {c.lower().strip(): c for c in colunas}
            coluna_prestador = mapa_colunas.get("cod_prestador_ts")
            coluna_arquivo = (
                mapa_colunas.get("nome_arquivo")
                or mapa_colunas.get("arquivo")
                or mapa_colunas.get("nom_arquivo")
                or mapa_colunas.get("nome")
                or mapa_colunas.get("xml")
            )

            if not coluna_prestador or not coluna_arquivo:
                registrar(
                    "[ERRO CRÍTICO] CSV deve conter as colunas 'cod_prestador_ts' e o nome do arquivo "
                    "(ex.: 'nome_arquivo')."
                )
                return

            registrar(f"[LOG] Coluna prestador: '{coluna_prestador}' | Coluna arquivo: '{coluna_arquivo}'")

            # --- Itera linhas do CSV ---
            for indice, linha in enumerate(leitor, start=1):
                registrar("-" * 70)
                registrar(f"[LOG] Linha {indice} do CSV: {linha}")

                cod_prestador_ts_str = (linha.get(coluna_prestador) or "").strip()
                nome_arquivo = (linha.get(coluna_arquivo) or "").strip()

                if not cod_prestador_ts_str or not nome_arquivo:
                    msg = f"Linha {indice} ignorada: cod_prestador_ts ou nome_arquivo vazio."
                    registrar(f"      [ERRO] {msg}")
                    falhas.append({"linha": indice, "arquivo": nome_arquivo, "motivo": msg})
                    continue

                try:
                    cod_prestador_ts = int(cod_prestador_ts_str)
                except ValueError:
                    msg = f"cod_prestador_ts inválido: '{cod_prestador_ts_str}'."
                    registrar(f"      [ERRO] {msg}")
                    falhas.append({"linha": indice, "arquivo": nome_arquivo, "motivo": msg})
                    continue

                # --- Lookup nos 4 fluxos para identificar registros e executar DELETEs ---
                fluxo_encontrado = None
                registros_fluxo = []
                for fluxo in FLUXOS_INDIVIDUAL:
                    registrar(f"      [LOG] Tentando fluxo: '{fluxo['nome']}' (tabela {fluxo['tabela_lookup']}).")
                    try:
                        resultado = buscar_registros_fluxo(cursor, fluxo, nome_arquivo, registrar)
                    except Exception as e:
                        registrar(f"      [ERRO] Falha ao consultar '{fluxo['tabela_lookup']}': {e}")
                        continue
                    if resultado:
                        fluxo_encontrado = fluxo
                        registros_fluxo = resultado
                        registrar(f"      [LOG] Fluxo selecionado: '{fluxo['nome']}'.")
                        break

                exclusoes_arquivo = 0
                detalhes_arquivo = []

                if fluxo_encontrado:
                    try:
                        for row in registros_fluxo:
                            r_cod_lote, r_num_grd, r_cod_prestador_ts, r_mes_ano_ref, r_ultima_data = row
                            registrar(
                                f"      [LOG] Registro encontrado | num_grd: {r_num_grd} | "
                                f"prestador: {r_cod_prestador_ts} | mes_ano_ref: {r_mes_ano_ref} | "
                                f"ultima_data: {r_ultima_data}"
                            )
                            total_excluido, detalhes = executar_deletes_fluxo(
                                cursor,
                                fluxo_encontrado["deletes"],
                                r_num_grd,
                                r_cod_prestador_ts,
                                r_mes_ano_ref,
                                r_ultima_data,
                                r_cod_lote,
                                registrar,
                            )
                            exclusoes_arquivo += total_excluido
                            detalhes_arquivo.extend(detalhes)
                        registrar(f"      [LOG] Total de exclusões para '{nome_arquivo}': {exclusoes_arquivo}.")
                    except Exception as e:
                        if connection:
                            connection.rollback()
                        msg = f"Erro ao executar DELETEs: {e}"
                        registrar(f"      [ERRO] {msg}")
                        registrar("      [LOG] Rollback realizado.")
                        falhas.append({"linha": indice, "arquivo": nome_arquivo, "motivo": msg})
                        continue
                else:
                    registrar(
                        f"      [AVISO] cod_lote '{nome_arquivo}' NÃO retornou registros em nenhum dos 4 fluxos."
                    )
                    registrar("      [AVISO] Nenhum DELETE foi executado para este arquivo.")
                    sem_fluxo.append({
                        "linha": indice,
                        "arquivo": nome_arquivo,
                        "cod_prestador_ts": cod_prestador_ts,
                    })

                total_exclusoes_geral += exclusoes_arquivo

                # --- Se a chave estiver desligada, pula a procedure e commita só as exclusões ---
                if not EXECUTAR_IMPORT_MASSA:
                    registrar("      [LOG] EXECUTAR_IMPORT_MASSA=False -> procedure NÃO será chamada.")
                    try:
                        connection.commit()
                        registrar(f"      [LOG] Commit das exclusões efetivado para '{nome_arquivo}'.")
                        sucessos.append({
                            "linha": indice,
                            "arquivo": nome_arquivo,
                            "cod_prestador_ts": cod_prestador_ts,
                            "cod_retorno": None,
                            "msg_retorno": "IMPORT IGNORADO (apenas exclusões)",
                            "exclusoes": exclusoes_arquivo,
                            "detalhes_exclusoes": detalhes_arquivo,
                        })
                    except Exception as e:
                        if connection:
                            connection.rollback()
                        msg = f"Erro ao commitar exclusões: {e}"
                        registrar(f"      [ERRO] {msg}")
                        falhas.append({"linha": indice, "arquivo": nome_arquivo, "motivo": msg})
                    continue

                # --- Caso a flag esteja ligada, segue com leitura do XML + procedure ---
                try:
                    conteudo_xml = ler_xml_do_lote(nome_arquivo, registrar)
                except FileNotFoundError as e:
                    if connection:
                        connection.rollback()
                    registrar("      [LOG] Rollback realizado pois XML não foi encontrado.")
                    falhas.append({"linha": indice, "arquivo": nome_arquivo, "motivo": str(e)})
                    continue
                except Exception as e:
                    if connection:
                        connection.rollback()
                    msg = f"Falha ao ler XML: {e}"
                    registrar(f"      [ERRO] {msg}")
                    falhas.append({"linha": indice, "arquivo": nome_arquivo, "motivo": msg})
                    continue

                try:
                    cod_retorno, msg_retorno = chamar_procedure(
                        cursor,
                        conteudo_xml=conteudo_xml,
                        nome_arquivo=nome_arquivo,
                        cod_prestador_ts=cod_prestador_ts,
                        mes_ano_ref=None,
                        num_grd=None,
                        p_mes_ano_ref_vinc=None,
                        p_dt_prev_pgto=None,
                        p_tipo=None,
                        registrar=registrar,
                        incluir_xml_no_log=False,
                    )
                    connection.commit()
                    registrar(f"      [LOG] Commit efetivado para o arquivo '{nome_arquivo}'.")
                    sucessos.append({
                        "linha": indice,
                        "arquivo": nome_arquivo,
                        "cod_prestador_ts": cod_prestador_ts,
                        "cod_retorno": cod_retorno,
                        "msg_retorno": msg_retorno,
                        "exclusoes": exclusoes_arquivo,
                        "detalhes_exclusoes": detalhes_arquivo,
                    })
                except Exception as e:
                    if connection:
                        connection.rollback()
                    msg = f"Erro ao executar procedure: {e}"
                    registrar(f"      [ERRO] {msg}")
                    registrar("      [LOG] Rollback realizado.")
                    falhas.append({"linha": indice, "arquivo": nome_arquivo, "motivo": msg})

        # --- Resumo final ---
        registrar("=" * 70)
        titulo_resumo = (
            "[RESUMO] Arquivos processados com sucesso (exclusões + procedure):"
            if EXECUTAR_IMPORT_MASSA
            else "[RESUMO] Arquivos processados com sucesso (somente exclusões, import ignorado):"
        )
        registrar(titulo_resumo)
        if sucessos:
            for item in sucessos:
                registrar(
                    f"  - Linha {item['linha']} | Arquivo: {item['arquivo']} | "
                    f"Prestador: {item['cod_prestador_ts']} | "
                    f"Exclusões: {item.get('exclusoes', 0)} | "
                    f"Retorno: {item['cod_retorno']} | Msg: {item['msg_retorno']}"
                )
                detalhes = item.get("detalhes_exclusoes") or []
                for det in detalhes:
                    registrar(f"        * {det['tabela']}: {det['deletados']} registro(s)")
        else:
            registrar("  - Nenhum arquivo processado com sucesso.")

        registrar("[RESUMO] Falhas durante a execução:")
        if falhas:
            for item in falhas:
                registrar(f"  - Linha {item['linha']} | Arquivo: {item['arquivo']} | Motivo: {item['motivo']}")
        else:
            registrar("  - Nenhuma falha registrada.")

        registrar("[RESUMO] Arquivos que NÃO entraram em nenhum fluxo (sem DELETEs executados):")
        if sem_fluxo:
            for item in sem_fluxo:
                registrar(
                    f"  - Linha {item['linha']} | Arquivo: {item['arquivo']} | "
                    f"Prestador: {item['cod_prestador_ts']}"
                )
        else:
            registrar("  - Nenhum arquivo nessa condição.")

        registrar(
            f"[RESUMO] Total sucesso: {len(sucessos)} | "
            f"Total falhas: {len(falhas)} | "
            f"Sem fluxo: {len(sem_fluxo)} | "
            f"Total exclusões geral: {total_exclusoes_geral}"
        )
        registrar("[FIM] Processamento em lote concluído.")

    except Exception as e:
        registrar(f"[ERRO] Erro inesperado no fluxo em lote: {e}")

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

        timestamp_fim = datetime.now()
        registrar(f"[LOG] Início do processamento: {timestamp_inicio.strftime('%Y-%m-%d %H:%M:%S')}")
        registrar(f"[LOG] Fim do processamento: {timestamp_fim.strftime('%Y-%m-%d %H:%M:%S')}")
        gravar_arquivo()


# -------------------------------------------------------------------------
# ETAPA 12: ENTRADA DE EXECUÇÃO VIA TERMINAL
# -------------------------------------------------------------------------
if __name__ == '__main__':
    print("Selecione o modo de execução:")
    print("  1 - Individual (informa um cod_lote)")
    print("  2 - Lote (lê arquivo lote.csv)")
    opcao = input("Informe a opção (1 ou 2): ").strip()

    if opcao == "1":
        cod_lote_entrada = input("Informe o cod_lote a ser processado: ").strip()
        if not cod_lote_entrada:
            print("[ERRO] cod_lote não informado.")
            raise SystemExit(1)
        processar_individual(cod_lote_entrada)

    elif opcao == "2":
        caminho_csv_padrao = os.path.join(get_base_dir(), "lote.csv")
        caminho_csv_input = input(
            f"Informe o caminho do CSV ou ENTER para usar '{caminho_csv_padrao}': "
        ).strip()
        caminho_csv = caminho_csv_input or caminho_csv_padrao
        processar_em_lote(caminho_csv)

    else:
        print("[ERRO] Opção inválida. Use 1 (individual) ou 2 (lote).")
        raise SystemExit(1)
