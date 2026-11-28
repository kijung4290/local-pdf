from string import Template

from PySide6.QtGui import QColor, QPalette


THEMES = {
    "light": {
        "chrome": "#f3f4f6", "panel": "#ecedf1", "surface": "#ffffff", "canvas": "#dce0e7",
        "text": "#232732", "muted": "#555e6e", "disabled": "#737a86", "line": "#ced3dc",
        "quiet": "#e3e6ed", "hover": "#e2e7f0", "accent": "#2452be", "accent_hover": "#1c43a4",
        "focus": "#4676e9", "selected": "#dce7ff", "selected_text": "#2049a9",
        "on_accent": "#ffffff", "scroll": "#a7afbe", "danger": "#a3313b",
    },
    "dark": {
        "chrome": "#272a32", "panel": "#23262e", "surface": "#313540", "canvas": "#191c23",
        "text": "#edf0f6", "muted": "#bdc6d6", "disabled": "#949dae", "line": "#484e5d",
        "quiet": "#373c48", "hover": "#414959", "accent": "#9cb8ff", "accent_hover": "#b7caff",
        "focus": "#a0bbff", "selected": "#344673", "selected_text": "#e2ebff",
        "on_accent": "#192c54", "scroll": "#6e788c", "danger": "#ffacb1",
    },
}


def apply_appearance(app, stylesheet, dark):
    colors = THEMES["dark" if dark else "light"]
    palette = QPalette()
    for role, color in {
        "Window": "chrome", "WindowText": "text", "Base": "surface", "AlternateBase": "panel",
        "Text": "text", "Button": "quiet", "ButtonText": "text", "ToolTipBase": "text",
        "ToolTipText": "surface", "PlaceholderText": "muted",
        "Highlight": "accent", "HighlightedText": "on_accent",
    }.items():
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(colors[color]))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(colors["disabled"]))
    app.setPalette(palette)
    app.setStyleSheet(Template(stylesheet).substitute(colors))
    return colors
