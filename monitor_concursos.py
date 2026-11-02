import urllib.request
import urllib.parse
import json
import os
import sys
import time
import webbrowser
import subprocess
import ssl
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

CONCURSOS = {
    "Triunfo-PB (Educa PB)": {
        "url": "https://educapb.selecao.net.br/informacoes/5/",
        "key": "triunfo"
    },
    "Jaguaribe-CE (Consulpam)": {
        "url": "https://www.consulpam.com.br/index.php?menu=concursos&acao=ver&id=874",
        "key": "jaguaribe"
    },
    "Poço Dantas-PB (IGECAP)": {
        "url": "https://concursos.igecap.org.br/informacoes/5/",
        "key": "pocodantas"
    }
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "concursos_state.json")
LOG_FILE = os.path.join(BASE_DIR, "monitor_concursos.log")

DESKTOP = os.path.expanduser("~/Área de trabalho")
if not os.path.exists(DESKTOP):
    DESKTOP = os.path.expanduser("~/Desktop")
ALERT_FILE = os.path.join(DESKTOP, "🚨_ATUALIZACAO_CONCURSOS.txt")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
}

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "COLE_SEU_TOKEN_AQUI")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "COLE_SEU_CHAT_ID_AQUI")

def log(msg):
    timestamp = datetime.now().strftime("[%H:%M:%S]")
    line = f"{timestamp} {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d')} {line}\n")
    except Exception:
        pass

def telegram_configurado():
    return "COLE_SEU" not in TELEGRAM_TOKEN and "COLE_SEU" not in TELEGRAM_CHAT_ID

def send_telegram(text):
    """Envia mensagem de texto para o Telegram. Retorna True se enviou."""
    if not telegram_configurado():
        log("Telegram não configurado (token/chat_id ausentes); pulando envio.")
        return False

    api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    ok = True
    for i in range(0, len(text), 4000):
        data = urllib.parse.urlencode({
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text[i:i + 4000],
            "disable_web_page_preview": "true",
        }).encode()
        try:
            req = urllib.request.Request(api, data=data)
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp.read()
        except Exception as e:
            log(f"Erro ao enviar Telegram: {type(e).__name__}: {e}")
            ok = False
            break
    if ok:
        log("📲 Mensagem enviada ao Telegram.")
    return ok

def fetch_links(url, key=None):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
        html = resp.read().decode("utf-8", errors="ignore")

    soup = BeautifulSoup(html, "html.parser")
    links = {}

    target_container = soup.find(id="blocoPublicacoes") if key == "triunfo" else None
    search_scope = target_container.find_all("a") if target_container else soup.find_all("a")

    for a in search_scope:
        href = a.get("href", "").strip()
        text = a.get_text(" ", strip=True)
        if not href or href.startswith("javascript:") or href.startswith("#"):
            continue

        full_url = urllib.parse.urljoin(url, href)

        is_relevant = (
            any(ext in full_url.lower() for ext in [".pdf", ".docx", ".doc", ".zip", "anexo", "download", "/anexos/"])
            or any(k in text.lower() for k in [
                "edital", "gabarito", "resultado", "retifica", "recurso", "isencao", "isen",
                "inscricao", "inscric", "convocacao", "comunicado", "nota", "classificacao", "homolog"
            ])
            or (key == "triunfo" and target_container is not None)
        )

        if is_relevant:
            clean_text = " ".join(text.split())
            if not clean_text:
                clean_text = os.path.basename(urllib.parse.urlparse(full_url).path)
            links[full_url] = clean_text

    return links

def trigger_alerts(contest_name, new_items):
    items_summary = "\n".join([f"• {t}" for t, _ in new_items[:4]])
    if len(new_items) > 4:
        items_summary += f"\n(+ {len(new_items) - 4} outros)"

    sound_files = [
        "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga",
        "/usr/share/sounds/freedesktop/stereo/complete.oga"
    ]
    sound_to_play = None
    for s in sound_files:
        if os.path.exists(s):
            sound_to_play = s
            break

    if sound_to_play:
        for _ in range(3):
            try:
                subprocess.run(["paplay", sound_to_play], stderr=subprocess.DEVNULL)
            except Exception:
                pass
    print('\a\a\a', flush=True)

    dialog_text = f"Novo(s) documento(s) publicado(s) em {contest_name}:\n\n{items_summary}\n\nVerifique seu navegador e a Área de Trabalho!"
    try:
        subprocess.Popen([
            "zenity",
            "--warning",
            "--title=🚨 ALERTA: CONCURSO ATUALIZADO!",
            f"--text={dialog_text}",
            "--width=450"
        ], env=dict(os.environ, DISPLAY=":0"))
    except Exception as e:
        log(f"Erro ao disparar janela Zenity: {e}")

    try:
        subprocess.run([
            "notify-send",
            "-u", "critical",
            "-t", "0",
            f"🚨 NOVIDADE: {contest_name}!",
            f"Novos documentos publicados:\n{items_summary}"
        ], stderr=subprocess.DEVNULL, env=dict(os.environ, DISPLAY=":0"))
    except Exception as e:
        log(f"Aviso notify-send: {e}")

