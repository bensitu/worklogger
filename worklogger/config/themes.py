"""Theme colors, cell palettes, and work-type accent colors."""

THEME_KEYS = ["blue", "pink", "green", "purple"]
THEME_NAMES = {
    "blue":   "🔵 Blue",
    "pink":   "🌸 Pink",
    "green":  "🌿 Green",
    "purple": "🟣 Purple",
}

# THEMES[theme][dark] = (accent, hover, dim, stat_background, stat_border)
THEMES = {
    "blue": {
        False: ("#4f8ef7", "#3070d8", "#e8f0fe", "#eef2ff", "#cdd5f0"),
        True:  ("#5a9ff5", "#3d87e8", "#1a3058", "#1a1e3a", "#2d3360"),
    },
    "pink": {
        False: ("#e05888", "#c03868", "#fce8f0", "#fff0f7", "#f0c8dc"),
        True:  ("#f07aaa", "#d85888", "#3a1028", "#2a1020", "#501838"),
    },
    "green": {
        False: ("#2daa7a", "#1a8a58", "#e0f5ec", "#edfaf4", "#bce8d4"),
        True:  ("#3dcc8a", "#2aaa68", "#0e3028", "#0a2820", "#1a5040"),
    },
    "purple": {
        False: ("#7c55d6", "#5c38b8", "#ede8ff", "#f2efff", "#cfc8f0"),
        True:  ("#9a78f0", "#7c55d6", "#261852", "#1a1038", "#3a2868"),
    },
}


def cell_pool(dark: bool, theme: str) -> dict:
    """Return cell color dict for the given dark/theme combo."""
    acc = THEMES[theme][dark][0]
    if dark:
        return {
            "default":  ("#1e2030", "#c0c8e0", "#2d2f4a", "1"),
            "today":    ("#2e2a00", "#ffd855", "#aa9500", "2"),
            "weekend":  ("#0c1d3c", "#5aafff", "#1a3a6a", "1"),
            "holiday":  ("#3c0d0d", "#ff7777", "#802020", "1"),
            "selected": (acc,      "#ffffff", acc,     "2"),
        }
    return {
        "default":  ("#ffffff", "#1e2035", "#dde1ee", "1"),
        "today":    ("#fffce0", "#8a6800", "#e0c800", "2"),
        "weekend":  ("#eef3ff", "#1e5cc4", "#b8cfff", "1"),
        "holiday":  ("#fff0f0", "#cc2222", "#ffaaaa", "1"),
        "selected": (acc,      "#ffffff", acc,     "2"),
    }


STYLE_PRIO = ["weekend", "today", "holiday", "selected"]

# Per-work-type accent color for calendar cells. None disables the stripe.
WT_BORDER_ACCENT = {
    True: {
        "normal": None, "remote": None,
        "business_trip": "#ffaa44", "paid_leave": "#66cc66",
        "comp_leave": "#bb88ff", "sick_leave": "#ff6666",
    },
    False: {
        "normal": None, "remote": None,
        "business_trip": "#e07800", "paid_leave": "#2a9a2a",
        "comp_leave": "#8844cc", "sick_leave": "#cc3333",
    },
}


