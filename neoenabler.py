"""
NEOENABLER v2.5 - PS4 Pro (Neo Mode) Unlocker, Old-SDK Patcher & Resolution/60FPS Enhancer for GoldHEN
Desktop GUI & CLI application to unlock 100% PS4 Pro GPU (36 CUs @ 911 MHz + 512 MB RAM)
in unpatched base PS4 games, upgrade old SDKs (< 4.00 -> 4.50 Neo), and generate/inject
GoldHEN Resolution (1080p / 1440p / 1620p / 4K) & 60 FPS patches.
"""

from __future__ import annotations
import argparse
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional, Tuple

from eboot_patcher import (
    NEO_COMPAT_SDK_VERSION,
    analyze_eboot_bytes,
    create_sample_fself_eboot,
    format_sdk_version,
    patch_eboot_sdk_version,
)
from ps4_ftp import BackupManager, GoldHenFtpClient, InstalledGame
from resolution_patcher import (
    CURATED_GAME_PATCHES,
    SOURCE_RESOLUTIONS,
    TARGET_RESOLUTIONS,
    ResolutionMatch,
    build_goldhen_xml,
    generate_resolution_patch_entries,
    patch_eboot_resolution_inplace,
    scan_eboot_for_resolutions,
)
from sfo_parser import NEO_MODE_BIT, SfoFile, create_sample_sfo


APP_TITLE = "NEOENABLER v2.5 - Inyector Modo Neo + Fix SDK Antiguo + Escalador de Resolución (GoldHEN)"

# Dark PlayStation-inspired theme palette
BG_DARK = "#0d1117"
BG_PANEL = "#161b22"
BG_CARD = "#21262d"
FG_PRIMARY = "#f0f6fc"
FG_SECONDARY = "#8b949e"
ACCENT_BLUE = "#1f6feb"
ACCENT_BLUE_HOVER = "#388bfd"
ACCENT_GREEN = "#238636"
ACCENT_PURPLE = "#8957e5"
ACCENT_CYAN = "#0969da"
ACCENT_ORANGE = "#d29922"
ACCENT_RED = "#da3633"


class NeoEnablerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1220x770")
        self.root.minsize(1040, 660)
        self.root.configure(bg=BG_DARK)

        self.backup_manager = BackupManager()
        self.ftp_client = GoldHenFtpClient(backup_manager=self.backup_manager)
        self.games: Dict[str, InstalledGame] = {}

        self.ip_var = tk.StringVar(value="192.168.1.100")
        self.port_var = tk.StringVar(value="2121")
        self.patch_old_sdk_var = tk.BooleanVar(value=True)
        self.sync_db_var = tk.BooleanVar(value=True)
        self.include_pfsmnt_var = tk.BooleanVar(value=True)
        self.search_var = tk.StringVar(value="")
        self.filter_only_base_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(
            value="Listo — Conéctate a GoldHEN FTP o abre archivos param.sfo + eboot.bin para inyectar Modo Neo y subir resolución"
        )

        self._configure_styles()
        self._build_ui()
        self.search_var.trace_add("write", lambda *_: self._refresh_table())

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")

        style.configure(".", background=BG_DARK, foreground=FG_PRIMARY, font=("Segoe UI", 10))
        style.configure("TFrame", background=BG_DARK)
        style.configure("Panel.TFrame", background=BG_PANEL)
        style.configure("Card.TFrame", background=BG_CARD)

        style.configure("TLabel", background=BG_DARK, foreground=FG_PRIMARY)
        style.configure("Panel.TLabel", background=BG_PANEL, foreground=FG_PRIMARY)
        style.configure("Muted.TLabel", background=BG_PANEL, foreground=FG_SECONDARY, font=("Segoe UI", 9))
        style.configure("Header.TLabel", background=BG_PANEL, foreground=FG_PRIMARY, font=("Segoe UI Semibold", 13))
        style.configure("SubHeader.TLabel", background=BG_PANEL, foreground="#58a6ff", font=("Segoe UI Semibold", 10))

        style.configure(
            "TEntry",
            fieldbackground=BG_CARD,
            foreground=FG_PRIMARY,
            insertcolor=FG_PRIMARY,
            borderwidth=1,
            padding=5,
        )

        style.configure(
            "TCombobox",
            fieldbackground=BG_CARD,
            background=BG_CARD,
            foreground=FG_PRIMARY,
            padding=4,
        )

        style.configure(
            "TCheckbutton",
            background=BG_PANEL,
            foreground=FG_PRIMARY,
            font=("Segoe UI", 9),
        )
        style.map("TCheckbutton", background=[("active", BG_PANEL)])

        style.configure(
            "Accent.TButton",
            background=ACCENT_BLUE,
            foreground=FG_PRIMARY,
            font=("Segoe UI Semibold", 10),
            padding=(11, 6),
            borderwidth=0,
        )
        style.map("Accent.TButton", background=[("active", ACCENT_BLUE_HOVER), ("disabled", "#30363d")])

        style.configure(
            "Purple.TButton",
            background=ACCENT_PURPLE,
            foreground=FG_PRIMARY,
            font=("Segoe UI Semibold", 10),
            padding=(11, 6),
            borderwidth=0,
        )
        style.map("Purple.TButton", background=[("active", "#a371f7"), ("disabled", "#30363d")])

        style.configure(
            "Success.TButton",
            background=ACCENT_GREEN,
            foreground=FG_PRIMARY,
            font=("Segoe UI Semibold", 10),
            padding=(12, 6),
            borderwidth=0,
        )
        style.map("Success.TButton", background=[("active", "#2ea043"), ("disabled", "#30363d")])

        style.configure(
            "Warn.TButton",
            background=ACCENT_ORANGE,
            foreground="#0d1117",
            font=("Segoe UI Semibold", 10),
            padding=(11, 6),
            borderwidth=0,
        )
        style.map("Warn.TButton", background=[("active", "#e3b341"), ("disabled", "#30363d")])

        style.configure(
            "Danger.TButton",
            background=ACCENT_RED,
            foreground=FG_PRIMARY,
            font=("Segoe UI Semibold", 10),
            padding=(11, 6),
            borderwidth=0,
        )
        style.map("Danger.TButton", background=[("active", "#f85149"), ("disabled", "#30363d")])

        style.configure(
            "Secondary.TButton",
            background=BG_CARD,
            foreground=FG_PRIMARY,
            font=("Segoe UI", 10),
            padding=(10, 6),
            borderwidth=1,
        )
        style.map("Secondary.TButton", background=[("active", "#30363d")])

        style.configure(
            "Treeview",
            background=BG_PANEL,
            foreground=FG_PRIMARY,
            fieldbackground=BG_PANEL,
            rowheight=30,
            borderwidth=0,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Treeview.Heading",
            background=BG_CARD,
            foreground="#58a6ff",
            font=("Segoe UI Semibold", 10),
            padding=(8, 6),
            borderwidth=0,
        )
        style.map(
            "Treeview",
            background=[("selected", ACCENT_BLUE)],
            foreground=[("selected", "#ffffff")],
        )

    def _build_ui(self) -> None:
        # 1. Top Banner & Connection Bar
        top_panel = ttk.Frame(self.root, style="Panel.TFrame", padding=(14, 10))
        top_panel.pack(fill=tk.X, padx=10, pady=(10, 6))

        title_row = ttk.Frame(top_panel, style="Panel.TFrame")
        title_row.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(
            title_row,
            text="⚡ NEOENABLER v2.5 — Inyector Modo Neo + Fix SDK Antiguo + Escalador de Resolución (1080p/1440p/4K)",
            style="Header.TLabel",
        ).pack(side=tk.LEFT)

        ttk.Label(
            title_row,
            text="GoldHEN FTP (2121) • PARAM.SFO • EBOOT ORBI • GoldHEN XML Patches",
            style="Muted.TLabel",
        ).pack(side=tk.RIGHT, padx=4)

        conn_row = ttk.Frame(top_panel, style="Panel.TFrame")
        conn_row.pack(fill=tk.X)

        ttk.Label(conn_row, text="IP PS4:", style="Panel.TLabel").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Entry(conn_row, textvariable=self.ip_var, width=14).pack(side=tk.LEFT, padx=(0, 8))

        ttk.Label(conn_row, text="Puerto:", style="Panel.TLabel").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Entry(conn_row, textvariable=self.port_var, width=6).pack(side=tk.LEFT, padx=(0, 10))

        self.btn_connect = ttk.Button(
            conn_row,
            text="🔌 Conectar FTP",
            style="Accent.TButton",
            command=self._on_connect_and_scan,
        )
        self.btn_connect.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_local = ttk.Button(
            conn_row,
            text="📂 Abrir param.sfo",
            style="Secondary.TButton",
            command=self._on_open_local_sfo,
        )
        self.btn_local.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_eboot = ttk.Button(
            conn_row,
            text="🧬 Parchear eboot.bin (SDK)",
            style="Secondary.TButton",
            command=self._on_open_and_patch_eboot,
        )
        self.btn_eboot.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_demo = ttk.Button(
            conn_row,
            text="🧪 Cargar Demo",
            style="Secondary.TButton",
            command=self._on_load_demo_games,
        )
        self.btn_demo.pack(side=tk.LEFT, padx=(0, 10))

        ttk.Checkbutton(
            conn_row,
            text="Auto-Elevar SDK (< 4.00 -> 4.50)",
            variable=self.patch_old_sdk_var,
        ).pack(side=tk.LEFT, padx=(0, 8))

        ttk.Checkbutton(
            conn_row,
            text="Sincronizar app.db",
            variable=self.sync_db_var,
        ).pack(side=tk.LEFT)

        # 2. Filter & Action Buttons Bar
        filter_panel = ttk.Frame(self.root, style="Panel.TFrame", padding=(14, 8))
        filter_panel.pack(fill=tk.X, padx=10, pady=(0, 6))

        ttk.Label(filter_panel, text="🔍 Buscar:", style="Panel.TLabel").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Entry(filter_panel, textvariable=self.search_var, width=22).pack(side=tk.LEFT, padx=(0, 10))

        ttk.Checkbutton(
            filter_panel,
            text="Solo sin Modo Neo",
            variable=self.filter_only_base_var,
            command=self._refresh_table,
        ).pack(side=tk.LEFT, padx=(0, 12))

        self.btn_restore = ttk.Button(
            filter_panel,
            text="⏪ Restaurar Original",
            style="Danger.TButton",
            command=self._on_restore_selected,
        )
        self.btn_restore.pack(side=tk.RIGHT, padx=(6, 0))

        self.btn_disable_neo = ttk.Button(
            filter_panel,
            text="⚪ Desactivar Neo",
            style="Warn.TButton",
            command=lambda: self._on_set_neo_selected(False),
        )
        self.btn_disable_neo.pack(side=tk.RIGHT, padx=(6, 0))

        self.btn_res_enhancer = ttk.Button(
            filter_panel,
            text="🖥️ Mejorar Resolución / 60 FPS (XML)",
            style="Purple.TButton",
            command=self._on_open_resolution_window,
        )
        self.btn_res_enhancer.pack(side=tk.RIGHT, padx=(6, 0))

        self.btn_enable_neo = ttk.Button(
            filter_panel,
            text="🚀 INYECTAR MODO NEO + FIX SDK",
            style="Success.TButton",
            command=lambda: self._on_set_neo_selected(True),
        )
        self.btn_enable_neo.pack(side=tk.RIGHT, padx=(6, 0))

        # 3. Main Split: Games Table (Left) + Technical Inspector (Right)
        main_pane = ttk.Frame(self.root)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 6))

        table_frame = ttk.Frame(main_pane, style="Panel.TFrame")
        table_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))

        columns = (
            "title_id",
            "title",
            "app_ver",
            "sys_ver",
            "sdk_status",
            "res_patch",
            "attribute",
            "neo_state",
        )
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended")

        self.tree.heading("title_id", text="Title ID")
        self.tree.heading("title", text="Nombre del Juego")
        self.tree.heading("app_ver", text="Ver.")
        self.tree.heading("sys_ver", text="SYSTEM_VER")
        self.tree.heading("sdk_status", text="Diagnóstico SDK")
        self.tree.heading("res_patch", text="Parche Res/60FPS")
        self.tree.heading("attribute", text="ATTRIBUTE")
        self.tree.heading("neo_state", text="Estado Modo Neo")

        self.tree.column("title_id", width=88, anchor=tk.CENTER)
        self.tree.column("title", width=215, anchor=tk.W)
        self.tree.column("app_ver", width=55, anchor=tk.CENTER)
        self.tree.column("sys_ver", width=110, anchor=tk.CENTER)
        self.tree.column("sdk_status", width=130, anchor=tk.CENTER)
        self.tree.column("res_patch", width=125, anchor=tk.CENTER)
        self.tree.column("attribute", width=95, anchor=tk.CENTER)
        self.tree.column("neo_state", width=130, anchor=tk.CENTER)

        self.tree.tag_configure("neo_on", foreground="#3fb950")
        self.tree.tag_configure("old_sdk_base", foreground="#ff7b72")
        self.tree.tag_configure("neo_off", foreground="#e3b341")

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Double-1>", lambda _e: self._on_toggle_double_click())

        # Right Inspector Panel
        inspector = ttk.Frame(main_pane, style="Panel.TFrame", width=355, padding=12)
        inspector.pack(side=tk.RIGHT, fill=tk.Y)
        inspector.pack_propagate(False)

        ttk.Label(inspector, text="🔬 Diagnóstico de SDK, Resolución & SFO", style="SubHeader.TLabel").pack(
            anchor=tk.W, pady=(0, 8)
        )

        self.detail_text = tk.Text(
            inspector,
            bg=BG_CARD,
            fg=FG_PRIMARY,
            font=("Consolas", 9),
            relief=tk.FLAT,
            padx=8,
            pady=8,
            wrap=tk.WORD,
            height=18,
        )
        self.detail_text.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
        self._set_inspector_text(
            "NOVEDAD EN NEOENABLER v2.5:\n"
            "¡Mejora de Resolución (1080p / 1440p / 1620p / 4K) y 60 FPS integrada!\n\n"
            "1. Inyecta primero el Modo Neo (+ Fix SDK 4.50) para desbloquear las "
            "36 CUs @ 911 MHz y +512 MB de RAM.\n"
            "2. Pulsa el botón morado '🖥️ Mejorar Resolución / 60 FPS (XML)'.\n"
            "3. Puedes aplicar parches verificados (Bloodborne 1440p/60fps, Driveclub 1440p/60fps, "
            "The Order 1886 1080p 16:9, AC Unity 1080p/1440p) o usar el Escáner Universal "
            "de eboot.bin para subir cualquier juego de 720p/900p/1080p a 1080p/1440p."
        )

        tip_frame = ttk.Frame(inspector, style="Card.TFrame", padding=8)
        tip_frame.pack(fill=tk.X)
        ttk.Label(
            tip_frame,
            text=(
                "🖥️ ¿Cómo funcionan los parches XML en GoldHEN?\n"
                "NEOENABLER genera el archivo <CUSAXXXXX>.xml y lo sube por FTP a "
                "/data/GoldHEN/patches/xml/ (o parcha el eboot.bin directo) para que el juego "
                "renderice a mayor resolución usando la GPU de PS4 Pro."
            ),
            background=BG_CARD,
            foreground="#d2a8ff",
            font=("Segoe UI", 8),
            wraplength=320,
            justify=tk.LEFT,
        ).pack(fill=tk.X)

        # 4. Bottom Log Console & Status Bar
        bottom_panel = ttk.Frame(self.root, style="Panel.TFrame", padding=(10, 8))
        bottom_panel.pack(fill=tk.X, padx=10, pady=(0, 10))

        ttk.Label(bottom_panel, text="📋 Registro de Operaciones:", style="SubHeader.TLabel").pack(anchor=tk.W, pady=(0, 4))

        self.log_text = tk.Text(
            bottom_panel,
            bg=BG_CARD,
            fg="#a5d6ff",
            font=("Consolas", 9),
            height=6,
            relief=tk.FLAT,
            padx=8,
            pady=6,
        )
        self.log_text.pack(fill=tk.X)

        status_bar = ttk.Frame(bottom_panel, style="Panel.TFrame")
        status_bar.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(status_bar, textvariable=self.status_var, style="Muted.TLabel").pack(side=tk.LEFT)
        ttk.Label(
            status_bar,
            text=f"Backups: {self.backup_manager.backups_root}",
            style="Muted.TLabel",
        ).pack(side=tk.RIGHT)

        self.log(
            "NEOENABLER v2.5 iniciado. Inyector de Modo Neo + Fix SDK Antiguo + Escalador de Resolución listo."
        )

    def log(self, message: str) -> None:
        def _append() -> None:
            self.log_text.insert(tk.END, f"> {message}\n")
            self.log_text.see(tk.END)
            self.status_var.set(message)

        self.root.after(0, _append)

    def _set_inspector_text(self, content: str) -> None:
        self.detail_text.configure(state=tk.NORMAL)
        self.detail_text.delete("1.0", tk.END)
        self.detail_text.insert(tk.END, content)
        self.detail_text.configure(state=tk.DISABLED)

    def _refresh_table(self) -> None:
        selected_ids = [self.tree.item(item, "values")[0] for item in self.tree.selection()]
        self.tree.delete(*self.tree.get_children())

        query = self.search_var.get().strip().lower()
        only_base = self.filter_only_base_var.get()

        for tid, game in sorted(self.games.items()):
            if only_base and game.is_neo_enabled:
                continue
            if query and query not in game.title_id.lower() and query not in game.title.lower():
                continue

            neo_str = "🟢 NEO ACTIVO (Pro)" if game.is_neo_enabled else "🟡 Modo Base"
            if game.is_old_sdk:
                sdk_status = "⚠️ SDK Antiguo (<4.0)"
                tag = "neo_on" if game.is_neo_enabled else "old_sdk_base"
            else:
                sdk_status = "✅ SDK >= 4.00 (OK)"
                tag = "neo_on" if game.is_neo_enabled else "neo_off"

            if game.has_goldhen_patch_xml:
                res_patch_str = "✨ XML Instalado"
            elif tid.upper() in CURATED_GAME_PATCHES:
                res_patch_str = "🎯 Perfil 1440p/60"
            else:
                res_patch_str = "🔍 Auto-Escáner"

            item_id = self.tree.insert(
                "",
                tk.END,
                values=(
                    game.title_id,
                    game.title,
                    game.app_ver,
                    game.system_ver,
                    sdk_status,
                    res_patch_str,
                    game.attribute_hex,
                    neo_str,
                ),
                tags=(tag,),
            )
            if tid in selected_ids:
                self.tree.selection_add(item_id)

    def _on_tree_select(self, _event: Optional[tk.Event] = None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        tid = str(self.tree.item(sel[0], "values")[0])
        game = self.games.get(tid)
        if not game:
            return

        sfo = next(iter(game.sfo_locations.values()), None)
        curated = CURATED_GAME_PATCHES.get(tid.upper(), [])
        lines = [
            f"TÍTULO:      {game.title}",
            f"TITLE ID:    {game.title_id} (v{game.app_ver})",
            f"SYSTEM_VER:  {game.system_ver}",
            f"ESTADO SDK:  {'⚠️ ANTIGUO (< 4.00) - Requiere Fix SDK' if game.is_old_sdk else '✅ Compatible con Neo (>= 4.00)'}",
            f"ATTRIBUTE:   {game.attribute_hex}",
            f"MODO NEO:    {'ACTIVO (Bit 23 = 1)' if game.is_neo_enabled else 'INACTIVO (Bit 23 = 0)'}",
        ]

        if curated:
            lines.append("-" * 38)
            lines.append("🎯 Parches de Resolución / 60 FPS incluidos:")
            for cp in curated:
                lines.append(f" • {cp.name}")

        if game.eboot_analysis:
            ea = game.eboot_analysis
            lines.append("-" * 38)
            lines.append(f"EBOOT.BIN:   {ea.container_type}")
            if ea.primary_sdk_version:
                lines.append(f"ORBI SDK:    {format_sdk_version(ea.primary_sdk_version)}")

        if sfo:
            lines.append("-" * 38)
            lines.append("Flags activos en ATTRIBUTE:")
            active_flags = sfo.get_active_attribute_flags()
            if active_flags:
                for bit, desc in active_flags:
                    lines.append(f" • 0x{bit:08X}: {desc}")
            else:
                lines.append(" • (Ninguno)")

        self._set_inspector_text("\n".join(lines))

    def _on_open_resolution_window(self) -> None:
        """Opens the Resolution & 60 FPS Patch Generator / Deployer dialog for the selected game."""
        selected = self._get_selected_games()
        if not selected:
            return
        game = selected[0]

        win = tk.Toplevel(self.root)
        win.title(f"🖥️ Escalador de Resolución & 60 FPS — {game.title} ({game.title_id})")
        win.geometry("760x620")
        win.configure(bg=BG_DARK)
        win.transient(self.root)
        win.grab_set()

        panel = ttk.Frame(win, style="Panel.TFrame", padding=14)
        panel.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        ttk.Label(
            panel,
            text=f"🖥️ Mejora de Resolución y Framerate para {game.title} ({game.title_id})",
            style="Header.TLabel",
        ).pack(anchor=tk.W, pady=(0, 6))

        curated_list = CURATED_GAME_PATCHES.get(game.title_id.upper(), [])
        if curated_list:
            cur_text = "✨ Este título tiene parches verificados en la base de datos: " + ", ".join(
                c.name for c in curated_list
            )
        else:
            cur_text = (
                "🔍 Este título usará el Escáner Heurístico de eboot.bin para localizar y escalar el framebuffer."
            )
        ttk.Label(panel, text=cur_text, style="SubHeader.TLabel", wraplength=710).pack(anchor=tk.W, pady=(0, 10))

        # Controls frame
        ctrl_frame = ttk.Frame(panel, style="Card.TFrame", padding=10)
        ctrl_frame.pack(fill=tk.X, pady=(0, 10))

        row1 = ttk.Frame(ctrl_frame, style="Card.TFrame")
        row1.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(row1, text="Resolución Base Original:", background=BG_CARD, foreground=FG_PRIMARY).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        src_res_var = tk.StringVar(value="900p (1600x900)")
        src_combo = ttk.Combobox(row1, textvariable=src_res_var, values=list(SOURCE_RESOLUTIONS.keys()), width=24, state="readonly")
        src_combo.pack(side=tk.LEFT, padx=(0, 14))

        ttk.Label(row1, text="Nueva Resolución (Modo Neo):", background=BG_CARD, foreground="#3fb950").pack(
            side=tk.LEFT, padx=(0, 6)
        )
        tgt_res_var = tk.StringVar(value="1440p QHD 2K (2560x1440)")
        tgt_combo = ttk.Combobox(row1, textvariable=tgt_res_var, values=list(TARGET_RESOLUTIONS.keys()), width=26, state="readonly")
        tgt_combo.pack(side=tk.LEFT)

        row2 = ttk.Frame(ctrl_frame, style="Card.TFrame")
        row2.pack(fill=tk.X)

        include_curated_var = tk.BooleanVar(value=True)
        patch_eboot_direct_var = tk.BooleanVar(value=False)

        ttk.Checkbutton(
            row2,
            text="Incluir perfil verificado (Resolución + 60 FPS) si existe",
            variable=include_curated_var,
        ).pack(side=tk.LEFT, padx=(0, 16))

        ttk.Checkbutton(
            row2,
            text="Parchear también el eboot.bin directamente en disco",
            variable=patch_eboot_direct_var,
        ).pack(side=tk.LEFT)

        # XML Preview Box
        ttk.Label(
            panel,
            text="📄 Vista previa del Parche XML para GoldHEN (/data/GoldHEN/patches/xml/):",
            style="Panel.TLabel",
        ).pack(anchor=tk.W, pady=(0, 4))

        xml_preview = tk.Text(
            panel,
            bg=BG_CARD,
            fg="#79c0ff",
            font=("Consolas", 9),
            height=16,
            relief=tk.FLAT,
            padx=8,
            pady=8,
        )
        xml_preview.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        discovered_matches: List[ResolutionMatch] = []

        def refresh_preview() -> None:
            nonlocal discovered_matches
            discovered_matches = []
            src_w, src_h = SOURCE_RESOLUTIONS.get(src_res_var.get(), (1600, 900))
            tgt_w, tgt_h = TARGET_RESOLUTIONS.get(tgt_res_var.get(), (2560, 1440))

            # Scan eboot.bin if available locally
            if game.local_eboot_path and Path(game.local_eboot_path).exists():
                raw_eb = Path(game.local_eboot_path).read_bytes()
                discovered_matches = scan_eboot_for_resolutions(raw_eb, src_w, src_h)

            entries = generate_resolution_patch_entries(
                title_id=game.title_id,
                title=game.title,
                app_ver=game.app_ver,
                matches=discovered_matches,
                target_width=tgt_w,
                target_height=tgt_h,
                include_curated=include_curated_var.get(),
            )
            xml_str = build_goldhen_xml(game.title_id, entries)
            xml_preview.delete("1.0", tk.END)
            xml_preview.insert(tk.END, xml_str)

        src_combo.bind("<<ComboboxSelected>>", lambda _e: refresh_preview())
        tgt_combo.bind("<<ComboboxSelected>>", lambda _e: refresh_preview())

        btn_row = ttk.Frame(panel, style="Panel.TFrame")
        btn_row.pack(fill=tk.X)

        def on_scan_custom_eboot() -> None:
            p = filedialog.askopenfilename(
                parent=win,
                title="Seleccionar eboot.bin para escanear su framebuffer de resolución",
                filetypes=[("eboot.bin / ELF", "*.bin *.elf"), ("Todos", "*.*")],
            )
            if p:
                game.local_eboot_path = p
                refresh_preview()
                self.log(f"Escaneado eboot.bin para resolución: {p} ({len(discovered_matches)} coincidencias x86_64)")

        def on_apply_and_deploy() -> None:
            xml_content = xml_preview.get("1.0", tk.END).strip() + "\n"
            tgt_w, tgt_h = TARGET_RESOLUTIONS.get(tgt_res_var.get(), (2560, 1440))

            # Optionally patch eboot.bin directly if requested and matches were found
            if patch_eboot_direct_var.get() and game.local_eboot_path and discovered_matches:
                ep = Path(game.local_eboot_path)
                raw_eb = ep.read_bytes()
                bak = Path(f"{ep}.res.bak")
                if not bak.exists():
                    bak.write_bytes(raw_eb)
                patched_eb = patch_eboot_resolution_inplace(raw_eb, discovered_matches, tgt_w, tgt_h)
                ep.write_bytes(patched_eb)
                self.log(
                    f"  [OK] eboot.bin parcheado directamente a {tgt_w}x{tgt_h} ({len(discovered_matches)} instrucciones)."
                )

            ok, msg = self.ftp_client.deploy_goldhen_xml_patch(
                title_id=game.title_id,
                xml_content=xml_content,
                log_cb=self.log,
            )
            game.has_goldhen_patch_xml = True
            self._refresh_table()
            self._on_tree_select()
            messagebox.showinfo("Parche de Resolución / 60 FPS Generado", msg, parent=win)
            win.destroy()

        ttk.Button(
            btn_row,
            text="🔍 Seleccionar eboot.bin y Re-escanear",
            style="Secondary.TButton",
            command=on_scan_custom_eboot,
        ).pack(side=tk.LEFT, padx=(0, 8))

        ttk.Button(
            btn_row,
            text="🔄 Actualizar Vista Previa",
            style="Secondary.TButton",
            command=refresh_preview,
        ).pack(side=tk.LEFT)

        ttk.Button(
            btn_row,
            text="🚀 Guardar e Inyectar XML en GoldHEN",
            style="Success.TButton",
            command=on_apply_and_deploy,
        ).pack(side=tk.RIGHT)

        refresh_preview()

    def _on_connect_and_scan(self) -> None:
        host = self.ip_var.get().strip()
        try:
            port = int(self.port_var.get().strip())
        except ValueError:
            messagebox.showerror("Puerto inválido", "El puerto FTP debe ser un número (por defecto 2121 en GoldHEN).")
            return

        self.btn_connect.configure(state=tk.DISABLED)

        def worker() -> None:
            try:
                self.ftp_client.host = host
                self.ftp_client.port = port
                self.ftp_client.connect(log_cb=self.log)
                scanned = self.ftp_client.scan_installed_games(
                    include_mounted_sandbox=self.include_pfsmnt_var.get(),
                    log_cb=self.log,
                )
                self.games = {g.title_id: g for g in scanned}
                self.root.after(0, self._refresh_table)
            except Exception as e:
                self.log(f"[Error FTP] No se pudo conectar a {host}:{port} -> {e}")
                self.root.after(
                    0,
                    lambda: messagebox.showwarning(
                        "Error de Conexión FTP",
                        f"No se pudo conectar a la PS4 en {host}:{port}.\n\nDetalle: {e}",
                    ),
                )
            finally:
                self.root.after(0, lambda: self.btn_connect.configure(state=tk.NORMAL))

        threading.Thread(target=worker, daemon=True).start()

    def _on_open_local_sfo(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Seleccionar archivo(s) param.sfo",
            filetypes=[("PlayStation PARAM.SFO", "*.sfo"), ("Todos los archivos", "*.*")],
        )
        if not paths:
            return

        for p in paths:
            try:
                sfo = SfoFile.from_file(p)
                tid = sfo.title_id if sfo.title_id != "UNKNOWN" else Path(p).stem.upper()
                sfo_path_obj = Path(p).resolve()
                candidate_eboots = [
                    sfo_path_obj.parent / "eboot.bin",
                    sfo_path_obj.parent.parent / "eboot.bin",
                    sfo_path_obj.parent / f"{tid}_eboot.bin",
                ]
                found_eboot: Optional[str] = None
                eboot_analysis = None
                for cand in candidate_eboots:
                    if cand.exists():
                        found_eboot = str(cand)
                        eboot_analysis = analyze_eboot_bytes(cand.read_bytes())
                        break

                game = InstalledGame(
                    title_id=tid,
                    title=sfo.title,
                    app_ver=sfo.app_ver,
                    category=sfo.category,
                    system_ver=sfo.system_ver_hex,
                    system_ver_int=sfo.system_ver,
                    attribute=sfo.attribute,
                    sfo_locations={p: sfo},
                    local_source_path=p,
                    local_eboot_path=found_eboot,
                    eboot_analysis=eboot_analysis,
                )
                self.games[tid] = game
                self.log(f"Cargado param.sfo local: {game.title} ({tid}) [SDK: {game.system_ver}]")
            except Exception as e:
                messagebox.showerror("Error al abrir param.sfo", f"No se pudo leer {p}:\n{e}")

        self._refresh_table()

    def _on_open_and_patch_eboot(self) -> None:
        path = filedialog.askopenfilename(
            title="Seleccionar eboot.bin / .elf / .prx (FPKG desencriptado)",
            filetypes=[("PS4 Executable (eboot.bin / .elf / .prx)", "*.bin *.elf *.prx *.sprx"), ("Todos", "*.*")],
        )
        if not path:
            return

        try:
            raw = Path(path).read_bytes()
            analysis = analyze_eboot_bytes(raw)
            if not analysis.is_patchable:
                messagebox.showwarning("eboot.bin no parcheable directamente", analysis.notes)
                self.log(f"[eboot.bin] {path}: {analysis.notes}")
                return

            cur_sdk = analysis.primary_sdk_version or 0
            locs_desc = "\n".join(
                f"• {loc.kind} en offset 0x{loc.file_offset:X} (sdk_version @ 0x{loc.sdk_version_offset:X})"
                for loc in analysis.locations
            )
            ask = messagebox.askyesno(
                "Inspección de OrbisProcParam ('ORBI') en eboot.bin",
                f"Archivo: {path}\n"
                f"Formato: {analysis.container_type}\n"
                f"SDK Compilado Actual: {format_sdk_version(cur_sdk)}\n\n"
                f"Estructuras encontradas:\n{locs_desc}\n\n"
                f"{analysis.notes}\n\n"
                f"¿Deseas crear un backup (.bak) y elevar el sdk_version a 0x{NEO_COMPAT_SDK_VERSION:08X} (SDK 4.50 Neo) "
                "para evitar el crash CE-34878-0 al activar el Modo Neo?",
            )
            if ask:
                bak_path = f"{path}.bak"
                if not Path(bak_path).exists():
                    Path(bak_path).write_bytes(raw)
                patched_bytes, new_analysis = patch_eboot_sdk_version(raw, NEO_COMPAT_SDK_VERSION)
                Path(path).write_bytes(patched_bytes)

                sel = self.tree.selection()
                if sel:
                    tid = str(self.tree.item(sel[0], "values")[0])
                    if tid in self.games:
                        self.games[tid].local_eboot_path = path
                        self.games[tid].eboot_analysis = new_analysis
                        self._refresh_table()
                        self._on_tree_select()

                self.log(
                    f"[OK] eboot.bin parcheado: SDK 0x{cur_sdk:08X} -> 0x{NEO_COMPAT_SDK_VERSION:08X} "
                    f"(Backup guardado en {bak_path})"
                )
                messagebox.showinfo(
                    "eboot.bin Parcheado con Éxito",
                    f"Se actualizó OrbisProcParam ('ORBI') a SDK 4.50 (0x{NEO_COMPAT_SDK_VERSION:08X}).\n"
                    f"Backup original: {bak_path}",
                )
        except Exception as e:
            messagebox.showerror("Error procesando eboot.bin", str(e))

    def _on_load_demo_games(self) -> None:
        demo_dir = Path(__file__).resolve().parent / "demo_sfo"
        demo_dir.mkdir(parents=True, exist_ok=True)

        samples = [
            ("CUSA00552", "Driveclub (SDK 2.00 - Pre-Pro)", "01.28", 0x00008002, 0x02000000, 0x02000001),
            ("CUSA00129", "Assassin's Creed Unity (SDK 2.50 - 900p)", "01.05", 0x00000002, 0x02500000, 0x02500001),
            ("CUSA00900", "Bloodborne (SDK 3.50 - Pre-Pro)", "01.09", 0x00000002, 0x03500000, 0x03500001),
            ("CUSA00207", "The Order: 1886 (SDK 2.00 - 800p)", "01.02", 0x00000002, 0x02000000, 0x02000001),
            ("CUSA00419", "Grand Theft Auto V (SDK 4.50)", "01.48", 0x00010002, 0x04500000, 0x04500001),
            ("CUSA07408", "God of War (Parche Pro Nativo)", "01.33", 0x02810002, 0x05500000, 0x05500001),
        ]

        for tid, title, ver, attr, sys_ver, eboot_sdk in samples:
            sfo = create_sample_sfo(
                title_id=tid,
                title=title,
                app_ver=ver,
                attribute=attr,
                system_ver=sys_ver,
            )
            sfo_path = str(demo_dir / f"{tid}_param.sfo")
            sfo.save(sfo_path)

            eboot_path = str(demo_dir / f"{tid}_eboot.bin")
            eboot_bytes = create_sample_fself_eboot(sdk_version=eboot_sdk, res_width=1600, res_height=900)
            Path(eboot_path).write_bytes(eboot_bytes)
            analysis = analyze_eboot_bytes(eboot_bytes)

            self.games[tid] = InstalledGame(
                title_id=tid,
                title=title,
                app_ver=ver,
                category="gd",
                system_ver=sfo.system_ver_hex,
                system_ver_int=sfo.system_ver,
                attribute=sfo.attribute,
                sfo_locations={sfo_path: sfo},
                local_source_path=sfo_path,
                local_eboot_path=eboot_path,
                eboot_analysis=analysis,
            )

        self._refresh_table()
        self.log(
            f"Cargados {len(samples)} juegos demo (param.sfo + eboot.bin con SDK < 4.00 y resolución 900p) en {demo_dir}."
        )

    def _get_selected_games(self) -> List[InstalledGame]:
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Sin selección", "Selecciona uno o más juegos de la lista primero.")
            return []
        result: List[InstalledGame] = []
        for item in sel:
            tid = str(self.tree.item(item, "values")[0])
            if tid in self.games:
                result.append(self.games[tid])
        return result

    def _on_set_neo_selected(self, enable: bool) -> None:
        selected = self._get_selected_games()
        if not selected:
            return

        def worker() -> None:
            for game in selected:
                self.ftp_client.apply_neo_mode(
                    game,
                    enable=enable,
                    patch_old_sdk=self.patch_old_sdk_var.get(),
                    sync_app_db=self.sync_db_var.get(),
                    log_cb=self.log,
                )
            self.root.after(0, self._refresh_table)
            self.root.after(0, self._on_tree_select)

        threading.Thread(target=worker, daemon=True).start()

    def _on_toggle_double_click(self) -> None:
        selected = self._get_selected_games()
        if not selected:
            return
        target_game = selected[0]
        self._on_set_neo_selected(not target_game.is_neo_enabled)

    def _on_restore_selected(self) -> None:
        selected = self._get_selected_games()
        if not selected:
            return

        def worker() -> None:
            for game in selected:
                self.ftp_client.restore_original_backup(
                    game,
                    sync_app_db=self.sync_db_var.get(),
                    log_cb=self.log,
                )
            self.root.after(0, self._refresh_table)
            self.root.after(0, self._on_tree_select)

        threading.Thread(target=worker, daemon=True).start()


def _parse_wh(res_str: str) -> Tuple[int, int]:
    """Parses '1440p', '1080p', '1620p', '2160p', or '2560x1440' into (width, height)."""
    s = res_str.strip().lower()
    presets = {
        "720p": (1280, 720),
        "900p": (1600, 900),
        "1080p": (1920, 1080),
        "1440p": (2560, 1440),
        "1620p": (2880, 1620),
        "2160p": (3840, 2160),
        "4k": (3840, 2160),
    }
    if s in presets:
        return presets[s]
    if "x" in s:
        parts = s.split("x", 1)
        return int(parts[0]), int(parts[1])
    raise ValueError(f"Formato de resolución no reconocido: {res_str} (usa ej. 1440p o 2560x1440)")


def run_cli(args: argparse.Namespace) -> int:
    if args.eboot:
        epath = Path(args.eboot).resolve()
        if not epath.exists():
            print(f"[Error] No existe el archivo eboot: {epath}", file=sys.stderr)
            return 1
        raw = epath.read_bytes()
        analysis = analyze_eboot_bytes(raw)
        print(f"Archivo EBOOT: {epath}")
        print(f"Formato:       {analysis.container_type}")
        if analysis.primary_sdk_version:
            print(f"ORBI SDK Ver:  {format_sdk_version(analysis.primary_sdk_version)}")
        print(f"Diagnóstico:   {analysis.notes}")
        if args.enable and analysis.is_patchable:
            bak = Path(f"{epath}.bak")
            if not bak.exists():
                bak.write_bytes(raw)
            patched, new_a = patch_eboot_sdk_version(raw, NEO_COMPAT_SDK_VERSION)
            epath.write_bytes(patched)
            print(
                f"[OK] OrbisProcParam ('ORBI') sdk_version actualizado a {format_sdk_version(new_a.primary_sdk_version or 0)}"
            )
        elif args.restore:
            bak = Path(f"{epath}.bak")
            if bak.exists():
                epath.write_bytes(bak.read_bytes())
                print(f"[OK] Restaurado eboot original desde {bak}")
        if not args.file and not args.target_res:
            return 0

    if args.file:
        path = Path(args.file).resolve()
        if not path.exists():
            print(f"[Error] No existe el archivo: {path}", file=sys.stderr)
            return 1

        sfo = SfoFile.from_file(str(path))
        print(f"Archivo SFO: {path}")
        print(f"Título:      {sfo.title} ({sfo.title_id}) v{sfo.app_ver}")
        print(f"SYSTEM_VER:  {sfo.system_ver_hex} ({'SDK ANTIGUO < 4.00' if sfo.is_old_sdk else 'SDK >= 4.00'})")
        print(f"ATTRIBUTE:   0x{sfo.attribute:08X} (Modo Neo: {'ACTIVO' if sfo.is_neo_enabled else 'INACTIVO'})")

        game = InstalledGame(
            title_id=sfo.title_id,
            title=sfo.title,
            app_ver=sfo.app_ver,
            category=sfo.category,
            system_ver=sfo.system_ver_hex,
            system_ver_int=sfo.system_ver,
            attribute=sfo.attribute,
            sfo_locations={str(path): sfo},
            local_source_path=str(path),
            local_eboot_path=str(Path(args.eboot).resolve()) if args.eboot else None,
        )
        client = GoldHenFtpClient()
        if args.enable or args.disable:
            ok, _ = client.apply_neo_mode(
                game,
                enable=bool(args.enable),
                patch_old_sdk=not args.no_sdk_patch,
                sync_app_db=False,
                log_cb=print,
            )
            if not ok:
                return 1
        elif args.restore:
            ok, _ = client.restore_original_backup(game, sync_app_db=False, log_cb=print)
            return 0 if ok else 1

        if args.target_res:
            src_w, src_h = _parse_wh(args.source_res)
            tgt_w, tgt_h = _parse_wh(args.target_res)
            matches: List[ResolutionMatch] = []
            if game.local_eboot_path and Path(game.local_eboot_path).exists():
                matches = scan_eboot_for_resolutions(Path(game.local_eboot_path).read_bytes(), src_w, src_h)
            entries = generate_resolution_patch_entries(
                title_id=game.title_id,
                title=game.title,
                app_ver=game.app_ver,
                matches=matches,
                target_width=tgt_w,
                target_height=tgt_h,
                include_curated=True,
            )
            xml_str = build_goldhen_xml(game.title_id, entries)
            client.deploy_goldhen_xml_patch(game.title_id, xml_str, log_cb=print)
        return 0

    if args.ftp_host:
        client = GoldHenFtpClient(host=args.ftp_host, port=args.ftp_port)
        client.connect(log_cb=print)
        games = client.scan_installed_games(log_cb=print)
        if args.title_id:
            target = next((g for g in games if g.title_id.upper() == args.title_id.upper()), None)
            if not target:
                print(f"[Error] No se encontró {args.title_id} en la PS4.", file=sys.stderr)
                return 1
            if args.enable or args.disable:
                ok, _ = client.apply_neo_mode(
                    target,
                    enable=bool(args.enable),
                    patch_old_sdk=not args.no_sdk_patch,
                    log_cb=print,
                )
                if not ok:
                    return 1
            elif args.restore:
                ok, _ = client.restore_original_backup(target, log_cb=print)
                return 0 if ok else 1

            if args.target_res:
                src_w, src_h = _parse_wh(args.source_res)
                tgt_w, tgt_h = _parse_wh(args.target_res)
                entries = generate_resolution_patch_entries(
                    title_id=target.title_id,
                    title=target.title,
                    app_ver=target.app_ver,
                    matches=[],
                    target_width=tgt_w,
                    target_height=tgt_h,
                    include_curated=True,
                )
                xml_str = build_goldhen_xml(target.title_id, entries)
                client.deploy_goldhen_xml_patch(target.title_id, xml_str, log_cb=print)
        client.disconnect()
        return 0

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="NEOENABLER v2.5 - Inyector de Modo Neo + Fix SDK Antiguo + Escalador de Resolución para GoldHEN"
    )
    parser.add_argument("--file", "-f", help="Ruta a un archivo param.sfo local para inspeccionar o parchear")
    parser.add_argument("--eboot", "-e", help="Ruta a un archivo eboot.bin (FSELF/ELF) para elevar SDK o escanear resolución")
    parser.add_argument("--ftp-host", help="IP de la PS4 con GoldHEN FTP activo")
    parser.add_argument("--ftp-port", type=int, default=2121, help="Puerto FTP de GoldHEN (por defecto: 2121)")
    parser.add_argument("--title-id", help="Title ID (ej. CUSA00552) a modificar por FTP")
    parser.add_argument("--no-sdk-patch", action="store_true", help="No elevar automáticamente SDKs antiguos (< 4.00)")
    parser.add_argument("--source-res", default="900p", help="Resolución base original para escaneo (ej. 900p, 1080p)")
    parser.add_argument("--target-res", help="Generar parche XML de resolución para GoldHEN (ej. 1080p, 1440p, 1620p, 4k)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--enable", action="store_true", help="Inyectar Modo Neo + Fix de SDK Antiguo")
    group.add_argument("--disable", action="store_true", help="Desactivar Modo Neo")
    group.add_argument("--restore", action="store_true", help="Restaurar el backup original de param.sfo y eboot.bin")

    args = parser.parse_args()

    if args.file or args.eboot or args.ftp_host:
        sys.exit(run_cli(args))

    root = tk.Tk()
    _app = NeoEnablerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
