$ErrorActionPreference = "Stop"

function Get-EnvMap {
    param([string]$Path)

    $map = @{}
    if (-not (Test-Path $Path)) {
        return $map
    }

    foreach ($line in Get-Content $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }
        $parts = $trimmed -split "=", 2
        if ($parts.Count -eq 2) {
            $map[$parts[0].Trim()] = $parts[1].Trim()
        }
    }
    return $map
}

function Normalize-Text {
    param([string]$Text)

    if (-not $Text) {
        return ""
    }
    return ($Text.ToLowerInvariant() -replace "\s+", " ").Trim()
}

function Extract-Command {
    param(
        [string]$Transcript,
        [string]$WakeWord
    )

    $normalizedTranscript = Normalize-Text $Transcript
    $normalizedWakeWord = Normalize-Text $WakeWord

    if (-not $normalizedWakeWord) {
        return $normalizedTranscript
    }

    $index = $normalizedTranscript.LastIndexOf($normalizedWakeWord)
    if ($index -lt 0) {
        return ""
    }

    $command = $normalizedTranscript.Substring($index + $normalizedWakeWord.Length).Trim()
    $command = $command -replace "^[,:-]\s*", ""
    return $command.Trim()
}

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$envPath = Join-Path $projectRoot ".env.safe"
$logDir = Join-Path $projectRoot "logs"
$logFile = Join-Path $logDir "jarvis-voice.log"
$envMap = Get-EnvMap -Path $envPath

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$accessToken = $envMap["STOA_ACCESS_TOKEN"]
if (-not $accessToken) {
    throw "STOA_ACCESS_TOKEN não encontrado em .env.safe"
}

$wakeWord = if ($envMap["STOA_WAKE_WORD"]) { $envMap["STOA_WAKE_WORD"] } elseif ($envMap["JARVIS_WAKE_WORD"]) { $envMap["JARVIS_WAKE_WORD"] } else { "stoa" }
$voiceEndpoint = if ($envMap["STOA_VOICE_ENDPOINT"]) { $envMap["STOA_VOICE_ENDPOINT"] } elseif ($envMap["JARVIS_VOICE_ENDPOINT"]) { $envMap["JARVIS_VOICE_ENDPOINT"] } else { "http://127.0.0.1:18000/api/coworker/intake" }
$voiceMode = if ($envMap["STOA_VOICE_MODE"]) { $envMap["STOA_VOICE_MODE"] } elseif ($envMap["JARVIS_VOICE_MODE"]) { $envMap["JARVIS_VOICE_MODE"] } else { "builder" }
$voiceSessionId = if ($envMap["STOA_VOICE_SESSION_ID"]) { $envMap["STOA_VOICE_SESSION_ID"] } elseif ($envMap["JARVIS_VOICE_SESSION_ID"]) { $envMap["JARVIS_VOICE_SESSION_ID"] } else { "" }
$confidenceThreshold = if ($envMap["STOA_VOICE_CONFIDENCE"]) { [double]$envMap["STOA_VOICE_CONFIDENCE"] } elseif ($envMap["JARVIS_VOICE_CONFIDENCE"]) { [double]$envMap["JARVIS_VOICE_CONFIDENCE"] } else { 0.70 }
$cooldownSeconds = if ($envMap["STOA_VOICE_COOLDOWN_SECONDS"]) { [int]$envMap["STOA_VOICE_COOLDOWN_SECONDS"] } elseif ($envMap["JARVIS_VOICE_COOLDOWN_SECONDS"]) { [int]$envMap["JARVIS_VOICE_COOLDOWN_SECONDS"] } else { 8 }

Add-Type -AssemblyName System.Speech

$engine = New-Object System.Speech.Recognition.SpeechRecognitionEngine
$engine.SetInputToDefaultAudioDevice()
$engine.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar))

$script:lastCommand = ""
$script:lastSentAt = [datetime]::MinValue

Register-ObjectEvent -InputObject $engine -EventName SpeechRecognized -Action {
    try {
        $result = $Event.SourceEventArgs.Result
        if (-not $result) {
            return
        }
        if ($result.Confidence -lt $confidenceThreshold) {
            return
        }

        $transcript = $result.Text
        $command = Extract-Command -Transcript $transcript -WakeWord $wakeWord
        if (-not $command) {
            return
        }

        $now = Get-Date
        if ($script:lastCommand -eq $command -and ($now - $script:lastSentAt).TotalSeconds -lt $cooldownSeconds) {
            return
        }

        $payload = @{
            text = $command
            mode = $voiceMode
            session_id = if ($voiceSessionId) { $voiceSessionId } else { $null }
        } | ConvertTo-Json

        $response = Invoke-RestMethod `
            -Method Post `
            -Uri $voiceEndpoint `
            -Headers @{ Authorization = "Bearer $accessToken" } `
            -ContentType "application/json" `
            -Body $payload

        $script:lastCommand = $command
        $script:lastSentAt = $now

        $logLine = @{
            timestamp = $now.ToString("s")
            transcript = $transcript
            command = $command
            response = $response
        } | ConvertTo-Json -Depth 6
        Add-Content -Path $logFile -Value $logLine
    } catch {
        Add-Content -Path $logFile -Value ("{0} ERROR {1}" -f (Get-Date).ToString("s"), $_.Exception.Message)
    }
} | Out-Null

Add-Content -Path $logFile -Value ("{0} Voice listener started with wake word '{1}'" -f (Get-Date).ToString("s"), $wakeWord)
$engine.RecognizeAsync([System.Speech.Recognition.RecognizeMode]::Multiple)

try {
    while ($true) {
        Start-Sleep -Seconds 5
    }
} finally {
    $engine.RecognizeAsyncStop()
    $engine.Dispose()
}
