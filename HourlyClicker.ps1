<#
    시간별 랜덤 클릭 스케줄러 (HourlyClicker)

    - 매 시간, 그 시간에 지정한 분(分) 범위 안의 랜덤한 시각에 매크로를 한 번 실행
    - 마우스는 베지어 곡선 + 가감속 + 미세 떨림 + 가끔 오버슈트로 사람처럼 이동
    - 프로필1 / 프로필2 각각 24시간 매크로 설정 저장 (profiles\profile1.json, profile2.json)
    - 시간별 "확률 미작동" : 확률에 걸리면 그 시간은 건너뜀
      (단, 직전 시간에 미작동으로 건너뛰었다면 이번 시간은 무조건 작동)
    - 어떤 시간에 50분 이후에 작업했다면, 다음 시간은 0~10분 사이에 작업

    사용법
      GUI(설정/실행) : HourlyClicker.ps1
      콘솔 실행      : HourlyClicker.ps1 -Run -ProfileNo 1
#>
param(
    [switch]$Run,
    [ValidateSet(1, 2)][int]$ProfileNo = 1
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$script:BaseDir    = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$script:ProfileDir = Join-Path $script:BaseDir 'profiles'
$script:LogDir     = Join-Path $script:BaseDir 'logs'
foreach ($d in @($script:ProfileDir, $script:LogDir)) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d | Out-Null }
}

$script:IsGui     = $false
$script:LogBox    = $null
$script:Running   = $false
$script:Busy      = $false
$script:ProfileNo = $ProfileNo
$script:Data      = $null

# 런타임 상태 (실행 시작 시 초기화)
function Reset-State {
    $script:S = @{
        HourKey     = ''      # yyyyMMddHH : 계획을 세운 시간
        PlanTime    = $null   # 이번 시간 실행 예정 시각
        Done        = $true   # 이번 시간 실행 완료 여부
        Macro       = ''      # 이번 시간에 실행할 매크로
        LastSkipped = $false  # 직전 판정이 "확률 미작동" 이었는지
        ForceEarly  = $false  # 다음 시간을 0~10분 사이에 실행해야 하는지
        LastMacro   = ''      # 마지막으로 실행한 매크로
        LastTick    = $null   # 마지막 타이머 동작 시각 (절전/멈춤 감지용)
        BeatKey     = ''      # 10분마다 남기는 "대기 중" 로그용
    }
}
Reset-State

