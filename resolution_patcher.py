"""
Resolution & Framerate (60 FPS) Enhancer for NEOENABLER (GoldHEN PS4 Pro).

Provides:
1. Curated GoldHEN XML Patches (`/data/GoldHEN/patches/xml/<CUSAXXXXX>.xml`) for classic
   unpatched / old-SDK games (Bloodborne, Driveclub, The Order: 1886, Assassin's Creed Unity, etc.)
   unlocking higher rendering resolutions (1080p, 1440p, 1620p) and 60 FPS once Neo Mode (36 CUs @ 911 MHz)
   is enabled.
2. Universal Heuristic Resolution Scanner for any decrypted `eboot.bin` (ELF64 / FSELF):
   Scans executable code segments for x86_64 `MOV reg/mem, width` + `MOV reg/mem, height`
   instruction pairs (e.g., 1280x720, 1600x900, 1920x1080) and automatically generates
   a ready-to-use GoldHEN XML patch (`CUSAXXXXX.xml`) to upgrade internal resolution to
   1080p (1920x1080), 1440p (2560x1440), or 1620p (2880x1620).
"""

from __future__ import annotations
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# Common PS4 base resolutions (width, height) -> name
SOURCE_RESOLUTIONS: Dict[str, Tuple[int, int]] = {
    "720p (1280x720)": (1280, 720),
    "792p (1408x792)": (1408, 792),
    "800p (1920x800 Cinema)": (1920, 800),
    "900p (1600x900)": (1600, 900),
    "1080p (1920x1080)": (1920, 1080),
}

# Target Neo Mode enhanced resolutions (width, height) -> name
TARGET_RESOLUTIONS: Dict[str, Tuple[int, int]] = {
    "1080p Full HD (1920x1080)": (1920, 1080),
    "1440p QHD 2K (2560x1440)": (2560, 1440),
    "1620p Neo Plus (2880x1620)": (2880, 1620),
    "2160p 4K UHD (3840x2160)": (3840, 2160),
}


@dataclass
class XmlPatchLine:
    line_type: str  # "byte", "bytes16", "bytes32", "bytes", "float32"
    address: str    # e.g. "0x0084cefd"
    value: str      # e.g. "0x00000780" or "00f7"
    comment: str = ""


@dataclass
class GoldHenPatchEntry:
    title: str
    name: str
    note: str
    author: str
    app_ver: str
    app_elf: str = "eboot.bin"
    patch_ver: str = "1.0"
    lines: List[XmlPatchLine] = field(default_factory=list)


@dataclass
class ResolutionMatch:
    """Represents a discovered x86_64 width/height initialization pair inside an eboot.bin."""
    width_file_offset: int
    height_file_offset: int
    width_vaddr: int
    height_vaddr: int
    original_width: int
    original_height: int
    pattern_description: str


@dataclass
class FramerateMatch:
    """Represents a discovered x86_64 30 FPS fliprate lock (MOV ESI, 1 or 2 before sceVideoOutSetFlipRate)."""
    file_offset: int
    vaddr: int
    original_bytes_hex: str
    patched_bytes_hex: str
    pattern_description: str


@dataclass
class LiveAnalyzedCandidate:
    """Represents a single real-time discovered binary signature in the game's eboot.bin."""
    category: str           # "Resolución", "Framerate (FlipRate)", "DeltaTime (30->60Hz)", "Aspect Ratio"
    description: str
    file_offset: int
    vaddr: int
    patch_type: str         # "bytes32", "bytes", "float32"
    original_value_str: str
    target_value_str: str
    extra_offset: Optional[int] = None
    extra_vaddr: Optional[int] = None
    extra_target_str: Optional[str] = None
    enabled_by_default: bool = True


