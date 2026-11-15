# Встановлення на Windows (без WSL). Запуск з кореня репо, у PowerShell:
#     powershell -ExecutionPolicy Bypass -File .\install.ps1
# Повторний запуск безпечний: що вже стоїть — пропускає.
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location -Path $PSScriptRoot

function Step($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Ok($t)   { Write-Host "  [ok] $t" -ForegroundColor Green }
function Warn($t) { Write-Host "  [!]  $t" -ForegroundColor Yellow }

Step "Git"
if (Get-Command git -ErrorAction SilentlyContinue) { Ok (git --version) }
else {
    Warn "Git немає. Claude Code на Windows теж потребує Git for Windows (Git Bash)."
    Write-Host "  Встановити: winget install --id Git.Git -e   (або https://git-scm.com/download/win), потім запустити цей файл ще раз"
    exit 1
}
git config core.longpaths true   # шляхи довші за 260 символів (довгі назви фікстур у raw/)
Ok "core.longpaths = true"

Step "uv (Python і бібліотеки для tools/)"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}
Ok (uv --version)

Step "Кирилиця в консолі"
[Environment]::SetEnvironmentVariable("PYTHONUTF8", "1", "User")
$env:PYTHONUTF8 = "1"
Ok "PYTHONUTF8=1 (для користувача)"

Step "Python і бібліотеки (pyproject.toml)"
uv sync
Ok "готово: скрипти запускаються як  uv run tools/<скрипт>.py"

Step "Claude Code"
if (Get-Command claude -ErrorAction SilentlyContinue) { Ok "claude є" }
else { Warn "claude у PATH немає — встановити Claude Code (розширення VS Code або https://claude.ai/download). Хуки репо його не потребують, але працювати буде нікому" }

Step "Перевірка середовища й джерел"
uv run tools/perevirka_seredovyshcha.py
Write-Host "`nДалі: README.md, розділ «Після встановлення»." -ForegroundColor Cyan