# ---------------------------------------------------------------------------
#  사람처럼 움직이는 마우스 (Win32)
# ---------------------------------------------------------------------------
if (-not ('HumanMouse' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Diagnostics;
using System.Threading;
using System.Runtime.InteropServices;

public static class HumanMouse
{
    [StructLayout(LayoutKind.Sequential)]
    public struct POINT { public int X; public int Y; }

    [DllImport("user32.dll")] static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] static extern bool GetCursorPos(out POINT p);
    [DllImport("user32.dll")] static extern void mouse_event(uint flags, uint dx, uint dy, int data, UIntPtr extra);
    [DllImport("user32.dll")] static extern short GetAsyncKeyState(int vKey);
    [DllImport("user32.dll")] static extern bool SetProcessDPIAware();
    [DllImport("kernel32.dll")] static extern uint SetThreadExecutionState(uint flags);
    [DllImport("winmm.dll")] static extern uint timeBeginPeriod(uint p);
    [DllImport("winmm.dll")] static extern uint timeEndPeriod(uint p);

    static readonly Random rnd = new Random();

    public static void Init()
    {
        try { SetProcessDPIAware(); } catch { }
    }

    // 실행 중 PC 절전 / 화면 꺼짐 방지
    // (모던 스탠바이 PC는 화면이 꺼지면 프로그램이 멈추므로 화면까지 켜둠)
    public static void KeepAwake(bool on)
    {
        try { SetThreadExecutionState(on ? 0x80000003u : 0x80000000u); } catch { }
    }

    public static bool IsKeyDown(int vk)
    {
        return (GetAsyncKeyState(vk) & 0x8000) != 0;
    }

    public static int[] GetPos()
    {
        POINT p;
        GetCursorPos(out p);
        return new int[] { p.X, p.Y };
    }

    static double R(double a, double b) { return a + rnd.NextDouble() * (b - a); }

    public static void MoveTo(int tx, int ty)
    {
        timeBeginPeriod(1);
        try
        {
            POINT p;
            GetCursorPos(out p);
            double dx = tx - p.X, dy = ty - p.Y;
            double dist = Math.Sqrt(dx * dx + dy * dy);
            if (dist < 2) { SetCursorPos(tx, ty); return; }

            // 먼 거리는 가끔 목표를 살짝 지나쳤다가 되돌아옴
            if (dist > 150 && rnd.NextDouble() < 0.3)
            {
                double ang = Math.Atan2(dy, dx);
                double o = R(4, Math.Min(20, 4 + dist * 0.04));
                double ox = tx + Math.Cos(ang) * o + R(-3, 3);
                double oy = ty + Math.Sin(ang) * o + R(-3, 3);
                Segment(p.X, p.Y, ox, oy);
                Thread.Sleep(rnd.Next(40, 140));
                GetCursorPos(out p);
                Segment(p.X, p.Y, tx, ty);
            }
            else
            {
                Segment(p.X, p.Y, tx, ty);
            }
            SetCursorPos(tx, ty);
        }
        finally { timeEndPeriod(1); }
    }

    // 3차 베지어 곡선 + 가감속 + 미세 떨림
    static void Segment(double sx, double sy, double ex, double ey)
    {
        double dx = ex - sx, dy = ey - sy;
        double dist = Math.Sqrt(dx * dx + dy * dy);
        if (dist < 1) return;

        double nx = -dy / dist, ny = dx / dist;
        double maxBend = Math.Min(dist * 0.3, 200);
        double b1 = R(-maxBend, maxBend), b2 = R(-maxBend, maxBend) * 0.6;
        double t1 = R(0.15, 0.4), t2 = R(0.6, 0.85);
        double c1x = sx + dx * t1 + nx * b1, c1y = sy + dy * t1 + ny * b1;
        double c2x = sx + dx * t2 + nx * b2, c2y = sy + dy * t2 + ny * b2;

        // 피츠 법칙 비슷하게: 멀수록 오래 걸리지만 비례하지는 않음
        double duration = (110 + 95 * Math.Log(dist / 12.0 + 1, 2)) * R(0.8, 1.3);
        int steps = (int)Math.Max(10, Math.Min(150, duration / 7));
        double jitter = Math.Min(1.2, dist / 250.0);

        Stopwatch sw = Stopwatch.StartNew();
        for (int i = 1; i <= steps; i++)
        {
            double t = (double)i / steps;
            // 빠르게 출발해서 목표 근처에서 감속
            double smooth = t * t * (3 - 2 * t);
            double outCubic = 1 - Math.Pow(1 - t, 3);
            double e = (smooth + outCubic) / 2;
            double u = 1 - e;
            double x = u * u * u * sx + 3 * u * u * e * c1x + 3 * u * e * e * c2x + e * e * e * ex;
            double y = u * u * u * sy + 3 * u * u * e * c1y + 3 * u * e * e * c2y + e * e * e * ey;
            if (i < steps) { x += R(-jitter, jitter); y += R(-jitter, jitter); }
            SetCursorPos((int)Math.Round(x), (int)Math.Round(y));

            long target = (long)(duration * t * R(0.9, 1.1));
            long wait = target - sw.ElapsedMilliseconds;
            Thread.Sleep((int)Math.Max(1, wait));
        }
    }

    // button: 0=왼쪽, 1=오른쪽, 2=가운데
    public static void Click(int button, int count)
    {
        uint down = button == 1 ? 0x0008u : (button == 2 ? 0x0020u : 0x0002u);
        uint up   = button == 1 ? 0x0010u : (button == 2 ? 0x0040u : 0x0004u);
        for (int i = 0; i < count; i++)
        {
            mouse_event(down, 0, 0, 0, UIntPtr.Zero);
            Thread.Sleep(rnd.Next(45, 130));
            mouse_event(up, 0, 0, 0, UIntPtr.Zero);
            if (i < count - 1) Thread.Sleep(rnd.Next(70, 140));
        }
    }

    public static void Scroll(int notches)
    {
        int dir = notches > 0 ? 1 : -1;
        for (int i = 0; i < Math.Abs(notches); i++)
        {
            mouse_event(0x0800, 0, 0, 120 * dir, UIntPtr.Zero);
            Thread.Sleep(rnd.Next(40, 170));
        }
    }
}
'@
}
[HumanMouse]::Init()

# ---------------------------------------------------------------------------
#  공통 유틸
# ---------------------------------------------------------------------------
function Write-Log([string]$msg) {
    $line = '[{0}] [프로필{1}] {2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $script:ProfileNo, $msg
    if ($script:LogBox) {
        $script:LogBox.AppendText($line + "`r`n")
    } else {
        Write-Host $line
    }
    try {
        $file = Join-Path $script:LogDir ((Get-Date -Format 'yyyyMMdd') + '.log')
        Add-Content -Path $file -Value $line -Encoding UTF8
    } catch { }
}

function ConvertTo-IntOr($v, [int]$default) {
    $n = 0
    if ([int]::TryParse(("$v").Trim(), [ref]$n)) { return $n }
    return $default
}

function Limit-Range([int]$v, [int]$min, [int]$max) {
    return [Math]::Max($min, [Math]::Min($max, $v))
}

function Get-StepCount([string]$macro) {
    if (-not $macro) { return 0 }
    return @($macro -split "`r?`n" | Where-Object { $_.Trim() -ne '' -and -not $_.Trim().StartsWith('#') }).Count
}