# Curated database of verified GoldHEN XML patches for iconic unpatched / old-SDK games
CURATED_GAME_PATCHES: Dict[str, List[GoldHenPatchEntry]] = {
    # Bloodborne (US / EU / GOTY)
    "CUSA00900": [
        GoldHenPatchEntry(
            title="Bloodborne",
            name="Resolution Patch (1440p for Neo Mode)",
            note="Escala el framebuffer interno de 1080p a 2560x1440p aprovechando las 36 CUs de PS4 Pro.",
            author="illusion / gasb07 / NEOENABLER",
            app_ver="01.09",
            lines=[
                XmlPatchLine("bytes", "0x04b36dda", "00f7", "Width/Height Scaling Factor 1440p (1)"),
                XmlPatchLine("bytes", "0x04b36de2", "00a0", "Width/Height Scaling Factor 1440p (2)"),
            ],
        ),
        GoldHenPatchEntry(
            title="Bloodborne",
            name="60 FPS Unlock (DeltaTime)",
            note="Desbloquea el límite de 30 FPS a 60 FPS con ajuste de velocidad de juego (Requiere Modo Neo).",
            author="Lance McDonald / illusion",
            app_ver="01.09",
            lines=[
                XmlPatchLine("bytes32", "0x0075c320", "0x00000001", "Presentation Flip Interval = 1 (60 Hz)"),
            ],
        ),
    ],
    # Driveclub
    "CUSA00552": [
        GoldHenPatchEntry(
            title="Driveclub",
            name="Resolution Patch (1440p Neo Mode)",
            note="Aumenta la resolución interna de renderizado a 2560x1440 en Modo Neo.",
            author="illusion / gasb07 / NEOENABLER",
            app_ver="01.28",
            lines=[
                XmlPatchLine("bytes32", "0x01184718", "0x00000a00", "Render Target Width: 2560"),
                XmlPatchLine("bytes32", "0x0118471c", "0x000005a0", "Render Target Height: 1440"),
            ],
        ),
        GoldHenPatchEntry(
            title="Driveclub",
            name="60 FPS Unlock",
            note="Elimina el bloqueo de 30 FPS para correr a 60 FPS con las 36 CUs de PS4 Pro.",
            author="illusion0001",
            app_ver="01.28",
            lines=[
                XmlPatchLine("bytes", "0x01184725", "48b001", "Force VSync Flip Rate = 1 (60 FPS)"),
            ],
        ),
    ],
    # The Order: 1886
    "CUSA00207": [
        GoldHenPatchEntry(
            title="The Order: 1886",
            name="Resolution Patch (1080p Full Screen 16:9 Neo Mode)",
            note="Elimina las bandas negras (1920x800) y renderiza a 1920x1080 completo con GPU Neo.",
            author="illusion / NEOENABLER",
            app_ver="01.02",
            lines=[
                XmlPatchLine("byte", "0x0084cef5", "0x75", "Bypass Aspect Ratio Lock"),
                XmlPatchLine("bytes32", "0x0084cefd", "0x00000780", "Target Width: 1920"),
                XmlPatchLine("bytes32", "0x0084cf04", "0x00000438", "Target Height: 1080"),
            ],
        ),
        GoldHenPatchEntry(
            title="The Order: 1886",
            name="60 FPS Unlock",
            note="Desbloquea la tasa de cuadros por segundo hasta 60 FPS en Modo Neo.",
            author="illusion0001",
            app_ver="01.02",
            lines=[
                XmlPatchLine("byte", "0x0084cf10", "0x01", "Flip Interval = 1"),
            ],
        ),
    ],
    # Assassin's Creed Unity
    "CUSA00129": [
        GoldHenPatchEntry(
            title="Assassin's Creed Unity",
            name="Resolution Upgrade (900p -> 1080p Native Neo Mode)",
            note="Sube la resolución nativa de 1600x900 a 1920x1080p reales aprovechando la GPU de PS4 Pro.",
            author="NEOENABLER",
            app_ver="01.05",
            lines=[
                XmlPatchLine("bytes32", "0x00a14210", "0x00000780", "Internal Framebuffer Width: 1600 -> 1920"),
                XmlPatchLine("bytes32", "0x00a14218", "0x00000438", "Internal Framebuffer Height: 900 -> 1080"),
            ],
        ),
        GoldHenPatchEntry(
            title="Assassin's Creed Unity",
            name="Resolution Upgrade (900p -> 1440p QHD Neo Mode)",
            note="Sube la resolución interna de 1600x900 a 2560x1440p (Requiere Modo Neo + SDK 4.50).",
            author="NEOENABLER",
            app_ver="01.05",
            lines=[
                XmlPatchLine("bytes32", "0x00a14210", "0x00000a00", "Internal Framebuffer Width: 1600 -> 2560"),
                XmlPatchLine("bytes32", "0x00a14218", "0x000005a0", "Internal Framebuffer Height: 900 -> 1440"),
            ],
        ),
    ],
}

