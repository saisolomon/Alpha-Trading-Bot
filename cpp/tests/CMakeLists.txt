# C++ unit tests (run via ctest after build).
# These are minimal sanity checks -- the REAL parity test is the Python-side
# tests/test_cpp_parity.py which compares C++ output against the existing
# pure-Python implementation on cached real data.

add_executable(test_basic test_basic.cpp)
target_link_libraries(test_basic PRIVATE quant_core)

add_test(NAME basic COMMAND test_basic)
