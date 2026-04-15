import sys

path = r'c:\Users\ernan\Downloads\agente stoa\main.py'
content = open(path, encoding='utf-8').read()

old = '@app.post("/api/command")\nasync def process_command(command: VoiceCommand):'

new = (
    '@app.post("/api/voice")\n'
    'async def transcribe_voice(file: UploadFile = File(...)):\n'
    '    """Recebe áudio (webm/ogg/mp4) e transcreve com Whisper"""\n'
    '    try:\n'
    '        audio_bytes = await file.read()\n'
    '        suffix = ".webm"\n'
    '        if file.filename:\n'
    '            ext = Path(file.filename).suffix.lower()\n'
    '            if ext in {".ogg", ".mp3", ".mp4", ".wav", ".m4a"}:\n'
    '                suffix = ext\n'
    '        import tempfile\n'
    '        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:\n'
    '            tmp.write(audio_bytes)\n'
    '            tmp_path = tmp.name\n'
    '        try:\n'
    '            with open(tmp_path, "rb") as audio_file:\n'
    '                transcription = OpenAIAdapter.client.audio.transcriptions.create(\n'
    '                    model="whisper-1",\n'
    '                    file=audio_file,\n'
    '                    language="pt",\n'
    '                )\n'
    '            text = transcription.text.strip()\n'
    '        finally:\n'
    '            Path(tmp_path).unlink(missing_ok=True)\n'
    '        return {"text": text, "language": "pt-BR"}\n'
    '    except Exception as e:\n'
    '        logger.exception("Erro na transcrição de voz")\n'
    '        raise HTTPException(status_code=500, detail=str(e))\n'
    '\n'
    '\n'
    '@app.post("/api/command")\n'
    'async def process_command(command: VoiceCommand):'
)

if old not in content:
    print('ERROR: anchor not found')
    sys.exit(1)

content = content.replace(old, new, 1)
open(path, 'w', encoding='utf-8').write(content)
print('OK')
