$ErrorActionPreference = "Stop"
Start-Process `
    -FilePath "explorer.exe" `
    -ArgumentList "http://127.0.0.1:18000/control"