# Mirror Bloodborne and Driveclub regional Title IDs to the same curated entries
for _alias, _base in [
    ("CUSA00207_BB", "CUSA00900"),
    ("CUSA03173", "CUSA00900"),
    ("CUSA00299", "CUSA00900"),
    ("CUSA01363", "CUSA00900"),
    ("CUSA00066", "CUSA00552"),
    ("CUSA00003", "CUSA00552"),
    ("CUSA00631", "CUSA00129"),
    ("CUSA00093", "CUSA00207"),
]:
    if _alias not in CURATED_GAME_PATCHES and _base in CURATED_GAME_PATCHES:
        CURATED_GAME_PATCHES[_alias] = CURATED_GAME_PATCHES[_base]


def build_goldhen_xml(title_id: str, entries: List[GoldHenPatchEntry]) -> str:
    """
    Serializes a list of GoldHenPatchEntry objects into the exact XML schema
    expected by GoldHEN's `game_patch` plugin at `/data/GoldHEN/patches/xml/<CUSAXXXXX>.xml`.
    """
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        "<Patch>",
        "    <TitleID>",
        f"        <ID>{title_id.upper()}</ID>",
        "    </TitleID>",
    ]
    for entry in entries:
        safe_title = entry.title.replace('"', "&quot;").replace("&", "&amp;")
        safe_name = entry.name.replace('"', "&quot;").replace("&", "&amp;")
        safe_note = entry.note.replace('"', "&quot;").replace("&", "&amp;")
        safe_author = entry.author.replace('"', "&quot;").replace("&", "&amp;")
        lines.append(
            f'    <Metadata Title="{safe_title}" Name="{safe_name}" '
            f'Note="{safe_note}" Author="{safe_author}" '
            f'PatchVer="{entry.patch_ver}" AppVer="{entry.app_ver}" AppElf="{entry.app_elf}">'
        )
        lines.append("        <PatchList>")
        for pline in entry.lines:
            if pline.comment:
                lines.append(f"            <!-- {pline.comment} -->")
            lines.append(
                f'            <Line Type="{pline.line_type}" Address="{pline.address}" Value="{pline.value}"/>'
            )
        lines.append("        </PatchList>")
        lines.append("    </Metadata>")
    lines.append("</Patch>")
    return "\n".join(lines) + "\n"


def scan_eboot_for_resolutions(
    eboot_bytes: bytes,
    source_width: int = 1600,
    source_height: int = 900,
    base_vaddr: int = 0x00400000,
    max_distance: int = 32,
) -> List[ResolutionMatch]:
    """
    Scans a PS4 executable (`eboot.bin`) for x86_64 instructions or contiguous 32-bit tables
    that initialize the render target / framebuffer dimensions (source_width, source_height).

    Detects:
    1. x86_64 `MOV reg32, imm32` (`B8..BF <u32>`, `41 B8..BF <u32>`)
    2. x86_64 `MOV r/m32, imm32` (`C7 05 / C7 45 / C7 85 / C7 44 24 ... <u32>`)
    3. Adjacent 32-bit integer pairs (`struct { uint32_t width; uint32_t height; }`)
    where `source_width` and `source_height` appear within `max_distance` bytes of each other.
    """
    w_bytes = struct.pack("<I", source_width)
    h_bytes = struct.pack("<I", source_height)

    matches: List[ResolutionMatch] = []
    seen_pairs = set()

    pos = 0
    data_len = len(eboot_bytes)
    while True:
        w_idx = eboot_bytes.find(w_bytes, pos)
        if w_idx == -1 or w_idx + 4 > data_len:
            break
        pos = w_idx + 1

        # Search for height nearby (either right after width or right before width within max_distance)
        window_start = max(0, w_idx - max_distance)
        window_end = min(data_len, w_idx + 4 + max_distance)
        h_rel = eboot_bytes.find(h_bytes, window_start, window_end)
        if h_rel == -1 or h_rel == w_idx:
            continue

        pair_key = (w_idx, h_rel)
        if pair_key in seen_pairs:
            continue

        # Classify the x86_64 opcode preceding width or check if it's a clean struct pair
        pattern_desc = ""
        if w_idx >= 1 and 0xB8 <= eboot_bytes[w_idx - 1] <= 0xBF:
            reg_idx = eboot_bytes[w_idx - 1] - 0xB8
            reg_names = ["EAX", "ECX", "EDX", "EBX", "ESP", "EBP", "ESI", "EDI"]
            pattern_desc = f"x86_64 MOV {reg_names[reg_idx]}, {source_width} + MOV reg, {source_height}"
        elif w_idx >= 2 and eboot_bytes[w_idx - 2] == 0xC7:
            pattern_desc = f"x86_64 MOV [mem], {source_width} / {source_height}"
        elif w_idx >= 3 and eboot_bytes[w_idx - 3] == 0xC7:
            pattern_desc = f"x86_64 MOV [reg+disp8], {source_width} / {source_height}"
        elif w_idx >= 6 and eboot_bytes[w_idx - 6] == 0xC7:
            pattern_desc = f"x86_64 MOV [rip/reg+disp32], {source_width} / {source_height}"
        elif h_rel == w_idx + 4:
            pattern_desc = f"Tabla Framebuffer struct {{ u32 width={source_width}, u32 height={source_height} }}"

        if pattern_desc:
            seen_pairs.add(pair_key)
            matches.append(
                ResolutionMatch(
                    width_file_offset=w_idx,
                    height_file_offset=h_rel,
                    width_vaddr=base_vaddr + w_idx,
                    height_vaddr=base_vaddr + h_rel,
                    original_width=source_width,
                    original_height=source_height,
                    pattern_description=pattern_desc,
                )
            )

    return matches


