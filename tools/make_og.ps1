# static/img/og.png üretir (1200x630). Depo kökünden çalıştır:
#   powershell -ExecutionPolicy Bypass -File tools\make_og.ps1
# Türkçe karakterler kod noktasıyla yazıldı: PowerShell 5.1 BOM'suz dosyayı ANSI okur.
Add-Type -AssemblyName System.Drawing
$w = 1200; $h = 630
$bmp = New-Object System.Drawing.Bitmap $w, $h
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.SmoothingMode = 'AntiAlias'; $g.TextRenderingHint = 'AntiAlias'
$g.Clear([System.Drawing.ColorTranslator]::FromHtml('#FAF9FF'))
function Pill($g, $x, $y, $wd, $ht, $color) {
  $r = $ht; $path = New-Object System.Drawing.Drawing2D.GraphicsPath
  $path.AddArc($x, $y, $r, $r, 90, 180); $path.AddArc($x + $wd - $r, $y, $r, $r, 270, 180); $path.CloseFigure()
  $g.FillPath((New-Object System.Drawing.SolidBrush ([System.Drawing.ColorTranslator]::FromHtml($color))), $path)
}
$ink = New-Object System.Drawing.SolidBrush ([System.Drawing.ColorTranslator]::FromHtml('#16143A'))
$muted = New-Object System.Drawing.SolidBrush ([System.Drawing.ColorTranslator]::FromHtml('#6B6890'))
$title = New-Object System.Drawing.Font 'Segoe UI', 108, ([System.Drawing.FontStyle]::Bold), ([System.Drawing.GraphicsUnit]::Pixel)
$sub = New-Object System.Drawing.Font 'Segoe UI', 44, ([System.Drawing.FontStyle]::Regular), ([System.Drawing.GraphicsUnit]::Pixel)
$i = [string][char]0x131
$g.DrawString(('Karars' + $i + 'z' + $i + 'm'), $title, $ink, 90, 120)
$g.DrawString(('Sen sor, kalabal' + $i + 'k karar versin.'), $sub, $muted, 96, 275)
# karar çubuğu
$x = 96; $y = 430; $total = 1008; $ht = 56
$segs = @(@(0.42, '#5B3DF5'), @(0.33, '#FF3D8B'), @(0.25, '#00D19A'))
$gap = 6; $cursor = $x
foreach ($s in $segs) { $wd = [int]($total * $s[0]); Pill $g $cursor $y ($wd - $gap) $ht $s[1]; $cursor += $wd }
$out = Join-Path (Get-Location) 'static\img\og.png'
$bmp.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Output "ok $((Get-Item $out).Length)"
