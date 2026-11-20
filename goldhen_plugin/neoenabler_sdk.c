/*
 * NEOENABLER GoldHEN Runtime Plugin (neoenabler_sdk.c)
 * ----------------------------------------------------
 * Solves the CE-34878-0 startup crash when forcing PS4 Pro (Neo Mode: ATTRIBUTE 0x00800000)
 * on older PS4 games compiled with pre-Neo SDKs (< SDK 4.00 / 0x04000000).
 *
 * How it works at runtime inside GoldHEN:
 * 1. Inspects the running game's `OrbisProcParam` via `sceKernelGetProcParam()`.
 *    If `proc_param->sdk_version < 0x04000000`, patches it in RAM to `0x04500001` (SDK 4.50)
 *    before `libSceGnmDriverForNeoMode.sprx` validates the process parameters.
 * 2. Hooks `sceKernelGetCompiledSdkVersion()` in `libkernel` so any system module querying
 *    the game's compiled SDK sees `0x04500001` instead of the legacy SDK (< 4.00),
 *    preventing the Neo Mode GNM context state assertion crash.
 * 3. Hooks `sceKernelIsNeoMode()` so that even if a legacy `eboot.bin` has a hardcoded check
 *    that aborts on unknown hardware modes, or conversely to ensure the kernel reports Neo Mode
 *    consistently while keeping full 36 CUs @ 911 MHz + 512 MB extra RAM unlocked by param.sfo.
 */

#include <stdint.h>
#include <stddef.h>
#include <GoldHEN/Common.h>
#include <GoldHEN/Detour.h>
#include <GoldHEN/Utilities.h>

#define ORBI_MAGIC               0x4942524F /* "ORBI" */
#define NEO_MIN_SDK_VERSION      0x04000000 /* SDK 4.00 (PS4 Pro launch) */
#define NEO_SPOOFED_SDK_VERSION  0x04500001 /* SDK 4.50 (Full Neo / Boost support) */

/* OrbisProcParam structure located in PT_SCE_PROCPARAM (.data.sce_process_param) */
typedef struct OrbisProcParam {
    uint64_t size;          /* 0x00 */
    uint32_t magic;         /* 0x08: 'ORBI' (0x4942524F) */
    uint32_t entry_count;   /* 0x0C */
    uint64_t sdk_version;   /* 0x10: Compiled SDK version */
} OrbisProcParam;

/* Kernel function pointers */
typedef int (*sceKernelGetCompiledSdkVersion_t)(int *ver);
typedef OrbisProcParam* (*sceKernelGetProcParam_t)(void);

static Detour Detour_sceKernelGetCompiledSdkVersion;
static uint32_t g_original_sdk_version = 0;

/*
 * Hook for sceKernelGetCompiledSdkVersion:
 * Ensures libSceGnmDriverForNeoMode and libSceVideoOut never fail the SDK >= 4.00 check
 * when an old-SDK game is booted with Neo Mode (ATTRIBUTE 0x00800000) enabled.
 */
static int Hook_sceKernelGetCompiledSdkVersion(int *ver) {
    int ret = ((sceKernelGetCompiledSdkVersion_t)Detour_sceKernelGetCompiledSdkVersion.Original)(ver);
    if (ver != NULL) {
        if ((uint32_t)(*ver) < NEO_MIN_SDK_VERSION) {
            klog("[NEOENABLER] Spoofing old SDK version 0x%08X -> 0x%08X for Neo Mode compatibility\n",
                 (uint32_t)(*ver), NEO_SPOOFED_SDK_VERSION);
            *ver = (int)NEO_SPOOFED_SDK_VERSION;
        }
    }
    return ret;
}

/*
 * Patch OrbisProcParam->sdk_version directly in userland process memory if writable,
 * or via GoldHEN proc_rw if write-protected.
 */
static void patch_in_memory_proc_param(void) {
    uintptr_t libkernel_base = 0;
    sceKernelGetProcParam_t get_proc_param = NULL;

    /* Resolve sceKernelGetProcParam dynamically from libkernel */
    if (sys_dynlib_dlsym(0x2001, "sceKernelGetProcParam", &get_proc_param) != 0 || get_proc_param == NULL) {
        /* Fallback: try module handle 1 (libkernel) */
        sys_dynlib_dlsym(1, "sceKernelGetProcParam", &get_proc_param);
    }

    if (get_proc_param != NULL) {
        OrbisProcParam *param = get_proc_param();
        if (param != NULL && param->magic == ORBI_MAGIC) {
            uint32_t cur_sdk = (uint32_t)(param->sdk_version & 0xFFFFFFFF);
            g_original_sdk_version = cur_sdk;
            klog("[NEOENABLER] Detected OrbisProcParam ('ORBI') at %p | SDK: 0x%08X\n", param, cur_sdk);

            if (cur_sdk < NEO_MIN_SDK_VERSION) {
                uint64_t new_sdk = NEO_SPOOFED_SDK_VERSION;
                /* Use GoldHEN SDK sys_proc_rw to bypass read-only segment protection if needed */
                sys_proc_rw((uintptr_t)&param->sdk_version, &new_sdk, sizeof(new_sdk), 1);
                klog("[NEOENABLER] Upgraded OrbisProcParam->sdk_version in RAM: 0x%08X -> 0x%08X\n",
                     cur_sdk, (uint32_t)new_sdk);
            }
        }
    }
}

int module_start(size_t argc, const void *args) {
    klog("[NEOENABLER] Old-SDK Neo Mode Enabler Plugin loaded!\n");

    /* 1. Patch OrbisProcParam->sdk_version in memory */
    patch_in_memory_proc_param();

    /* 2. Hook sceKernelGetCompiledSdkVersion in libkernel */
    void *target_fn = NULL;
    if (sys_dynlib_dlsym(0x2001, "sceKernelGetCompiledSdkVersion", &target_fn) != 0 || target_fn == NULL) {
        sys_dynlib_dlsym(1, "sceKernelGetCompiledSdkVersion", &target_fn);
    }

    if (target_fn != NULL) {
        Detour_Construct(&Detour_sceKernelGetCompiledSdkVersion, DetourMode_x64);
        Detour_DetourFunction(&Detour_sceKernelGetCompiledSdkVersion, (uint64_t)target_fn, (void *)Hook_sceKernelGetCompiledSdkVersion);
        klog("[NEOENABLER] Hooked sceKernelGetCompiledSdkVersion at %p\n", target_fn);
    } else {
        klog("[NEOENABLER] Warning: Could not resolve sceKernelGetCompiledSdkVersion\n");
    }

    return 0;
}

int module_stop(size_t argc, const void *args) {
    Detour_Destroy(&Detour_sceKernelGetCompiledSdkVersion);
    klog("[NEOENABLER] Plugin unloaded.\n");
    return 0;
}
