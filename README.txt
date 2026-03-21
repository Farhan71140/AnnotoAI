================================================
  AnnotoAI - Complete Setup Guide
  DesicrewAI Internship Tool - 100% FREE
================================================

WHAT'S IN THIS FOLDER:
-----------------------
1_SETUP.bat         → Run ONCE to install everything
2_TRANSCRIBE.bat    → Run DAILY to transcribe audio
transcribe.py       → Python script (don't delete)
annotation_tool.html → Open in browser daily
README.txt          → This file


FIRST TIME SETUP (Do this ONCE):
---------------------------------
1. Make sure Python is installed
   - Open CMD and type: python --version
   - If you see a version number, you're good!
   - If not, download from: https://python.org

2. Double-click: 1_SETUP.bat
   - Wait for it to finish (2-5 minutes)
   - It installs Whisper and all dependencies

3. Install ffmpeg (needed for audio):
   - Download from: https://ffmpeg.org/download.html
   - Or try: winget install ffmpeg (in CMD)


DAILY WORKFLOW:
--------------
STEP 1: Put your .wav file in this folder

STEP 2: Double-click 2_TRANSCRIBE.bat
        - Drag your .wav file into the black window
        - Press Enter
        - Wait ~30-60 seconds
        - It creates: transcript_output.json

STEP 3: Open transcript_output.json with Notepad
        - Press Ctrl+A to select all
        - Press Ctrl+C to copy

STEP 4: Open annotation_tool.html in Chrome/Edge

STEP 5: Paste the JSON into the tool
        - Click "Load Whisper Output"

STEP 6: Add the Reference Text
        (the text the participant was supposed to read)

STEP 7: Add any notes about what you heard
        (stutters, noise, fillers etc.)

STEP 8: Click "Apply All PDF Annotation Rules"
        - Claude AI applies all rules automatically!

STEP 9: Download the final JSON
        - Use it in Annotic!


ANNOTATION TAGS (from PDF):
-----------------------------
<SIL></SIL>     = Silence longer than 2 seconds
<MB></MB>       = Mumbling/unintelligible speech
<NOISE></NOISE> = Background noise
<FIL></FIL>     = Filler sounds (aaah, ummm)
<LN></LN>       = Letter names spelled out


TROUBLESHOOTING:
----------------
Q: 2_TRANSCRIBE.bat shows an error
A: Make sure you ran 1_SETUP.bat first
   Also make sure ffmpeg is installed

Q: "whisper not found" error
A: Run: pip install openai-whisper (in CMD)

Q: Transcription is slow
A: Normal! Whisper takes 20-60s for a 2min audio

Q: annotation_tool.html not working
A: Open in Chrome or Edge browser (not IE)

Q: JSON not loading
A: Make sure you copied the ENTIRE content of
   transcript_output.json (Ctrl+A then Ctrl+C)


TIPS:
------
- Keep all files in the SAME folder
- Use Chrome or Edge browser for best results
- The tool works 100% offline for Whisper
- Only the annotation step needs internet (Claude AI)


================================================
  Built for DesicrewAI Internship
  Spoken English Assessment & Practice Jan 2026
================================================
