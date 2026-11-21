"""
SFO Parser & Neo Mode Patcher for PlayStation 4 (Orbis) PARAM.SFO files.
Supports reading all SFO parameters, checking/toggling the PS4 Pro (Neo Mode)
flag in ATTRIBUTE (bit 23: 0x00800000), and rebuilding valid binary SFO files.
"""

from __future__ import annotations
import struct
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union


SFO_MAGIC = b"\x00PSF"
SFO_VERSION_DEFAULT = 0x00000101

FMT_UTF8_SPECIAL = 0x0004  # Unterminated / raw UTF-8 or binary
FMT_UTF8 = 0x0204          # Null-terminated UTF-8 string
FMT_INT32 = 0x0404         # 32-bit unsigned integer (little-endian)

# Bit 23 in ATTRIBUTE: "The application supports NEO mode (for PlayStation(R)4 Pro)"
NEO_MODE_BIT = 0x00800000

# Bit 16 in ATTRIBUTE: "CPU Mode (7 CPU cores unlocked for application)"
SEVEN_CPU_CORES_BIT = 0x00010000

# Other known PS4 ATTRIBUTE flags for diagnostics / reference
KNOWN_ATTRIBUTE_BITS: Dict[int, str] = {
    0x00000001: "Initial User Logout Aware",
    0x00000002: "Enter Button Assignment (Common Dialog)",
    0x00000004: "Menu for Warning Dialog in PS Vita Remote Play",
    0x00000008: "Stereoscopic 3D",
    0x00000010: "Share Button Hold Behavior",
    0x00000020: "Share Menu Assignment Behavior",
    0x00000100: " Suspend when Output Resolution Changes",
    0x00000200: "HDCP Required",
    0x00000400: "HDCP Disabled for non-game",
    0x00008000: "PS VR Support (PlayStation VR)",
    0x00010000: "CPU Mode (7 CPU cores)",
    0x00020000: "PS VR Required",
    0x00800000: "NEO Mode Support (PS4 Pro 36 CUs @ 911 MHz + +512MB RAM)",
    0x02000000: "HDR Support",
    0x10000000: "Display Location",
    0x20000000: "Common Dialog Overwrite",
}


@dataclass
class SfoEntry:
    key: str
    fmt: int
    length: int
    max_length: int
    raw_value: bytes

    @property
    def value(self) -> Union[int, str, bytes]:
        if self.fmt == FMT_INT32 and len(self.raw_value) >= 4:
            return struct.unpack("<I", self.raw_value[:4])[0]
        elif self.fmt == FMT_UTF8:
            # Strip trailing null bytes
            return self.raw_value[:self.length].rstrip(b"\x00").decode("utf-8", errors="replace")
        elif self.fmt == FMT_UTF8_SPECIAL:
            try:
                return self.raw_value[:self.length].rstrip(b"\x00").decode("utf-8")
            except UnicodeDecodeError:
                return self.raw_value[:self.length]
        return self.raw_value[:self.length]

    def set_int32(self, val: int) -> None:
        if self.fmt != FMT_INT32:
            raise ValueError(f"Entry '{self.key}' is not an INT32 parameter (fmt=0x{self.fmt:04X})")
        self.raw_value = struct.pack("<I", val & 0xFFFFFFFF)
        self.length = 4
        if self.max_length < 4:
            self.max_length = 4

    def set_utf8(self, val: str) -> None:
        encoded = val.encode("utf-8") + b"\x00"
        if len(encoded) > self.max_length:
            # Expand max_length aligned to 4 bytes
            self.max_length = (len(encoded) + 3) & ~3
        self.length = len(encoded)
        self.raw_value = encoded.ljust(self.max_length, b"\x00")


