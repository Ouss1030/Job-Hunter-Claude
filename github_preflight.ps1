# Job Hunter Belgium - vérification avant publication GitHub
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\github_preflight.ps1

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=== JOB HUNTER GITHUB PREFLIGHT ==="
Write-Host ""

if (-not (Test-Path ".gitignore")) {
    Write-Host "ERREUR: .gitignore absent." -ForegroundColor Red
    exit 1
}

$riskyPatterns = @(
    "database\jobs.db",
    ".env",
    "config\profile.py",
    "config\ai_generation.py"
)

Write-Host "Fichiers sensibles connus:"
foreach ($p in $riskyPatterns) {
    if (Test-Path $p) {
        Write-Host "  LOCAL (normal): $p"
    }
}

if (Get-Command git -ErrorAction SilentlyContinue) {
    Write-Host ""
    Write-Host "Verification Git..."

    $inside = git rev-parse --is-inside-work-tree 2>$null
    if ($inside -eq "true") {
        $tracked = git ls-files

        $bad = @()
        foreach ($f in $tracked) {
            if (
                $f -match '(^|/)jobs\.db$' -or
                $f -match '(^|/)\.env($|\.)' -or
                $f -match '^config/profile\.py$' -or
                $f -match '^config/ai_generation\.py$' -or
                $f -match '^exports/logs/' -or
                $f -match '^exports/applications/' -or
                $f -match '\.(docx|pdf)$'
            ) {
                $bad += $f
            }
        }

        if ($bad.Count -gt 0) {
            Write-Host ""
            Write-Host "ATTENTION: fichiers sensibles deja suivis par Git:" -ForegroundColor Red
            foreach ($f in $bad) {
                Write-Host "  $f" -ForegroundColor Red
            }
            Write-Host ""
            Write-Host "NE PUSH PAS avant correction." -ForegroundColor Red
            exit 2
        }

        Write-Host "OK: aucun fichier sensible connu n'est suivi par Git." -ForegroundColor Green
    }
    else {
        Write-Host "Le dossier n'est pas encore initialise avec Git."
    }
}
else {
    Write-Host ""
    Write-Host "Git n'est pas disponible en ligne de commande."
    Write-Host "Ce n'est pas bloquant si tu utilises GitHub Desktop."
}

Write-Host ""
Write-Host "PREFLIGHT TERMINE."
