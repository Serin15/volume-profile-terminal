"""
Lanseaza terminalul desktop de Volume Profile.

    .venv\\Scripts\\python run_desktop.py
"""

from app.desktop.main import main

if __name__ == "__main__":
    app, win = main()
    app.exec()