def check_all_updates():
    previous_state = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                previous_state = json.load(f)
        except Exception:
            previous_state = {}

    current_state = {}
    all_new_items = {}
    urls_to_open = []

    for name, info in CONCURSOS.items():
        key = info["key"]
        url = info["url"]
        try:
            links = fetch_links(url, key)
            current_state[key] = links

            if key in previous_state and isinstance(previous_state[key], dict):
                prev_links = previous_state[key]
                new_in_contest = []
                for full_url, text in links.items():
                    if full_url not in prev_links:
                        new_in_contest.append((text, full_url))
                if new_in_contest:
                    all_new_items[name] = new_in_contest
                    urls_to_open.append(url)
                    for _, direct_url in new_in_contest:
                        urls_to_open.append(direct_url)
                log(f"  • {name}: {len(links)} documentos lidos ({len(new_in_contest)} novo(s)).")
            else:
                log(f"  • [{name}] Registro inicial estabelecido com {len(links)} links.")
        except Exception as e:
            log(f"  ❌ Erro ao consultar {name}: {e}")
            if key in previous_state:
                current_state[key] = previous_state[key]

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(current_state, f, ensure_ascii=False, indent=2)

    if all_new_items:
        now_str = datetime.now().strftime("%d/%m/%Y às %H:%M:%S")
        content = "=====================================================\n"
        content += f"🚨 ALERTA DE ATUALIZAÇÃO DE CONCURSOS ({now_str})\n"
        content += "=====================================================\n\n"
        telegram_msg = f"🚨 CONCURSOS ATUALIZADOS ({now_str})\n\n"

        for name, items in all_new_items.items():
            content += f"📌 {name.upper()}:\n"
            telegram_msg += f"📌 {name}\n"
            for text, link in items:
                content += f"  • {text}\n    Link direto: {link}\n"
                telegram_msg += f"• {text}\n{link}\n"
            content += "\n"
            telegram_msg += f"Página: {CONCURSOS[name]['url']}\n\n"
            trigger_alerts(name, items)

        send_telegram(telegram_msg)

        try:
            with open(ALERT_FILE, "w", encoding="utf-8") as f:
                f.write(content)
            log(f"Arquivo de alerta criado no Desktop: {ALERT_FILE}")
        except Exception as e:
            log(f"Erro ao salvar arquivo de alerta: {e}")

        for url in set(urls_to_open):
            try:
                subprocess.Popen(["xdg-open", url], stderr=subprocess.DEVNULL)
            except Exception:
                pass
            try:
                webbrowser.open(url)
            except Exception:
                pass

        log(f"🚨 ALERTA DISPARADO! Novidades detectadas em {len(all_new_items)} concurso(s)!")
        return True
    return False

def run_loop(interval_minutes=10):
    log("=====================================================")
    log("🎯 MONITOR ATIVO DE CONCURSOS (Triunfo, Jaguaribe, Poço Dantas)")
    log(f"⏱️ Intervalo configurado: a cada {interval_minutes} minutos")
    log("🌐 Foco prioritário: Triunfo-PB (https://educapb.selecao.net.br/informacoes/5/)")
    log(f"📲 Telegram: {'ativado' if telegram_configurado() else 'NÃO configurado'}")
    log("=====================================================")

    interval_seconds = interval_minutes * 60
    while True:
        try:
            log("Iniciando verificação dos sites...")
            check_all_updates()
            proxima = (datetime.now() + timedelta(seconds=interval_seconds)).strftime("%H:%M:%S")
            log(f"💤 Aguardando {interval_minutes} minutos. Próxima checagem às {proxima}...\n")
        except Exception as e:
            log(f"Erro inesperado no ciclo de monitoramento: {e}\n")
        time.sleep(interval_seconds)

if __name__ == "__main__":
    if "--test-telegram" in sys.argv:
        ok = send_telegram("✅ Teste do monitor de concursos: o Telegram está funcionando!")
        sys.exit(0 if ok else 1)

    if "--once" in sys.argv:
        log("Executando verificação única (--once)...")
        check_all_updates()
    else:
        interval = 10
        if "--interval" in sys.argv:
            try:
                idx = sys.argv.index("--interval")
                interval = int(sys.argv[idx + 1])
            except Exception:
                interval = 10
        run_loop(interval_minutes=interval)
