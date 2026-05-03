import os
import sys
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime

import index as core


# -------------------------------------------------------------------------
# Aplicativo GUI (Tkinter)
# -------------------------------------------------------------------------
class PTU550App(tk.Tk):
    PADX = 8
    PADY = 4

    def __init__(self):
        super().__init__()
        self.title("PTU 550 - Importação")
        self.geometry("980x780")
        self.minsize(820, 640)

        self.log_queue = queue.Queue()
        self.processing_thread = None

        self._build_ui()
        self._popular_defaults()
        self._iniciar_consumidor_log()

    # ---------------------------------------------------------------------
    # UI
    # ---------------------------------------------------------------------
    def _build_ui(self):
        container = ttk.Frame(self, padding=self.PADX)
        container.pack(fill=tk.BOTH, expand=True)

        # ----- Configurações -----
        frm_config = ttk.LabelFrame(container, text="Configurações", padding=self.PADX)
        frm_config.pack(fill=tk.X, pady=(0, self.PADY))

        ttk.Label(frm_config, text="Ambiente:").grid(row=0, column=0, sticky=tk.W, padx=self.PADX, pady=self.PADY)
        self.var_ambiente = tk.StringVar(value="OPER1")
        cb_ambiente = ttk.Combobox(
            frm_config,
            textvariable=self.var_ambiente,
            values=list(core.AMBIENTES.keys()),
            state="readonly",
            width=20,
        )
        cb_ambiente.grid(row=0, column=1, sticky=tk.W, padx=self.PADX, pady=self.PADY)

        ttk.Label(frm_config, text="Diretório dos XMLs:").grid(row=1, column=0, sticky=tk.W, padx=self.PADX, pady=self.PADY)
        self.var_diretorio = tk.StringVar()
        ttk.Entry(frm_config, textvariable=self.var_diretorio, width=70).grid(row=1, column=1, sticky=tk.EW, padx=self.PADX, pady=self.PADY)
        ttk.Button(frm_config, text="...", width=3, command=self._escolher_diretorio_xml).grid(row=1, column=2, padx=(0, self.PADX), pady=self.PADY)

        ttk.Label(
            frm_config,
            text="Oracle Instant Client (pasta com os arquivos baixados do site da Oracle):",
        ).grid(row=2, column=0, columnspan=3, sticky=tk.W, padx=self.PADX, pady=(self.PADY, 0))
        self.var_instant_client = tk.StringVar()
        self.entry_instant_client = ttk.Entry(frm_config, textvariable=self.var_instant_client, width=70)
        self.entry_instant_client.grid(row=3, column=0, columnspan=2, sticky=tk.EW, padx=self.PADX, pady=self.PADY)
        self.btn_instant_client = ttk.Button(frm_config, text="...", width=3, command=self._escolher_instant_client)
        self.btn_instant_client.grid(row=3, column=2, padx=(0, self.PADX), pady=self.PADY)

        frm_config.columnconfigure(1, weight=1)

        # ----- Modo / Execução -----
        frm_modo = ttk.LabelFrame(container, text="Modo de execução", padding=self.PADX)
        frm_modo.pack(fill=tk.X, pady=(0, self.PADY))

        self.var_modo = tk.StringVar(value="individual")
        ttk.Radiobutton(frm_modo, text="Individual (informa um cod_lote)", variable=self.var_modo, value="individual", command=self._atualizar_visibilidade).grid(row=0, column=0, sticky=tk.W, padx=self.PADX, pady=self.PADY)
        ttk.Radiobutton(frm_modo, text="Lote (lê lote.csv ao lado do executável)", variable=self.var_modo, value="lote", command=self._atualizar_visibilidade).grid(row=0, column=1, sticky=tk.W, padx=self.PADX, pady=self.PADY)

        ttk.Label(frm_modo, text="cod_lote:").grid(row=1, column=0, sticky=tk.W, padx=self.PADX, pady=self.PADY)
        self.var_cod_lote = tk.StringVar()
        self.entry_cod_lote = ttk.Entry(frm_modo, textvariable=self.var_cod_lote, width=40)
        self.entry_cod_lote.grid(row=1, column=1, sticky=tk.W, padx=self.PADX, pady=self.PADY)

        self.var_executar_import = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            frm_modo,
            text="Executar import (chamar procedure). Se desligado, apenas DELETEs serão feitos no modo lote.",
            variable=self.var_executar_import,
        ).grid(row=2, column=0, columnspan=3, sticky=tk.W, padx=self.PADX, pady=self.PADY)

        frm_modo.columnconfigure(1, weight=1)

        # ----- Parâmetros manuais (apenas Individual) -----
        self.frm_manual = ttk.LabelFrame(
            container,
            text="Parâmetros manuais (usados se cod_lote não for encontrado em nenhum dos 4 fluxos)",
            padding=self.PADX,
        )
        self.frm_manual.pack(fill=tk.X, pady=(0, self.PADY))

        labels_manuais = [
            ("cod_prestador_ts (obrigatório se manual):", "cod_prestador_ts"),
            ("mes_ano_ref (YYYY-MM-DD):", "mes_ano_ref"),
            ("num_grd:", "num_grd"),
            ("mes_ano_ref_vinc (YYYY-MM-DD):", "mes_ano_ref_vinc"),
            ("dt_prev_pgto (YYYY-MM-DD):", "dt_prev_pgto"),
            ("tipo:", "tipo"),
        ]
        self.vars_manuais = {}
        for i, (texto, chave) in enumerate(labels_manuais):
            ttk.Label(self.frm_manual, text=texto).grid(row=i, column=0, sticky=tk.W, padx=self.PADX, pady=2)
            var = tk.StringVar()
            ttk.Entry(self.frm_manual, textvariable=var, width=40).grid(row=i, column=1, sticky=tk.W, padx=self.PADX, pady=2)
            self.vars_manuais[chave] = var

        self.frm_manual.columnconfigure(1, weight=1)

        # ----- Botões -----
        frm_acoes = ttk.Frame(container)
        frm_acoes.pack(fill=tk.X, pady=(0, self.PADY))
        self.btn_executar = ttk.Button(frm_acoes, text="Executar", command=self._executar)
        self.btn_executar.pack(side=tk.LEFT, padx=self.PADX)
        ttk.Button(frm_acoes, text="Limpar log", command=self._limpar_log).pack(side=tk.LEFT)
        ttk.Button(frm_acoes, text="Abrir pasta de logs", command=self._abrir_pasta_log).pack(side=tk.LEFT, padx=self.PADX)

        # ----- Log -----
        frm_log = ttk.LabelFrame(container, text="Log", padding=self.PADX)
        frm_log.pack(fill=tk.BOTH, expand=True)

        self.txt_log = tk.Text(frm_log, wrap=tk.NONE, height=20, font=("Menlo", 11))
        scroll_y = ttk.Scrollbar(frm_log, orient=tk.VERTICAL, command=self.txt_log.yview)
        scroll_x = ttk.Scrollbar(frm_log, orient=tk.HORIZONTAL, command=self.txt_log.xview)
        self.txt_log.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set, state=tk.DISABLED)
        self.txt_log.grid(row=0, column=0, sticky=tk.NSEW)
        scroll_y.grid(row=0, column=1, sticky=tk.NS)
        scroll_x.grid(row=1, column=0, sticky=tk.EW)
        frm_log.rowconfigure(0, weight=1)
        frm_log.columnconfigure(0, weight=1)

        # ----- Status -----
        self.var_status = tk.StringVar(value="Pronto.")
        ttk.Label(container, textvariable=self.var_status, anchor=tk.W).pack(fill=tk.X, pady=(self.PADY, 0))

    def _popular_defaults(self):
        self.var_diretorio.set(core.DIRETORIO_LOCAL)
        self.var_instant_client.set(core.CAMINHO_INSTANT_CLIENT)
        self._atualizar_visibilidade()

    def _atualizar_visibilidade(self):
        modo = self.var_modo.get()
        habilitado = modo == "individual"
        estado = tk.NORMAL if habilitado else tk.DISABLED

        # cod_lote (modo individual)
        self.entry_cod_lote.configure(state=estado)

        # Parâmetros manuais (somente individual)
        for child in self.frm_manual.winfo_children():
            if isinstance(child, (ttk.Entry, ttk.Label)):
                try:
                    child.configure(state=estado)
                except tk.TclError:
                    pass

        # Atualiza título do frame para deixar claro o estado
        if habilitado:
            self.frm_manual.configure(
                text="Parâmetros manuais (usados se cod_lote não for encontrado em nenhum dos 4 fluxos)"
            )
        else:
            self.frm_manual.configure(
                text="Parâmetros manuais (DESABILITADOS no modo Lote)"
            )

    # ---------------------------------------------------------------------
    # Helpers de UI
    # ---------------------------------------------------------------------
    def _escolher_diretorio_xml(self):
        path = filedialog.askdirectory(initialdir=self.var_diretorio.get() or os.path.expanduser("~"))
        if path:
            self.var_diretorio.set(path)

    def _escolher_instant_client(self):
        path = filedialog.askdirectory(initialdir=self.var_instant_client.get() or os.path.expanduser("~"))
        if path:
            self.var_instant_client.set(path)

    def _abrir_pasta_log(self):
        pasta = os.path.join(core.get_base_dir(), "log")
        os.makedirs(pasta, exist_ok=True)
        if sys.platform == "darwin":
            os.system(f'open "{pasta}"')
        elif os.name == "nt":
            os.startfile(pasta)  # type: ignore[attr-defined]
        else:
            os.system(f'xdg-open "{pasta}"')

    def _limpar_log(self):
        self.txt_log.configure(state=tk.NORMAL)
        self.txt_log.delete("1.0", tk.END)
        self.txt_log.configure(state=tk.DISABLED)

    # ---------------------------------------------------------------------
    # Streaming de log
    # ---------------------------------------------------------------------
    def _enfileirar_log(self, mensagem):
        self.log_queue.put(mensagem)

    def _iniciar_consumidor_log(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.txt_log.configure(state=tk.NORMAL)
                self.txt_log.insert(tk.END, msg + "\n")
                self.txt_log.see(tk.END)
                self.txt_log.configure(state=tk.DISABLED)
        except queue.Empty:
            pass
        self.after(100, self._iniciar_consumidor_log)

    # ---------------------------------------------------------------------
    # Execução
    # ---------------------------------------------------------------------
    def _executar(self):
        if self.processing_thread and self.processing_thread.is_alive():
            messagebox.showinfo("Aguarde", "Processamento em andamento.")
            return

        # --- Validações ---
        diretorio = self.var_diretorio.get().strip()
        if not diretorio or not os.path.isdir(diretorio):
            messagebox.showerror("Erro", f"Diretório dos XMLs inválido:\n{diretorio}")
            return

        instant_client = self.var_instant_client.get().strip()
        if not instant_client or not os.path.isdir(instant_client):
            messagebox.showerror(
                "Erro",
                "Informe a pasta do Oracle Instant Client (baixada do site da Oracle).\n"
                f"Caminho informado: {instant_client or '(vazio)'}",
            )
            return

        modo = self.var_modo.get()
        cod_lote = self.var_cod_lote.get().strip()
        if modo == "individual" and not cod_lote:
            messagebox.showerror("Erro", "Informe o cod_lote no modo Individual.")
            return

        if modo == "lote":
            caminho_csv = os.path.join(core.get_base_dir(), "lote.csv")
            if not os.path.isfile(caminho_csv):
                messagebox.showerror(
                    "Erro",
                    f"Arquivo lote.csv não encontrado ao lado do executável:\n{caminho_csv}",
                )
                return
        else:
            caminho_csv = None

        # --- Aplica configuração no core ---
        try:
            core.set_ambiente(self.var_ambiente.get())
        except ValueError as e:
            messagebox.showerror("Erro", str(e))
            return
        core.set_diretorio_local(diretorio)
        core.set_usar_thin_mode(False)
        core.set_instant_client_path(instant_client)
        core.set_executar_import_massa(self.var_executar_import.get())
        core.set_log_callback(self._enfileirar_log)

        parametros_manuais_pre = self._coletar_parametros_manuais() if modo == "individual" else None

        # --- Dispara em thread ---
        self.btn_executar.configure(state=tk.DISABLED)
        self.var_status.set("Executando...")
        self._enfileirar_log("=" * 80)
        self._enfileirar_log(f"[GUI] Início em {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self._enfileirar_log(f"[GUI] Ambiente: {self.var_ambiente.get()}")
        self._enfileirar_log(f"[GUI] Modo: {modo}")
        self._enfileirar_log(f"[GUI] Instant Client: {instant_client}")
        self._enfileirar_log(f"[GUI] EXECUTAR_IMPORT_MASSA: {self.var_executar_import.get()}")
        self._enfileirar_log(f"[GUI] Diretório XMLs: {diretorio}")

        self.processing_thread = threading.Thread(
            target=self._executar_worker,
            args=(modo, cod_lote, caminho_csv, parametros_manuais_pre),
            daemon=True,
        )
        self.processing_thread.start()

    def _coletar_parametros_manuais(self):
        bruto = {chave: var.get().strip() for chave, var in self.vars_manuais.items()}
        params = {}

        # cod_prestador_ts (apenas se preenchido — convertido para int)
        cod_prestador = bruto.get("cod_prestador_ts")
        params["cod_prestador_ts"] = int(cod_prestador) if cod_prestador.isdigit() else None

        # num_grd opcional
        num_grd = bruto.get("num_grd")
        params["num_grd"] = int(num_grd) if num_grd.isdigit() else None

        # datas opcionais
        for chave in ("mes_ano_ref", "mes_ano_ref_vinc", "dt_prev_pgto"):
            valor = bruto.get(chave)
            if not valor:
                params[chave] = None
                continue
            try:
                params[chave] = datetime.strptime(valor, "%Y-%m-%d")
            except ValueError:
                params[chave] = None

        params["tipo"] = bruto.get("tipo") or None
        return params

    def _executar_worker(self, modo, cod_lote, caminho_csv, parametros_manuais_pre):
        try:
            if modo == "individual":
                core.processar_individual(cod_lote, parametros_manuais_pre=parametros_manuais_pre)
            else:
                core.processar_em_lote(caminho_csv)
        except Exception as e:
            self._enfileirar_log(f"[ERRO FATAL] {e}")
        finally:
            self._enfileirar_log("[GUI] Processamento finalizado.")
            self.after(0, self._reabilitar_botao)

    def _reabilitar_botao(self):
        self.btn_executar.configure(state=tk.NORMAL)
        self.var_status.set("Pronto.")


def main():
    app = PTU550App()
    app.mainloop()


if __name__ == "__main__":
    main()