class SfoFile:
    """Represents a parsed PlayStation 4 PARAM.SFO file."""

    def __init__(self, version: int = SFO_VERSION_DEFAULT) -> None:
        self.version: int = version
        self.entries: List[SfoEntry] = []
        self._original_bytes: Optional[bytes] = None
        self._entry_data_offsets: Dict[str, int] = {}

    @classmethod
    def from_bytes(cls, data: bytes) -> "SfoFile":
        if len(data) < 20:
            raise ValueError("Data is too small to be a valid PARAM.SFO file (< 20 bytes).")
        magic, version, key_table_offset, data_table_offset, count = struct.unpack("<4sIIII", data[:20])
        if magic != SFO_MAGIC:
            raise ValueError(f"Invalid PARAM.SFO magic bytes: {magic!r} (expected {SFO_MAGIC!r}).")

        sfo = cls(version=version)
        sfo._original_bytes = bytes(data)

        idx_offset = 20
        for i in range(count):
            if idx_offset + 16 > len(data):
                raise ValueError(f"Truncated index table at entry {i}.")
            key_off, fmt, length, max_len, data_off = struct.unpack(
                "<HHIII", data[idx_offset : idx_offset + 16]
            )
            idx_offset += 16

            abs_key_start = key_table_offset + key_off
            abs_key_end = data.find(b"\x00", abs_key_start)
            if abs_key_end == -1:
                raise ValueError(f"Unterminated key string at offset {abs_key_start}.")
            key = data[abs_key_start:abs_key_end].decode("utf-8", errors="replace")

            abs_data_start = data_table_offset + data_off
            abs_data_end = abs_data_start + max_len
            if abs_data_end > len(data):
                # Fallback to actual length if max_len reaches past EOF
                abs_data_end = min(len(data), abs_data_start + length)
            raw_val = data[abs_data_start:abs_data_end]

            sfo.entries.append(
                SfoEntry(
                    key=key,
                    fmt=fmt,
                    length=length,
                    max_length=max_len,
                    raw_value=raw_val,
                )
            )
            sfo._entry_data_offsets[key] = abs_data_start

        return sfo

    @classmethod
    def from_file(cls, path: str) -> "SfoFile":
        with open(path, "rb") as f:
            return cls.from_bytes(f.read())

    def get_entry(self, key: str) -> Optional[SfoEntry]:
        for entry in self.entries:
            if entry.key == key:
                return entry
        return None

    def get(self, key: str, default: Union[int, str, bytes, None] = None) -> Union[int, str, bytes, None]:
        entry = self.get_entry(key)
        return entry.value if entry is not None else default

    @property
    def title_id(self) -> str:
        return str(self.get("TITLE_ID", "UNKNOWN"))

    @property
    def title(self) -> str:
        return str(self.get("TITLE", "Unknown Title"))

    @property
    def app_ver(self) -> str:
        return str(self.get("APP_VER", self.get("VERSION", "01.00")))

    @property
    def category(self) -> str:
        return str(self.get("CATEGORY", "gd"))

    @property
    def content_id(self) -> str:
        return str(self.get("CONTENT_ID", ""))

    @property
    def system_ver(self) -> int:
        val = self.get("SYSTEM_VER", 0)
        return int(val) if isinstance(val, int) else 0

    @system_ver.setter
    def system_ver(self, value: int) -> None:
        entry = self.get_entry("SYSTEM_VER")
        if entry is not None:
            entry.set_int32(value)
        else:
            self.entries.append(
                SfoEntry(
                    key="SYSTEM_VER",
                    fmt=FMT_INT32,
                    length=4,
                    max_length=4,
                    raw_value=struct.pack("<I", value & 0xFFFFFFFF),
                )
            )
            self.entries.sort(key=lambda e: e.key)
            self._original_bytes = None

    @property
    def is_old_sdk(self) -> bool:
        """Returns True if SYSTEM_VER is older than FW 4.00 (0x04000000), predating PS4 Pro (Neo)."""
        return 0 < self.system_ver < 0x04000000

    @property
    def system_ver_hex(self) -> str:
        sys_ver = self.system_ver
        if sys_ver > 0:
            major = (sys_ver >> 24) & 0xFF
            minor = (sys_ver >> 16) & 0xFF
            return f"{major:X}.{minor:02X} (0x{sys_ver:08X})"
        return "0.00"

    @property
    def attribute(self) -> int:
        val = self.get("ATTRIBUTE", 0)
        return int(val) if isinstance(val, int) else 0

    @attribute.setter
    def attribute(self, value: int) -> None:
        entry = self.get_entry("ATTRIBUTE")
        if entry is not None:
            entry.set_int32(value)
        else:
            self.entries.append(
                SfoEntry(
                    key="ATTRIBUTE",
                    fmt=FMT_INT32,
                    length=4,
                    max_length=4,
                    raw_value=struct.pack("<I", value & 0xFFFFFFFF),
                )
            )
            self.entries.sort(key=lambda e: e.key)
            self._original_bytes = None  # Structure changed, cannot patch in-place

    @property
    def is_neo_enabled(self) -> bool:
        return bool(self.attribute & NEO_MODE_BIT)

    @property
    def is_7cpu_enabled(self) -> bool:
        return bool(self.attribute & SEVEN_CPU_CORES_BIT)

    def set_neo_mode(self, enabled: bool, unlock_7cpu: bool = False) -> int:
        """Sets or clears the Neo Mode flag (0x00800000) and optionally 7-CPU-Core bit (0x00010000) in ATTRIBUTE."""
        current = self.attribute
        if enabled:
            new_val = current | NEO_MODE_BIT
            if unlock_7cpu:
                new_val |= SEVEN_CPU_CORES_BIT
        else:
            new_val = current & ~NEO_MODE_BIT
        self.attribute = new_val
        return new_val

    def get_active_attribute_flags(self) -> List[Tuple[int, str]]:
        """Returns a list of (bit_mask, description) active in ATTRIBUTE."""
        attr = self.attribute
        active: List[Tuple[int, str]] = []
        for bit, desc in sorted(KNOWN_ATTRIBUTE_BITS.items()):
            if attr & bit:
                active.append((bit, desc))
        return active

    def to_bytes(self, prefer_inplace: bool = True) -> bytes:
        """
        Serializes the SFO file back to binary.
        If prefer_inplace=True and the file came from existing bytes where only INT32
        values (like ATTRIBUTE) were modified, patches the exact bytes in-place to preserve
        any proprietary padding/layout. Otherwise rebuilds the full SFO table structure.
        """
        if prefer_inplace and self._original_bytes is not None:
            buf = bytearray(self._original_bytes)
            can_inplace = True
            for entry in self.entries:
                if entry.key not in self._entry_data_offsets:
                    can_inplace = False
                    break
                offset = self._entry_data_offsets[entry.key]
                if len(entry.raw_value) > entry.max_length or offset + len(entry.raw_value) > len(buf):
                    can_inplace = False
                    break
                buf[offset : offset + len(entry.raw_value)] = entry.raw_value
            if can_inplace:
                return bytes(buf)

        # Full SFO rebuild (keys must be sorted lexicographically per Sony SFO specification)
        sorted_entries = sorted(self.entries, key=lambda e: e.key)
        count = len(sorted_entries)
        header_size = 20
        index_table_size = count * 16

        key_table = bytearray()
        data_table = bytearray()
        index_records = bytearray()

        for entry in sorted_entries:
            key_offset = len(key_table)
            key_bytes = entry.key.encode("utf-8") + b"\x00"
            key_table.extend(key_bytes)

            data_offset = len(data_table)
            raw_padded = entry.raw_value[: entry.max_length].ljust(entry.max_length, b"\x00")
            data_table.extend(raw_padded)

            index_records.extend(
                struct.pack(
                    "<HHIII",
                    key_offset,
                    entry.fmt,
                    entry.length,
                    entry.max_length,
                    data_offset,
                )
            )

        # Align key_table to 4-byte boundary
        while len(key_table) % 4 != 0:
            key_table.append(0)

        key_table_offset = header_size + index_table_size
        data_table_offset = key_table_offset + len(key_table)

        header = struct.pack(
            "<4sIIII",
            SFO_MAGIC,
            self.version,
            key_table_offset,
            data_table_offset,
            count,
        )
        return header + bytes(index_records) + bytes(key_table) + bytes(data_table)

    def save(self, path: str, prefer_inplace: bool = True) -> None:
        data = self.to_bytes(prefer_inplace=prefer_inplace)
        with open(path, "wb") as f:
            f.write(data)


