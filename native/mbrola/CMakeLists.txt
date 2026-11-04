# Builds the MBROLA "one channel" library as a shared library:
#   Windows: mbrola.dll   (the exact API eSpeak NG loads with LoadLibraryA("mbrola.dll"))
#   Linux:   libmbrola.so (used only by the Linux test harness)
#
# Upstream MBROLA has no CMake build. We compile its single-file "unity"
# wrapper LibOneChannel/lib1.c, which #includes every needed source file.
#
# Usage:
#   cmake -S native/mbrola -B build/mbrola -DMBROLA_SOURCE_DIR=<checkout>
#   cmake --build build/mbrola --config Release

cmake_minimum_required(VERSION 3.16)
project(mbrola_shared C)

set(MBROLA_SOURCE_DIR "" CACHE PATH "Path to a checkout of numediart/MBROLA")
if(NOT EXISTS "${MBROLA_SOURCE_DIR}/LibOneChannel/lib1.c")
  message(FATAL_ERROR "MBROLA_SOURCE_DIR must point to an MBROLA checkout (got '${MBROLA_SOURCE_DIR}')")
endif()

add_library(mbrola SHARED "${MBROLA_SOURCE_DIR}/LibOneChannel/lib1.c")

target_include_directories(mbrola PRIVATE
  "${MBROLA_SOURCE_DIR}/Parser"
  "${MBROLA_SOURCE_DIR}/Misc"
  "${MBROLA_SOURCE_DIR}/LibOneChannel"
  "${MBROLA_SOURCE_DIR}/Engine"
  "${MBROLA_SOURCE_DIR}/Database"
)

if(WIN32)
  # Same definitions as upstream VisualC/mbrolalib/mbrolalib.vcxproj.
  # DLL selects the exported (WINAPI) entry points; on x64 WINAPI is a no-op.
  target_compile_definitions(mbrola PRIVATE
    WIN32 NDEBUG _WINDOWS _USRDLL MBROLADLL_EXPORTS
    _CRT_SECURE_NO_WARNINGS TARGET_OS_DOS LITTLE_ENDIAN DLL)
  target_sources(mbrola PRIVATE
    "${MBROLA_SOURCE_DIR}/VisualC/mbrolalib/dllmain.c"
    "${MBROLA_SOURCE_DIR}/VisualC/mbrolalib/mbrola.def")
  # Output exactly "mbrola.dll" (no "lib" prefix) because eSpeak NG looks it up by that name.
  set_target_properties(mbrola PROPERTIES PREFIX "" OUTPUT_NAME "mbrola")
  # Static C runtime: the DLL must not depend on a particular vcruntime being present.
  set_property(TARGET mbrola PROPERTY MSVC_RUNTIME_LIBRARY "MultiThreaded")
else()
  target_compile_definitions(mbrola PRIVATE LIBRARY _DEFAULT_SOURCE _XOPEN_SOURCE=700)
  target_link_libraries(mbrola PRIVATE m)
  # The soname matters: the Linux test harness (mbrowrap_dlopen.c) calls
  # dlopen("libmbrola.so"), which resolves to an already-loaded object with this soname.
  set_target_properties(mbrola PROPERTIES OUTPUT_NAME "mbrola" NO_SONAME OFF)
  target_link_options(mbrola PRIVATE "-Wl,-soname,libmbrola.so")
endif()

install(TARGETS mbrola RUNTIME DESTINATION bin LIBRARY DESTINATION lib)