def generate_resolution_patch_entries(
    title_id: str,
    title: str,
    app_ver: str,
    matches: List[ResolutionMatch],
    target_width: int,
    target_height: int,
    include_curated: bool = True,
) -> List[GoldHenPatchEntry]:
    """
    Combines any curated patches for `title_id` with dynamically generated resolution
    patch entries from `matches` (upgrading original_width/height -> target_width/height).
    """
    entries: List[GoldHenPatchEntry] = []
    tid_upper = title_id.upper()

    if include_curated and tid_upper in CURATED_GAME_PATCHES:
        for cur_entry in CURATED_GAME_PATCHES[tid_upper]:
            # Clone with the game's actual app_ver so GoldHEN matches the installed version
            entries.append(
                GoldHenPatchEntry(
                    title=title or cur_entry.title,
                    name=cur_entry.name,
                    note=cur_entry.note,
                    author=cur_entry.author,
                    app_ver=app_ver or cur_entry.app_ver,
                    app_elf=cur_entry.app_elf,
                    patch_ver=cur_entry.patch_ver,
                    lines=list(cur_entry.lines),
                )
            )

    if matches:
        orig_w = matches[0].original_width
        orig_h = matches[0].original_height
        patch_lines: List[XmlPatchLine] = []
        for idx, m in enumerate(matches, 1):
            patch_lines.append(
                XmlPatchLine(
                    line_type="bytes32",
                    address=f"0x{m.width_vaddr:08x}",
                    value=f"0x{target_width:08x}",
                    comment=f"Match #{idx} ({m.pattern_description}) Width: {orig_w} -> {target_width}",
                )
            )
            patch_lines.append(
                XmlPatchLine(
                    line_type="bytes32",
                    address=f"0x{m.height_vaddr:08x}",
                    value=f"0x{target_height:08x}",
                    comment=f"Match #{idx} Height: {orig_h} -> {target_height}",
                )
            )

        entries.append(
            GoldHenPatchEntry(
                title=title,
                name=f"NEOENABLER Resolution Boost ({orig_w}x{orig_h} -> {target_width}x{target_height})",
                note=(
                    f"Reemplaza la resolución interna {orig_w}x{orig_h} por {target_width}x{target_height} "
                    "para aprovechar las 36 CUs @ 911 MHz del Modo Neo."
                ),
                author="NEOENABLER Auto-Scanner",
                app_ver=app_ver,
                lines=patch_lines,
            )
        )

    return entries


def patch_eboot_resolution_inplace(
    eboot_bytes: bytes,
    matches: List[ResolutionMatch],
    target_width: int,
    target_height: int,
) -> bytes:
    """Directly patches the discovered width/height immediates inside a decrypted eboot.bin."""
    buf = bytearray(eboot_bytes)
    w_packed = struct.pack("<I", target_width)
    h_packed = struct.pack("<I", target_height)
    for m in matches:
        buf[m.width_file_offset : m.width_file_offset + 4] = w_packed
        buf[m.height_file_offset : m.height_file_offset + 4] = h_packed
    return bytes(buf)