function Wait-Ms([int]$ms) {
    $end = (Get-Date).AddMilliseconds($ms)
    while ($true) {
        if ($script:IsGui) { [System.Windows.Forms.Application]::DoEvents() }
        $left = ($end - (Get-Date)).TotalMilliseconds
        if ($left -le 0) { break }
        Start-Sleep -Milliseconds ([int][Math]::Min(30, [Math]::Ceiling($left)))
    }
}

# ---------------------------------------------------------------------------
#  프로필 저장 / 불러오기
# ---------------------------------------------------------------------------
function New-HourConfig([int]$hour) {
    return @{
        Hour        = $hour
        Enabled     = $false
        StartMin    = 0
        EndMin      = 59
        SkipEnabled = $false
        SkipPercent = 30
        Macro       = ''
    }
}

function Get-ProfilePath([int]$no) {
    return Join-Path $script:ProfileDir ("profile{0}.json" -f $no)
}

function Import-ProfileData([int]$no) {
    $hours = New-Object object[] 24
    for ($i = 0; $i -lt 24; $i++) { $hours[$i] = New-HourConfig $i }

    $path = Get-ProfilePath $no
    if (Test-Path $path) {
        try {
            $json = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
            foreach ($x in @($json.Hours)) {
                $i = ConvertTo-IntOr $x.Hour -1
                if ($i -lt 0 -or $i -gt 23) { continue }
                $h = $hours[$i]
                $h.Enabled     = [bool]$x.Enabled
                $h.StartMin    = Limit-Range (ConvertTo-IntOr $x.StartMin 0) 0 59
                $h.EndMin      = Limit-Range (ConvertTo-IntOr $x.EndMin 59) 0 59
                $h.SkipEnabled = [bool]$x.SkipEnabled
                $h.SkipPercent = Limit-Range (ConvertTo-IntOr $x.SkipPercent 30) 0 100
                $h.Macro       = [string]$x.Macro
                if ($h.StartMin -gt $h.EndMin) { $t = $h.StartMin; $h.StartMin = $h.EndMin; $h.EndMin = $t }
            }
        } catch {
            Write-Log ("프로필{0} 불러오기 실패: {1}" -f $no, $_.Exception.Message)
        }
    }
    $script:Data = @{ Hours = $hours }
}

function Export-ProfileData([int]$no) {
    $list = foreach ($h in $script:Data.Hours) {
        [pscustomobject][ordered]@{
            Hour        = [int]$h.Hour
            Enabled     = [bool]$h.Enabled
            StartMin    = [int]$h.StartMin
            EndMin      = [int]$h.EndMin
            SkipEnabled = [bool]$h.SkipEnabled
            SkipPercent = [int]$h.SkipPercent
            Macro       = [string]$h.Macro
        }
    }
    $obj  = [pscustomobject][ordered]@{ Version = 1; Hours = @($list) }
    $json = $obj | ConvertTo-Json -Depth 5
    [System.IO.File]::WriteAllText((Get-ProfilePath $no), $json, (New-Object System.Text.UTF8Encoding($false)))
}

# ---------------------------------------------------------------------------
#  매크로 실행
# ---------------------------------------------------------------------------
function Invoke-Macro([string]$text) {
    foreach ($raw in ($text -split "`r?`n")) {
        $line = $raw.Trim()
        if ($line -eq '' -or $line.StartsWith('#')) { continue }

        if ([HumanMouse]::IsKeyDown(0x7B)) {   # F12
            Write-Log '  F12 입력 → 매크로 중단'
            return $false
        }

        $sp  = $line -split '\s+', 2
        $cmd = $sp[0].ToUpper()
        $arg = if ($sp.Count -gt 1) { $sp[1] } else { '' }

        try {
            switch ($cmd) {
                { $_ -in 'CLICK', 'RCLICK', 'DCLICK', 'MCLICK', 'MOVE' } {
                    $v = @(($arg -split '[\s,]+') | Where-Object { $_ -ne '' } | ForEach-Object { [int]$_ })
                    if ($v.Count -lt 2) { throw '좌표(x y)가 필요합니다' }
                    $r = if ($v.Count -ge 3) { [Math]::Abs($v[2]) } else { 3 }
                    $x = $v[0] + (Get-Random -Minimum (-$r) -Maximum ($r + 1))
                    $y = $v[1] + (Get-Random -Minimum (-$r) -Maximum ($r + 1))
                    [HumanMouse]::MoveTo($x, $y)
                    if ($cmd -ne 'MOVE') {
                        Wait-Ms (Get-Random -Minimum 60 -Maximum 230)
                        switch ($cmd) {
                            'CLICK'  { [HumanMouse]::Click(0, 1) }
                            'RCLICK' { [HumanMouse]::Click(1, 1) }
                            'MCLICK' { [HumanMouse]::Click(2, 1) }
                            'DCLICK' { [HumanMouse]::Click(0, 2) }
                        }
                    }
                }
                'WAIT' {
                    $v = @(($arg -split '[\s,~-]+') | Where-Object { $_ -ne '' } | ForEach-Object { [int]$_ })
                    if ($v.Count -eq 0) { throw '대기 시간(ms)이 필요합니다' }
                    $a = $v[0]
                    $b = if ($v.Count -ge 2) { $v[1] } else { $v[0] }
                    if ($a -gt $b) { $t = $a; $a = $b; $b = $t }
                    Wait-Ms (Get-Random -Minimum $a -Maximum ($b + 1))
                }
                'KEY' {
                    [System.Windows.Forms.SendKeys]::SendWait($arg)
                }
                'SCROLL' {
                    [HumanMouse]::Scroll((ConvertTo-IntOr $arg 0))
                }
                default { throw '알 수 없는 명령' }
            }
        } catch {
            Write-Log ("  오류: '{0}' → {1}" -f $line, $_.Exception.Message)
        }

        # 단계 사이 사람같은 텀
        Wait-Ms (Get-Random -Minimum 80 -Maximum 280)
    }
    return $true
}

