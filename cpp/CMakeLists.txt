cmake_minimum_required(VERSION 3.20)
project(libquant
    VERSION 0.1.0
    DESCRIPTION "Hot-path math library for the FTMO MT5 quant trading system"
    LANGUAGES CXX
)

# C++17 is plenty -- we don't need bleeding edge.
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Position-independent code so we can build a shared library on all platforms.
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# Strict warnings -- a math library has no business with implicit conversions.
if(MSVC)
    add_compile_options(/W4 /permissive-)
else()
    add_compile_options(-Wall -Wextra -Wpedantic -Wconversion)
endif()

# When building with MinGW, statically link the GCC and stdc++ runtimes so
# the resulting .dll / .pyd files don't depend on libgcc_s_seh-1.dll etc.
# being on PATH at load time. Without this, importing the Python module from
# the venv fails with "DLL load failed".
if(MINGW)
    add_link_options(-static -static-libgcc -static-libstdc++)
endif()

# ---------------------------------------------------------------------------
# Core static library -- the math itself
# ---------------------------------------------------------------------------
add_library(quant_core STATIC
    src/features.cpp
    src/ftmo_rules.cpp
    src/markov.cpp
    src/version.cpp
)
target_include_directories(quant_core PUBLIC include)
target_compile_features(quant_core PUBLIC cxx_std_17)

# ---------------------------------------------------------------------------
# Shared DLL (the C ABI MQL5 imports)
# ---------------------------------------------------------------------------
add_library(libquant SHARED src/c_abi.cpp)
target_link_libraries(libquant PRIVATE quant_core)
set_target_properties(libquant PROPERTIES
    OUTPUT_NAME "libquant"
    PREFIX ""           # MQL5 expects libquant.dll, not liblibquant.dll
)

# ---------------------------------------------------------------------------
# Python module (pybind11)
# ---------------------------------------------------------------------------
find_package(pybind11 CONFIG QUIET)
if(pybind11_FOUND)
    pybind11_add_module(quantlib bindings/python_module.cpp)
    target_link_libraries(quantlib PRIVATE quant_core)
    message(STATUS "pybind11 found -- Python module 'quantlib' will be built")
else()
    message(WARNING "pybind11 not found -- Python module will not be built. "
                    "Install with: uv pip install pybind11")
endif()

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
enable_testing()
add_subdirectory(tests)
