"""
PS4 GoldHEN FTP Manager, Backup System, Old-SDK Eboot Upgrader, and app.db Synchronizer for NEOENABLER.
Scans installed games on a PS4 running GoldHEN FTP server (port 2121),
checks all param.sfo locations (/user/appmeta, /system_data/priv/appmeta, /mnt/sandbox/pfsmnt),
creates automatic local backups before modifying anything, patches old-SDK (< 4.00) SYSTEM_VER
and eboot.bin (OrbisProcParam 'ORBI' sdk_version -> 0x04500001) so pre-Pro games don't crash
when Neo Mode is injected, and synchronizes ATTRIBUTE in /system_data/priv/mms/app.db (tbl_appinfo).
"""

from __future__ import annotations
import ftplib
import io
import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from eboot_patcher import (
    NEO_COMPAT_SDK_VERSION,
    NEO_MIN_SDK_VERSION,
    EbootAnalysis,
    analyze_eboot_bytes,
    format_sdk_version,
    patch_eboot_sdk_version,
)
from sfo_parser import NEO_MODE_BIT, SfoFile


DEFAULT_BACKUPS_DIR = Path(__file__).resolve().parent / "backups"

# Directories on the PS4 where param.sfo and eboot.bin files for installed titles reside
APPMETA_USER_DIR = "/user/appmeta"
APPMETA_SYS_DIR = "/system_data/priv/appmeta"
SANDBOX_PFSMNT_DIR = "/mnt/sandbox/pfsmnt"
APP_DB_REMOTE_PATH = "/system_data/priv/mms/app.db"
GOLDHEN_PATCHES_XML_DIR = "/data/GoldHEN/patches/xml"
GOLDHEN_PLUGINS_INI_PATH = "/data/GoldHEN/plugins.ini"
GOLDHEN_PLUGINS_DIR = "/data/GoldHEN/plugins"


@dataclass
class InstalledGame:
    title_id: str
    title: str
    app_ver: str
    category: str
    system_ver: str
    system_ver_int: int
    attribute: int
    sfo_locations: Dict[str, SfoFile] = field(default_factory=dict)
    eboot_locations: List[str] = field(default_factory=list)
    has_goldhen_patch_xml: bool = False
    local_source_path: Optional[str] = None
    local_eboot_path: Optional[str] = None
    eboot_analysis: Optional[EbootAnalysis] = None

    @property
    def is_neo_enabled(self) -> bool:
        return bool(self.attribute & NEO_MODE_BIT)

    @property
    def is_old_sdk(self) -> bool:
        if self.eboot_analysis and self.eboot_analysis.primary_sdk_version:
            return self.eboot_analysis.primary_sdk_version < NEO_MIN_SDK_VERSION
        return 0 < self.system_ver_int < NEO_MIN_SDK_VERSION

    @property
    def attribute_hex(self) -> str:
        return f"0x{self.attribute:08X}"

    @property
    def neo_toggled_attribute_hex(self) -> str:
        new_attr = (self.attribute & ~NEO_MODE_BIT) if self.is_neo_enabled else (self.attribute | NEO_MODE_BIT)
        return f"0x{new_attr:08X}"

    @property
    def locations_summary(self) -> str:
        if self.local_source_path:
            base = f"Local ({Path(self.local_source_path).name})"
            if self.local_eboot_path:
                base += " + eboot.bin"
            return base
        labels = []
        for path in self.sfo_locations:
            if path.startswith(APPMETA_USER_DIR):
                labels.append("user/appmeta")
            elif path.startswith(APPMETA_SYS_DIR):
                labels.append("sys/appmeta")
            elif path.startswith(SANDBOX_PFSMNT_DIR):
                labels.append("pfsmnt")
            else:
                labels.append(path)
        if self.eboot_locations:
            labels.append("eboot.bin")
        return ", ".join(labels) if labels else "N/A"