# ---------------------------------------------------------------------------
#  스케줄러
# ---------------------------------------------------------------------------
function New-HourPlan([datetime]$now) {
    $S = $script:S
    $S.HourKey  = $now.ToString('yyyyMMddHH')
    $S.PlanTime = $null
    $S.Done     = $true
    $S.Macro    = ''

    $hour   = $now.Hour
    $cfg    = $script:Data.Hours[$hour]
    $forced = [bool]$S.ForceEarly
    $S.ForceEarly = $false
    $tag = '[{0:D2}시]' -f $hour

    $macro = [string]$cfg.Macro
    if ($forced) {
        # 이 시간 매크로가 비어 있으면 직전에 실행한 매크로 사용
        if ((Get-StepCount $macro) -eq 0) { $macro = $S.LastMacro }
        if ((Get-StepCount $macro) -eq 0) {
            Write-Log "$tag 0~10분 추가 작업 예정이었으나 실행할 매크로가 없음"
            return
        }
    } else {
        if (-not $cfg.Enabled) { Write-Log "$tag 사용 안 함"; return }
        if ((Get-StepCount $macro) -eq 0) { Write-Log "$tag 매크로가 비어 있음 → 건너뜀"; return }

        if ($cfg.SkipEnabled -and $cfg.SkipPercent -gt 0) {
            if ($S.LastSkipped) {
                Write-Log "$tag 직전 시간에 미작동했으므로 이번 시간은 미작동 판정 없이 실행"
            } else {
                $roll = Get-Random -Minimum 0.0 -Maximum 100.0
                if ($roll -lt $cfg.SkipPercent) {
                    $S.LastSkipped = $true
                    Write-Log ("{0} 확률 미작동 당첨 ({1:N1} < {2}%) → 이번 시간 건너뜀" -f $tag, $roll, $cfg.SkipPercent)
                    return
                }
            }
        }
    }

    if ($forced) { $sMin = 0; $eMin = 10 } else { $sMin = [int]$cfg.StartMin; $eMin = [int]$cfg.EndMin }

    $hourStart = $now.Date.AddHours($hour)
    $winStart  = $hourStart.AddMinutes($sMin)
    $winEnd    = $hourStart.AddMinutes($eMin).AddSeconds(59)
    if ($now -gt $winEnd) {
        Write-Log ("{0} 실행 구간({1:D2}~{2:D2}분)이 이미 지나서 이번 시간은 건너뜀" -f $tag, $sMin, $eMin)
        return
    }
    $from = if ($now -gt $winStart) { $now } else { $winStart }
    $span = [int][Math]::Floor(($winEnd - $from).TotalSeconds)
    $S.PlanTime = $from.AddSeconds((Get-Random -Minimum 0 -Maximum ($span + 1)))
    $S.Macro    = $macro
    $S.Done     = $false

    $kind = if ($forced) { '0~10분 추가 작업' } else { '{0:D2}~{1:D2}분 랜덤' -f $sMin, $eMin }
    Write-Log ("{0} 실행 예정: {1:HH:mm:ss} ({2})" -f $tag, $S.PlanTime, $kind)
}

function Invoke-PlannedRun([datetime]$start = (Get-Date)) {
    $S = $script:S
    Write-Log ('[{0:D2}시] 클릭 작업 실행' -f $start.Hour)
    $ok = Invoke-Macro $S.Macro
    $S.LastSkipped = $false
    $S.LastMacro   = $S.Macro
    if ($start.Minute -ge 50) {
        $S.ForceEarly = $true
        Write-Log ('[{0:D2}시] {1}분에 실행됨 → 다음 시간 0~10분 사이에 추가 작업' -f $start.Hour, $start.Minute)
    }
    if ($ok) { Write-Log '  완료' }
}

