#!/usr/bin/env python3
"""m4top — monitor de terminal para Apple Silicon, Python >= 3.10.

Instalação no Mac (Homebrew deve estar instalado):
    brew install macmon
    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install psutil
    python m4top.py

Teclas: q sair; c ordenar CPU; m ordenar RAM; setas rolar CPUs.
Opções: --interval 1.0; --macmon /caminho/macmon; --no-gpu.
CPU por núcleo lógico via psutil. GPU agregada via macmon pipe.
Ausências são exibidas como N/D, sem estimar uso por núcleo da GPU.
Potência depende de contadores privados do macOS; zero não garante
consumo nulo em uma combinação de hardware/macOS não suportada.
Fontes do formato: https://github.com/vladkens/macmon
"""
import argparse
from collections import deque
import curses
import json
import math
import platform
import shutil
import subprocess
import threading
import time

try:
    import psutil
except ImportError:
    raise SystemExit('Instale a dependência com: python -m pip install psutil')


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def fmt(value, unit='', digits=1):
    return f'{value:.{digits}f}{unit}' if number(value) else 'N/D'


def gpu_values(data):
    """Formato atual e compatibilidade com gpu_usage=[MHz, ratio]."""
    old = data.get('gpu_usage')
    freq = data.get('gpu_freq_mhz')
    scaled = data.get('gpu_scaled_ratio')
    if isinstance(old, (list, tuple)) and len(old) == 2:
        if freq is None:
            freq = old[0]
        if scaled is None:
            scaled = old[1]
    active = data.get('gpu_active_ratio')
    return freq, active * 100 if number(active) else None, scaled * 100 if number(scaled) else None


class GPUReader:
    def __init__(self, executable, interval, disabled=False):
        self.lock = threading.Lock()
        self.data = {}
        self.updated = 0.0
        self.error = 'GPU desativada' if disabled else 'Aguardando macmon'
        self.process = None
        self.thread = None
        self.stderr_thread = None
        self.stderr = deque(maxlen=4)
        if disabled:
            return
        path = shutil.which(executable)
        if not path:
            self.error = 'macmon ausente. Instale com brew install macmon'
            return
        try:
            self.process = subprocess.Popen(
                [path, 'pipe', '-i', str(max(100, int(interval * 1000)))],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8', errors='replace', bufsize=1,
            )
        except OSError as exc:
            self.error = str(exc)
            return
        self.thread = threading.Thread(target=self.read, daemon=True)
        self.stderr_thread = threading.Thread(target=self.read_errors, daemon=True)
        self.stderr_thread.start()
        self.thread.start()

    def read_errors(self):
        for line in self.process.stderr:
            with self.lock:
                self.stderr.append(line.strip())

    def read(self):
        for line in self.process.stdout:
            try:
                data = json.loads(line)
                if not isinstance(data, dict):
                    continue
            except (ValueError, TypeError):
                with self.lock:
                    self.error = 'JSON inválido recebido do macmon'
                continue
            with self.lock:
                self.data = data
                self.updated = time.monotonic()
                self.error = ''
        with self.lock:
            self.error = 'macmon encerrou. ' + (self.stderr[-1] if self.stderr else 'Verifique macmon pipe no terminal')

    def snapshot(self):
        with self.lock:
            return self.data.copy(), self.updated, self.error

    def close(self):
        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            for thread in (self.thread, self.stderr_thread):
                if thread:
                    thread.join(timeout=1)
            self.process.stdout.close()
            self.process.stderr.close()


def processes():
    rows = []
    for p in psutil.process_iter():
        try:
            with p.oneshot():
                rows.append((p.pid, p.name(), p.cpu_percent(), p.memory_info().rss))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return rows