class BackupManager:
    """Manages timestamped and original baseline backups of PARAM.SFO, eboot.bin, and app.db files."""

    def __init__(self, backups_root: Path = DEFAULT_BACKUPS_DIR) -> None:
        self.backups_root = backups_root
        self.backups_root.mkdir(parents=True, exist_ok=True)

    def get_title_backup_dir(self, title_id: str) -> Path:
        d = self.backups_root / title_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def has_original_backup(self, title_id: str) -> bool:
        d = self.backups_root / title_id
        return d.exists() and (d / "manifest.json").exists()

    def save_original_backup(
        self,
        game: InstalledGame,
        eboot_bytes_map: Optional[Dict[str, bytes]] = None,
    ) -> Path:
        """
        Saves the ORIGINAL (unmodified) param.sfo and eboot.bin files for a game if not already backed up,
        plus a timestamped snapshot whenever called.
        """
        title_dir = self.get_title_backup_dir(game.title_id)
        manifest_path = title_dir / "manifest.json"

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        is_first_backup = not manifest_path.exists()

        manifest: dict = {}
        if not is_first_backup:
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                is_first_backup = True

        saved_files: Dict[str, str] = manifest.get("files", {})
        saved_eboots: Dict[str, str] = manifest.get("eboots", {})

        for idx, (remote_path, sfo) in enumerate(game.sfo_locations.items()):
            raw_bytes = sfo.to_bytes(prefer_inplace=True)
            safe_label = (
                remote_path.strip("/")
                .replace("/", "_")
                .replace("\\", "_")
                .replace(":", "")
            )
            if is_first_backup or remote_path not in saved_files:
                orig_filename = f"ORIGINAL_{idx}_{safe_label}"
                (title_dir / orig_filename).write_bytes(raw_bytes)
                saved_files[remote_path] = orig_filename

            snap_filename = f"{timestamp}_{idx}_{safe_label}"
            (title_dir / snap_filename).write_bytes(raw_bytes)

        if eboot_bytes_map:
            for idx, (epath, ebytes) in enumerate(eboot_bytes_map.items()):
                safe_label = (
                    epath.strip("/")
                    .replace("/", "_")
                    .replace("\\", "_")
                    .replace(":", "")
                )
                if epath not in saved_eboots:
                    orig_ename = f"ORIGINAL_EBOOT_{idx}_{safe_label}"
                    (title_dir / orig_ename).write_bytes(ebytes)
                    saved_eboots[epath] = orig_ename

        manifest_data = {
            "title_id": game.title_id,
            "title": game.title,
            "created_at": manifest.get("created_at", datetime.now().isoformat()),
            "original_attribute": manifest.get("original_attribute", game.attribute),
            "original_attribute_hex": manifest.get("original_attribute_hex", f"0x{game.attribute:08X}"),
            "original_system_ver": manifest.get("original_system_ver", game.system_ver_int),
            "original_neo_enabled": manifest.get("original_neo_enabled", game.is_neo_enabled),
            "files": saved_files,
            "eboots": saved_eboots,
        }
        manifest_path.write_text(json.dumps(manifest_data, indent=2, ensure_ascii=False), encoding="utf-8")
        return title_dir

    def load_original_backup(self, title_id: str) -> Optional[Tuple[Dict[str, bytes], Dict[str, bytes]]]:
        """Loads the original unmodified (sfo_map, eboot_map) bytes for each remote/local path."""
        title_dir = self.backups_root / title_id
        manifest_path = title_dir / "manifest.json"
        if not manifest_path.exists():
            return None

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        restored_sfos: Dict[str, bytes] = {}
        for remote_path, filename in manifest.get("files", {}).items():
            file_path = title_dir / filename
            if file_path.exists():
                restored_sfos[remote_path] = file_path.read_bytes()

        restored_eboots: Dict[str, bytes] = {}
        for epath, filename in manifest.get("eboots", {}).items():
            file_path = title_dir / filename
            if file_path.exists():
                restored_eboots[epath] = file_path.read_bytes()

        return restored_sfos, restored_eboots

    def backup_app_db(self, db_bytes: bytes) -> Path:
        db_dir = self.backups_root / "_app_db"
        db_dir.mkdir(parents=True, exist_ok=True)
        orig_path = db_dir / "app_ORIGINAL.db"
        if not orig_path.exists():
            orig_path.write_bytes(db_bytes)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        snap_path = db_dir / f"app_{ts}.db"
        snap_path.write_bytes(db_bytes)
        return snap_path


