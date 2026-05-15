#pragma once

namespace quant {

// Library version. Bumped manually -- callers can use this to verify the
// expected DLL is loaded.
constexpr int VERSION_MAJOR = 0;
constexpr int VERSION_MINOR = 1;
constexpr int VERSION_PATCH = 0;

const char* version_string();

}  // namespace quant
