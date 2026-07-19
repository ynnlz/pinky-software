import json
import os
import sys
import threading
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk
import requests
from PIL import Image


APP_NAME = "PinkGift Tool"
DEFAULT_PANEL_URL = "https://site--pinky-software--65sy8vr2snqw.code.run"
BG = "#090a0f"
SIDEBAR = "#0d0f16"
CARD = "#12151e"
CARD_ALT = "#171a25"
BORDER = "#252938"
TEXT = "#f5f3fa"
MUTED = "#9196aa"
PINK = "#ff4fa3"
PINK_HOVER = "#e33d8e"
PURPLE = "#8b5cf6"
GREEN = "#46d39a"
RED = "#ef5a75"


def resource_path(*parts):
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return root.joinpath(*parts)


def settings_path():
    base = Path(os.getenv("APPDATA") or Path.home()) / "PinkGiftTool"
    base.mkdir(parents=True, exist_ok=True)
    return base / "settings.json"


def load_settings():
    try:
        return json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def save_settings(data):
    settings_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class ApiError(RuntimeError):
    pass


class PinkGiftApi:
    def __init__(self):
        self.base_url = DEFAULT_PANEL_URL
        self.session = requests.Session()
        self.session.headers.update({
            "X-PinkGift-Desktop": "1",
            "User-Agent": "PinkGiftTool/1.0",
            "Accept": "application/json",
        })

    def _request(self, method, path, **kwargs):
        try:
            response = self.session.request(method, self.base_url + path, timeout=25, **kwargs)
        except requests.RequestException as error:
            raise ApiError("Impossible de joindre le panel PinkGift.") from error
        try:
            payload = response.json()
        except ValueError as error:
            raise ApiError("Le panel a renvoyé une réponse invalide.") from error
        if not response.ok or not payload.get("ok", False):
            raise ApiError(payload.get("error") or f"Erreur HTTP {response.status_code}")
        return payload

    def login(self, base_url, password):
        clean_url = base_url.strip().rstrip("/")
        if not clean_url.startswith(("https://", "http://")):
            raise ApiError("L’adresse doit commencer par https://")
        self.base_url = clean_url
        return self._request("POST", "/api/desktop/login", json={"password": password})

    def status(self):
        return self._request("GET", "/api/desktop/status")

    def guilds(self):
        return self._request("GET", "/api/desktop/guilds")["guilds"]

    def channels(self, guild_id):
        return self._request("GET", f"/api/desktop/guilds/{guild_id}/channels")["channels"]

    def embeds(self):
        return self._request("GET", "/api/desktop/embeds")["embeds"]

    def publish(self, guild_id, channel_id, embed_key, mention_everyone=False):
        return self._request("POST", "/api/desktop/publish", json={
            "guild_id": guild_id,
            "channel_id": channel_id,
            "embed_key": embed_key,
            "mention_everyone": bool(mention_everyone),
        })["published"]