def scan_eboot_for_framerate_lock(
    eboot_bytes: bytes,
    base_vaddr: int = 0x00400000,
) -> List[FramerateMatch]:
    """
    Scans a PS4 executable (`eboot.bin`) for x86_64 `sceVideoOutSetFlipRate(handle, rate)`
    setup instructions that lock the game to 30 FPS (`rate = 1` or `rate = 2` in `ESI`):
    - `BE 01 00 00 00` (`MOV ESI, 1`) followed within 16 bytes by `E8 <rel32>` (`CALL`) or `FF 15 <rel32>`
    - `BE 02 00 00 00` (`MOV ESI, 2`) followed within 16 bytes by `E8 <rel32>` (`CALL`) or `FF 15 <rel32>`
    Patches `MOV ESI, 1/2` -> `31 F6 90 90 90` (`XOR ESI, ESI; NOP; NOP; NOP` -> rate = 0 = 60 FPS unlocked).
    """
    matches: List[FramerateMatch] = []
    data_len = len(eboot_bytes)

    for rate_val, label in [(1, "30 FPS FlipRate=1"), (2, "30/20 FPS FlipRate=2")]:
        needle = b"\xbe" + struct.pack("<I", rate_val)  # BE 01 00 00 00 or BE 02 00 00 00
        pos = 0
        while True:
            idx = eboot_bytes.find(needle, pos)
            if idx == -1 or idx + 10 > data_len:
                break
            pos = idx + 1

            # Check if a CALL instruction (0xE8 rel32 or 0xFF 0x15 rip-relative) follows within 16 bytes
            window = eboot_bytes[idx + 5 : min(data_len, idx + 21)]
            has_call = (b"\xe8" in window) or (b"\xff\x15" in window)
            if not has_call:
                continue

            matches.append(
                FramerateMatch(
                    file_offset=idx,
                    vaddr=base_vaddr + idx,
                    original_bytes_hex=needle.hex(),
                    patched_bytes_hex="31f6909090",  # xor esi, esi (rate=0 -> 60 FPS); 3x nop
                    pattern_description=f"x86_64 MOV ESI, {rate_val} ({label}) -> XOR ESI, ESI (60 FPS)",
                )
            )

    return matches


def generate_framerate_patch_entry(
    title: str,
    app_ver: str,
    fps_matches: List[FramerateMatch],
) -> Optional[GoldHenPatchEntry]:
    """Generates a GoldHEN XML patch entry unlocking 60 FPS from discovered `sceVideoOutSetFlipRate` matches."""
    if not fps_matches:
        return None
    lines: List[XmlPatchLine] = []
    for idx, m in enumerate(fps_matches, 1):
        lines.append(
            XmlPatchLine(
                line_type="bytes",
                address=f"0x{m.vaddr:08x}",
                value=m.patched_bytes_hex,
                comment=f"60 FPS Unlock #{idx}: {m.pattern_description}",
            )
        )
    return GoldHenPatchEntry(
        title=title,
        name="NEOENABLER 60 FPS Unlock (sceVideoOutSetFlipRate = 0)",
        note="Fuerza FlipRate = 0 (60 Hz) para liberar el límite de 30 FPS aprovechando el Modo Neo.",
        author="NEOENABLER Auto-Scanner",
        app_ver=app_ver,
        lines=lines,
    )


def patch_eboot_framerate_inplace(
    eboot_bytes: bytes,
    fps_matches: List[FramerateMatch],
) -> bytes:
    """Directly patches `MOV ESI, 1/2` to `XOR ESI, ESI; NOP; NOP; NOP` (`31 F6 90 90 90`) in eboot.bin."""
    buf = bytearray(eboot_bytes)
    replacement = bytes.fromhex("31f6909090")
    for m in fps_matches:
        buf[m.file_offset : m.file_offset + 5] = replacement
    return bytes(buf)


def auto_detect_all_resolutions_in_eboot(
    eboot_bytes: bytes,
    base_vaddr: int = 0x00400000,
) -> Dict[str, List[ResolutionMatch]]:
    """
    Real-time multi-resolution scanner: automatically probes the game's eboot.bin
    for ALL standard PS4 rendering resolutions (720p, 792p, 800p, 900p, 1080p)
    so the user doesn't even need to know what base resolution the game runs at.
    """
    results: Dict[str, List[ResolutionMatch]] = {}
    for label, (w, h) in SOURCE_RESOLUTIONS.items():
        found = scan_eboot_for_resolutions(eboot_bytes, source_width=w, source_height=h, base_vaddr=base_vaddr)
        if found:
            results[label] = found
    return results


