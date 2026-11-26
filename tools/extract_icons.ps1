# Windows 탐색기와 같은 방식(IShellItemImageFactory)으로 아이콘을 PNG로 추출합니다.
# exe, lnk, 폴더, 네트워크 폴더(UNC), 스토어 앱(shell:AppsFolder\...) 모두 지원합니다.
# 사용법: powershell -NoProfile -ExecutionPolicy Bypass -File extract_icons.ps1 -Jobs jobs.json
#   jobs.json = [ { "src": "C:\\...\\app.exe", "out": "D:\\...\\web\\icons\\app.png" }, ... ]
param([Parameter(Mandatory = $true)][string]$Jobs, [int]$Size = 256)

$ErrorActionPreference = 'Stop'
Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @'
using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;

public static class ShellIcon {
    [ComImport, Guid("bcc18b79-ba16-442f-80c4-8a59c30c463b"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IShellItemImageFactory { void GetImage(SIZE size, int flags, out IntPtr phbm); }

    [StructLayout(LayoutKind.Sequential)] struct SIZE { public int cx, cy; }

    [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
    static extern void SHCreateItemFromParsingName(string path, IntPtr pbc, [MarshalAs(UnmanagedType.LPStruct)] Guid riid,
        [MarshalAs(UnmanagedType.Interface)] out IShellItemImageFactory ppv);

    [DllImport("gdi32.dll")] static extern bool DeleteObject(IntPtr h);

    public static void Save(string src, string outPng, int size) {
        IShellItemImageFactory f;
        SHCreateItemFromParsingName(src, IntPtr.Zero, typeof(IShellItemImageFactory).GUID, out f);
        IntPtr hbm;
        // SIIGBF_ICONONLY(0x4): 썸네일이 아니라 아이콘을 가져옴 / SIIGBF_BIGGERSIZEOK(0x1)
        f.GetImage(new SIZE { cx = size, cy = size }, 0x4 | 0x1, out hbm);
        try {
            using (var b = Image.FromHbitmap(hbm)) {
                var rect = new Rectangle(0, 0, b.Width, b.Height);
                var d = b.LockBits(rect, ImageLockMode.ReadOnly, b.PixelFormat);
                try {
                    // FromHbitmap 은 알파 채널을 버리므로 원본 비트를 ARGB 로 다시 읽음
                    using (var argb = new Bitmap(d.Width, d.Height, d.Stride, PixelFormat.Format32bppArgb, d.Scan0))
                    using (var copy = new Bitmap(argb)) {
                        copy.Save(outPng, ImageFormat.Png);
                    }
                } finally { b.UnlockBits(d); }
            }
        } finally { DeleteObject(hbm); }
    }
}
'@

$list = Get-Content -LiteralPath $Jobs -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($j in @($list)) {
    try {
        $dir = Split-Path -Parent $j.out
        if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
        [ShellIcon]::Save($j.src, $j.out, $Size)
        Write-Output ("OK   " + $j.src)
    } catch {
        Write-Output ("FAIL " + $j.src + " :: " + $_.Exception.Message)
    }
}