def create_sample_sfo(
    title_id: str = "CUSA00900",
    title: str = "Bloodborne",
    app_ver: str = "01.09",
    category: str = "gd",
    attribute: int = 0x00000002,
    system_ver: int = 0x04500000,
) -> SfoFile:
    """Creates a realistic PS4 PARAM.SFO instance for testing or offline template generation."""
    sfo = SfoFile()
    content_id = f"UP9000-{title_id}_00-0000000000000001"
    sfo.entries = [
        SfoEntry("APP_TYPE", FMT_INT32, 4, 4, struct.pack("<I", 1)),
        SfoEntry("APP_VER", FMT_UTF8, len(app_ver) + 1, 8, (app_ver.encode() + b"\x00").ljust(8, b"\x00")),
        SfoEntry("ATTRIBUTE", FMT_INT32, 4, 4, struct.pack("<I", attribute)),
        SfoEntry("ATTRIBUTE2", FMT_INT32, 4, 4, struct.pack("<I", 0)),
        SfoEntry("CATEGORY", FMT_UTF8, len(category) + 1, 4, (category.encode() + b"\x00").ljust(4, b"\x00")),
        SfoEntry("CONTENT_ID", FMT_UTF8, len(content_id) + 1, 48, (content_id.encode() + b"\x00").ljust(48, b"\x00")),
        SfoEntry("SYSTEM_VER", FMT_INT32, 4, 4, struct.pack("<I", system_ver)),
        SfoEntry("TITLE", FMT_UTF8, len(title.encode()) + 1, 128, (title.encode() + b"\x00").ljust(128, b"\x00")),
        SfoEntry("TITLE_ID", FMT_UTF8, len(title_id) + 1, 12, (title_id.encode() + b"\x00").ljust(12, b"\x00")),
        SfoEntry("VERSION", FMT_UTF8, 6, 8, b"01.00\x00\x00\x00"),
    ]
    # Re-parse from serialized bytes so _original_bytes and _entry_data_offsets are populated
    return SfoFile.from_bytes(sfo.to_bytes(prefer_inplace=False))