function Invoke-SchedulerTick {
    if ($script:Busy) { return }
    $script:Busy = $true
    try {
        $now = Get-Date
        $S = $script:S
        if ($S.LastTick -and ($now - $S.LastTick).TotalSeconds -gt 90) {
            Write-Log ('경고: {0:HH:mm:ss} ~ {1:HH:mm:ss} 동안 프로그램이 멈춰 있었음 (PC 절전/화면 꺼짐/일시정지 등)' -f $S.LastTick, $now)
        }
        $S.LastTick = $now

        if ($now.ToString('yyyyMMddHH') -ne $S.HourKey) {
            if ($S.HourKey -and -not $S.Done -and $S.PlanTime) {
                Write-Log ('[{0:D2}시] 예정 시각 {1:HH:mm:ss}에 실행하지 못하고 시간이 지나감' -f $S.PlanTime.Hour, $S.PlanTime)
            }
            New-HourPlan $now
        }

        if (-not $S.Done -and $S.PlanTime -and $now -ge $S.PlanTime) {
            $S.Done = $true
            $late = ($now - $S.PlanTime).TotalSeconds
            if ($late -gt 60) { Write-Log ('  예정 {0:HH:mm:ss}보다 {1}초 늦게 실행' -f $S.PlanTime, [int]$late) }
            Invoke-PlannedRun
        }

        # 살아 있는지 확인할 수 있도록 10분마다 기록
        $beat = '{0}{1}' -f $now.ToString('yyyyMMddHH'), [int][Math]::Floor($now.Minute / 10)
        if ($beat -ne $S.BeatKey) {
            if ($S.BeatKey -and $now.Minute % 10 -eq 0) { Write-Log ('대기 중 · ' + ((Get-StatusText) -replace '^실행 중 · ', '')) }
            $S.BeatKey = $beat
        }
    } catch {
        Write-Log ("스케줄러 오류: " + $_.Exception.Message)
    } finally {
        $script:Busy = $false
    }
}

function Get-StatusText {
    if (-not $script:Running) { return '중지됨' }
    if (-not $script:S.Done -and $script:S.PlanTime) {
        return ('실행 중 · 다음 클릭 {0:HH:mm:ss}' -f $script:S.PlanTime)
    }
    $next = (Get-Date).Date.AddHours((Get-Date).Hour + 1)
    return ('실행 중 · 이번 시간 작업 없음 (다음 판정 {0:HH:mm})' -f $next)
}

# ---------------------------------------------------------------------------
#  콘솔 실행 모드
# ---------------------------------------------------------------------------
function Start-ConsoleRun {
    Import-ProfileData $script:ProfileNo
    $enabled = @($script:Data.Hours | Where-Object { $_.Enabled -and (Get-StepCount $_.Macro) -gt 0 }).Count
    Write-Host ''
    Write-Host ("  프로필{0} 실행 (사용 시간 {1}개). 종료: Ctrl+C, 매크로 중단: F12" -f $script:ProfileNo, $enabled)
    Write-Host ''
    if ($enabled -eq 0) { Write-Log '사용 중인 시간이 없습니다. GUI에서 먼저 설정하세요.' }
    Reset-State
    $script:Running = $true
    [HumanMouse]::KeepAwake($true)
    try {
        while ($true) {
            Invoke-SchedulerTick
            Start-Sleep -Milliseconds 500
        }
    } finally {
        [HumanMouse]::KeepAwake($false)
    }
}