class PinkGiftTool(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        self.title(APP_NAME)
        self.geometry("1280x780")
        self.minsize(1040, 680)
        self.configure(fg_color=BG)

        self.api = PinkGiftApi()
        self.guilds = []
        self.channels = []
        self.embeds = []
        self.guild_by_label = {}
        self.channel_by_label = {}
        self.embed_by_label = {}
        self.active_nav = None
        self.nav_buttons = {}
        self.logo_image = self._load_logo((66, 66))

        self._show_login()

    def _load_logo(self, size):
        logo = resource_path("static", "discord_icon.gif")
        try:
            image = Image.open(logo)
            image.seek(0)
            return ctk.CTkImage(light_image=image.copy(), dark_image=image.copy(), size=size)
        except (OSError, EOFError):
            return None

    def _clear(self):
        for child in self.winfo_children():
            child.destroy()

    def _run_async(self, job, success=None, failure=None):
        def runner():
            try:
                result = job()
            except Exception as error:
                self.after(0, lambda: (failure or self._show_error)(error))
            else:
                if success:
                    self.after(0, lambda: success(result))
        threading.Thread(target=runner, daemon=True).start()

    def _show_error(self, error):
        messagebox.showerror(APP_NAME, str(error), parent=self)

    def _show_login(self):
        self._clear()
        settings = load_settings()
        shell = ctk.CTkFrame(self, width=470, height=560, fg_color=CARD, border_color=BORDER, border_width=1, corner_radius=18)
        shell.place(relx=0.5, rely=0.5, anchor="center")
        shell.grid_propagate(False)
        shell.grid_columnconfigure(0, weight=1)

        if self.logo_image:
            ctk.CTkLabel(shell, text="", image=self.logo_image).grid(row=0, column=0, pady=(40, 10))
        else:
            ctk.CTkLabel(shell, text="P", font=ctk.CTkFont(size=54, weight="bold"), text_color=PINK).grid(row=0, column=0, pady=(40, 10))
        ctk.CTkLabel(shell, text="PinkGift Tool", font=ctk.CTkFont(size=28, weight="bold"), text_color=TEXT).grid(row=1, column=0)
        ctk.CTkLabel(shell, text="Connecte-toi avec le mot de passe du panel", font=ctk.CTkFont(size=13), text_color=MUTED).grid(row=2, column=0, pady=(6, 28))

        form = ctk.CTkFrame(shell, fg_color="transparent")
        form.grid(row=3, column=0, padx=42, sticky="ew")
        form.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(form, text="ADRESSE DU PANEL", anchor="w", font=ctk.CTkFont(size=11, weight="bold"), text_color=MUTED).grid(row=0, column=0, sticky="ew", pady=(0, 7))
        self.url_entry = ctk.CTkEntry(form, height=44, fg_color=BG, border_color=BORDER, text_color=TEXT)
        self.url_entry.grid(row=1, column=0, sticky="ew")
        self.url_entry.insert(0, settings.get("panel_url", DEFAULT_PANEL_URL))
        ctk.CTkLabel(form, text="MOT DE PASSE", anchor="w", font=ctk.CTkFont(size=11, weight="bold"), text_color=MUTED).grid(row=2, column=0, sticky="ew", pady=(20, 7))
        self.password_entry = ctk.CTkEntry(form, height=44, show="●", fg_color=BG, border_color=BORDER, text_color=TEXT)
        self.password_entry.grid(row=3, column=0, sticky="ew")
        self.password_entry.bind("<Return>", lambda _event: self._login())
        self.login_button = ctk.CTkButton(form, text="Se connecter", height=45, fg_color=PINK, hover_color=PINK_HOVER, font=ctk.CTkFont(size=14, weight="bold"), command=self._login)
        self.login_button.grid(row=4, column=0, sticky="ew", pady=(28, 0))
        self.login_status = ctk.CTkLabel(form, text="", text_color=MUTED)
        self.login_status.grid(row=5, column=0, pady=12)
        self.password_entry.focus_set()

    def _login(self):
        url = self.url_entry.get().strip()
        password = self.password_entry.get()
        if not password:
            self.login_status.configure(text="Entre le mot de passe du panel.", text_color=RED)
            return
        self.login_button.configure(state="disabled", text="Connexion…")
        self.login_status.configure(text="Connexion sécurisée au bot…", text_color=MUTED)

        def success(_payload):
            save_settings({"panel_url": self.api.base_url})
            self.password_entry.delete(0, "end")
            self._build_shell()
            self._load_initial_data()

        def failure(error):
            self.login_button.configure(state="normal", text="Se connecter")
            self.login_status.configure(text=str(error), text_color=RED)

        self._run_async(lambda: self.api.login(url, password), success, failure)

    def _build_shell(self):
        self._clear()
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(self, width=215, corner_radius=0, fg_color=SIDEBAR, border_color=BORDER, border_width=1)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_rowconfigure(8, weight=1)

        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=18, pady=(22, 28))
        if self.logo_image:
            ctk.CTkLabel(brand, text="", image=self.logo_image).pack(side="left")
        ctk.CTkLabel(brand, text="PinkGift", font=ctk.CTkFont(size=21, weight="bold"), text_color=TEXT).pack(side="left", padx=9)

        ctk.CTkLabel(sidebar, text="GÉNÉRAL", anchor="w", font=ctk.CTkFont(size=10, weight="bold"), text_color="#64697b").grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 6))
        self._nav_button(sidebar, 2, "dashboard", "▣  Tableau de bord", self._show_dashboard)
        ctk.CTkLabel(sidebar, text="COMMUNICATION", anchor="w", font=ctk.CTkFont(size=10, weight="bold"), text_color="#64697b").grid(row=3, column=0, sticky="ew", padx=20, pady=(22, 6))
        self._nav_button(sidebar, 4, "embeds", "▤  Publier un embed", self._show_embeds)
        ctk.CTkLabel(sidebar, text="SYSTÈME", anchor="w", font=ctk.CTkFont(size=10, weight="bold"), text_color="#64697b").grid(row=5, column=0, sticky="ew", padx=20, pady=(22, 6))
        self._nav_button(sidebar, 6, "config", "⚙  Configuration", self._show_config)

        self.connection_label = ctk.CTkLabel(sidebar, text="● Connexion au bot…", anchor="w", text_color=MUTED, font=ctk.CTkFont(size=12))
        self.connection_label.grid(row=9, column=0, sticky="ew", padx=20, pady=(0, 12))
        ctk.CTkButton(sidebar, text="QUITTER", height=40, fg_color="#321820", hover_color="#4a202d", text_color="#ff8199", command=self.destroy).grid(row=10, column=0, sticky="ew", padx=14, pady=(0, 18))

        self.content = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(1, weight=1)

        topbar = ctk.CTkFrame(self.content, height=64, fg_color=SIDEBAR, corner_radius=0, border_color=BORDER, border_width=1)
        topbar.grid(row=0, column=0, sticky="ew")
        topbar.grid_propagate(False)
        self.page_title = ctk.CTkLabel(topbar, text="Tableau de bord", font=ctk.CTkFont(size=18, weight="bold"), text_color=TEXT)
        self.page_title.pack(side="left", padx=28, pady=20)
        self.top_status = ctk.CTkLabel(topbar, text="BOT EN COURS DE CONNEXION", text_color=MUTED, font=ctk.CTkFont(size=11, weight="bold"))
        self.top_status.pack(side="right", padx=28)

        self.page = ctk.CTkFrame(self.content, fg_color=BG, corner_radius=0)
        self.page.grid(row=1, column=0, sticky="nsew")
        self._show_dashboard()

    def _nav_button(self, parent, row, key, label, command):
        button = ctk.CTkButton(parent, text=label, anchor="w", height=40, corner_radius=7, fg_color="transparent", hover_color=CARD_ALT, text_color=MUTED, font=ctk.CTkFont(size=13), command=command)
        button.grid(row=row, column=0, sticky="ew", padx=10, pady=2)
        self.nav_buttons[key] = button

    def _select_nav(self, key, title):
        self.active_nav = key
        self.page_title.configure(text=title)
        for name, button in self.nav_buttons.items():
            button.configure(fg_color="#211934" if name == key else "transparent", text_color="#c7a7ff" if name == key else MUTED)
        for child in self.page.winfo_children():
            child.destroy()

    def _load_initial_data(self):
        def job():
            return self.api.status(), self.api.guilds(), self.api.embeds()

        def success(result):
            status, self.guilds, self.embeds = result
            ready = status.get("discord_ready", False)
            self.connection_label.configure(text="● Bot connecté" if ready else "● Bot hors ligne", text_color=GREEN if ready else RED)
            self.top_status.configure(text="BOT CONNECTÉ" if ready else "BOT HORS LIGNE", text_color=GREEN if ready else RED)
            self._show_dashboard()

        self._run_async(job, success)

    def _card(self, parent):
        return ctk.CTkFrame(parent, fg_color=CARD, border_color=BORDER, border_width=1, corner_radius=12)

    def _show_dashboard(self):
        self._select_nav("dashboard", "Tableau de bord")
        body = ctk.CTkScrollableFrame(self.page, fg_color=BG)
        body.pack(fill="both", expand=True, padx=22, pady=22)
        ctk.CTkLabel(body, text="Bienvenue dans PinkGift Tool", anchor="w", font=ctk.CTkFont(size=25, weight="bold"), text_color=TEXT).pack(fill="x", pady=(0, 5))
        ctk.CTkLabel(body, text="Publie les panneaux du shop sans utiliser de commande Discord.", anchor="w", font=ctk.CTkFont(size=13), text_color=MUTED).pack(fill="x", pady=(0, 24))

        stats = ctk.CTkFrame(body, fg_color="transparent")
        stats.pack(fill="x")
        for title, value, color in [
            ("SERVEURS CONNECTÉS", str(len(self.guilds)), PURPLE),
            ("EMBEDS DISPONIBLES", str(len(self.embeds)), PINK),
            ("ÉTAT DU SERVICE", "EN LIGNE" if self.guilds else "CHARGEMENT", GREEN if self.guilds else MUTED),
        ]:
            card = self._card(stats)
            card.pack(side="left", fill="x", expand=True, padx=(0, 12))
            ctk.CTkLabel(card, text=title, anchor="w", text_color=MUTED, font=ctk.CTkFont(size=10, weight="bold")).pack(fill="x", padx=18, pady=(17, 5))
            ctk.CTkLabel(card, text=value, anchor="w", text_color=color, font=ctk.CTkFont(size=27, weight="bold")).pack(fill="x", padx=18, pady=(0, 17))

        quick = self._card(body)
        quick.pack(fill="x", pady=22)
        ctk.CTkLabel(quick, text="Publication rapide", anchor="w", text_color=TEXT, font=ctk.CTkFont(size=17, weight="bold")).pack(fill="x", padx=20, pady=(18, 5))
        ctk.CTkLabel(quick, text="Choisis un embed, un serveur et un salon depuis l’onglet de publication.", anchor="w", text_color=MUTED).pack(fill="x", padx=20)
        ctk.CTkButton(quick, text="Ouvrir les embeds", width=180, height=40, fg_color=PURPLE, hover_color="#7447dc", command=self._show_embeds).pack(anchor="w", padx=20, pady=18)

    def _show_embeds(self):
        self._select_nav("embeds", "Publier un embed")
        wrapper = ctk.CTkFrame(self.page, fg_color="transparent")
        wrapper.pack(fill="both", expand=True, padx=24, pady=22)
        wrapper.grid_columnconfigure(0, weight=5)
        wrapper.grid_columnconfigure(1, weight=4)
        wrapper.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(wrapper, text="Publication Discord", anchor="w", font=ctk.CTkFont(size=23, weight="bold"), text_color=TEXT).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        form = self._card(wrapper)
        form.grid(row=1, column=0, sticky="nsew", padx=(0, 12))
        form.grid_columnconfigure(0, weight=1)

        self.guild_by_label = {f"{item['name']}  ·  {item['member_count']} membres": item for item in self.guilds}
        guild_values = list(self.guild_by_label) or ["Aucun serveur disponible"]
        self._field_label(form, "SERVEUR DISCORD", 0)
        self.guild_combo = ctk.CTkComboBox(form, values=guild_values, height=42, state="readonly", fg_color=BG, border_color=BORDER, command=self._guild_changed)
        self.guild_combo.grid(row=1, column=0, sticky="ew", padx=20)
        self.guild_combo.set(guild_values[0])

        self._field_label(form, "SALON DE PUBLICATION", 2)
        self.channel_combo = ctk.CTkComboBox(form, values=["Chargement…"], height=42, state="readonly", fg_color=BG, border_color=BORDER)
        self.channel_combo.grid(row=3, column=0, sticky="ew", padx=20)
        self.channel_combo.set("Chargement…")

        self._field_label(form, "EMBED À PUBLIER", 4)
        self.embed_by_label = {f"{item['category']}  ·  {item['label']}": item for item in self.embeds}
        embed_values = list(self.embed_by_label) or ["Chargement…"]
        self.embed_combo = ctk.CTkComboBox(form, values=embed_values, height=42, state="readonly", fg_color=BG, border_color=BORDER, command=self._embed_changed)
        self.embed_combo.grid(row=5, column=0, sticky="ew", padx=20)
        self.embed_combo.set(embed_values[0])

        mention_box = ctk.CTkFrame(form, fg_color=CARD_ALT, corner_radius=8)
        mention_box.grid(row=6, column=0, sticky="ew", padx=20, pady=20)
        mention_box.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(mention_box, text="Mentionner @everyone", anchor="w", text_color=TEXT, font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 2))
        ctk.CTkLabel(mention_box, text="Désactivé par défaut pour éviter les pings accidentels.", anchor="w", text_color=MUTED, font=ctk.CTkFont(size=11)).grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 12))
        self.mention_switch = ctk.CTkSwitch(mention_box, text="", progress_color=PINK)
        self.mention_switch.grid(row=0, column=1, rowspan=2, padx=14)

        self.publish_button = ctk.CTkButton(form, text="Publier dans le salon", height=46, fg_color=PURPLE, hover_color="#7447dc", font=ctk.CTkFont(size=14, weight="bold"), command=self._publish)
        self.publish_button.grid(row=7, column=0, sticky="ew", padx=20, pady=(0, 12))
        self.publish_status = ctk.CTkLabel(form, text="", text_color=MUTED, wraplength=460)
        self.publish_status.grid(row=8, column=0, sticky="ew", padx=20, pady=(0, 15))

        preview = self._card(wrapper)
        preview.grid(row=1, column=1, sticky="nsew")
        preview.grid_columnconfigure(0, weight=1)
        preview.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(preview, text="APERÇU DE L’EMBED", anchor="w", text_color=MUTED, font=ctk.CTkFont(size=10, weight="bold")).grid(row=0, column=0, sticky="ew", padx=18, pady=(17, 8))
        self.preview_title = ctk.CTkLabel(preview, text="", anchor="w", justify="left", text_color=TEXT, font=ctk.CTkFont(size=17, weight="bold"), wraplength=430)
        self.preview_title.grid(row=1, column=0, sticky="ew", padx=18)
        self.preview_text = ctk.CTkTextbox(preview, fg_color="#0f1118", border_color=BORDER, border_width=1, text_color="#d6d8e2", wrap="word", font=ctk.CTkFont(size=12))
        self.preview_text.grid(row=2, column=0, sticky="nsew", padx=18, pady=14)
        self.preview_text.configure(state="disabled")

        if self.guilds:
            self._guild_changed(self.guild_combo.get())
        if self.embeds:
            self._embed_changed(self.embed_combo.get())

    def _field_label(self, parent, text, row):
        ctk.CTkLabel(parent, text=text, anchor="w", text_color=MUTED, font=ctk.CTkFont(size=10, weight="bold")).grid(row=row, column=0, sticky="ew", padx=20, pady=(18 if row == 0 else 15, 7))

    def _guild_changed(self, label):
        guild = self.guild_by_label.get(label)
        if not guild:
            return
        self.channel_combo.configure(values=["Chargement…"])
        self.channel_combo.set("Chargement…")

        def success(channels):
            self.channels = channels
            self.channel_by_label = {
                f"{item['category']}  /  #{item['name']}": item for item in channels
            }
            values = list(self.channel_by_label) or ["Aucun salon accessible"]
            self.channel_combo.configure(values=values)
            self.channel_combo.set(values[0])

        self._run_async(lambda: self.api.channels(guild["id"]), success)

    def _embed_changed(self, label):
        item = self.embed_by_label.get(label)
        if not item:
            return
        preview = item.get("preview") or {}
        self.preview_title.configure(text=preview.get("title") or item["label"])
        lines = []
        if preview.get("description"):
            lines.append(preview["description"])
        for field in preview.get("fields", []):
            lines.extend(["", field.get("name", ""), field.get("value", "")])
        if preview.get("footer"):
            lines.extend(["", f"— {preview['footer']}"])
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", "\n".join(lines).strip() or "Aucun aperçu disponible")
        self.preview_text.configure(state="disabled")

    def _publish(self):
        guild = self.guild_by_label.get(self.guild_combo.get())
        channel = self.channel_by_label.get(self.channel_combo.get())
        embed = self.embed_by_label.get(self.embed_combo.get())
        if not guild or not channel or not embed:
            self.publish_status.configure(text="Sélectionne un serveur, un salon et un embed.", text_color=RED)
            return
        if self.mention_switch.get() and not messagebox.askyesno(APP_NAME, "Confirmer la mention @everyone ?", parent=self):
            return
        self.publish_button.configure(state="disabled", text="Publication…")
        self.publish_status.configure(text="Envoi du panneau à Discord…", text_color=MUTED)

        def success(result):
            self.publish_button.configure(state="normal", text="Publier dans le salon")
            self.publish_status.configure(text=f"✓ Publié dans #{result['channel_name']}", text_color=GREEN)

        def failure(error):
            self.publish_button.configure(state="normal", text="Publier dans le salon")
            self.publish_status.configure(text=str(error), text_color=RED)

        self._run_async(lambda: self.api.publish(guild["id"], channel["id"], embed["key"], self.mention_switch.get()), success, failure)

    def _show_config(self):
        self._select_nav("config", "Configuration")
        body = ctk.CTkFrame(self.page, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24, pady=22)
        card = self._card(body)
        card.pack(fill="x")
        ctk.CTkLabel(card, text="Connexion au panel", anchor="w", font=ctk.CTkFont(size=18, weight="bold"), text_color=TEXT).pack(fill="x", padx=20, pady=(18, 6))
        ctk.CTkLabel(card, text=self.api.base_url, anchor="w", text_color=MUTED).pack(fill="x", padx=20)
        ctk.CTkLabel(card, text="Le mot de passe n’est jamais enregistré sur l’ordinateur.", anchor="w", text_color=GREEN, font=ctk.CTkFont(size=12)).pack(fill="x", padx=20, pady=(7, 0))
        ctk.CTkButton(card, text="Changer de connexion", width=190, height=40, fg_color="#32223f", hover_color="#443052", command=self._show_login).pack(anchor="w", padx=20, pady=18)


if __name__ == "__main__":
    PinkGiftTool().mainloop()
