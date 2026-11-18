# Legacy scripts

One-off development scripts from earlier phases, moved out of the project root.

- They are **not** part of the test suite. Some have real side effects, for example
  `test_notepad.py` types into Notepad and `test_mic.py` records from the microphone.
- Several assume they run from the project root, or hard-code `D:\Jarvis`.
- `jarvis_install.py` and `install_voice.bat` are out of date. Use `requirements.txt` instead.

The real automated tests live in `tests/`.