# ---------------------------------------------------------------------------
#  GUI
# ---------------------------------------------------------------------------
function Show-Gui {
    $script:IsGui = $true
    [System.Windows.Forms.Application]::EnableVisualStyles()

    $form = New-Object System.Windows.Forms.Form
    $form.Text = '시간별 랜덤 클릭 스케줄러'
    $form.ClientSize = New-Object System.Drawing.Size(1050, 720)
    $form.StartPosition = 'CenterScreen'
    $form.FormBorderStyle = 'FixedSingle'
    $form.MaximizeBox = $false
    $form.Font = New-Object System.Drawing.Font('Malgun Gothic', 9)
    $script:Form = $form

    function New-Ctl([string]$type, [int]$x, [int]$y, [int]$w, [int]$h, $text) {
        $c = New-Object "System.Windows.Forms.$type"
        $c.Location = New-Object System.Drawing.Point($x, $y)
        $c.Size = New-Object System.Drawing.Size($w, $h)
        if ($null -ne $text) { $c.Text = $text }
        $script:Form.Controls.Add($c)
        return $c
    }

    # --- 상단 ---
    $null = New-Ctl 'Label' 10 14 45 20 '프로필'
    $cmbProfile = New-Ctl 'ComboBox' 58 10 90 24 $null
    $cmbProfile.DropDownStyle = 'DropDownList'
    [void]$cmbProfile.Items.AddRange(@('프로필1', '프로필2'))
    $btnSave  = New-Ctl 'Button' 158 9 80 27 '저장'
    $btnStart = New-Ctl 'Button' 250 9 90 27 '▶ 시작'
    $btnStop  = New-Ctl 'Button' 346 9 90 27 '■ 중지'
    $btnStop.Enabled = $false
    $chkMin   = New-Ctl 'CheckBox' 448 12 150 22 '시작 시 창 최소화'
    $chkMin.Checked = $true
    $lblStatus = New-Ctl 'Label' 605 14 435 20 '중지됨'
    $lblStatus.ForeColor = [System.Drawing.Color]::DarkBlue

    # --- 시간표 ---
    $grid = New-Ctl 'DataGridView' 10 45 560 562 $null
    $grid.AllowUserToAddRows = $false
    $grid.AllowUserToDeleteRows = $false
    $grid.AllowUserToResizeRows = $false
    $grid.RowHeadersVisible = $false
    $grid.MultiSelect = $false
    $grid.SelectionMode = 'CellSelect'
    $grid.AutoSizeColumnsMode = 'Fill'
    $grid.RowTemplate.Height = 22
    $grid.ColumnHeadersHeightSizeMode = 'DisableResizing'
    $grid.ColumnHeadersHeight = 26
    $script:Grid = $grid

    $cols = @(
        @('TextBox',  'Hour',  '시간',        $true),
        @('CheckBox', 'Use',   '사용',        $false),
        @('TextBox',  'Start', '시작분',      $false),
        @('TextBox',  'End',   '끝분',        $false),
        @('CheckBox', 'Skip',  '확률미작동',  $false),
        @('TextBox',  'Pct',   '확률(%)',     $false),
        @('TextBox',  'Steps', '단계수',      $true)
    )
    foreach ($c in $cols) {
        $col = New-Object ("System.Windows.Forms.DataGridView{0}Column" -f $c[0])
        $col.Name = $c[1]
        $col.HeaderText = $c[2]
        $col.ReadOnly = $c[3]
        $col.SortMode = 'NotSortable'
        [void]$grid.Columns.Add($col)
    }
    $grid.Columns['Hour'].DefaultCellStyle.BackColor = [System.Drawing.Color]::WhiteSmoke
    $grid.Columns['Steps'].DefaultCellStyle.BackColor = [System.Drawing.Color]::WhiteSmoke

    # --- 매크로 편집 ---
    $lblSel = New-Ctl 'Label' 585 48 455 20 '선택한 시간의 매크로'
    $lblSel.Font = New-Object System.Drawing.Font('Malgun Gothic', 9, [System.Drawing.FontStyle]::Bold)
    $txtMacro = New-Ctl 'TextBox' 585 70 455 250 $null
    $txtMacro.Multiline = $true
    $txtMacro.ScrollBars = 'Vertical'
    $txtMacro.AcceptsReturn = $true
    $txtMacro.Font = New-Object System.Drawing.Font('Consolas', 10)

    $chkCap = New-Ctl 'CheckBox' 585 330 165 22 'F8 키로 좌표 기록'
    $cmbCap = New-Ctl 'ComboBox' 752 329 85 24 $null
    $cmbCap.DropDownStyle = 'DropDownList'
    [void]$cmbCap.Items.AddRange(@('CLICK', 'RCLICK', 'DCLICK', 'MOVE'))
    $cmbCap.SelectedIndex = 0
    $chkCapWait = New-Ctl 'CheckBox' 845 330 195 22 '기록 시 WAIT 자동 추가'
    $chkCapWait.Checked = $true

    $btnTest     = New-Ctl 'Button' 585 360 145 28 '선택 매크로 테스트'
    $btnCopyMac  = New-Ctl 'Button' 738 360 150 28 '매크로 → 모든 시간'
    $btnCopyCfg  = New-Ctl 'Button' 896 360 144 28 '설정 → 모든 시간'

    $help = @'
[매크로 명령] 한 줄에 하나씩
  CLICK x y [r]    좌클릭  (r = 랜덤 오차 반경px, 기본 3)
  RCLICK x y [r]   우클릭        DCLICK x y [r]  더블클릭
  MOVE x y [r]     이동만        MCLICK x y [r]  휠클릭
  WAIT a [b]       a~b ms 사이 랜덤 대기
  KEY 텍스트       키 입력 (SendKeys: {ENTER} {TAB} ^c %{F4})
  SCROLL n         휠 n칸 (+위, -아래)
  # 주석

[동작 규칙]
 · 매 시간 [시작분~끝분] 사이 랜덤 시각에 1회 실행
 · 확률미작동 체크 시 확률(%)에 걸리면 그 시간은 건너뜀
   (직전 시간에 건너뛰었으면 이번 시간은 반드시 실행)
 · 50분 이후에 실행되면 다음 시간 0~10분 사이에 추가 실행
 · 실행 중 수정한 내용은 다음 시간부터 반영 / F12: 매크로 중단
'@
    $lblHelp = New-Ctl 'Label' 585 398 455 210 $help
    $lblHelp.Font = New-Object System.Drawing.Font('Malgun Gothic', 8.5)

    # --- 로그 ---
    $txtLog = New-Ctl 'TextBox' 10 615 1030 95 $null
    $txtLog.Multiline = $true
    $txtLog.ReadOnly = $true
    $txtLog.ScrollBars = 'Vertical'
    $txtLog.BackColor = [System.Drawing.Color]::White
    $script:LogBox = $txtLog

    $script:Loading = $false
    $script:SelHour = 0
    $script:F8Prev  = $false

    # --- 데이터 <-> 화면 ---
    $fillGrid = {
        $script:Loading = $true
        $grid.Rows.Clear()
        for ($i = 0; $i -lt 24; $i++) {
            $h = $script:Data.Hours[$i]
            [void]$grid.Rows.Add([object[]]@(
                ('{0:D2}시' -f $i), [bool]$h.Enabled, [string]$h.StartMin, [string]$h.EndMin,
                [bool]$h.SkipEnabled, [string]$h.SkipPercent, [string](Get-StepCount $h.Macro)))
        }
        $script:Loading = $false
        $grid.CurrentCell = $grid.Rows[(Get-Date).Hour].Cells['Hour']
        & $selectHour (Get-Date).Hour
    }

    $selectHour = {
        param([int]$i)
        $script:SelHour = $i
        $script:Loading = $true
        $txtMacro.Text = [string]$script:Data.Hours[$i].Macro
        $script:Loading = $false
        $lblSel.Text = ('{0:D2}시 매크로  (프로필{1})' -f $i, $script:ProfileNo)
    }

    $readRow = {
        param([int]$r)
        $row = $grid.Rows[$r]
        $h = $script:Data.Hours[$r]
        $h.Enabled     = [bool]$row.Cells['Use'].Value
        $h.SkipEnabled = [bool]$row.Cells['Skip'].Value
        $h.StartMin    = Limit-Range (ConvertTo-IntOr $row.Cells['Start'].Value $h.StartMin) 0 59
        $h.EndMin      = Limit-Range (ConvertTo-IntOr $row.Cells['End'].Value $h.EndMin) 0 59
        $h.SkipPercent = Limit-Range (ConvertTo-IntOr $row.Cells['Pct'].Value $h.SkipPercent) 0 100
        if ($h.StartMin -gt $h.EndMin) { $t = $h.StartMin; $h.StartMin = $h.EndMin; $h.EndMin = $t }
        $script:Loading = $true
        $row.Cells['Start'].Value = [string]$h.StartMin
        $row.Cells['End'].Value   = [string]$h.EndMin
        $row.Cells['Pct'].Value   = [string]$h.SkipPercent
        $script:Loading = $false
    }

    $grid.Add_CurrentCellDirtyStateChanged({
        if ($grid.IsCurrentCellDirty -and $grid.CurrentCell -is [System.Windows.Forms.DataGridViewCheckBoxCell]) {
            [void]$grid.CommitEdit([System.Windows.Forms.DataGridViewDataErrorContexts]::Commit)
        }
    })
    $grid.Add_CellValueChanged({
        param($sender, $e)
        if ($script:Loading -or $e.RowIndex -lt 0) { return }
        & $readRow $e.RowIndex
    })
    $grid.Add_SelectionChanged({
        if ($script:Loading -or $null -eq $grid.CurrentCell) { return }
        $r = $grid.CurrentCell.RowIndex
        if ($r -ne $script:SelHour) { & $selectHour $r }
    })
    $grid.Add_DataError({ param($sender, $e) $e.ThrowException = $false })

    $txtMacro.Add_TextChanged({
        if ($script:Loading) { return }
        $script:Data.Hours[$script:SelHour].Macro = $txtMacro.Text
        $script:Loading = $true
        $grid.Rows[$script:SelHour].Cells['Steps'].Value = [string](Get-StepCount $txtMacro.Text)
        $script:Loading = $false
    })

    # --- 프로필 ---
    $cmbProfile.Add_SelectedIndexChanged({
        $no = $cmbProfile.SelectedIndex + 1
        if ($no -eq $script:ProfileNo -and $null -ne $script:Data) { return }
        if ($null -ne $script:Data) {
            [void]$grid.EndEdit()
            Export-ProfileData $script:ProfileNo
            Write-Log '저장됨 (프로필 전환)'
        }
        $script:ProfileNo = $no
        Import-ProfileData $no
        & $fillGrid
        Write-Log '프로필 불러옴'
    })

    $btnSave.Add_Click({
        [void]$grid.EndEdit()
        try {
            Export-ProfileData $script:ProfileNo
            Write-Log ('저장 완료 → ' + (Get-ProfilePath $script:ProfileNo))
        } catch {
            [void][System.Windows.Forms.MessageBox]::Show('저장 실패: ' + $_.Exception.Message)
        }
    })

    # --- 실행 / 중지 ---
    $btnStart.Add_Click({
        [void]$grid.EndEdit()
        Export-ProfileData $script:ProfileNo
        $cnt = @($script:Data.Hours | Where-Object { $_.Enabled -and (Get-StepCount $_.Macro) -gt 0 }).Count
        if ($cnt -eq 0) {
            [void][System.Windows.Forms.MessageBox]::Show('사용 체크 + 매크로가 입력된 시간이 하나도 없습니다.', '알림')
            return
        }
        Reset-State
        $script:Running = $true
        [HumanMouse]::KeepAwake($true)
        $btnStart.Enabled = $false; $btnStop.Enabled = $true; $cmbProfile.Enabled = $false
        Write-Log ("스케줄 시작 (사용 시간 {0}개)" -f $cnt)
        Invoke-SchedulerTick
        $lblStatus.Text = Get-StatusText
        if ($chkMin.Checked) { $form.WindowState = 'Minimized' }
    })

    $btnStop.Add_Click({
        $script:Running = $false
        [HumanMouse]::KeepAwake($false)
        $btnStart.Enabled = $true; $btnStop.Enabled = $false; $cmbProfile.Enabled = $true
        Write-Log '스케줄 중지'
        $lblStatus.Text = Get-StatusText
    })

    # --- 테스트 / 복사 ---
    $btnTest.Add_Click({
        $m = [string]$script:Data.Hours[$script:SelHour].Macro
        if ((Get-StepCount $m) -eq 0) { [void][System.Windows.Forms.MessageBox]::Show('매크로가 비어 있습니다.'); return }
        if ($script:Busy) { return }
        $script:Busy = $true
        try {
            Write-Log ('[{0:D2}시] 매크로 테스트 (2초 후 시작, F12 중단)' -f $script:SelHour)
            $form.WindowState = 'Minimized'
            Wait-Ms 2000
            [void](Invoke-Macro $m)
            Write-Log '  테스트 끝'
        } finally {
            $script:Busy = $false
            $form.WindowState = 'Normal'
            $form.Activate()
        }
    })

    $btnCopyMac.Add_Click({
        $src = $script:Data.Hours[$script:SelHour]
        $ans = [System.Windows.Forms.MessageBox]::Show(
            ('{0:D2}시 매크로를 다른 모든 시간에 복사할까요?' -f $script:SelHour), '확인', 'YesNo')
        if ($ans -ne 'Yes') { return }
        foreach ($h in $script:Data.Hours) { $h.Macro = $src.Macro }
        & $fillGrid
        $grid.CurrentCell = $grid.Rows[$src.Hour].Cells['Hour']
        & $selectHour $src.Hour
        Write-Log '매크로를 모든 시간에 복사함 (저장 버튼을 눌러야 파일에 저장)'
    })

    $btnCopyCfg.Add_Click({
        [void]$grid.EndEdit()
        $src = $script:Data.Hours[$script:SelHour]
        $ans = [System.Windows.Forms.MessageBox]::Show(
            ('{0:D2}시의 사용/시작분/끝분/확률미작동 설정을 모든 시간에 복사할까요?' -f $script:SelHour), '확인', 'YesNo')
        if ($ans -ne 'Yes') { return }
        foreach ($h in $script:Data.Hours) {
            $h.Enabled = $src.Enabled; $h.StartMin = $src.StartMin; $h.EndMin = $src.EndMin
            $h.SkipEnabled = $src.SkipEnabled; $h.SkipPercent = $src.SkipPercent
        }
        & $fillGrid
        $grid.CurrentCell = $grid.Rows[$src.Hour].Cells['Hour']
        & $selectHour $src.Hour
        Write-Log '시간 설정을 모든 시간에 복사함 (저장 버튼을 눌러야 파일에 저장)'
    })

    # --- 타이머 (스케줄 + F8 좌표 기록) ---
    $timer = New-Object System.Windows.Forms.Timer
    $timer.Interval = 300
    $timer.Add_Tick({
      try {
        if ($chkCap.Checked) {
            $down = [HumanMouse]::IsKeyDown(0x77)   # F8
            if ($down -and -not $script:F8Prev) {
                $p = [HumanMouse]::GetPos()
                $add = ''
                if ($txtMacro.Text.Length -gt 0 -and -not $txtMacro.Text.EndsWith("`n")) { $add += "`r`n" }
                if ($chkCapWait.Checked -and (Get-StepCount $txtMacro.Text) -gt 0) { $add += "WAIT 400 1200`r`n" }
                $add += ('{0} {1} {2}' -f $cmbCap.SelectedItem, $p[0], $p[1])
                $txtMacro.AppendText($add)
            }
            $script:F8Prev = $down
        }
        if ($script:Running) {
            Invoke-SchedulerTick
            $lblStatus.Text = Get-StatusText
        }
      } catch {
        Write-Log ('타이머 오류: ' + $_.Exception.Message)
      }
    })

    $form.Add_FormClosing({
        $timer.Stop()
        try { [void]$grid.EndEdit(); Export-ProfileData $script:ProfileNo } catch { }
        [HumanMouse]::KeepAwake($false)
    })

    $cmbProfile.SelectedIndex = $script:ProfileNo - 1
    if ($null -eq $script:Data) { Import-ProfileData $script:ProfileNo; & $fillGrid }
    $timer.Start()
    [void]$form.ShowDialog()
    $timer.Dispose()
}

# ---------------------------------------------------------------------------
if ($Run) { Start-ConsoleRun } else { Show-Gui }