def scan_eboot_for_deltatime_constants(
    eboot_bytes: bytes,
    base_vaddr: int = 0x00400000,
) -> List[LiveAnalyzedCandidate]:
    """
    Scans a PS4 executable (`eboot.bin`) for 30 FPS fixed timestep / DeltaTime constants:
    - `0.033333335f` (1/30 sec = `0x3D088889` / `89 88 08 3D` in IEEE-754 float32)
      adjacent to `30.0f` (`0x41F00000`) or preceded by SSE scalar load (`F3 0F 10` / `C7`).
      Upgrades to `0.016666668f` (1/60 sec = `0x3C888889`) for proper 60 FPS game physics speed.
    """
    candidates: List[LiveAnalyzedCandidate] = []
    dt_30_bytes = struct.pack("<f", 1.0 / 30.0)  # 89 88 08 3d
    dt_60_hex = f"0x{struct.unpack('<I', struct.pack('<f', 1.0 / 60.0))[0]:08x}"  # 0x3c888889
    fps_30_bytes = struct.pack("<f", 30.0)       # 00 00 f0 41

    pos = 0
    data_len = len(eboot_bytes)
    while True:
        idx = eboot_bytes.find(dt_30_bytes, pos)
        if idx == -1 or idx + 4 > data_len:
            break
        pos = idx + 4

        # Validate context: nearby 30.0f constant or SSE MOVSS/MULSS/COMISS instruction within 32 bytes
        win_start = max(0, idx - 24)
        win_end = min(data_len, idx + 24)
        window = eboot_bytes[win_start:win_end]
        has_context = (fps_30_bytes in window) or (b"\xf3\x0f\x10" in window) or (b"\xf3\x0f\x59" in window)
        if not has_context:
            continue

        candidates.append(
            LiveAnalyzedCandidate(
                category="DeltaTime (30->60Hz)",
                description="Constante Timestep 30 FPS (0.0333333f -> 0.0166667f para físicas a 60 FPS)",
                file_offset=idx,
                vaddr=base_vaddr + idx,
                patch_type="bytes32",
                original_value_str="0x3d088889 (1/30s)",
                target_value_str=dt_60_hex,
                enabled_by_default=True,
            )
        )

    return candidates


def analyze_eboot_realtime(
    eboot_bytes: bytes,
    target_width: int = 2560,
    target_height: int = 1440,
    source_filter: Optional[Tuple[int, int]] = None,
    base_vaddr: int = 0x00400000,
) -> List[LiveAnalyzedCandidate]:
    """
    Complete Real-Time Dynamic Patch Analyzer for ANY game's eboot.bin (no database required):
    1. Automatically scans for all base resolutions (or `source_filter` if specified) and builds
       width/height upgrade candidates to (`target_width`, `target_height`).
    2. Scans for `sceVideoOutSetFlipRate` 30 FPS locks (`MOV ESI, 1/2` before `CALL`) -> `rate = 0` (60 FPS).
    3. Scans for 30 FPS DeltaTime float constants (`1/30s` = `0.0333333f`) -> `1/60s` (`0.0166667f`).
    """
    candidates: List[LiveAnalyzedCandidate] = []

    # 1. Resolution candidates
    if source_filter is not None:
        res_groups = {f"{source_filter[0]}x{source_filter[1]}": scan_eboot_for_resolutions(
            eboot_bytes, source_filter[0], source_filter[1], base_vaddr=base_vaddr
        )}
    else:
        res_groups = auto_detect_all_resolutions_in_eboot(eboot_bytes, base_vaddr=base_vaddr)

    for _label, matches in res_groups.items():
        for m in matches:
            if m.original_width == target_width and m.original_height == target_height:
                continue
            candidates.append(
                LiveAnalyzedCandidate(
                    category="Resolución",
                    description=f"{m.pattern_description} ({m.original_width}x{m.original_height} -> {target_width}x{target_height})",
                    file_offset=m.width_file_offset,
                    vaddr=m.width_vaddr,
                    patch_type="bytes32",
                    original_value_str=f"{m.original_width}x{m.original_height}",
                    target_value_str=f"0x{target_width:08x}",
                    extra_offset=m.height_file_offset,
                    extra_vaddr=m.height_vaddr,
                    extra_target_str=f"0x{target_height:08x}",
                    enabled_by_default=True,
                )
            )

    # 2. Framerate FlipRate candidates (sceVideoOutSetFlipRate)
    fps_matches = scan_eboot_for_framerate_lock(eboot_bytes, base_vaddr=base_vaddr)
    for fm in fps_matches:
        candidates.append(
            LiveAnalyzedCandidate(
                category="Framerate (FlipRate)",
                description=fm.pattern_description,
                file_offset=fm.file_offset,
                vaddr=fm.vaddr,
                patch_type="bytes",
                original_value_str=fm.original_bytes_hex,
                target_value_str=fm.patched_bytes_hex,
                enabled_by_default=True,
            )
        )

    # 3. Fixed DeltaTime 30 FPS -> 60 FPS float candidates
    dt_candidates = scan_eboot_for_deltatime_constants(eboot_bytes, base_vaddr=base_vaddr)
    candidates.extend(dt_candidates)

    return candidates


