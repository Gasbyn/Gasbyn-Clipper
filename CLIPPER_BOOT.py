"""Vstupní bod: napojí hlášení chyb a spustí Gasbyn Clipper."""
from __future__ import annotations

def main() -> None:
    from app import App
    try:
        import ui_bugreport
        ui_bugreport.install(App)
    except Exception:
        pass
    App().mainloop()


if __name__ == "__main__":
    main()
