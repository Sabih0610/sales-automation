$ErrorActionPreference = "Stop"

$assetsDir = Resolve-Path (Join-Path $PSScriptRoot "..\assets")
$iconPath = Join-Path $assetsDir "icon.ico"

Add-Type -AssemblyName System.Drawing

function New-RoundedRectanglePath {
    param(
        [float]$X,
        [float]$Y,
        [float]$Width,
        [float]$Height,
        [float]$Radius
    )

    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $diameter = $Radius * 2
    $path.AddArc($X, $Y, $diameter, $diameter, 180, 90)
    $path.AddArc($X + $Width - $diameter, $Y, $diameter, $diameter, 270, 90)
    $path.AddArc($X + $Width - $diameter, $Y + $Height - $diameter, $diameter, $diameter, 0, 90)
    $path.AddArc($X, $Y + $Height - $diameter, $diameter, $diameter, 90, 90)
    $path.CloseFigure()
    return $path
}

function New-IconPng {
    param([int]$Size)

    $bitmap = New-Object System.Drawing.Bitmap $Size, $Size, ([System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
    $graphics.Clear([System.Drawing.Color]::Transparent)

    $scale = $Size / 512.0
    $rect = New-RoundedRectanglePath `
        -X ([single](32 * $scale)) `
        -Y ([single](32 * $scale)) `
        -Width ([single](448 * $scale)) `
        -Height ([single](448 * $scale)) `
        -Radius ([single](96 * $scale))
    $gradientStart = New-Object System.Drawing.PointF -ArgumentList ([single](72 * $scale)), ([single](56 * $scale))
    $gradientEnd = New-Object System.Drawing.PointF -ArgumentList ([single](440 * $scale)), ([single](456 * $scale))
    $brush = New-Object System.Drawing.Drawing2D.LinearGradientBrush -ArgumentList $gradientStart, $gradientEnd, ([System.Drawing.Color]::FromArgb(255, 18, 58, 93)), ([System.Drawing.Color]::FromArgb(255, 15, 118, 110))
    $graphics.FillPath($brush, $rect)

    $fontFamily = New-Object System.Drawing.FontFamily "Segoe UI"
    $fontStyle = [System.Drawing.FontStyle]::Bold
    $font = New-Object System.Drawing.Font($fontFamily, [single](176 * $scale), $fontStyle, [System.Drawing.GraphicsUnit]::Pixel)
    $textBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::White)
    $format = New-Object System.Drawing.StringFormat
    $format.Alignment = [System.Drawing.StringAlignment]::Center
    $format.LineAlignment = [System.Drawing.StringAlignment]::Center
    $textRect = New-Object System.Drawing.RectangleF -ArgumentList ([single](34 * $scale)), ([single](96 * $scale)), ([single](444 * $scale)), ([single](260 * $scale))
    $graphics.DrawString("RC", $font, $textBrush, $textRect, $format)

    $accent = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 244, 197, 66))
    $graphics.FillRectangle($accent, [single](132 * $scale), [single](376 * $scale), [single](248 * $scale), [single](36 * $scale))

    $stream = New-Object System.IO.MemoryStream
    $bitmap.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
    $bytes = $stream.ToArray()

    $stream.Dispose()
    $accent.Dispose()
    $format.Dispose()
    $textBrush.Dispose()
    $font.Dispose()
    $fontFamily.Dispose()
    $brush.Dispose()
    $rect.Dispose()
    $graphics.Dispose()
    $bitmap.Dispose()

    return ,$bytes
}

$sizes = @(256, 128, 64, 48, 32, 16)
$images = foreach ($size in $sizes) {
    [pscustomobject]@{
        Size = $size
        Bytes = New-IconPng -Size $size
    }
}

$stream = [System.IO.File]::Create($iconPath)
$writer = New-Object System.IO.BinaryWriter($stream)
try {
    $writer.Write([uint16]0)
    $writer.Write([uint16]1)
    $writer.Write([uint16]$images.Count)

    $offset = 6 + ($images.Count * 16)
    foreach ($image in $images) {
        $encodedSize = if ($image.Size -eq 256) { 0 } else { $image.Size }
        $writer.Write([byte]$encodedSize)
        $writer.Write([byte]$encodedSize)
        $writer.Write([byte]0)
        $writer.Write([byte]0)
        $writer.Write([uint16]1)
        $writer.Write([uint16]32)
        $writer.Write([uint32]$image.Bytes.Length)
        $writer.Write([uint32]$offset)
        $offset += $image.Bytes.Length
    }

    foreach ($image in $images) {
        $writer.Write($image.Bytes)
    }
} finally {
    $writer.Dispose()
    $stream.Dispose()
}

Write-Host "Created $iconPath"
