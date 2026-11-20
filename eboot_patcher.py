"""
PS4 ELF / FSELF (`eboot.bin` / `.prx` / `.sprx`) SDK Version Inspector & Upgrader for Old SDK Games.

Why old SDK games (< SDK 3.70 / 4.00) crash when Neo Mode (0x00800000) is enabled in param.sfo:
1. When ATTRIBUTE bit 23 (0x00800000) is active, the PS4 Pro OS mounts `libSceGnmDriverForNeoMode.sprx`
   and runs the process under the Neo hardware context (36 CUs @ 911 MHz + 5.5 GB memory budget).
2. During initialization, `libkernel` and `libSceGnmDriverForNeoMode` read the binary's `PT_SCE_PROCPARAM`
   (`0x61000001`, magic `ORBI` / `0x4942524F`) and `PT_SCE_MODULE_PARAM` (`0x61000002`, magic `0x3C13F4BF`).
3. At offset +0x10 inside `OrbisProcParam` (and +0x10 inside `OrbisModuleParam`) sits `sdk_version`.
   If `sdk_version < 0x04000000` (SDK 4.00, predating PS4 Pro), the Neo Mode driver / kernel validation
   detects an impossible hardware/SDK combination (Neo Mode flag on a pre-Neo SDK binary) or fails
   the 4.00 GNM hardware state initialization check, resulting in instant crash CE-34878-0.
4. Additionally, `SYSTEM_VER` inside `param.sfo` should be >= `0x04000000` (or `0x04500000`) when Neo Mode is enabled.

This module parses both raw ELF64 and Fake-Signed SELF (FSELF, magic `0x1D3D154F`) files,
locates `OrbisProcParam` (`ORBI`) and `OrbisModuleParam`, inspects their `sdk_version`, and patches
them cleanly to a Neo-compatible SDK version (e.g., `0x04500001` / SDK 4.50) while preserving a backup.
"""

from __future__ import annotations
import struct
from dataclasses import dataclass
from typing import List, Optional, Tuple


ELF_MAGIC = b"\x7fELF"
FSELF_MAGIC = 0x1D3D154F  # Little-endian: 4F 15 3D 1D

PT_LOAD = 0x00000001
PT_SCE_RELRO = 0x61000010
PT_SCE_PROCPARAM = 0x61000001
PT_SCE_MODULE_PARAM = 0x61000002

ORBI_MAGIC = b"ORBI"  # 0x4942524F in little-endian
MODULE_PARAM_MAGIC = 0x3C13F4BF

# Default Neo-compatible SDK version (SDK 4.50.001 = 0x04500001)
NEO_COMPAT_SDK_VERSION = 0x04500001
NEO_MIN_SDK_VERSION = 0x04000000


def format_sdk_version(sdk_ver: int) -> str:
    major = (sdk_ver >> 24) & 0xFF
    minor = (sdk_ver >> 12) & 0xFFF
    patch = sdk_ver & 0xFFF
    return f"{major:02X}.{minor:03X}.{patch:03X} (0x{sdk_ver:08X})"


@dataclass
class ParamLocation:
    kind: str  # "OrbisProcParam (ORBI)" or "OrbisModuleParam"
    file_offset: int
    sdk_version_offset: int
    current_sdk_version: int
    struct_size: int


@dataclass
class EbootAnalysis:
    container_type: str  # "ELF64", "FSELF (Fake Signed)", or "Encrypted Retail SELF / Unknown"
    is_patchable: bool
    locations: List[ParamLocation]
    notes: str

    @property
    def primary_sdk_version(self) -> Optional[int]:
        if not self.locations:
            return None
        return self.locations[0].current_sdk_version

    @property
    def is_old_sdk(self) -> bool:
        ver = self.primary_sdk_version
        return ver is not None and ver < NEO_MIN_SDK_VERSION


