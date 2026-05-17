# build_dll.ps1
# Build libftmorisk.dll = OCaml ftmo_rules state machine + C shim, packaged
# as a Windows DLL that MQL5 (via #import) and Python (via ctypes) can load.
#
# Requires:
#   - opam switch 5.1.0 active in PATH (the same switch that has ocamlmklib,
#     flexlink, gcc / MinGW UCRT)
#   - From the repo root run:  cd ocaml && .\build_dll.ps1
#
# Output: ocaml/_build/dll/libftmorisk.dll  (+ a few .a / .cmxa intermediates)
#
# Approach:
#   1. Compile ftmo_rules.ml + c_stubs.ml to native .cmx (no dune needed).
#   2. Pack into an archive (ftmo_risk.cmxa).
#   3. Compile ftmo_risk_stubs.c with gcc, with OCaml's caml/*.h on the
#      include path.
#   4. Invoke ocamlmklib to link OCaml archive + C stubs + OCaml asmrun
#      into libftmorisk.dll via flexdll.

$ErrorActionPreference = "Stop"

# Make sure opam env is in PATH for THIS shell.
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
(& opam env --switch=5.1.0) -split '\r?\n' | ForEach-Object { Invoke-Expression $_ }

# Sanity
foreach ($tool in @("ocamlfind", "ocamlmklib", "flexlink", "gcc")) {
    $found = Get-Command $tool -ErrorAction SilentlyContinue
    if (-not $found) { throw "Required tool not on PATH: $tool" }
}

$camlInc = ocamlfind printconf stdlib
if (-not $camlInc) { throw "Cannot locate OCaml stdlib via ocamlfind" }
Write-Host "OCaml stdlib: $camlInc"

$libDir   = Resolve-Path .\lib
$buildDir = ".\_build\dll"
if (-not (Test-Path $buildDir)) { New-Item -ItemType Directory -Path $buildDir | Out-Null }

Write-Host ""
Write-Host "Step 1/4  Compile ftmo_rules.ml + c_stubs.ml to native .cmx"
Push-Location $libDir
try {
    ocamlfind ocamlopt -package threads.posix -thread `
        -c ftmo_rules.mli `
        -o $buildDir\ftmo_rules.cmi 2>&1 | Where-Object { $_ } | ForEach-Object { Write-Host "  $_" }
    # Compile .ml files in dependency order
    ocamlfind ocamlopt -package threads.posix -thread `
        -I $buildDir `
        -c ftmo_rules.ml `
        -o $buildDir\ftmo_rules.cmx 2>&1 | Where-Object { $_ } | ForEach-Object { Write-Host "  $_" }
    ocamlfind ocamlopt -package threads.posix -thread `
        -I $buildDir `
        -c c_stubs.ml `
        -o $buildDir\c_stubs.cmx 2>&1 | Where-Object { $_ } | ForEach-Object { Write-Host "  $_" }
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "Step 2/4  Pack into native archive (.cmxa + .a)"
ocamlfind ocamlopt -package threads.posix -thread -a `
    -o "$buildDir\ftmo_risk.cmxa" `
    "$buildDir\ftmo_rules.cmx" "$buildDir\c_stubs.cmx" 2>&1 |
    Where-Object { $_ } | ForEach-Object { Write-Host "  $_" }

Write-Host ""
Write-Host "Step 3/4  Compile ftmo_risk_stubs.c (the C shim)"
gcc -c -O2 -fPIC `
    "-I$camlInc" `
    -o "$buildDir\ftmo_risk_stubs.o" `
    "$libDir\ftmo_risk_stubs.c" 2>&1 | Where-Object { $_ } | ForEach-Object { Write-Host "  $_" }

Write-Host ""
Write-Host "Step 4/4  Link via ocamlmklib -> libftmorisk.dll"
# ocamlmklib produces:
#   - libftmorisk.dll  (the actual DLL; includes flexdll exports)
#   - libftmorisk.a    (static archive of the same code)
#   - dllftmorisk.dll  (OCaml-bytecode-style alias if applicable)
Push-Location $buildDir
try {
    ocamlmklib -verbose `
        -o ftmo_risk `
        ftmo_risk.cmxa `
        ftmo_risk_stubs.o 2>&1 | Where-Object { $_ } | ForEach-Object { Write-Host "  $_" }
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "Artefacts:"
Get-ChildItem $buildDir -Filter "*.dll" | ForEach-Object { "  $($_.FullName) ($([math]::Round($_.Length/1KB,1)) KB)" }
Get-ChildItem $buildDir -Filter "*.a"   | ForEach-Object { "  $($_.FullName) ($([math]::Round($_.Length/1KB,1)) KB)" }

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "Next: test via Python ctypes (see tests/test_libftmorisk_dll.py)"