def make_qss(dark: bool, theme: str = "blue") -> str:
    """Generate full application QSS stylesheet."""
    acc, acc_hov, acc_dim, stat_bg, stat_bd = THEMES[theme][dark]
    if dark:
        bg, surf, bdr = "#13141d", "#1c1d2b", "#2d2f48"
        txt, txt2 = "#c8cde8", "#8890b8"
        inp_bg, inp_bd = "#181928", "#33365a"
        btn, btn_bd, hov = "#232438", "#333558", "#2c2e50"
        dis_bg, dis_bd = "#1b1c2a", "#2a2c44"
        dis_txt, dis_t2 = "#6f7699", "#5c627d"
        ot = "#ff8585"
        tip_bg, tip_bdr = "#252640", "#3d3f60"
    else:
        bg, surf, bdr = "#f0f2f7", "#ffffff", "#dde1ee"
        txt, txt2 = "#1e2035", "#606888"
        inp_bg, inp_bd = "#ffffff", "#d0d5e8"
        btn, btn_bd, hov = "#f4f5fa", "#dde1ee", "#e8ecf8"
        dis_bg, dis_bd = "#eef1f7", "#d9dfef"
        dis_txt, dis_t2 = "#9aa3bb", "#aab1c5"
        ot = "#cc2222"
        tip_bg, tip_bdr = "#ffffff", "#c8d0e8"

    return f"""
QWidget{{background-color:{bg};color:{txt};font-size:13px;
  font-family:-apple-system,"Segoe UI","Noto Sans",sans-serif;}}
QDialog{{background-color:{surf};}}
QFrame#sidebar{{background-color:{surf};border-left:1px solid {bdr};}}
QLabel{{background:transparent;color:{txt};}}
QLabel#muted{{color:{txt2};font-size:11px;font-weight:600;}}
QLabel#time_value{{background:{btn};border:1px solid {btn_bd};border-radius:6px;
  padding:3px 8px;color:{txt};font-weight:600;}}
QLabel#month_title{{font-size:17px;font-weight:bold;color:{txt};}}
QLabel#date_banner{{font-size:19px;font-weight:bold;color:{txt};}}
QLabel#week_lbl{{color:{txt2};font-size:11px;background:transparent;}}
QLabel#week_total_lbl{{color:{txt2};font-size:10px;background:transparent;}}
QLabel#stat_val_leave{{color:{txt};font-size:13px;font-weight:bold;
  border-bottom:1px dotted {txt2};}}
QFrame#stat_card{{background-color:{stat_bg};border:1px solid {stat_bd};border-radius:12px;}}
QFrame#stat_card QLabel{{background:transparent;}}
QLabel#stat_key{{color:{txt2};font-size:11px;}}
QLabel#stat_val{{color:{txt};font-size:13px;font-weight:bold;}}
QLabel#stat_val_ot{{color:{ot};font-size:13px;font-weight:bold;}}
QFrame#divider{{background:{bdr};max-height:1px;min-height:1px;border:none;}}
QToolTip{{background-color:{tip_bg};color:{txt};border:1px solid {tip_bdr};
  padding:5px 8px;border-radius:6px;font-size:12px;}}
QPushButton#nav_btn{{background:transparent;border:none;color:{txt2};
  font-size:17px;padding:2px 10px;border-radius:6px;}}
QPushButton#nav_btn:hover{{background:{hov};color:{acc};}}
QTabWidget::pane{{border:1px solid {bdr};border-radius:8px;background:{surf};}}
QTabBar::tab{{background:{btn};border:1px solid {btn_bd};padding:6px 16px;
  border-top-left-radius:6px;border-top-right-radius:6px;color:{txt2};}}
QTabBar::tab:selected{{background:{surf};color:{txt};border-bottom:none;}}
QTabBar::tab:hover{{background:{hov};color:{txt};}}

QTabWidget#time_tabs::pane{{border:1px solid {bdr};border-radius:12px;background:{surf};
  margin-top:5px;top:0px;}}
QTabWidget#time_tabs{{background:transparent;border:none;}}
QTabWidget#time_tabs QTabBar{{alignment:center;}}
QTabWidget#time_tabs QTabBar::tab{{background:transparent;
  min-width:124px;padding:6px 0px;border-radius:0px;margin:0;color:{txt2};}}
QTabWidget#time_tabs QTabBar::tab:selected{{background:{acc_dim};border-top:2px solid {acc};
  color:{txt};}}
QTabWidget#time_tabs QTabBar::tab:hover{{background:{hov};border-top:2px solid {acc};
  color:{txt};}}
QWidget#time_tab_panel{{background:{surf};border:none;}}
QListWidget{{background:{surf};border:1px solid {bdr};border-radius:10px;
  outline:none;padding:4px;}}
QListWidget::item{{border-radius:8px;padding:6px 8px;margin:2px 0;}}
QListWidget::item:selected{{background:{acc_dim};color:{txt};border:1px solid {acc};}}
QListWidget::item:hover{{background:{hov};}}
QComboBox{{background:{btn};border:1px solid {btn_bd};border-radius:6px;
  padding:4px 8px;color:{txt};font-size:12px;}}
QComboBox::drop-down{{border:none;width:20px;}}
QComboBox QAbstractItemView{{background:{surf};border:1px solid {bdr};color:{txt};
  font-size:12px;selection-background-color:{acc};selection-color:#ffffff;outline:none;}}
QDoubleSpinBox{{background:{inp_bg};border:1px solid {inp_bd};
  border-radius:8px;padding:5px 8px;color:{txt};}}
QDoubleSpinBox::up-button,QDoubleSpinBox::down-button{{width:18px;}}
QCheckBox{{color:{txt};spacing:8px;}}
QCheckBox::indicator{{width:16px;height:16px;border:1px solid {btn_bd};
  border-radius:4px;background:{btn};}}
QCheckBox::indicator:checked{{background:{acc};border-color:{acc};}}
QPushButton{{background:{btn};border:1px solid {btn_bd};border-radius:8px;
  padding:7px 14px;color:{txt};}}
QPushButton:hover{{background:{hov};border-color:{acc};}}
QPushButton:pressed{{background:{acc_dim};}}
QPushButton:disabled{{background:{dis_bg};border:1px solid {dis_bd};color:{dis_txt};}}
QPushButton#primary_btn{{background:{acc};color:#ffffff;border:none;
  font-weight:600;border-radius:8px;padding:8px 14px;}}
QPushButton#primary_btn:hover{{background:{acc_hov};color:#ffffff;border:none;}}
QPushButton#primary_btn:pressed{{background:{acc_dim};color:{txt};border:1px solid {btn_bd};}}
QPushButton#primary_btn:disabled{{background:{acc_dim};border:none;color:{dis_t2};}}
QPushButton#clock_btn{{background:{acc_dim};border:1px solid {acc};
  border-radius:6px;color:{acc};padding:5px 10px;font-size:12px;
  font-weight:600;min-width:52px;}}
QPushButton#clock_btn:hover{{background:{acc};color:#ffffff;}}
QPushButton#clock_btn:disabled{{background:{dis_bg};border-color:{dis_bd};color:{dis_txt};}}
QPushButton#action_btn{{background:{btn};border:1px solid {btn_bd};
  border-radius:8px;padding:7px 10px;color:{txt2};font-size:12px;}}
QPushButton#action_btn:hover{{background:{hov};border-color:{acc};color:{txt};}}
QPushButton#action_btn:disabled{{background:{dis_bg};border-color:{dis_bd};color:{dis_txt};}}
QLineEdit,QTextEdit,QPlainTextEdit{{background:{inp_bg};border:1px solid {inp_bd};
  border-radius:8px;padding:4px 8px;color:{txt};}}
QTabWidget#time_tabs QLineEdit{{min-height:15px;padding:5px 10px;line-height:18px;font-size:13px;}}
QLineEdit::placeholder,QTextEdit::placeholder,QPlainTextEdit::placeholder{{color:{txt2};}}
QLineEdit:focus,QTextEdit:focus,QPlainTextEdit:focus{{border-color:{acc};}}
QDialogButtonBox QPushButton{{min-width:72px;}}
QDialogButtonBox QPushButton:disabled{{color:{dis_txt};}}
QProgressBar{{text-align:center;color:{txt};}}
QProgressBar::chunk{{background:{acc};border-radius:3px;}}
"""

def progress_bar_qss(accent: str, dark: bool = False) -> str:
    """Return a QProgressBar stylesheet string matching the active theme.

    Used by ``LocalDownloadDialog`` so the progress-bar chunk colour
    always reflects the current accent colour without inline hard-coding.
    """
    txt = "#e8e8e8" if dark else "#333333"
    return (
        "QProgressBar{{"
            "text-align:center;color:{txt};border-radius:4px;"
            "background:#d0d0d0;min-height:14px;}}"
        "QProgressBar::chunk{{"
            "background:{acc};border-radius:4px;}}"
    ).format(txt=txt, acc=accent)

