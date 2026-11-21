# ⚡ NEOENABLER — Desbloqueador de Modo Neo (PS4 Pro) para GoldHEN

**NEOENABLER** es una herramienta de escritorio (con interfaz gráfica y modo CLI) diseñada para consolas **PS4 Pro con GoldHEN**. Permite activar o desactivar el **Modo Neo** (`0x00800000`, bit 23 del parámetro `ATTRIBUTE` en `param.sfo`) en juegos base que nunca recibieron un parche oficial para PS4 Pro.

---

## 🚀 ¿Qué logra activar el Modo Neo en un juego sin parche Pro?

En una PS4 Pro, cuando ejecutas un juego sin parche Pro:
* **Modo Base normal:** La consola apaga la mitad de la GPU (ejecuta solo 18 CUs a 800 MHz en lugar de 36 CUs) para imitar a una PS4 Fat/Slim.
* **Modo Boost de sistema:** Sube la frecuencia de reloj a 911 MHz, pero **mantiene apagadas las otras 18 CUs** de la GPU y no asigna la memoria extra de PS4 Pro.
* **Modo Neo completo (activado con NEOENABLER):** Al activar el bit 23 (`0x00800000`) en el `ATTRIBUTE` del `param.sfo` y sincronizar `app.db`, el kernel de la PS4 Pro inicia el juego con el perfil completo de hardware Neo:
  * **100% de la GPU desbloqueada:** 36 Compute Units a 911 MHz (4.20 TFLOPS en vez de 1.84 TFLOPS).
  * **CPU a 2.13 GHz** y ancho de banda de memoria completo (218 GB/s).
  * **+512 MB de memoria RAM adicional** disponibles para la aplicación.
  * Ideal para mantener **FPS estables** o combinarlo con **parches de 60 FPS / resolución de GoldHEN Cheat Manager** (por ejemplo, en *Bloodborne*, *Driveclub*, *Assassin's Creed Unity*, etc.).

---

## 🛠️ Características principales

1. **Inyección de Modo Neo en Juegos con SDK Antiguo (`< FW 4.00 -> 4.50`):**
   * Los juegos compilados antes de que existiera la PS4 Pro (`SDK < 0x04000000`, ej. *Driveclub*, *Bloodborne* base, *AC Unity*, *The Order: 1886*) suelen crashear con error `CE-34878-0` si solo activas el bit Neo en `param.sfo`, porque el driver `libSceGnmDriverForNeoMode.sprx` verifica el `sdk_version` en la cabecera **`ORBI`** (`OrbisProcParam` en `PT_SCE_PROCPARAM`) del `eboot.bin` y `SYSTEM_VER` en `param.sfo`.
   * **NEOENABLER v2.0** resuelve esto de tres formas complementarias:
     * **En `eboot.bin` (`eboot_patcher.py`):** Localiza las estructuras `OrbisProcParam` (`ORBI`) y `OrbisModuleParam` (`0x3C13F4BF`) en binarios ELF64 o FSELF (`0x1D3D154F`) y eleva su `sdk_version` a `0x04500001` (SDK 4.50 Neo).
     * **En `param.sfo` y `app.db` (`sfo_parser.py` / `ps4_ftp.py`):** Eleva `SYSTEM_VER` a `0x04500000` junto con el bit 23 (`0x00800000`) de `ATTRIBUTE`.
     * **En RAM mediante Plugin de GoldHEN (`goldhen_plugin/neoenabler_sdk.c`):** Incluye el código fuente de un plugin `.prx` para GoldHEN que parchea `OrbisProcParam->sdk_version` en memoria al arrancar el juego y hookea `sceKernelGetCompiledSdkVersion()`.
2. **Escaneo directo por FTP (GoldHEN puerto 2121):**
   * Escanea automáticamente `/user/appmeta`, `/system_data/priv/appmeta` y `/mnt/sandbox/pfsmnt`.
   * Envía automáticamente el comando `SITE MTRW` para habilitar permisos de lectura/escritura en particiones del sistema si es necesario.
3. **Copia de Seguridad Automática (Backups):**
   * Antes de tocar un solo byte, guarda el `param.sfo` y `eboot.bin` originales intactos en la carpeta `backups/<CUSAXXXXX>/` junto con un `manifest.json`.
   * Puedes revertir cualquier juego a su estado original con un solo clic en **"⏪ Restaurar Original"**.
4. **Sincronización con `app.db` (`tbl_appinfo`):**
   * Actualiza opcionalmente `ATTRIBUTE` y `SYSTEM_VER` en `/system_data/priv/mms/app.db` (haciendo backup previo de `app.db`) para que el sistema operativo de la PS4 aplique el cambio sin necesidad de reinstalar el FPKG.
5. **Escalador de Resolución (1080p / 1440p / 1620p / 4K) & 60 FPS para GoldHEN (`resolution_patcher.py`):**
   * Incluye perfiles verificados de aumento de resolución y 60 FPS para clásicos sin parche Pro (*Bloodborne*, *Driveclub*, *The Order: 1886*, *Assassin's Creed Unity*).
   * Incluye un **Escáner Heurístico Universal de `eboot.bin`** que localiza las instrucciones `MOV` x86_64 donde el juego inicializa el ancho y alto del framebuffer (`720p`, `900p`, `1080p`) y genera o sube por FTP el parche `/data/GoldHEN/patches/xml/<CUSAXXXXX>.xml` (o parcha el `eboot.bin` directamente).
6. **Modo Local / Offline:**
   * Puedes abrir y parchear cualquier archivo `param.sfo` y `eboot.bin` sueltos en tu PC antes de empaquetar un FPKG.

---

## ▶️ Cómo usarlo

### Interfaz Gráfica (GUI)
Haz doble clic en **`Iniciar_NEOENABLER.bat`** o ejecuta en terminal:
```powershell
python neoenabler.py
```

1. En tu PS4 con **GoldHEN**, activa el **FTP Server** (por defecto usa el puerto `2121`).
2. Escribe la dirección IP de tu PS4 en NEOENABLER y pulsa **"🔌 Conectar y Escanear PS4"**.
3. Selecciona cualquier juego en **Modo Base** y haz clic en **"🚀 ACTIVAR MODO NEO (PS4 PRO)"** (o haz doble clic sobre el juego).
4. Reinicia la PS4 (o cierra y vuelve a abrir el juego) para que el kernel cargue el nuevo perfil de hardware.

### Línea de Comandos (CLI)
También puedes usarlo desde terminal o scripts:
```powershell
# Inspeccionar un param.sfo local
python neoenabler.py --file ruta\a\param.sfo

# Activar Modo Neo en un param.sfo local
python neoenabler.py --file ruta\a\param.sfo --enable

# Restaurar el backup original
python neoenabler.py --file ruta\a\param.sfo --restore

# Activar Modo Neo remotamente por FTP en un Title ID específico
python neoenabler.py --ftp-host 192.168.1.100 --ftp-port 2121 --title-id CUSA00900 --enable
```