class GoldHenFtpClient:
    """FTP Client tailored for GoldHEN FTP Server on PS4 (default port 2121)."""

    def __init__(
        self,
        host: str = "192.168.1.100",
        port: int = 2121,
        timeout: int = 10,
        backup_manager: Optional[BackupManager] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.ftp: Optional[ftplib.FTP] = None
        self.backup_manager = backup_manager or BackupManager()
        self.mtrw_supported: bool = False

    @property
    def is_connected(self) -> bool:
        if self.ftp is None:
            return False
        try:
            self.ftp.voidcmd("NOOP")
            return True
        except Exception:
            return False

    def connect(self, log_cb: Optional[Callable[[str], None]] = None) -> str:
        def log(msg: str) -> None:
            if log_cb:
                log_cb(msg)

        if self.ftp is not None:
            try:
                self.ftp.close()
            except Exception:
                pass

        self.ftp = ftplib.FTP()
        log(f"Conectando a PS4 GoldHEN FTP ({self.host}:{self.port})...")
        welcome = self.ftp.connect(self.host, self.port, timeout=self.timeout)
        self.ftp.login("anonymous", "")
        self.ftp.set_pasv(True)
        log(f"Conectado: {welcome}")

        try:
            resp = self.ftp.sendcmd("SITE MTRW")
            self.mtrw_supported = True
            log(f"Permisos de escritura de sistema activados (SITE MTRW): {resp}")
        except Exception:
            self.mtrw_supported = False
            log("Nota: SITE MTRW no requerido o ya activo en GoldHEN.")

        return welcome

    def disconnect(self) -> None:
        if self.ftp is not None:
            try:
                self.ftp.quit()
            except Exception:
                try:
                    self.ftp.close()
                except Exception:
                    pass
            self.ftp = None

    def list_dir_names(self, remote_dir: str) -> List[str]:
        if not self.ftp:
            raise ConnectionError("No hay conexión FTP activa con la PS4.")

        names: List[str] = []
        try:
            for name, _facts in self.ftp.mlsd(remote_dir):
                if name not in (".", ".."):
                    names.append(name)
            if names:
                return names
        except Exception:
            pass

        try:
            raw_list = self.ftp.nlst(remote_dir)
            for item in raw_list:
                base = item.rstrip("/").split("/")[-1]
                if base not in (".", "..", ""):
                    names.append(base)
            if names:
                return names
        except Exception:
            pass

        lines: List[str] = []
        try:
            self.ftp.cwd(remote_dir)
            self.ftp.retrlines("LIST", lines.append)
            for line in lines:
                parts = line.split(None, 8)
                if len(parts) >= 9:
                    name = parts[8].strip()
                    if name not in (".", ".."):
                        names.append(name)
        except Exception:
            pass

        return names

    def download_bytes(self, remote_path: str) -> Optional[bytes]:
        if not self.ftp:
            raise ConnectionError("No hay conexión FTP activa con la PS4.")
        buf = io.BytesIO()
        try:
            self.ftp.retrbinary(f"RETR {remote_path}", buf.write)
            data = buf.getvalue()
            return data if len(data) > 0 else None
        except Exception:
            return None

    def upload_bytes(self, remote_path: str, data: bytes) -> bool:
        if not self.ftp:
            raise ConnectionError("No hay conexión FTP activa con la PS4.")
        buf = io.BytesIO(data)
        try:
            self.ftp.storbinary(f"STOR {remote_path}", buf)
            return True
        except Exception:
            try:
                self.ftp.sendcmd("SITE MTRW")
                buf.seek(0)
                self.ftp.storbinary(f"STOR {remote_path}", buf)
                return True
            except Exception:
                return False

    def scan_installed_games(
        self,
        include_mounted_sandbox: bool = True,
        log_cb: Optional[Callable[[str], None]] = None,
    ) -> List[InstalledGame]:
        """
        Scans /user/appmeta, /system_data/priv/appmeta, and optionally /mnt/sandbox/pfsmnt
        for installed CUSAXXXXX games, parses their param.sfo files, and locates eboot.bin paths.
        """
        def log(msg: str) -> None:
            if log_cb:
                log_cb(msg)

        if not self.ftp:
            raise ConnectionError("No hay conexión FTP activa con la PS4.")

        log("Escaneando directorios de metadatos en la PS4...")
        user_entries = self.list_dir_names(APPMETA_USER_DIR)
        sys_entries = self.list_dir_names(APPMETA_SYS_DIR)
        xml_files = set(self.list_dir_names(GOLDHEN_PATCHES_XML_DIR))

        title_ids = sorted(
            {
                name.upper()
                for name in (user_entries + sys_entries)
                if len(name) == 9 and (name.upper().startswith("CUSA") or name.upper().startswith("PCAS"))
            }
        )

        mounted_sfo_map: Dict[str, List[str]] = {}
        mounted_eboot_map: Dict[str, List[str]] = {}
        if include_mounted_sandbox:
            pfsmnt_entries = self.list_dir_names(SANDBOX_PFSMNT_DIR)
            for entry in pfsmnt_entries:
                if "-" in entry and not entry.endswith("-nest"):
                    tid = entry.split("-")[0].upper()
                    if len(tid) == 9 and (tid.startswith("CUSA") or tid.startswith("PCAS")):
                        mounted_sfo_map.setdefault(tid, []).append(
                            f"{SANDBOX_PFSMNT_DIR}/{entry}/sce_sys/param.sfo"
                        )
                        mounted_eboot_map.setdefault(tid, []).append(
                            f"{SANDBOX_PFSMNT_DIR}/{entry}/eboot.bin"
                        )
                        if tid not in title_ids:
                            title_ids.append(tid)

        games: List[InstalledGame] = []
        total = len(title_ids)
        log(f"Se encontraron {total} posibles títulos instalados. Leyendo param.sfo...")

        for idx, tid in enumerate(title_ids, 1):
            candidate_paths = [
                f"{APPMETA_USER_DIR}/{tid}/param.sfo",
                f"{APPMETA_SYS_DIR}/{tid}/param.sfo",
            ]
            if tid in mounted_sfo_map:
                candidate_paths.extend(mounted_sfo_map[tid])

            sfo_locations: Dict[str, SfoFile] = {}
            primary_sfo: Optional[SfoFile] = None

            for rpath in candidate_paths:
                raw = self.download_bytes(rpath)
                if raw:
                    try:
                        parsed = SfoFile.from_bytes(raw)
                        sfo_locations[rpath] = parsed
                        if primary_sfo is None:
                            primary_sfo = parsed
                    except Exception as e:
                        log(f"  [!] Error parseando {rpath}: {e}")

            if primary_sfo is None:
                continue

            game = InstalledGame(
                title_id=primary_sfo.title_id if primary_sfo.title_id != "UNKNOWN" else tid,
                title=primary_sfo.title,
                app_ver=primary_sfo.app_ver,
                category=primary_sfo.category,
                system_ver=primary_sfo.system_ver_hex,
                system_ver_int=primary_sfo.system_ver,
                attribute=primary_sfo.attribute,
                sfo_locations=sfo_locations,
                eboot_locations=mounted_eboot_map.get(tid, []),
                has_goldhen_patch_xml=f"{tid}.xml" in xml_files,
            )
            games.append(game)
            sdk_tag = " [SDK ANTIGUO < 4.00]" if game.is_old_sdk else ""
            status = "NEO ACTIVO" if game.is_neo_enabled else "Modo Base"
            log(f"  [{idx}/{total}] {game.title_id} - {game.title} (v{game.app_ver}) [{status}]{sdk_tag}")

        log(f"Escaneo completado: {len(games)} juegos listos.")
        return games

    def apply_neo_mode(
        self,
        game: InstalledGame,
        enable: bool,
        patch_old_sdk: bool = True,
        sync_app_db: bool = True,
        log_cb: Optional[Callable[[str], None]] = None,
    ) -> Tuple[bool, str]:
        """
        Injects Neo Mode (ATTRIBUTE bit 23: 0x00800000) into a game.
        When `patch_old_sdk=True` and the game was compiled with an old SDK (< 4.00 / 0x04000000):
        1. Upgrades `SYSTEM_VER` in `param.sfo` to `0x04500000` (FW 4.50, Neo/Boost threshold)
           so the kernel doesn't flag an ATTRIBUTE vs SYSTEM_VER inconsistency.
        2. If `eboot.bin` is accessible (locally or in `/mnt/sandbox/pfsmnt`), upgrades
           `OrbisProcParam` (`ORBI`) and `OrbisModuleParam` `sdk_version` to `0x04500001` (SDK 4.50)
           so `libSceGnmDriverForNeoMode.sprx` initializes the Neo GPU context without crashing!
        """
        def log(msg: str) -> None:
            if log_cb:
                log_cb(msg)

        # Download or read any accessible eboot.bin files before saving backup
        eboot_raw_map: Dict[str, bytes] = {}
        if enable and patch_old_sdk:
            if game.local_eboot_path and Path(game.local_eboot_path).exists():
                eboot_raw_map[game.local_eboot_path] = Path(game.local_eboot_path).read_bytes()
            elif self.ftp and game.eboot_locations:
                for ep in game.eboot_locations:
                    eb = self.download_bytes(ep)
                    if eb:
                        eboot_raw_map[ep] = eb

        # 1. Create automatic backup first (includes original param.sfo and original eboot.bin)
        backup_dir = self.backup_manager.save_original_backup(game, eboot_bytes_map=eboot_raw_map)
        log(f"Backup de seguridad verificado en: {backup_dir}")

        old_attr = game.attribute
        new_attr = (old_attr | NEO_MODE_BIT) if enable else (old_attr & ~NEO_MODE_BIT)
        old_sys_ver = game.system_ver_int
        upgraded_sfo_sdk = False

        # Upgrade SYSTEM_VER in param.sfo if enabling Neo Mode on an old SDK (< 0x04000000)
        for sfo in game.sfo_locations.values():
            sfo.set_neo_mode(enable)
            if enable and patch_old_sdk and 0 < sfo.system_ver < NEO_MIN_SDK_VERSION:
                sfo.system_ver = 0x04500000
                upgraded_sfo_sdk = True

        if upgraded_sfo_sdk:
            primary = next(iter(game.sfo_locations.values()))
            game.system_ver_int = primary.system_ver
            game.system_ver = primary.system_ver_hex
            log(
                f"  [Fix SDK Antiguo] SYSTEM_VER en param.sfo elevado de 0x{old_sys_ver:08X} -> 0x04500000 (FW 4.50 Neo)"
            )

        # Patch eboot.bin OrbisProcParam ('ORBI') sdk_version if accessible
        eboot_patched_count = 0
        if enable and patch_old_sdk and eboot_raw_map:
            for epath, raw_eboot in eboot_raw_map.items():
                analysis = analyze_eboot_bytes(raw_eboot)
                game.eboot_analysis = analysis
                if analysis.is_patchable and analysis.is_old_sdk:
                    old_eboot_sdk = analysis.primary_sdk_version or 0
                    patched_eboot, new_analysis = patch_eboot_sdk_version(raw_eboot, NEO_COMPAT_SDK_VERSION)
                    game.eboot_analysis = new_analysis
                    if game.local_eboot_path and epath == game.local_eboot_path:
                        Path(epath).write_bytes(patched_eboot)
                        eboot_patched_count += 1
                        log(
                            f"  [Fix SDK Antiguo] eboot.bin ('ORBI' OrbisProcParam) sdk_version elevado: "
                            f"0x{old_eboot_sdk:08X} -> 0x{NEO_COMPAT_SDK_VERSION:08X}"
                        )
                    elif self.ftp and self.upload_bytes(epath, patched_eboot):
                        eboot_patched_count += 1
                        log(
                            f"  [Fix SDK Antiguo] eboot.bin remoto ({epath}) sdk_version elevado: "
                            f"0x{old_eboot_sdk:08X} -> 0x{NEO_COMPAT_SDK_VERSION:08X}"
                        )
                elif not analysis.is_patchable:
                    log(f"  [Aviso eboot.bin] {analysis.notes}")

        # Handle offline/local file mode
        if game.local_source_path:
            sfo = next(iter(game.sfo_locations.values()))
            sfo.save(game.local_source_path, prefer_inplace=True)
            game.attribute = new_attr
            action_str = "ACTIVADO" if enable else "DESACTIVADO"
            sdk_note = " + Parche SDK Antiguo (4.50)" if (upgraded_sfo_sdk or eboot_patched_count > 0) else ""
            msg = (
                f"Modo Neo {action_str}{sdk_note} en {game.local_source_path} "
                f"(ATTRIBUTE: 0x{old_attr:08X} -> 0x{new_attr:08X})"
            )
            log(msg)
            return True, msg

        if not self.ftp:
            return False, "No hay conexión FTP activa con la PS4."

        # 2. Upload patched param.sfo files to all discovered PS4 locations
        uploaded_paths: List[str] = []
        for rpath, sfo in game.sfo_locations.items():
            patched_bytes = sfo.to_bytes(prefer_inplace=True)
            if self.upload_bytes(rpath, patched_bytes):
                uploaded_paths.append(rpath)
                log(f"  [OK] Actualizado: {rpath} -> ATTRIBUTE 0x{new_attr:08X}")
            else:
                log(f"  [!] No se pudo escribir en: {rpath} (puede ser de solo lectura si el juego está montado)")

        if not uploaded_paths:
            return False, f"No se pudo actualizar ningún param.sfo para {game.title_id}."

        game.attribute = new_attr

        # 3. Optionally synchronize /system_data/priv/mms/app.db (tbl_appinfo)
        if sync_app_db:
            db_ok, db_msg = self.sync_attribute_in_app_db(
                game.title_id,
                new_attr,
                new_system_ver=game.system_ver_int if upgraded_sfo_sdk else None,
                log_cb=log_cb,
            )
            if not db_ok:
                log(f"  [Aviso app.db] {db_msg}")

        action_str = "ACTIVADO" if enable else "DESACTIVADO"
        sdk_note = " [SDK Antiguo actualizado a 4.50 Neo]" if (upgraded_sfo_sdk or eboot_patched_count > 0) else ""
        summary = (
            f"Modo Neo {action_str} para {game.title} ({game.title_id}){sdk_note}. "
            f"ATTRIBUTE: 0x{old_attr:08X} -> 0x{new_attr:08X} "
            f"({len(uploaded_paths)} param.sfo y {eboot_patched_count} eboot.bin actualizados)."
        )
        log(summary)
        return True, summary

    def restore_original_backup(
        self,
        game: InstalledGame,
        sync_app_db: bool = True,
        log_cb: Optional[Callable[[str], None]] = None,
    ) -> Tuple[bool, str]:
        """Restores the original unmodified param.sfo and eboot.bin files from the local backup."""
        def log(msg: str) -> None:
            if log_cb:
                log_cb(msg)

        loaded = self.backup_manager.load_original_backup(game.title_id)
        if not loaded:
            return False, f"No existe un backup original registrado para {game.title_id}."

        restored_sfos, restored_eboots = loaded

        if game.local_source_path:
            raw_bytes = next(iter(restored_sfos.values()))
            Path(game.local_source_path).write_bytes(raw_bytes)
            parsed = SfoFile.from_bytes(raw_bytes)
            game.sfo_locations[game.local_source_path] = parsed
            game.attribute = parsed.attribute
            game.system_ver_int = parsed.system_ver
            game.system_ver = parsed.system_ver_hex

            if game.local_eboot_path and game.local_eboot_path in restored_eboots:
                eb_raw = restored_eboots[game.local_eboot_path]
                Path(game.local_eboot_path).write_bytes(eb_raw)
                game.eboot_analysis = analyze_eboot_bytes(eb_raw)
                log(f"  [OK] Restaurado eboot.bin original: {game.local_eboot_path}")

            msg = f"Backup original restaurado en {game.local_source_path} (ATTRIBUTE: 0x{game.attribute:08X})."
            log(msg)
            return True, msg

        if not self.ftp:
            return False, "No hay conexión FTP activa con la PS4."

        restored_count = 0
        new_attr = game.attribute
        new_sys_ver = game.system_ver_int
        for rpath, raw_bytes in restored_sfos.items():
            if self.upload_bytes(rpath, raw_bytes):
                restored_count += 1
                parsed = SfoFile.from_bytes(raw_bytes)
                game.sfo_locations[rpath] = parsed
                new_attr = parsed.attribute
                new_sys_ver = parsed.system_ver
                game.system_ver = parsed.system_ver_hex
                log(f"  [OK] Restaurado param.sfo original: {rpath}")

        for epath, eb_bytes in restored_eboots.items():
            if self.upload_bytes(epath, eb_bytes):
                game.eboot_analysis = analyze_eboot_bytes(eb_bytes)
                log(f"  [OK] Restaurado eboot.bin original: {epath}")

        if restored_count == 0:
            return False, f"Error al subir los archivos de backup para {game.title_id}."

        game.attribute = new_attr
        game.system_ver_int = new_sys_ver
        if sync_app_db:
            self.sync_attribute_in_app_db(game.title_id, new_attr, new_system_ver=new_sys_ver, log_cb=log_cb)

        msg = f"Backup original restaurado para {game.title} ({game.title_id}) -> ATTRIBUTE 0x{new_attr:08X}."
        log(msg)
        return True, msg

    def sync_attribute_in_app_db(
        self,
        title_id: str,
        new_attribute: int,
        new_system_ver: Optional[int] = None,
        log_cb: Optional[Callable[[str], None]] = None,
    ) -> Tuple[bool, str]:
        """
        Downloads /system_data/priv/mms/app.db, updates key='ATTRIBUTE' (and SYSTEM_VER if upgraded)
        for titleId in tbl_appinfo, and re-uploads it so the PS4 OS database stays in sync.
        """
        def log(msg: str) -> None:
            if log_cb:
                log_cb(msg)

        log(f"Sincronizando ATTRIBUTE en {APP_DB_REMOTE_PATH} para {title_id}...")
        db_bytes = self.download_bytes(APP_DB_REMOTE_PATH)
        if not db_bytes:
            return False, "No se pudo descargar app.db (puede requerir permisos o ruta distinta)."

        self.backup_manager.backup_app_db(db_bytes)

        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".db")
        os.close(tmp_fd)
        try:
            Path(tmp_path).write_bytes(db_bytes)
            conn = sqlite3.connect(tmp_path)
            try:
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tbl_appinfo'")
                if not cur.fetchone():
                    return False, "La tabla tbl_appinfo no se encontró en app.db."

                cur.execute(
                    "UPDATE tbl_appinfo SET val = ? WHERE titleId = ? AND key = 'ATTRIBUTE'",
                    (str(new_attribute), title_id),
                )
                rows_updated = cur.rowcount

                if new_system_ver is not None:
                    cur.execute(
                        "UPDATE tbl_appinfo SET val = ? WHERE titleId = ? AND key = 'SYSTEM_VER'",
                        (str(new_system_ver), title_id),
                    )
                    rows_updated += cur.rowcount

                conn.commit()
            finally:
                conn.close()

            if rows_updated > 0:
                updated_bytes = Path(tmp_path).read_bytes()
                if self.upload_bytes(APP_DB_REMOTE_PATH, updated_bytes):
                    msg = f"app.db (tbl_appinfo) sincronizado correctamente ({rows_updated} fila(s) actualizada(s))."
                    log(f"  [OK] {msg}")
                    return True, msg
                return False, "No se pudo subir app.db modificado."
            else:
                return True, "app.db no requería cambios en tbl_appinfo para este título."
        except Exception as e:
            return False, f"Error procesando app.db: {e}"
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    def ensure_remote_dir(self, remote_dir: str) -> None:
        if not self.ftp:
            return
        parts = [p for p in remote_dir.strip("/").split("/") if p]
        curr = ""
        for p in parts:
            curr += f"/{p}"
            try:
                self.ftp.mkd(curr)
            except Exception:
                pass

    def deploy_goldhen_xml_patch(
        self,
        title_id: str,
        xml_content: str,
        local_save_dir: Optional[Path] = None,
        log_cb: Optional[Callable[[str], None]] = None,
    ) -> Tuple[bool, str]:
        """
        Saves the generated GoldHEN resolution/60FPS XML patch (`<CUSAXXXXX>.xml`) locally
        and, if connected via FTP, uploads it directly to `/data/GoldHEN/patches/xml/<CUSAXXXXX>.xml`.
        """
        def log(msg: str) -> None:
            if log_cb:
                log_cb(msg)

        tid_upper = title_id.upper()
        xml_bytes = xml_content.encode("utf-8")

        out_dir = local_save_dir or (self.backup_manager.backups_root.parent / "goldhen_patches_xml")
        out_dir.mkdir(parents=True, exist_ok=True)
        local_xml_path = out_dir / f"{tid_upper}.xml"
        local_xml_path.write_bytes(xml_bytes)
        log(f"  [XML] Parche de Resolución/60FPS guardado en PC: {local_xml_path}")

        if self.ftp and self.is_connected:
            self.ensure_remote_dir(GOLDHEN_PATCHES_XML_DIR)
            remote_xml_path = f"{GOLDHEN_PATCHES_XML_DIR}/{tid_upper}.xml"
            if self.upload_bytes(remote_xml_path, xml_bytes):
                msg = (
                    f"Parche XML subido a PS4 ({remote_xml_path}) y guardado en {local_xml_path}. "
                    "Actívalo desde GoldHEN Cheat/Patch Menu al iniciar el juego."
                )
                log(f"  [OK] {msg}")
                return True, msg
            else:
                msg = f"Guardado localmente en {local_xml_path}, pero falló la subida FTP a {remote_xml_path}."
                log(f"  [!] {msg}")
                return False, msg

        msg = (
            f"Parche XML generado en: {local_xml_path} "
            f"(Cópialo a {GOLDHEN_PATCHES_XML_DIR}/{tid_upper}.xml en tu PS4 o conecta el FTP)."
        )
        log(f"  [OK] {msg}")
        return True, msg

    def fetch_game_eboot_bytes(
        self,
        game: InstalledGame,
        log_cb: Optional[Callable[[str], None]] = None,
    ) -> Tuple[Optional[bytes], Optional[str]]:
        """
        Fetches the raw eboot.bin bytes for the selected game in real-time:
        1. If `game.local_eboot_path` exists on PC, reads it directly.
        2. If connected via FTP, checks `/mnt/sandbox/pfsmnt/<TITLE_ID>-app0/eboot.bin`
           or `/mnt/sandbox/pfsmnt/<TITLE_ID>-patch0/eboot.bin` (if the game is running/mounted on the PS4)
           and caches it locally inside `backups/<TITLE_ID>/live_eboot.bin` for instant analysis.
        Returns (eboot_bytes, local_or_remote_source_path).
        """
        def log(msg: str) -> None:
            if log_cb:
                log_cb(msg)

        if game.local_eboot_path and Path(game.local_eboot_path).exists():
            log(f"Leyendo eboot.bin local de {game.title_id}: {game.local_eboot_path}")
            return Path(game.local_eboot_path).read_bytes(), game.local_eboot_path

        if not self.ftp or not self.is_connected:
            return None, None

        # Check known eboot locations or re-scan /mnt/sandbox/pfsmnt for freshly launched game
        candidates = list(game.eboot_locations)
        tid = game.title_id.upper()
        for suffix in ("app0", "patch0"):
            rpath = f"{SANDBOX_PFSMNT_DIR}/{tid}-{suffix}/eboot.bin"
            if rpath not in candidates:
                candidates.append(rpath)

        for rpath in candidates:
            log(f"Intentando descargar eboot.bin en tiempo real desde PS4 ({rpath})...")
            data = self.download_bytes(rpath)
            if data and len(data) > 64:
                cache_dir = self.backup_manager.get_title_backup_dir(tid)
                local_cache = cache_dir / f"{tid}_live_eboot.bin"
                local_cache.write_bytes(data)
                game.local_eboot_path = str(local_cache)
                if rpath not in game.eboot_locations:
                    game.eboot_locations.append(rpath)
                log(f"  [OK] eboot.bin descargado en tiempo real ({len(data):,} bytes) -> {local_cache}")
                return data, rpath

        return None, None