def main_ui(screen, reader, interval):
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    screen.timeout(100)
    screen.keypad(True)
    if curses.has_colors():
        curses.start_color()
        try:
            curses.use_default_colors()
            bg = -1
        except curses.error:
            bg = curses.COLOR_BLACK
        for i, color in enumerate((curses.COLOR_CYAN, curses.COLOR_GREEN,
                                   curses.COLOR_YELLOW, curses.COLOR_RED), 1):
            curses.init_pair(i, color, bg)

    def put(y, x, text, color=0, bold=False):
        h, w = screen.getmaxyx()
        if 0 <= y < h and 0 <= x < w - 1:
            attr = curses.color_pair(color) if curses.has_colors() else 0
            if bold:
                attr |= curses.A_BOLD
            # Filtra caracteres de controle de nomes de processos e erros.
            text = ''.join(c if c.isprintable() else ' ' for c in str(text))
            try:
                screen.addnstr(y, x, text, max(0, w - x - 1), attr)
            except curses.error:
                pass

    def bar(y, x, label, value, width):
        width = max(4, width)
        if not number(value):
            put(y, x, f'{label:<8} N/D', 3)
            return
        value = max(0, min(100, value))
        n = round(width * value / 100)
        color = 2 if value < 60 else 3 if value < 85 else 4
        put(y, x, f'{label:<8}[', 1)
        put(y, x + 9, '|' * n + ' ' * (width - n), color)
        put(y, x + 9 + width, f'] {value:5.1f}%')

    history = deque(maxlen=60)
    psutil.cpu_percent(percpu=True)
    processes()  # Inicializa os deltas de CPU dos processos.
    cpus, rows = [], []
    sort = 'cpu'
    offset = 0
    next_sample = time.monotonic() + interval
    last_gpu = 0
    while True:
        now = time.monotonic()
        if now >= next_sample:
            cpus = psutil.cpu_percent(percpu=True)
            rows = processes()
            next_sample = now + interval
        data, updated, error = reader.snapshot()
        stale = not updated or now - updated > max(5, interval * 3)
        freq, active, scaled = gpu_values(data if not stale and not error else {})
        if updated != last_gpu:
            last_gpu = updated
            history.append(active if number(active) else scaled)
        screen.erase()
        h, w = screen.getmaxyx()
        if h < 26 or w < 76:
            put(0, 0, 'Aumente o terminal para pelo menos 76 colunas e 26 linhas.', 3)
            put(2, 0, 'q sair')
        else:
            vm, swap = psutil.virtual_memory(), psutil.swap_memory()
            put(0, 1, 'm4top  |  Apple Silicon  |  ' + platform.node(), 1, True)
            put(1, 1, f'{len(cpus) or psutil.cpu_count()} CPUs lógicas  |  {time.strftime("%H:%M:%S")}  |  intervalo {interval:g}s')
            put(3, 1, 'CPU POR NÚCLEO LÓGICO · ocupação do sistema operacional', 1, True)
            columns = 2 if w >= 100 else 1
            count = min(8, max(3, h - 23))
            visible = count * columns
            offset = min(offset, max(0, len(cpus) - visible))
            colwidth = (w - 2) // columns
            for i, value in enumerate(cpus[offset:offset + visible]):
                col, row = divmod(i, count)
                bar(4 + row, 1 + col * colwidth, f'CPU {offset+i:02}', value, colwidth - 20)
            if not cpus:
                put(4, 1, 'Coletando primeira amostra...', 3)
            y = 4 + count
            put(y, 1, f'Núcleos {offset + 1 if cpus else 0}–{min(offset+visible, len(cpus))} de {len(cpus)}  |  ↑ ↓ rolar', 1)
            y += 2
            put(y, 1, 'GPU · agregada, sem contadores individuais por núcleo', 1, True)
            bar(y + 1, 1, 'Ativa', active, min(36, w - 24))
            bar(y + 2, 1, 'Freq.adj', scaled, min(36, w - 24))
            temp = data.get('temp') or {}
            if not isinstance(temp, dict):
                temp = {}
            valid = not stale and not error
            put(y + 3, 1, 'Clock ' + fmt(freq, ' MHz', 0) + '  |  GPU ' + fmt(data.get('gpu_power') if valid else None, ' W', 2)
                + '  |  ' + fmt(temp.get('gpu_temp_avg') if valid else None, ' °C'))
            levels = '▁▂▃▄▅▆▇█'
            spark = ''.join(levels[min(7, int(max(0, min(100, v)) * 7 / 100))] if number(v) else '·' for v in history)
            put(y + 4, 1, 'Histórico ' + (spark or 'aguardando'), 2)
            status = error or ('Coleta sem atualização' if stale else 'GPU recebendo dados do macmon')
            put(y + 5, 1, status, 3 if error or stale else 1)
            y += 7
            bar(y, 1, 'RAM', vm.percent, min(28, w - 50))
            put(y, min(49, w - 25), f'{vm.used/2**30:.1f}/{vm.total/2**30:.1f} GiB')
            put(y + 1, 1, f'Swap {swap.used/2**30:.2f}/{swap.total/2**30:.2f} GiB  |  CPU '
                + fmt(data.get('cpu_power') if valid else None, ' W', 2)
                + '  |  ' + fmt(temp.get('cpu_temp_avg') if valid else None, ' °C'))
            y += 3
            put(y, 1, f'PROCESSOS · ordem {sort.upper()} · CPU pode exceder 100% com múltiplos núcleos', 1, True)
            put(y + 1, 1, f'{"PID":>7}  {"CPU%":>7}  {"RAM MiB":>9}  NOME', 1)
            ordered = sorted(rows, key=lambda r: r[2] if sort == 'cpu' else r[3], reverse=True)
            for i, (pid, name, cpu, rss) in enumerate(ordered[:max(0, h - y - 4)]):
                put(y + 2 + i, 1, f'{pid:7}  {cpu:7.1f}  {rss/2**20:9.1f}  {name}')
            put(h - 1, 1, 'q sair  |  c CPU  |  m RAM  |  ↑ ↓ núcleos  |  N/D = indisponível', 1)
        screen.refresh()
        key = screen.getch()
        if key in (ord('q'), ord('Q'), 27):
            break
        if key == ord('c'):
            sort = 'cpu'
        elif key == ord('m'):
            sort = 'ram'
        elif key == curses.KEY_DOWN:
            offset += 1
        elif key == curses.KEY_UP:
            offset = max(0, offset - 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--interval', type=float, default=1.0)
    parser.add_argument('--macmon', default='macmon', help='Nome ou caminho do executável macmon')
    parser.add_argument('--no-gpu', action='store_true')
    args = parser.parse_args()
    if not math.isfinite(args.interval) or args.interval < 0.2:
        parser.error('--interval deve ser finito e >= 0.2 segundos')
    reader = GPUReader(args.macmon, args.interval, args.no_gpu)
    try:
        curses.wrapper(main_ui, reader, args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        reader.close()


if __name__ == '__main__':
    main()