def analyze_eboot_bytes(data: bytes) -> EbootAnalysis:
    """
    Analyzes a PS4 eboot.bin / .elf / .prx binary (either raw ELF64 or Fake-Signed FSELF)
    and locates all OrbisProcParam ('ORBI') and OrbisModuleParam structures and their sdk_version offsets.
    """
    if len(data) < 64:
        return EbootAnalysis("Invalid (< 64 bytes)", False, [], "Archivo demasiado pequeño.")

    magic_u32 = struct.unpack("<I", data[:4])[0]
    container_type = "Unknown"
    elf_offset: Optional[int] = None

    if data[:4] == ELF_MAGIC:
        container_type = "ELF64"
        elf_offset = 0
    elif magic_u32 == FSELF_MAGIC:
        # Parse 32-byte SELF header: <I BBBB I HH Q HH I
        _magic, _ver, _mode, _endian, _attr, _key_type, _hdr_size, _meta_size, _file_size, num_entries, _flags, _pad = (
            struct.unpack("<IBBBBIHHQHHI", data[:32])
        )
        # Each SELF segment entry is 32 bytes right after the 32-byte header
        entries_end = 32 + (num_entries * 32)
        # Find embedded ELF64 header (\x7fELF\x02\x01\x01) right after SELF entries
        idx = data.find(b"\x7fELF\x02\x01\x01", 32, min(len(data), entries_end + 0x200))
        if idx != -1:
            elf_offset = idx
            container_type = "FSELF (Fake Signed SELF)"
        else:
            container_type = "SELF (Encrypted / Retail)"

    locations: List[ParamLocation] = []

    # 1. Try exact ELF64 Program Header parsing if ELF header is accessible and unencrypted
    if elf_offset is not None and elf_offset + 64 <= len(data):
        ehdr = data[elf_offset : elf_offset + 64]
        e_phoff = struct.unpack("<Q", ehdr[32:40])[0]
        e_phentsize = struct.unpack("<H", ehdr[54:56])[0]
        e_phnum = struct.unpack("<H", ehdr[56:58])[0]

        ph_table_start = elf_offset + e_phoff
        if e_phentsize >= 56 and ph_table_start + (e_phnum * e_phentsize) <= len(data):
            for i in range(e_phnum):
                ph_off = ph_table_start + i * e_phentsize
                p_type, _p_flags, p_offset, _p_vaddr, _p_paddr, p_filesz, _p_memsz, _p_align = struct.unpack(
                    "<IIQQQQQQ", data[ph_off : ph_off + 56]
                )
                if p_type in (PT_SCE_PROCPARAM, PT_SCE_MODULE_PARAM):
                    # In raw ELF64, p_offset is direct from file start (0)
                    cand_offsets = [p_offset]
                    if elf_offset > 0:
                        cand_offsets.append(elf_offset + p_offset)
                    for base in cand_offsets:
                        if 0 <= base and base + 20 <= len(data):
                            sz, mag = struct.unpack("<QI", data[base : base + 12])
                            if p_type == PT_SCE_PROCPARAM and data[base + 8 : base + 12] == ORBI_MAGIC:
                                sdk_ver = struct.unpack("<I", data[base + 16 : base + 20])[0]
                                locations.append(
                                    ParamLocation(
                                        kind="OrbisProcParam (ORBI)",
                                        file_offset=base,
                                        sdk_version_offset=base + 16,
                                        current_sdk_version=sdk_ver,
                                        struct_size=sz,
                                    )
                                )
                            elif p_type == PT_SCE_MODULE_PARAM and mag == MODULE_PARAM_MAGIC:
                                sdk_ver = struct.unpack("<I", data[base + 16 : base + 20])[0]
                                locations.append(
                                    ParamLocation(
                                        kind="OrbisModuleParam",
                                        file_offset=base,
                                        sdk_version_offset=base + 16,
                                        current_sdk_version=sdk_ver,
                                        struct_size=sz,
                                    )
                                )

    # 2. Also scan binary directly for validated OrbisProcParam ('ORBI') and OrbisModuleParam blocks
    # (Vital for FSELF files where segment offsets inside the FSELF container differ from raw ELF p_offset)
    known_sdk_offsets = {loc.sdk_version_offset for loc in locations}

    # Scan for 'ORBI' at offset +8 of OrbisProcParam:
    # struct OrbisProcParam { u64 size; u32 magic ('ORBI'); u32 entry_count; u64 sdk_version; ... }
    search_pos = 0
    while True:
        idx = data.find(ORBI_MAGIC, search_pos)
        if idx == -1 or idx + 16 > len(data):
            break
        search_pos = idx + 4
        if idx < 8:
            continue
        struct_start = idx - 8
        size_val, _mag, entry_count, sdk_ver_lo, sdk_ver_hi = struct.unpack(
            "<QIIII", data[struct_start : struct_start + 24]
        )
        # Validate realistic OrbisProcParam fields:
        # size is typically between 0x30 (48) and 0x200 (512), entry_count between 1 and 32,
        # and sdk_version is between 0x01000000 (SDK 1.00) and 0x15000000 (SDK 15.00)
        if (
            0x20 <= size_val <= 0x400
            and 0 <= entry_count <= 64
            and 0x01000000 <= sdk_ver_lo <= 0x15000000
            and sdk_ver_hi == 0
        ):
            sdk_off = struct_start + 16
            if sdk_off not in known_sdk_offsets:
                locations.append(
                    ParamLocation(
                        kind="OrbisProcParam (ORBI)",
                        file_offset=struct_start,
                        sdk_version_offset=sdk_off,
                        current_sdk_version=sdk_ver_lo,
                        struct_size=size_val,
                    )
                )
                known_sdk_offsets.add(sdk_off)

    # Scan for OrbisModuleParam magic (0x3C13F4BF = BF F4 13 3C) at offset +8:
    mod_magic_bytes = struct.pack("<I", MODULE_PARAM_MAGIC)
    search_pos = 0
    while True:
        idx = data.find(mod_magic_bytes, search_pos)
        if idx == -1 or idx + 16 > len(data):
            break
        search_pos = idx + 4
        if idx < 8:
            continue
        struct_start = idx - 8
        size_val, _mag, _pad_or_ver, sdk_ver_lo = struct.unpack(
            "<QIII", data[struct_start : struct_start + 20]
        )
        if 0x18 <= size_val <= 0x400 and 0x01000000 <= sdk_ver_lo <= 0x15000000:
            sdk_off = struct_start + 16
            if sdk_off not in known_sdk_offsets:
                locations.append(
                    ParamLocation(
                        kind="OrbisModuleParam",
                        file_offset=struct_start,
                        sdk_version_offset=sdk_off,
                        current_sdk_version=sdk_ver_lo,
                        struct_size=size_val,
                    )
                )
                known_sdk_offsets.add(sdk_off)

    if not locations:
        if container_type.startswith("SELF"):
            note = (
                "El archivo eboot.bin es un SELF encriptado original (Retail) o comprimido. "
                "Para parchear el eboot.bin directamente debe ser un FPKG (FSELF desencriptado), "
                "o bien usa el plugin de GoldHEN 'neoenabler_sdk.prx' en tiempo de ejecución."
            )
        else:
            note = "No se encontraron cabeceras OrbisProcParam ('ORBI') en el archivo."
        return EbootAnalysis(container_type, False, [], note)

    ver = locations[0].current_sdk_version
    if ver < NEO_MIN_SDK_VERSION:
        note = (
            f"¡SDK Antiguo detectado ({format_sdk_version(ver)})! "
            "Este ejecutable fue compilado antes de que existiera la PS4 Pro (SDK < 4.00). "
            "Si activas el Modo Neo en param.sfo sin elevar este sdk_version a >= 0x04000000, "
            "libSceGnmDriverForNeoMode provocará crash CE-34878-0 al iniciar."
        )
    else:
        note = (
            f"SDK Compatible con Modo Neo ({format_sdk_version(ver)} >= 4.00). "
            "El ejecutable ya soporta la inicialización de libSceGnmDriverForNeoMode."
        )

    return EbootAnalysis(container_type, True, locations, note)


