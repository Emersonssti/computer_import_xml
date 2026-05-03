# PTU 550 — Manual de Uso (Windows)

Aplicativo para importação e processamento de PTU 550 no Oracle, com modo individual (`cod_lote`) e modo lote (CSV).

---

## 1. Pré-requisitos

### 1.1. Python 3.10+ (apenas para gerar o executável)

Baixe e instale em [python.org/downloads/windows](https://www.python.org/downloads/windows/).

> Marque a opção **"Add Python to PATH"** durante a instalação.

### 1.2. Oracle Instant Client (obrigatório em qualquer máquina que vá rodar o app)

#### Por que é necessário?

O app conecta no banco Oracle usando a biblioteca Python `python-oracledb`, que pode operar em dois modos:

- **Modo THIN** (puro Python, sem Instant Client): só funciona com bancos modernos que usam *password verifier* 11G+ (`0x4`, `0x5`).
- **Modo THICK** (usa as DLLs nativas do Oracle): funciona com qualquer banco, incluindo bancos legados com *password verifier* 10G (`0x939`).

Como o ambiente atual (**OPER1**) usa o verifier antigo (`0x939`), a conexão **só funciona em modo THICK**, que exige o Oracle Instant Client instalado na máquina. Por isso ele é obrigatório.

#### Erro que ocorre sem o Instant Client

Se você tentar rodar sem o Instant Client (ou com caminho errado), aparece no log:

```
DPY-3015: password verifier type 0x939 is not supported by python-oracledb in thin mode
```

Outros erros possíveis se o caminho estiver incorreto:

```
DPI-1047: Cannot locate a 64-bit Oracle Client library
```
ou
```
[ERRO CRÍTICO] Falha na validação da conexão com o banco de dados
```

Em todos os casos, a solução é **apontar a tela do app para a pasta correta do Instant Client**.

#### Como instalar

1. Acesse [Oracle Instant Client - Windows x64](https://www.oracle.com/database/technologies/instant-client/winx64-64-downloads.html).
2. Baixe o **Basic Package** (ex.: `instantclient-basic-windows.x64-21.13.0.0.0dbru.zip`).
3. Extraia em uma pasta de sua preferência. Exemplo:
   ```
   C:\oracle\instantclient_21_13\
   ```
4. Anote esse caminho — você vai informá-lo na tela do app.

> A pasta correta é a que contém o arquivo `oci.dll`. Se você abrir e não ver o `oci.dll`, está apontando para o lugar errado.

---

## 2. Estrutura de pastas esperada

Em qualquer máquina que rodar o `PTU550.exe`, monte assim:

```
C:\PTU550\
├── PTU550.exe                  <- executável gerado
├── lote.csv                    <- (modo Lote) deve ficar AQUI
└── log\                        <- criado automaticamente
    ├── log_lote_<cod_lote>_<timestamp>.txt
    └── log_massa_lote_csv_<timestamp>.txt
```

E em outra pasta qualquer (configurada no app), os XMLs:

```
D:\arquivos_ptu\
├── NR6_9367648.032
├── NR8_8977865.032
└── ...
```

> O nome de cada arquivo XML **deve ser exatamente igual ao `cod_lote`**.

---

## 3. Como gerar o executável (somente uma vez, em uma máquina Windows)

### 3.1. Abra o `cmd` ou `PowerShell` na pasta do projeto

```cmd
cd C:\caminho\para\PTU_550
```

### 3.2. (Opcional) Crie um ambiente virtual

```cmd
python -m venv venv
venv\Scripts\activate
```

### 3.3. Instale as dependências

```cmd
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 3.4. Gere o executável

```cmd
build_windows.bat
```

ou manualmente:

```cmd
pyinstaller --noconfirm --onefile --windowed --name "PTU550" ^
  --collect-all oracledb ^
  --hidden-import tkinter ^
  --hidden-import tkinter.ttk ^
  --hidden-import tkinter.filedialog ^
  --hidden-import tkinter.messagebox ^
  app_gui.py
```

O executável final estará em:

```
dist\PTU550.exe
```

### 3.5. Distribua

Copie o `PTU550.exe` da pasta `dist\` para qualquer máquina Windows.
A máquina destino precisa:
- Ter o **Oracle Instant Client** baixado e extraído (passo 1.2).
- Ter acesso de rede ao banco Oracle.

---

## 4. Como executar o app (usuário final)

### 4.1. Abrir o app

Dê duplo clique em `PTU550.exe`.

### 4.2. Preencher a tela

| Campo | O que informar |
|---|---|
| **Ambiente** | Por padrão `OPER1` (única opção atual). |
| **Diretório dos XMLs** | Pasta onde estão os arquivos XML do PTU (ex.: `D:\arquivos_ptu`). Use o botão `...` para navegar. |
| **Oracle Instant Client** | Pasta extraída no passo 1.2 (ex.: `C:\oracle\instantclient_21_13`). Use o botão `...` para navegar. |
| **Modo** | `Individual` ou `Lote (lê lote.csv ao lado do executável)`. |
| **cod_lote** | Apenas no modo Individual. Nome do arquivo XML que será importado. |
| **Executar import (procedure)** | Marcado: faz DELETE + chama a procedure. Desmarcado: faz somente DELETE. |
| **Parâmetros manuais** | Apenas modo Individual. Usados se o `cod_lote` não for encontrado em nenhum dos 4 fluxos. **Apenas `cod_prestador_ts` é obrigatório nesse caso**, os outros podem ficar em branco. |

### 4.3. Clicar em **Executar**

- O app processa em segundo plano.
- O log aparece em tempo real na parte inferior.
- Ao final, é gerado um arquivo `.txt` na pasta `log\` ao lado do `PTU550.exe`.

### 4.4. Abrir a pasta de logs

Botão **"Abrir pasta de logs"** abre o diretório no Windows Explorer.

---

## 5. Modo Lote — formato do `lote.csv`

### 5.1. Local

O arquivo **deve se chamar `lote.csv`** e ficar **no mesmo diretório do `PTU550.exe`**.

### 5.2. Colunas obrigatórias

| Coluna | Descrição |
|---|---|
| `cod_prestador_ts` | Código numérico do prestador (inteiro). |
| `nome_arquivo` | Nome exato do arquivo XML (sem caminho). |

> Aliases aceitos para o nome do arquivo: `arquivo`, `nom_arquivo`, `nome`, `xml`.

### 5.3. Delimitador

Aceita automaticamente: vírgula `,`, ponto-e-vírgula `;`, pipe `|` ou tab.

### 5.4. Exemplo

```csv
cod_prestador_ts,nome_arquivo
219267,NR6_9367648.032
219267,NR8_8977865.032
189235,NR4_18938120_1.032
```

### 5.5. Comportamento por linha

Para cada linha do CSV:
1. Tenta achar o `cod_lote` (= `nome_arquivo`) nos **4 fluxos**, em ordem:
   - `ctm_grd_cob_r` (Intercâmbio a cobrar - revisão fechada)
   - `ctm_grd_in_r` (Intercâmbio a cobrar - revisão aberta)
   - `ctm_grd_pag_r` (Intercâmbio a pagar - revisão fechada)
   - `ctm_grd` (Intercâmbio a pagar - revisão aberta)
2. Se encontrar, executa todos os DELETEs do fluxo correspondente.
3. Se a opção **"Executar import"** estiver marcada: chama a procedure `PTU_XML_IMPORTA_A550.PTU_IMPORTA_550` enviando o XML + `cod_prestador_ts` (demais parâmetros = `NULL`).
4. Se a opção estiver desmarcada: faz só os DELETEs.
5. Se nenhum fluxo encontrar registros, registra `[AVISO]` e não executa DELETE.
6. No fim, escreve um resumo no log (sucessos, falhas, sem fluxo, total de exclusões).

---

## 6. Modo Individual

1. Marque o radio **Individual**.
2. Informe o `cod_lote` (= nome do arquivo XML).
3. Opcionalmente preencha os parâmetros manuais (usados só se o `cod_lote` não estiver no banco).
4. Clique **Executar**.

---

## 7. Onde fica cada coisa

| Item | Onde |
|---|---|
| `PTU550.exe` | Qualquer pasta na máquina (ex.: `C:\PTU550\`) |
| `lote.csv` | **Mesma pasta** do `PTU550.exe` |
| Pasta `log\` | Criada automaticamente ao lado do `PTU550.exe` |
| Pasta dos XMLs | Qualquer lugar — informe o caminho na tela do app |
| Oracle Instant Client | Qualquer lugar — informe o caminho na tela do app |

---

## 8. Solução de problemas

### Erro `DPI-1047` ou `cannot locate Oracle Client`
- Caminho do Instant Client está incorreto.
- Verifique se a pasta informada contém `oci.dll`.
- Recomenda-se baixar a versão **x64** (compatível com Python x64).

### Erro `[ERRO CRÍTICO] Falha na validação da conexão`
- Verifique acesso de rede ao banco.
- Verifique credenciais do ambiente (configuradas no `index.py`).

### Arquivo XML não encontrado
- O nome do arquivo deve ser **idêntico** ao `cod_lote`.
- Confirme o caminho do diretório dos XMLs na tela.

### CSV não é lido
- Confirme que o nome é **`lote.csv`** (minúsculo).
- Confirme que está na **mesma pasta** do `PTU550.exe`.
- Confirme as colunas `cod_prestador_ts` e `nome_arquivo`.

### Log não aparece
- Confirme que a pasta `log\` ao lado do `PTU550.exe` tem permissão de escrita.

---

## 9. O que o app faz tecnicamente

1. **Lookup nas 4 tabelas** (`ctm_grd_cob_r`, `ctm_grd_in_r`, `ctm_grd_pag_r`, `ctm_grd`) usando `cod_lote`.
2. **Executa DELETEs em cascata** nas tabelas filhas/pais correspondentes ao fluxo encontrado.
3. **Lê o XML** do diretório informado.
4. **Chama a procedure** `PTU_XML_IMPORTA_A550.PTU_IMPORTA_550` com o XML + parâmetros do registro encontrado.
5. **Commita** a transação ou faz **rollback** em caso de erro.
6. **Gera log completo** em `log\*.txt` com tudo que foi feito (incluindo XML enviado, em modo individual).
