<#
.SYNOPSIS
  Build the Windows installer: PyInstaller backend + FFmpeg (ffmpeg.exe, ffprobe.exe), then the Tauri NSIS bundle.

.DESCRIPTION
  Output: app\src-tauri\target\release\bundle\nsis\VideoConverter_<version>_x64-setup.exe

  The installer holds the app, the Python backend, ffmpeg.exe and ffprobe.exe, so conversion works on
  machines without FFmpeg.

  FFmpeg is one pinned build (gyan.dev "essentials", which has NVENC, the CUDA decoders and libx264),
  not whatever happens to be on this PC: the conversion was tested with that build. It is downloaded
  once from GyanD's GitHub release, checked against the SHA-256 below and cached in backend\.tools.
  To move to a newer build, change $FFmpegVersion and $FFmpegSha256 together and test a conversion.

  The licenses of everything shipped (app MIT, FFmpeg GPL with its source pointer, Python packages,
  Rust crates, JS packages and fonts) are written to backend\licenses in the install folder.
  See THIRD_PARTY_NOTICES.md.

  Needs: uv, pnpm, Rust (stable MSVC). Run from anywhere.
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

$FFmpegVersion = "8.1"
$FFmpegSha256 = "8748283d821613d930b0e7be685aaa9df4ca6f0ad4d0c42fd02622b3623463c6"

# Returns the unpacked build folder (bin\ffmpeg.exe, bin\ffprobe.exe, LICENSE, README.txt)
function Get-FFmpeg {
    $name = "ffmpeg-$FFmpegVersion-essentials_build"
    $tools = Join-Path $root "backend\.tools"
    $dir = Join-Path $tools $name
    if (Test-Path (Join-Path $dir "bin\ffprobe.exe")) { return $dir }
    New-Item -ItemType Directory -Force $tools | Out-Null
    $zip = Join-Path $tools "$name.zip"
    if (-not (Test-Path $zip)) {
        $url = "https://github.com/GyanD/codexffmpeg/releases/download/$FFmpegVersion/$name.zip"
        Write-Host "Downloading FFmpeg from $url"  # Write-Host: a bare string would become part of the return value
        Invoke-WebRequest $url -OutFile $zip -UseBasicParsing
    }
    $got = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
    if ($got -ne $FFmpegSha256) { Remove-Item $zip; throw "FFmpeg download checksum mismatch (expected $FFmpegSha256, got $got)" }
    Expand-Archive $zip -DestinationPath $tools -Force
    return $dir
}

$ffmpeg = Get-FFmpeg
"Bundling FFmpeg from $ffmpeg"

Push-Location (Join-Path $root "backend")
try {
    uv sync --locked
    if ($LASTEXITCODE) { throw "uv sync failed" }
    uv run pyinstaller --noconfirm --clean --distpath dist --workpath build packaging\videoconverter-backend.spec
    if ($LASTEXITCODE) { throw "PyInstaller failed" }
    $out = ".\dist\videoconverter-backend"
    Copy-Item (Join-Path $ffmpeg "bin\ffmpeg.exe") $out -Force
    Copy-Item (Join-Path $ffmpeg "bin\ffprobe.exe") $out -Force

    # Licenses of everything the installer ships (THIRD_PARTY_NOTICES.md explains them)
    $lic = New-Item -ItemType Directory -Force (Join-Path $out "licenses")
    Copy-Item (Join-Path $root "LICENSE") (Join-Path $lic "LICENSE.txt") -Force
    Copy-Item (Join-Path $root "THIRD_PARTY_NOTICES.md") $lic -Force
    # FFmpeg is GPL: its license and the build's README (which names the exact source commit) ship with it
    Copy-Item (Join-Path $ffmpeg "LICENSE") (Join-Path $lic "FFmpeg-LICENSE.txt") -Force
    Copy-Item (Join-Path $ffmpeg "README.txt") (Join-Path $lic "FFmpeg-README.txt") -Force
    $collect = Join-Path $root "scripts\collect_licenses.py"
    uv export --no-dev --no-hashes --format requirements-txt | uv run python $collect python (Join-Path $lic "python-packages.txt")
    if ($LASTEXITCODE) { throw "collecting Python package licenses failed" }
    uv run python $collect cargo (Join-Path $root "app\src-tauri") (Join-Path $lic "rust-crates.txt")
    if ($LASTEXITCODE) { throw "collecting Rust crate licenses failed" }
    & "$out\videoconverter-backend.exe" doctor --bundled
    if ($LASTEXITCODE) { throw "the packaged backend is missing FFmpeg, ffprobe, NVENC or libx264" }
} finally { Pop-Location }

Push-Location (Join-Path $root "app")
try {
    pnpm install --frozen-lockfile
    if ($LASTEXITCODE) { throw "pnpm install failed" }
    # needs node_modules, so it runs here rather than with the other licenses
    $jsLicenses = Join-Path $root "backend\dist\videoconverter-backend\licenses\js-packages.txt"
    uv run --project (Join-Path $root "backend") python (Join-Path $root "scripts\collect_licenses.py") npm . $jsLicenses
    if ($LASTEXITCODE) { throw "collecting JavaScript package licenses failed" }
    pnpm tauri build
    if ($LASTEXITCODE) { throw "tauri build failed" }
} finally { Pop-Location }

Get-ChildItem (Join-Path $root "app\src-tauri\target\release\bundle\nsis\*.exe") | ForEach-Object {
    "{0}  {1:N1} MB" -f $_.FullName, ($_.Length / 1MB)
}