def patch_eboot_sdk_version(
    data: bytes,
    target_sdk_version: int = NEO_COMPAT_SDK_VERSION,
) -> Tuple[bytes, EbootAnalysis]:
    """
    Patches all discovered OrbisProcParam / OrbisModuleParam `sdk_version` fields
    inside an ELF64 or FSELF (`eboot.bin`) to `target_sdk_version` (default 0x04500001 / SDK 4.50).
    Returns (patched_bytes, updated_analysis).
    """
    analysis = analyze_eboot_bytes(data)
    if not analysis.is_patchable or not analysis.locations:
        raise ValueError(analysis.notes)

    buf = bytearray(data)
    packed_ver = struct.pack("<I", target_sdk_version & 0xFFFFFFFF)
    for loc in analysis.locations:
        buf[loc.sdk_version_offset : loc.sdk_version_offset + 4] = packed_ver

    updated_bytes = bytes(buf)
    return updated_bytes, analyze_eboot_bytes(updated_bytes)


def create_sample_fself_eboot(sdk_version: int = 0x02500001) -> bytes:
    """
    Creates a realistic mock FSELF (Fake Signed SELF) eboot.bin containing an embedded ELF64 header
    and a valid OrbisProcParam ('ORBI') block for testing old-SDK Neo Mode injection.
    """
    # 1. 32-byte SELF header (magic 0x1D3D154F, 1 segment entry)
    self_hdr = struct.pack(
        "<IBBBBIHHQHHI",
        FSELF_MAGIC,
        0x00,
        0x01,
        0x01,
        0x12,
        0x101,
        0x20,
        0x40,
        0x200,
        1,  # num_entries = 1
        0x00,
        0,
    )
    # 32-byte segment entry
    seg_entry = struct.pack("<QQQQ", 0x00, 0x100, 0x100, 0x100)

    # 2. Embedded 64-byte ELF64 header at offset 0x40 (64)
    # Program header table at +0x40 (offset 128), 1 entry of 56 bytes
    e_ident = b"\x7fELF\x02\x01\x01\x09" + b"\x00" * 8
    elf_hdr = e_ident + struct.pack(
        "<HHIQQQIHHHHHH",
        0xFE10,  # e_type (ET_SCE_EXEC)
        0x003E,  # e_machine (EM_X86_64)
        1,       # e_version
        0x400000,# e_entry
        64,      # e_phoff (immediately follows 64-byte ELF header)
        0,       # e_shoff
        0,       # e_flags
        64,      # e_ehsize
        56,      # e_phentsize
        1,       # e_phnum
        64,      # e_shentsize
        0,       # e_shnum
        0,       # e_shstrndx
    )

    # 3. 56-byte Program Header (PT_SCE_PROCPARAM) pointing to offset 0x100
    phdr = struct.pack(
        "<IIQQQQQQ",
        PT_SCE_PROCPARAM,
        0x04,    # PF_R
        0x100,   # p_offset (relative to file or ELF)
        0x600000,# p_vaddr
        0x600000,# p_paddr
        0x40,    # p_filesz
        0x40,    # p_memsz
        0x08,    # p_align
    )

    prefix = self_hdr + seg_entry + elf_hdr + phdr
    padding = b"\x00" * (0x100 - len(prefix))

    # 4. 64-byte OrbisProcParam block at offset 0x100
    # struct OrbisProcParam { u64 size=0x40; u32 magic='ORBI'; u32 entry_count=4; u64 sdk_version; ... }
    proc_param = (
        struct.pack("<Q", 0x40)
        + ORBI_MAGIC
        + struct.pack("<I", 4)
        + struct.pack("<Q", sdk_version)
        + b"\x00" * 40
    )

    return prefix + padding + proc_param