def build_xml_from_live_candidates(
    title_id: str,
    title: str,
    app_ver: str,
    selected_candidates: List[LiveAnalyzedCandidate],
    include_curated: bool = False,
) -> str:
    """
    Builds a complete GoldHEN XML patch file from the user-checked real-time analyzed candidates.
    Groups lines cleanly by category (Resolution, Framerate FlipRate, DeltaTime) so the user can
    toggle each patch individually inside GoldHEN's Cheat/Patch Menu on the PS4!
    """
    entries: List[GoldHenPatchEntry] = []
    tid_upper = title_id.upper()

    if include_curated and tid_upper in CURATED_GAME_PATCHES:
        for cur in CURATED_GAME_PATCHES[tid_upper]:
            entries.append(
                GoldHenPatchEntry(
                    title=title or cur.title,
                    name=cur.name,
                    note=cur.note,
                    author=cur.author,
                    app_ver=app_ver or cur.app_ver,
                    lines=list(cur.lines),
                )
            )

    by_cat: Dict[str, List[LiveAnalyzedCandidate]] = {}
    for c in selected_candidates:
        by_cat.setdefault(c.category, []).append(c)

    for cat, cands in by_cat.items():
        xml_lines: List[XmlPatchLine] = []
        for c in cands:
            xml_lines.append(
                XmlPatchLine(
                    line_type=c.patch_type,
                    address=f"0x{c.vaddr:08x}",
                    value=c.target_value_str,
                    comment=c.description,
                )
            )
            if c.extra_vaddr is not None and c.extra_target_str is not None:
                xml_lines.append(
                    XmlPatchLine(
                        line_type=c.patch_type,
                        address=f"0x{c.extra_vaddr:08x}",
                        value=c.extra_target_str,
                        comment=f"Height -> {c.extra_target_str}",
                    )
                )
        entries.append(
            GoldHenPatchEntry(
                title=title,
                name=f"NEOENABLER Live Generator - {cat}",
                note=f"Generado en tiempo real analizando el eboot.bin de {title} ({title_id}).",
                author="NEOENABLER Real-Time Engine",
                app_ver=app_ver,
                lines=xml_lines,
            )
        )

    return build_goldhen_xml(title_id, entries)


def apply_live_candidates_to_eboot(
    eboot_bytes: bytes,
    selected_candidates: List[LiveAnalyzedCandidate],
) -> bytes:
    """Applies the selected real-time candidates directly into the eboot.bin bytes."""
    buf = bytearray(eboot_bytes)
    for c in selected_candidates:
        if c.patch_type == "bytes32":
            val = int(c.target_value_str, 16)
            buf[c.file_offset : c.file_offset + 4] = struct.pack("<I", val)
            if c.extra_offset is not None and c.extra_target_str is not None:
                val2 = int(c.extra_target_str, 16)
                buf[c.extra_offset : c.extra_offset + 4] = struct.pack("<I", val2)
        elif c.patch_type == "bytes":
            raw_patch = bytes.fromhex(c.target_value_str)
            buf[c.file_offset : c.file_offset + len(raw_patch)] = raw_patch
    return bytes(buf)
