# PowerShell Push Script for StudyBuddy
Write-Host 'Checking repository status...' -ForegroundColor Cyan
git status
git add .
git commit -m 'feat: complete hackathon docs, PolyForm non-commercial license, and MCP 2025-11-25'
git push -u origin main
Write-Host 'StudyBuddy push complete!' -ForegroundColor Green
