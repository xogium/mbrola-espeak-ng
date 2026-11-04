/*
 * Linux test-harness replacement for eSpeak NG's src/libespeak-ng/mbrowrap.c.
 *
 * Why this exists:
 *   On Windows, eSpeak NG talks to MBROLA through mbrola.dll, loaded with
 *   LoadLibraryA("mbrola.dll") and resolved with GetProcAddress. On Linux,
 *   upstream instead spawns the `mbrola` executable and talks over pipes,
 *   which is a different code path (and needs /proc).
 *
 *   To test on Linux the same thing NVDA will run on Windows, the harness
 *   build swaps mbrowrap.c for this file. It does what the Windows branch of
 *   upstream mbrowrap.c does, using dlopen/dlsym against libmbrola.so (built
 *   from the same MBROLA sources as mbrola.dll).
 *
 *   Like LoadLibraryA with a bare name, dlopen("libmbrola.so") returns an
 *   already-loaded object with that soname. The Python binding uses that to
 *   pre-load the library from an explicit path, the same way it does on
 *   Windows.
 *
 * This file is never shipped in the NVDA add-on.
 *
 * License: GPL-3.0-or-later (same as eSpeak NG).
 */

#include "config.h"

#include <dlfcn.h>
#include <stddef.h>

#include "mbrowrap.h"

int (WINAPI *init_MBR)(char *voice_path);
void (WINAPI *close_MBR)(void);
void (WINAPI *reset_MBR)(void);
int (WINAPI *read_MBR)(short *buffer, int nb_samples);
int (WINAPI *write_MBR)(char *data);
int (WINAPI *flush_MBR)(void);
int (WINAPI *getFreq_MBR)(void);
void (WINAPI *setVolumeRatio_MBR)(float value);
char * (WINAPI *lastErrorStr_MBR)(char *buffer, int bufsize);
void (WINAPI *setNoError_MBR)(int no_error);

static void *mbrola_handle = NULL;

#define RESOLVE(name) \
	do { \
		*(void **)(&name) = dlsym(mbrola_handle, #name); \
		if (name == NULL) { unload_MBR(); return 0; } \
	} while (0)

BOOL load_MBR(void)
{
	if (mbrola_handle != NULL)
		return 1;

	mbrola_handle = dlopen("libmbrola.so", RTLD_NOW | RTLD_LOCAL);
	if (mbrola_handle == NULL)
		return 0;

	RESOLVE(init_MBR);
	RESOLVE(write_MBR);
	RESOLVE(flush_MBR);
	RESOLVE(getFreq_MBR);
	RESOLVE(read_MBR);
	RESOLVE(close_MBR);
	RESOLVE(reset_MBR);
	RESOLVE(lastErrorStr_MBR);
	RESOLVE(setNoError_MBR);
	RESOLVE(setVolumeRatio_MBR);
	return 1;
}

void unload_MBR(void)
{
	if (mbrola_handle != NULL) {
		dlclose(mbrola_handle);
		mbrola_handle = NULL;
	}
}
